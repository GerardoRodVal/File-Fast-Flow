import os
import shutil
import re
import errno
import threading
from pathlib import Path
from uuid import UUID, uuid4

from PySide6.QtCore import QThread, Signal

from devicedrop.network.transfer import publish
from devicedrop.security.files import validate_filename, RESERVED


def publish_copy(temp, folder, name):
    if os.name != "nt":
        return publish(temp, folder, name)
    # Windows rename is atomic and refuses an existing destination. It also
    # works in environments that don't permit creating NTFS hard links.
    validate_filename(name)
    source = Path(name)
    for index in range(10000):
        destination = folder / (name if index == 0 else f"{source.stem} ({index}){source.suffix}")
        try:
            temp.rename(destination)
            return destination
        except FileExistsError:
            continue
    raise OSError("Demasiados archivos con el mismo nombre.")


class FileSpaces:
    """General files at the shared root, private files under device names."""

    def __init__(self, root, db=None):
        self.db = db
        self.root = Path(db.setting("receive_folder")) if db else Path(root) / "shared"
        self.legacy_root = Path(root) / "spaces"
        self.lock = db.lock if db else threading.RLock()
        self.mapping = {} if db is None else db.setting("space_device_folders", {})

    @staticmethod
    def safe_name(name):
        name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip()[:100].rstrip(". ")
        if not name:
            name = "Dispositivo"
        if name.split(".")[0].upper() in RESERVED:
            name = "_" + name
        validate_filename(name)
        return name

    def device_folder_name(self, device_id):
        device_id = str(UUID(device_id))
        with self.lock:
            if self.db:
                self.mapping = self.db.setting("space_device_folders", {})
            if device_id not in self.mapping:
                peers = self.db.trusted(device_id) if self.db else []
                name = self.safe_name(peers[0]["name"] if peers else f"Dispositivo {device_id[:8]}")
                used = {value.casefold() for value in self.mapping.values()}
                base = name
                if name.casefold() in used:
                    name = f"{base} ({device_id[:8]})"
                suffix = 2
                while name.casefold() in used:
                    name = f"{base} ({device_id[:8]}-{suffix})"; suffix += 1
                self.mapping[device_id] = name
                if self.db:
                    self.db.set_setting("space_device_folders", self.mapping)
            name = self.mapping[device_id]
            validate_filename(name)
            return name

    def folder(self, device_id=None):
        folder = self.root if device_id is None else self.root / self.device_folder_name(device_id)
        if not folder.resolve().is_relative_to(self.root.resolve()):
            raise ValueError("La carpeta del dispositivo debe estar dentro de la carpeta general.")
        if device_id is not None and (folder.is_symlink() or getattr(folder, "is_junction", lambda: False)() or folder.resolve().parent != self.root.resolve()):
            raise ValueError("La carpeta individual no puede ser un enlace a otra carpeta.")
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def mark_managed(self, path):
        if self.db:
            stat = path.stat()
            self.db.execute("INSERT OR REPLACE INTO space_files VALUES (?,?,?)", (str(path.resolve()), stat.st_size, stat.st_mtime_ns))

    def is_managed(self, path):
        if not self.db:
            return False
        rows = self.db.execute("SELECT size,mtime_ns FROM space_files WHERE path=?", (str(path.resolve()),))
        if not rows:
            return False
        stat = path.stat()
        return rows[0]["size"] == stat.st_size and rows[0]["mtime_ns"] == stat.st_mtime_ns

    def is_private(self, path):
        try:
            relative = path.resolve().relative_to(self.root.resolve())
        except ValueError:
            return False
        mapping = self.db.setting("space_device_folders", {}) if self.db else self.mapping
        return len(relative.parts) > 1 and relative.parts[0].casefold() in {name.casefold() for name in mapping.values()}

    def sharing_context(self, path):
        path = Path(path).resolve()
        if path.parent == self.root.resolve():
            return "general", None
        mapping = self.db.setting("space_device_folders", {}) if self.db else self.mapping
        for device_id, name in mapping.items():
            folder = self.folder(device_id).resolve()
            if path.is_relative_to(folder):
                return "device", device_id
        return None

    def move_file(self, source, destination, source_root):
        source, destination = Path(source), Path(destination).resolve()
        if not source.resolve().is_relative_to(Path(source_root).resolve()) or not destination.is_relative_to(self.root.resolve()):
            raise ValueError("La migración debe permanecer dentro de las carpetas de FileFastFlow.")
        try:
            saved = publish_copy(source, destination, source.name)
        except OSError as error:
            if error.errno != errno.EXDEV:
                raise
            temp = destination / f".{uuid4()}.space-part"
            try:
                shutil.copyfile(source, temp)
                saved = publish_copy(temp, destination, source.name)
                source.unlink()
            finally:
                temp.unlink(missing_ok=True)
        self.mark_managed(saved)
        return saved

    def migrate_received(self, old_folder):
        old_folder = Path(old_folder).resolve()
        if old_folder == self.root.resolve() or not self.db:
            return
        records = self.db.execute("SELECT * FROM transfers WHERE direction='incoming' AND status='completed' AND saved_path IS NOT NULL")
        for record in records:
            source = Path(record["saved_path"])
            if not source.is_file() or not source.resolve().is_relative_to(old_folder):
                continue
            device_id = None if record["share_scope"] == "general" else record["source_device"]
            destination = self.folder(device_id)
            saved = self.move_file(source, destination, old_folder)
            self.db.execute("UPDATE transfers SET saved_path=? WHERE saved_path=?", (str(saved), str(source)))
            self.db.execute("UPDATE processed_files SET path=? WHERE path=?", (str(saved), str(source)))

    def migrate_legacy(self):
        sources = [(self.legacy_root / "general", None)]
        devices = self.legacy_root / "devices"
        if devices.is_dir():
            for directory in devices.iterdir():
                if directory.is_dir():
                    try:
                        sources.append((directory, str(UUID(directory.name))))
                    except ValueError:
                        continue
        for directory, device_id in sources:
            if not directory.is_dir():
                continue
            destination = self.folder(device_id).resolve()
            for source in directory.iterdir():
                if not source.is_file() or source.name.endswith(".space-part"):
                    continue
                saved = self.move_file(source, destination, self.legacy_root)
                if self.db:
                    self.db.execute("UPDATE transfers SET original_path=? WHERE original_path=?", (str(saved), str(source)))

    def files(self, device_id=None):
        folder = self.folder(device_id).resolve()
        return sorted((p for p in folder.iterdir()
                       if p.is_file() and not p.name.startswith(".") and not p.is_symlink() and p.resolve().parent == folder),
                      key=lambda p: p.name.casefold())

    def store(self, paths, device_id=None):
        folder = self.folder(device_id).resolve()
        saved = []
        for source in map(Path, paths):
            if source.resolve().parent == folder:
                if source.is_file():
                    self.mark_managed(source)
                    saved.append(source)
                continue
            temp = folder / f".{uuid4()}.space-part"
            try:
                shutil.copyfile(source, temp)
                destination = publish_copy(temp, folder, source.name)
                self.mark_managed(destination); saved.append(destination)
            finally:
                temp.unlink(missing_ok=True)
        return saved


class SpaceStoreWorker(QThread):
    completed = Signal(list, str)

    def __init__(self, spaces, paths, device_id=None, parent=None):
        super().__init__(parent)
        self.spaces, self.paths, self.device_id = spaces, paths, device_id

    def run(self):
        saved = []
        error = ""
        try:
            for path in self.paths:
                saved.extend(self.spaces.store([path], self.device_id))
        except Exception as exc:
            error = str(exc)
        self.completed.emit(saved, error)
