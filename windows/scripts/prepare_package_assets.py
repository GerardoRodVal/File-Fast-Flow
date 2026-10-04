"""Stage the Android binary and portable Inno compiler for offline packaging."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tomllib

WINDOWS = Path(__file__).resolve().parents[1]
ASSETS = WINDOWS / "devicedrop" / "assets"
VERSION = tomllib.loads((WINDOWS / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]


def prepare(apk=None, inno_dir=None):
    if apk is not None:
        apk = Path(apk).resolve()
        if not apk.is_file():
            raise SystemExit(f"APK no encontrado: {apk}")
        target = ASSETS / "android"
        target.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(apk, target / "FileFastFlow.apk")
        data = (target / "FileFastFlow.apk").read_bytes()
        (target / "manifest.json").write_text(json.dumps({"version": VERSION, "variant": "debug",
            "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}, indent=2), encoding="utf-8")
    if inno_dir is not None:
        source = Path(inno_dir).resolve()
        if not (source / "ISCC.exe").is_file() or not (source / "license.txt").is_file():
            raise SystemExit("Indica la carpeta portátil de Inno Setup 6.7.3 con ISCC.exe y license.txt.")
        target = ASSETS / "inno"
        target.mkdir(parents=True, exist_ok=True)
        excluded = {"Compil32.exe", "ISetup.chm", "ISetup-dark.chm", "isfaq.url", "whatsnew.htm", "isscint.dll", "isscint.dll.issig"}
        for path in source.iterdir():
            if path.is_file() and path.name not in excluded:
                shutil.copyfile(path, target / path.name)
        (target / "Languages").mkdir(exist_ok=True)
        shutil.copyfile(source / "Languages" / "Spanish.isl", target / "Languages" / "Spanish.isl")
    required = [ASSETS / "android" / "FileFastFlow.apk", ASSETS / "android" / "manifest.json",
                ASSETS / "inno" / "ISCC.exe", ASSETS / "inno" / "Languages" / "Spanish.isl"]
    if any(not path.is_file() for path in required):
        raise SystemExit("Faltan los recursos de instaladores. Usa --apk <APK> --inno-dir <carpeta de Inno Setup 6.7.3>.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apk", type=Path)
    parser.add_argument("--inno-dir", type=Path)
    args = parser.parse_args()
    prepare(args.apk, args.inno_dir)
    print(f"Recursos preparados: {ASSETS}")
