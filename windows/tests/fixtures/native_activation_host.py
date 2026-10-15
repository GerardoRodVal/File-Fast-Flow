"""Exercise restoration when Windows and Qt disagree about visibility."""
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import sys
import traceback

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QApplication, QWidget
from devicedrop.window_activation import show_window


output = Path(sys.argv[1])
app = QApplication([]); app.setQuitOnLastWindowClosed(False)
window = QWidget(None, Qt.WindowType.Tool)
window.resize(260, 120); window.move(-10000, -10000)
window.show()
api = ctypes.WinDLL("user32", use_last_error=True)
for name in ("IsWindowVisible", "IsIconic", "IsZoomed"):
    method = getattr(api, name); method.argtypes = [wintypes.HWND]; method.restype = wintypes.BOOL
api.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]

def verify():
    try:
        handle = int(window.winId())
        show_window(window)
        started_visible = bool(api.IsWindowVisible(handle))
        api.ShowWindow(handle, 0)
        hidden_natively = not api.IsWindowVisible(handle)
        show_window(window)
        restored_visible = bool(api.IsWindowVisible(handle))
        window.showMinimized(); show_window(window)
        restored_minimized = not api.IsIconic(handle)
        window.showMaximized(); window.showMinimized(); show_window(window)
        preserved_maximized = bool(api.IsZoomed(handle))
        result = {"started_visible": started_visible, "hidden_natively": hidden_natively,
                  "restored_visible": restored_visible, "restored_minimized": restored_minimized,
                  "preserved_maximized": preserved_maximized}
        output.write_text(json.dumps(result), encoding="utf-8")
        app.exit(0 if all(result.values()) else 1)
    except Exception:
        output.write_text(traceback.format_exc(), encoding="utf-8"); app.exit(1)

QTimer.singleShot(0, verify)
QTimer.singleShot(5000, lambda: app.exit(2))
raise SystemExit(app.exec())
