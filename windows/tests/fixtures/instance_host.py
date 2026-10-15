"""Isolated desktop host for real process/IPC/background-service checks."""
import json
import os
from pathlib import Path
import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from devicedrop.instance import SingleInstance
from devicedrop.runtime import Runtime
from devicedrop.ui.main_window import MainWindow


root = Path(sys.argv[1]); port = int(sys.argv[2])
app = QApplication([]); app.setQuitOnLastWindowClosed(False)
instance = SingleInstance(root)
assert instance.start_or_activate()
runtime = Runtime(root, port)
runtime.db.set_setting("onboarded", True); runtime.db.set_setting("auto_updates", False)
window = MainWindow(runtime)
window.initial_update_timer.stop(); window.update_timer.stop(); window.timer.stop()
window.show(); runtime.start(discovery=False, watching=False)
activations = 0
notification_actions = []
ready = False

def snapshot():
    data = {"pid": os.getpid(), "ready": ready, "visible": window.isVisible(),
            "activations": activations, "server_started": bool(runtime.server and runtime.server.started),
            "error": runtime.start_error, "notification_actions": notification_actions,
            "clipboard_files": [u.toLocalFile() for u in app.clipboard().mimeData().urls()] if app.clipboard().mimeData() else []}
    temp = root / "state.tmp"
    temp.write_text(json.dumps(data), encoding="utf-8"); temp.replace(root / "state.json")

def activate():
    global activations
    window.restore_window(); activations += 1; snapshot()

def tick():
    global ready
    if not ready and runtime.ready.is_set():
        ready = True; window.close(); snapshot()
    if (root / "hide").exists():
        (root / "hide").unlink(); window.close(); snapshot()
    if (root / "tray_click").exists():
        from PySide6.QtWidgets import QSystemTrayIcon
        (root / "tray_click").unlink()
        window.tray.activated.emit(QSystemTrayIcon.ActivationReason.Trigger); snapshot()
    if (root / "stop").exists():
        window.quit()

instance.activated.connect(activate)
def receipt_action(action, tid):
    window.handle_receipt_action(action, tid)
    notification_actions.append([action, tid]); snapshot()
instance.notification_requested.connect(receipt_action)
timer = QTimer(); timer.timeout.connect(tick); timer.start(30)
QTimer.singleShot(15000, window.quit)
try:
    app.exec()
finally:
    if app.platformName() == "offscreen":
        app.clipboard().clear()
    instance.close()
