"""Launch the current checkout from the desktop shortcut without a console."""
import os
from pathlib import Path
import sys
import site


windows_root = Path(__file__).resolve().parents[1]
# Use the base interpreter directly to avoid the extra process created by the
# Windows venv redirector, while loading only this project's venv dependencies.
virtualenv = windows_root / ".venv"
packages = virtualenv / "Lib" / "site-packages"
if not packages.is_dir():
    raise RuntimeError("No se encontró el entorno virtual de FileFastFlow.")
sys.prefix = sys.exec_prefix = str(virtualenv)
sys.path.insert(0, str(packages))
site.addsitedir(str(packages))
os.chdir(windows_root)
sys.path.insert(0, str(windows_root))

from devicedrop.main import main


if __name__ == "__main__":
    raise SystemExit(main() or 0)
