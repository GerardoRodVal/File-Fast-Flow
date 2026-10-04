import hashlib
import os
import re
from pathlib import Path

CHUNK = 1024 * 1024
RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


def validate_filename(name: str) -> str:
    if (not name or len(name) > 240 or name in {".", ".."}
            or re.search(r'[<>:"/\\|?*\x00-\x1f]', name)
            or name.endswith((".", " ")) or name.split(".")[0].upper() in RESERVED):
        raise ValueError("INVALID_FILE")
    return name


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def reserve_destination(folder: Path, name: str) -> Path:
    """O_EXCL reserves a name atomically; concurrent receivers never overwrite."""
    validate_filename(name)
    folder.mkdir(parents=True, exist_ok=True)
    original = Path(name)
    for index in range(10000):
        candidate = folder / (name if index == 0 else f"{original.stem} ({index}){original.suffix}")
        try:
            fd = os.open(candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(fd)
            return candidate
        except FileExistsError:
            continue
    raise ValueError("TOO_MANY_COLLISIONS")
