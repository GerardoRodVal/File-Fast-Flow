"""Offline distribution of the binaries included in this FileFastFlow version."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from PySide6.QtCore import QThread, Signal


from . import __version__ as VERSION


def assets_dir():
    return Path(__file__).resolve().parent / "assets"


def windows_bundle():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1] / "dist" / "FileFastFlow"


def default_filename(kind):
    return f"FileFastFlow-{VERSION}-Setup.exe" if kind == "windows" else f"FileFastFlow-{VERSION}-debug.apk"


def create_package(kind, destination, assets=None, bundle=None, progress=None):
    """Publish atomically, preserving an existing destination on any failure."""
    if kind not in {"windows", "android"}:
        raise ValueError("Tipo de paquete desconocido.")
    assets = Path(assets) if assets is not None else assets_dir()
    bundle = Path(bundle) if bundle is not None else windows_bundle()
    destination = Path(destination).resolve()
    if destination.is_relative_to(bundle.resolve()) or destination.is_relative_to(assets.resolve()):
        raise ValueError("Guarda el instalador fuera de la carpeta de la aplicación.")
    if not destination.parent.is_dir():
        raise ValueError("La carpeta de destino no existe.")
    if kind == "windows" and sys.platform != "win32":
        raise ValueError("El instalador EXE se genera desde Windows.")
    with tempfile.TemporaryDirectory(prefix=".devicedrop-package-", dir=destination.parent) as temporary:
        staging = Path(temporary)
        if kind == "android":
            apk = assets / "android" / "FileFastFlow.apk"
            manifest_path = assets / "android" / "manifest.json"
            if not apk.is_file() or not manifest_path.is_file():
                raise ValueError("No se encontró el APK incluido. Reempaqueta FileFastFlow con scripts/build_windows.py.")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            output = staging / "FileFastFlow.apk"
            digest = hashlib.sha256()
            copied = 0
            with apk.open("rb") as source, output.open("wb") as target:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    target.write(chunk)
                    digest.update(chunk)
                    copied += len(chunk)
                    if progress:
                        progress(int(copied * 100 / max(apk.stat().st_size, 1)))
            if digest.hexdigest() != manifest["sha256"] or copied != manifest["bytes"]:
                raise ValueError("El APK incluido está dañado. Reinstala FileFastFlow.")
        else:
            compiler = assets / "inno" / "ISCC.exe"
            recipe = assets / "FileFastFlow.iss"
            if not compiler.is_file() or not recipe.is_file():
                raise ValueError("No se encontró el generador del instalador. Reinstala FileFastFlow.")
            if not (bundle / "FileFastFlow.exe").is_file() or not (bundle / "_internal").is_dir():
                raise ValueError("Primero compila FileFastFlow con scripts/build_windows.py.")
            command = [str(compiler), "/Q", f"/DAppSource={bundle.resolve()}", f"/DAppVersion={VERSION}",
                       f"/O{staging}", "/FFileFastFlow-Setup", str(recipe)]
            with (staging / "compiler.log").open("wb") as log:
                try:
                    result = subprocess.run(command, cwd=assets, stdout=log, stderr=subprocess.STDOUT,
                                            creationflags=subprocess.CREATE_NO_WINDOW, timeout=600)
                except subprocess.TimeoutExpired as error:
                    raise ValueError("El instalador tardó demasiado. Inténtalo de nuevo.") from error
            if result.returncode:
                detail = (staging / "compiler.log").read_text(encoding="utf-8", errors="replace")[-3000:]
                raise ValueError(f"No se pudo generar el instalador EXE.\n{detail}")
            output = staging / "FileFastFlow-Setup.exe"
            if not output.is_file() or output.stat().st_size == 0:
                raise ValueError("El generador no produjo un instalador EXE válido.")
        os.replace(output, destination)
    return destination


class PackageWorker(QThread):
    progress = Signal(int)
    completed = Signal(bool, str)

    def __init__(self, kind, destination, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.destination = Path(destination)

    def run(self):
        try:
            path = create_package(self.kind, self.destination, progress=self.progress.emit)
            self.completed.emit(True, str(path))
        except Exception as error:
            self.completed.emit(False, str(error))
