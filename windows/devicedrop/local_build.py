"""Build the current sources in an isolated tree before distributing them."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import tomllib

from PySide6.QtCore import QThread, Signal

from .packages import assets_dir, create_package


def project_root():
    root = Path(__file__).resolve().parents[2]
    return root if not getattr(sys, "frozen", False) and (root / "android" / "gradlew.bat").is_file() else None


def source_files(root):
    roots = [root / "windows" / "devicedrop", root / "windows" / "scripts", root / "android" / "app" / "src", root / "android" / "gradle", root / "assets"]
    files = []
    for directory in roots:
        for path in directory.rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc" and not path.is_relative_to(root / "windows" / "devicedrop" / "assets"):
                files.append(path)
    for pattern in ["windows/*.txt", "windows/*.toml", "android/*.kts", "android/*.properties", "android/gradlew*", "android/app/*.kts", "android/debug.keystore", "windows/devicedrop/assets/*.iss"]:
        files.extend(p for p in root.glob(pattern) if p.is_file() and p.name != "local.properties")
    return sorted(set(files))


def source_revision(root):
    digest = hashlib.sha256()
    for path in source_files(root):
        digest.update(path.relative_to(root).as_posix().encode()); digest.update(b"\0")
        digest.update(path.read_bytes()); digest.update(b"\0")
    return digest.hexdigest()


def installed_revision():
    try:
        return json.loads((assets_dir() / "local-build.json").read_text())["revision"]
    except (OSError, ValueError, KeyError):
        return ""


def artifact_valid(item):
    from .security.files import sha256_file
    try:
        path = Path(item["path"])
        return path.is_file() and path.stat().st_size == item["size"] and sha256_file(path) == item["sha256"]
    except (OSError, KeyError, TypeError):
        return False


def build_local(root, output, revision, version_code, progress=lambda text: None):
    from .security.files import sha256_file
    staging = output / f"{revision[:16]}-{version_code}"
    snapshot = staging / "source"; snapshot.mkdir(parents=True, exist_ok=True)
    progress("Preparando una copia de los cambios actuales…")
    for path in source_files(root):
        target = snapshot / path.relative_to(root); target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    assets = snapshot / "windows" / "devicedrop" / "assets"
    shutil.copytree(assets_dir() / "inno", assets / "inno", dirs_exist_ok=True)
    (assets / "local-build.json").write_text(json.dumps({"revision": revision}))
    version = tomllib.loads((snapshot / "windows" / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    env = dict(os.environ)
    if not env.get("JAVA_HOME"):
        env["JAVA_HOME"] = str(Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Android" / "Android Studio" / "jbr")
    env.setdefault("ANDROID_HOME", str(Path(os.environ["LOCALAPPDATA"]) / "Android" / "Sdk"))
    env["PATH"] = str(Path(env["JAVA_HOME"]) / "bin") + os.pathsep + env.get("PATH", "")
    python = root / "windows" / ".venv" / "Scripts" / "python.exe"
    if not python.is_file():
        raise ValueError("No se encontró el entorno de compilación de esta PC.")
    def run(command, cwd):
        with (staging / "build.log").open("ab") as log:
            result = subprocess.run(command, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=1800)
        if result.returncode:
            raise ValueError(f"No se pudo compilar. Revisa {staging / 'build.log'}")
    progress("Compilando Android con los cambios actuales…")
    run([str(snapshot / "android" / "gradlew.bat"), "--no-daemon", "testDebugUnitTest", "assembleDebug", f"-PlocalVersionCode={version_code}", f"-PlocalRevision={revision}"], snapshot / "android")
    apk = snapshot / "android" / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk"
    progress("Compilando Windows con los cambios actuales…")
    run([str(python), str(snapshot / "windows" / "scripts" / "build_windows.py"), "--apk", str(apk)], snapshot)
    # Verify that a moving working tree was never published as a finished build.
    if source_revision(root) != revision:
        raise ValueError("El código cambió durante la compilación. Vuelve a actualizar para incluir todos los cambios.")
    manifest = {"revision": revision, "version": version, "version_code": version_code, "created_at": time.time(), "artifacts": {}}
    for platform, kind, suffix in [("windows", "windows", "Setup.exe"), ("android", "android", "debug.apk")]:
        progress(f"Preparando instalador {platform}…")
        target = staging / f"FileFastFlow-{version}-{suffix}"
        create_package(kind, target, assets=assets, bundle=snapshot / "windows" / "dist" / "FileFastFlow")
        manifest["artifacts"][platform] = {"path": str(target), "size": target.stat().st_size, "sha256": sha256_file(target)}
    if source_revision(root) != revision:
        raise ValueError("El código cambió mientras se preparaban los instaladores. Vuelve a actualizar.")
    (staging / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest


class LocalBuildWorker(QThread):
    progress = Signal(str)
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, runtime, automatic=False, parent=None):
        super().__init__(parent); self.runtime = runtime; self.automatic = automatic

    def run(self):
        try:
            root = project_root()
            if root is None:
                raise ValueError("Prepara los cambios desde la PC que tiene el proyecto y las herramientas de compilación.")
            revision = source_revision(root)
            previous = self.runtime.db.setting("fleet_manifest", {})
            remote_codes = [r.get("remote_version_code", 0) for r in self.runtime.connections.results.values() if type(r.get("remote_version_code")) is int and 0 <= r["remote_version_code"] < 2100000000]
            minimum = max([100100, *remote_codes])
            if previous.get("revision") == revision and previous.get("version_code", 0) >= minimum and all(artifact_valid(a) for a in previous.get("artifacts", {}).values()) and len(previous.get("artifacts", {})) == 2:
                self.completed.emit(previous); return
            if self.automatic:
                seen = self.runtime.db.setting("fleet_seen", {})
                if seen.get("revision") != revision:
                    self.runtime.db.set_setting("fleet_seen", {"revision": revision, "time": time.time()})
                    self.completed.emit(None); return
                if time.time() - seen["time"] < 30:
                    self.completed.emit(None); return
            code = max(minimum, self.runtime.db.setting("fleet_version_code", 100100)) + 1
            self.runtime.db.set_setting("fleet_version_code", code)
            manifest = build_local(root, self.runtime.root / "fleet", revision, code, self.progress.emit)
            self.completed.emit(manifest)
        except Exception as error:
            self.failed.emit(str(error))
