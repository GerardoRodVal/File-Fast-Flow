"""Native integration: run with QT_QPA_PLATFORM=windows on a desktop session."""
import ctypes
from ctypes import wintypes

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QApplication

from devicedrop.ui.desktop_widget import DesktopWidget


@pytest.mark.parametrize("theme", ["classic", "minimal"])
def test_windows_widget_is_a_desktop_child_instead_of_a_floating_window(runtime, peer, theme):
    app = QApplication.instance() or QApplication([])
    if app.platformName() != "windows":
        pytest.skip("Requires the native Windows desktop; unavailable in offscreen mode")
    widget = DesktopWidget(runtime.db)
    try:
        widget.set_theme(theme)
        widget.refresh([peer], {}, {}, set(), {}, {})
        assert widget.show_on_desktop()
        app.processEvents()
        host = widget.desktop_host
        api = host.api
        handle = int(widget.winId())
        assert host.valid() and api.GetParent(handle) == host.handle
        get_style = api.GetWindowLongPtrW if ctypes.sizeof(ctypes.c_void_p) == 8 else api.GetWindowLongW
        get_style.argtypes = [wintypes.HWND, ctypes.c_int]
        get_style.restype = ctypes.c_ssize_t
        assert get_style(handle, -16) & 0x40000000  # WS_CHILD
        assert not get_style(handle, -16) & 0x80000000  # WS_POPUP
        assert not get_style(handle, -20) & 0x00000008  # WS_EX_TOPMOST
        assert not get_style(handle, -20) & 0x00040000  # WS_EX_APPWINDOW
        assert not widget.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
        original = widget.desktop_position()
        widget.move_on_desktop(original + QPoint(-20, 20))
        app.processEvents()
        assert widget.desktop_position() == original + QPoint(-20, 20)
        widget.save_position()
        assert runtime.db.setting("widget_position") == [original.x() - 20, original.y() + 20]
        sent = []
        widget.send_requested.connect(sent.append)
        widget.rows[peer["device_id"]].send.click()
        assert sent == [peer["device_id"]]
        widget.hide()
        assert not widget.isVisible()
        assert widget.show_on_desktop()
        assert api.GetParent(handle) == host.handle
    finally:
        widget.hide()
        widget.deleteLater()
        app.sendPostedEvents(None, 0)
        app.processEvents()
