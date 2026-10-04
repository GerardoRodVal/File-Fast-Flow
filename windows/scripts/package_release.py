"""Refresh release archives and SHA-256 for the current binaries and source."""
import hashlib
import json
import argparse
from pathlib import Path
import zipfile
import tomllib

root = Path(__file__).resolve().parents[2]
VERSION = tomllib.loads((root / "windows" / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--bundle-dir", type=Path, default=root / "windows" / "dist" / "FileFastFlow")
args = parser.parse_args()
release = root / "releases"
bundle = args.bundle_dir.resolve()
release.mkdir(exist_ok=True)
archive = release / "FileFastFlow-Windows-x64.zip"
with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as output:
    for path in sorted(bundle.rglob("*")):
        if path.is_file():
            output.write(path, str(Path("FileFastFlow") / path.relative_to(bundle)))
with zipfile.ZipFile(archive) as output:
    assert output.testzip() is None
    assert "FileFastFlow/FileFastFlow.exe" in output.namelist()
    assert "FileFastFlow/_internal/devicedrop/assets/inno/ISCC.exe" in output.namelist()
    assert "FileFastFlow/_internal/devicedrop/assets/android/FileFastFlow.apk" in output.namelist()

source_zip = release / "FileFastFlow-source.zip"
excluded = {".git", ".venv", "__pycache__", ".pytest_cache", ".gradle", ".idea", "build", "dist", "releases", "work"}
with zipfile.ZipFile(source_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as output:
    # Prune build/cache trees before walking; SDK caches can contain thousands of files.
    import os
    for directory, directories, names in os.walk(root):
        current = Path(directory)
        directories[:] = [name for name in directories if name not in excluded and
            not (current == root / "windows" / "devicedrop" / "assets" and name in {"android", "inno"})]
        for name in sorted(names):
            path = current / name
            if name == "local.properties" or path.suffix in {".pyc", ".spec", ".log", ".db"}:
                continue
            output.write(path, str(Path("FileFastFlow") / path.relative_to(root)))
with zipfile.ZipFile(source_zip) as output:
    assert output.testzip() is None

files = [archive, source_zip, release / f"FileFastFlow-{VERSION}-debug.apk",
         release / f"FileFastFlow-{VERSION}-Setup.exe", bundle / "FileFastFlow.exe"]
manifest = {}
for path in files:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    manifest[path.relative_to(root).as_posix()] = {"bytes": path.stat().st_size, "sha256": digest.hexdigest()}
(release / "SHA256.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
print(json.dumps(manifest, indent=2))
