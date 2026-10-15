import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.skipif(sys.platform != "win32", reason="Windows native window restoration")
def test_native_hidden_startup_and_restore_keep_window_visible(tmp_path):
    windows = Path(__file__).resolve().parents[1]
    env = {**os.environ, "QT_QPA_PLATFORM": "windows", "PYTHONPATH": os.pathsep.join(
        [str(windows), str(windows / ".venv" / "Lib" / "site-packages")])}
    pythonw = Path(getattr(sys, "_base_executable", sys.executable)).with_name("pythonw.exe")
    output = tmp_path / "visibility.json"
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW; startup.wShowWindow = 0
    process = subprocess.run([str(pythonw), "-S", str(windows / "tests" / "fixtures" / "native_activation_host.py"),
                              str(output)], env=env, startupinfo=startup, timeout=10)
    assert process.returncode == 0, output.read_text() if output.exists() else "La prueba nativa no generó un resultado."
    assert all(json.loads(output.read_text()).values())
