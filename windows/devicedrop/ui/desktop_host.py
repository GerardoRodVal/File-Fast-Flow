"""Embed a Qt window in Explorer's desktop, above its icons and below apps."""
import ctypes
from ctypes import wintypes

from PySide6.QtCore import QPoint
from PySide6.QtGui import QWindow


class DesktopHost:
    def __init__(self, handle, window, api):
        self.handle = handle
        self.window = window
        self.api = api

    @staticmethod
    def windows_api():
        api = ctypes.WinDLL("user32", use_last_error=True)
        api.FindWindowExW.argtypes = [wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR]
        api.FindWindowExW.restype = wintypes.HWND
        api.GetParent.argtypes = [wintypes.HWND]
        api.GetParent.restype = wintypes.HWND
        api.IsWindow.argtypes = [wintypes.HWND]
        api.IsWindow.restype = wintypes.BOOL
        return api

    @classmethod
    def attach(cls, widget):
        api = cls.windows_api()
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        api.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
        api.EnumWindows.restype = wintypes.BOOL
        views = []

        @callback_type
        def find_view(handle, _):
            view = api.FindWindowExW(handle, None, "SHELLDLL_DefView", None)
            if view:
                views.append(view)
                return False
            return True

        api.EnumWindows(find_view, 0)
        if not views:
            return None
        # Let Qt manage native parenting and the WS_CHILD/WS_POPUP styles.
        # The foreign QWindow does not own or destroy Explorer's native window.
        parent = QWindow.fromWinId(views[0])
        if parent is None:
            return None
        widget.winId()
        widget.windowHandle().setParent(parent)
        if api.GetParent(int(widget.winId())) != views[0]:
            widget.windowHandle().setParent(None)
            parent.deleteLater()
            return None
        widget.destroyed.connect(parent.deleteLater)
        return cls(views[0], parent, api)

    def valid(self):
        return bool(self.api.IsWindow(self.handle))

    def origin(self):
        # Keep all saved positions in Qt's logical desktop coordinates.
        return self.window.mapToGlobal(QPoint(0, 0))
