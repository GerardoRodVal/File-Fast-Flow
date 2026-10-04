from pathlib import Path
import argparse
import subprocess
import sys
from prepare_package_assets import prepare

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description="Compila FileFastFlow con los generadores EXE y APK sin conexión.")
parser.add_argument("--apk", type=Path, help="APK Android de esta versión")
parser.add_argument("--inno-dir", type=Path, help="Carpeta portátil de Inno Setup 6.7.3")
parser.add_argument("--dist-dir", type=Path, default=root / "dist", help="Carpeta de salida")
args = parser.parse_args()
prepare(args.apk, args.inno_dir)
subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--windowed",
    "--name", "FileFastFlow", "--paths", str(root), "--collect-submodules", "uvicorn",
    "--icon", str(root.parent / "assets" / "FileFastFlow.ico"),
    "--collect-submodules", "zeroconf", "--hidden-import", "PIL.Image",
    "--add-data", f"{root / 'devicedrop' / 'assets'}:devicedrop/assets",
    "--distpath", str(args.dist_dir.resolve()), "--workpath", str(root / "build"), str(root / "devicedrop" / "main.py")], cwd=root, check=True)
