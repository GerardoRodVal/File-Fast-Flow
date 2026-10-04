"""Stamp both platforms with a monotonically increasing CI release version."""
import argparse
from pathlib import Path
import re
import tomllib


def stamp(root, run_number):
    if run_number < 1:
        raise ValueError("run_number must be positive")
    project = root / "windows" / "pyproject.toml"
    base = tomllib.loads(project.read_text(encoding="utf-8"))["project"]["version"]
    major, minor, patch = map(int, base.split("."))
    version = f"{major}.{minor}.{patch + run_number}"
    project.write_text(re.sub(r'^version = "[^"]+"', f'version = "{version}"', project.read_text(encoding="utf-8"), flags=re.M), encoding="utf-8")
    (root / "windows" / "devicedrop" / "__init__.py").write_text(f'__version__ = "{version}"\n', encoding="utf-8")
    gradle = root / "android" / "app" / "build.gradle.kts"
    text = re.sub(r'versionCode = \d+', f'versionCode = {100000 + run_number}', gradle.read_text(encoding="utf-8"))
    text = re.sub(r'versionName = "[^"]+"', f'versionName = "{version}"', text)
    gradle.write_text(text, encoding="utf-8")
    return version


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_number", type=int)
    args = parser.parse_args()
    print(stamp(Path(__file__).resolve().parents[2], args.run_number))
