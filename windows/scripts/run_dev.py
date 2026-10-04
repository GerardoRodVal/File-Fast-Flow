from pathlib import Path
import subprocess
import sys

subprocess.run([sys.executable, "-m", "devicedrop.main", *sys.argv[1:]], cwd=Path(__file__).resolve().parents[1], check=True)
