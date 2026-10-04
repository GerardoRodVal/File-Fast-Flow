"""Updates published by the project's main-branch GitHub release workflow."""
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import urlsplit

import httpx
from PySide6.QtCore import QThread, Signal

from . import __version__

REPOSITORY = "GerardoRodVal/File-Fast-Flow"
REPOSITORY_URL = f"https://github.com/{REPOSITORY}"
RELEASES_URL = f"{REPOSITORY_URL}/releases/latest"
API_URL = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
MAX_INSTALLER_SIZE = 1024**3


def version_tuple(value):
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", value)
    if not match:
        raise ValueError("La publicación no tiene una versión válida.")
    return tuple(int(part) for part in match.groups())


@dataclass(frozen=True)
class Release:
    version: str
    filename: str
    url: str
    size: int
    sha256: str
    notes: str = ""


def parse_release(data, current_version=__version__):
    if data.get("draft") or data.get("prerelease"):
        return None
    version = data.get("tag_name", "")
    if version_tuple(version) <= version_tuple(current_version):
        return None
    filename = f"FileFastFlow-{version.removeprefix('v')}-Setup.exe"
    asset = next((item for item in data.get("assets", []) if item.get("name") == filename and item.get("state") == "uploaded"), None)
    if not asset:
        raise ValueError("La nueva versión todavía no tiene un instalador Windows disponible.")
    expected_url = f"{REPOSITORY_URL}/releases/download/{version}/{filename}"
    if asset.get("browser_download_url") != expected_url:
        raise ValueError("El instalador no pertenece al repositorio de FileFastFlow.")
    digest = asset.get("digest") or ""
    if not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", digest):
        raise ValueError("GitHub todavía no ofrece el SHA-256 del instalador. Inténtalo más tarde.")
    size = asset.get("size")
    if type(size) is not int or not 0 < size <= MAX_INSTALLER_SIZE:
        raise ValueError("El tamaño del instalador no es válido.")
    return Release(version.removeprefix("v"), filename, expected_url, size, digest[7:].lower(), (data.get("body") or "")[:12000])


def check_latest(client, current_version=__version__):
    response = client.get(API_URL)
    if response.status_code == 404:
        return None
    if response.status_code == 403:
        raise ValueError("GitHub limitó las consultas. Inténtalo más tarde.")
    response.raise_for_status()
    return parse_release(response.json(), current_version)


def verify_installer(path, release):
    path = Path(path)
    if not path.is_file() or path.stat().st_size != release.size:
        raise ValueError("El instalador está incompleto. Descárgalo de nuevo.")
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != release.sha256:
        raise ValueError("La verificación SHA-256 falló. Descarga el instalador de nuevo.")


def download_installer(client, release, destination, progress=None, cancelled=lambda: False):
    # Validate again even if callers construct Release directly.
    expected = f"{REPOSITORY_URL}/releases/download/v{release.version}/{release.filename}"
    alternative = f"{REPOSITORY_URL}/releases/download/{release.version}/{release.filename}"
    if release.url not in (expected, alternative) or release.filename != f"FileFastFlow-{release.version}-Setup.exe":
        raise ValueError("URL de actualización inválida.")
    version_tuple(release.version)
    if not 0 < release.size <= MAX_INSTALLER_SIZE or not re.fullmatch(r"[0-9a-f]{64}", release.sha256):
        raise ValueError("Metadatos de actualización inválidos.")
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        try:
            verify_installer(destination, release)
            if progress:
                progress(100)
            return destination
        except ValueError:
            pass
    with tempfile.TemporaryDirectory(prefix=".filefastflow-update-", dir=destination.parent) as directory:
        partial = Path(directory) / "installer.part"
        received = 0
        digest = hashlib.sha256()
        with client.stream("GET", release.url, follow_redirects=True) as response:
            response.raise_for_status()
            if response.url.scheme != "https":
                raise ValueError("La descarga requiere HTTPS.")
            with partial.open("wb") as target:
                for chunk in response.iter_bytes(1024 * 1024):
                    if cancelled():
                        raise ValueError("Descarga cancelada.")
                    received += len(chunk)
                    if received > release.size:
                        raise ValueError("El tamaño descargado no coincide con la publicación.")
                    target.write(chunk)
                    digest.update(chunk)
                    if progress:
                        progress(min(99, received * 100 // release.size))
        if cancelled():
            raise ValueError("Descarga cancelada.")
        if received != release.size or digest.hexdigest() != release.sha256:
            raise ValueError("La verificación SHA-256 o de tamaño falló. Inténtalo de nuevo.")
        os.replace(partial, destination)
    if progress:
        progress(100)
    return destination


def require_https(request):
    address = urlsplit(str(request.url))
    if address.scheme != "https" or address.hostname not in {
        "api.github.com", "github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"
    }:
        raise ValueError("Servidor de actualización no permitido.")


class UpdateWorker(QThread):
    checked = Signal(object)
    downloaded = Signal(str)
    failed = Signal(str)
    progress = Signal(int)

    def __init__(self, release=None, destination=None, parent=None):
        super().__init__(parent)
        self.release = release
        self.destination = destination

    def run(self):
        try:
            with httpx.Client(timeout=httpx.Timeout(30, connect=10), headers={
                "User-Agent": f"FileFastFlow/{__version__}", "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2026-03-10"
            }, event_hooks={"request": [require_https]}) as client:
                if self.release is None:
                    self.checked.emit(check_latest(client))
                else:
                    path = download_installer(client, self.release, self.destination, self.progress.emit, self.isInterruptionRequested)
                    self.downloaded.emit(str(path))
        except (httpx.HTTPError, OSError, ValueError, TypeError, KeyError) as error:
            self.failed.emit(str(error))
