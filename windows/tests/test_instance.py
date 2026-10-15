import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import time
from uuid import uuid4

from devicedrop.runtime import Runtime


WINDOWS = Path(__file__).resolve().parents[1]


def wait_state(root, predicate):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        try:
            data = json.loads((root / "state.json").read_text(encoding="utf-8"))
            if predicate(data):
                return data
        except (FileNotFoundError, json.JSONDecodeError, PermissionError):
            pass
        time.sleep(.03)
    raise AssertionError("La instancia no alcanzó el estado esperado.")


def free_lan_port():
    for port in range(45970, 45985):
        with socket.socket() as listener:
            try:
                listener.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise AssertionError("No hay un puerto LAN libre para la prueba.")


def test_relaunch_restores_one_process_without_reopening_database_and_close_keeps_lan(tmp_path):
    root = tmp_path / "instance"
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen",
           "PYTHONPATH": os.pathsep.join([str(WINDOWS), str(WINDOWS / ".venv" / "Lib" / "site-packages")])}
    # Launch the base interpreter, matching the desktop shortcut's single process.
    python = getattr(sys, "_base_executable", sys.executable)
    host = subprocess.Popen([python, "-S", str(WINDOWS / "tests" / "fixtures" / "instance_host.py"),
                             str(root), str(free_lan_port())], env=env)
    try:
        first = wait_state(root, lambda state: state["ready"])
        assert not first["visible"] and first["server_started"] and not first["error"]
        assert first["pid"] == host.pid
        with sqlite3.connect(root / "devicedrop.db") as db:
            db.execute("INSERT INTO transfers (transfer_id,status) VALUES ('sentinel','queued')")
        command = [python, "-S", str(WINDOWS / "scripts" / "launch_desktop.pyw"), "--data-dir", str(root)]
        secondary = subprocess.run(command, env=env, timeout=10)
        assert secondary.returncode == 0
        restored = wait_state(root, lambda state: state["activations"] == 1)
        assert restored["visible"] and restored["pid"] == first["pid"] and host.poll() is None
        with sqlite3.connect(root / "devicedrop.db") as db:
            assert db.execute("SELECT status FROM transfers WHERE transfer_id='sentinel'").fetchone()[0] == "queued"
        (root / "hide").touch()
        hidden = wait_state(root, lambda state: not state["visible"])
        assert hidden["server_started"]
        (root / "tray_click").touch()
        assert wait_state(root, lambda state: state["visible"])["pid"] == first["pid"]
        (root / "hide").touch()
        wait_state(root, lambda state: not state["visible"])
        assert subprocess.run(command, env=env, timeout=10).returncode == 0
        assert wait_state(root, lambda state: state["activations"] == 2)["visible"]
    finally:
        root.mkdir(parents=True, exist_ok=True); (root / "stop").touch()
        try:
            host.wait(timeout=10)
        except subprocess.TimeoutExpired:
            host.kill(); host.wait()
    assert host.returncode == 0
    assert not (root / "desktop.lock").exists()


def test_launcher_starts_main_window_when_no_process_exists(tmp_path):
    root = tmp_path / "cold-start"
    runtime = Runtime(root, free_lan_port())
    runtime.db.set_setting("onboarded", True); runtime.db.set_setting("widget_enabled", False)
    port = runtime.port; runtime.db.close()
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    python = getattr(sys, "_base_executable", sys.executable)
    command = [python, "-S", str(WINDOWS / "scripts" / "launch_desktop.pyw"),
               "--data-dir", str(root), "--port", str(port), "--smoke-test"]
    result = subprocess.run(command, env=env, timeout=15)
    assert result.returncode == 0
    assert json.loads((root / "smoke_result.json").read_text()) == {"ui_started": True, "server_started": True}
    assert (root / "windows-smoke.png").is_file()
    assert not (root / "desktop.lock").exists()


def test_occupied_lan_port_reports_conflict_without_hanging(tmp_path):
    port = free_lan_port()
    with socket.socket() as listener:
        if os.name == "nt":
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        listener.bind(("0.0.0.0", port)); listener.listen()
        runtime = Runtime(tmp_path / "conflict", port)
        try:
            runtime.start(discovery=False, watching=False)
            assert runtime.ready.wait(5)
            assert runtime.stopped.wait(5)
            assert runtime.start_error == "PORT_IN_USE"
            assert not runtime.server.started
        finally:
            runtime.stop()


def test_notification_copy_reuses_hidden_instance_without_opening_database(tmp_path):
    root = tmp_path / "copy-instance"
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen",
           "PYTHONPATH": os.pathsep.join([str(WINDOWS), str(WINDOWS / ".venv" / "Lib" / "site-packages")])}
    python = getattr(sys, "_base_executable", sys.executable)
    host = subprocess.Popen([python, "-S", str(WINDOWS / "tests" / "fixtures" / "instance_host.py"), str(root), str(free_lan_port())], env=env)
    try:
        first = wait_state(root, lambda state: state["ready"])
        source = root / "shared" / "received.txt"; source.write_text("copy me")
        tid = str(uuid4())
        with sqlite3.connect(root / "devicedrop.db") as db:
            db.execute("INSERT INTO transfers (transfer_id,direction,status,saved_path,filename,size,source_device,mime_type,started_at,completed_at) VALUES (?,'incoming','completed',?,'received.txt',7,?,'text/plain',?,?)", (tid, str(source), str(uuid4()), time.time(), time.time()))
            db.execute("INSERT INTO transfers (transfer_id,status) VALUES ('sentinel','queued')")
        command = [python, "-S", str(WINDOWS / "scripts" / "launch_desktop.pyw"), "--data-dir", str(root), "--notification-url", f"filefastflow://copy/{tid}"]
        assert subprocess.run(command, env=env, timeout=10).returncode == 0
        state = wait_state(root, lambda data: len(data["notification_actions"]) == 1)
        assert not state["visible"] and state["pid"] == host.pid
        assert [Path(p) for p in state["clipboard_files"]] == [source]
        with sqlite3.connect(root / "devicedrop.db") as db:
            assert db.execute("SELECT status FROM transfers WHERE transfer_id='sentinel'").fetchone()[0] == "queued"
        command[-1] = f"filefastflow://open/{tid}"
        assert subprocess.run(command, env=env, timeout=10).returncode == 0
        assert wait_state(root, lambda data: len(data["notification_actions"]) == 2)["visible"]
        assert host.poll() is None
    finally:
        (root / "stop").touch()
        try:
            host.wait(timeout=10)
        except subprocess.TimeoutExpired:
            host.kill(); host.wait()
    assert host.returncode == 0
