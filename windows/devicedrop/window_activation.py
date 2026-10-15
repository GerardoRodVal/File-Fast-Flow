"""Restore application windows and hand off foreground permission on Windows."""
import sys


def grant_foreground_permission(process_id):
    if sys.platform != "win32" or process_id <= 0:
        return
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.AllowSetForegroundWindow.argtypes = [wintypes.DWORD]
        user32.AllowSetForegroundWindow.restype = wintypes.BOOL
        user32.AllowSetForegroundWindow(process_id)
    except (OSError, AttributeError):
        # Qt still restores the window if foreground permission isn't available.
        pass


def show_window(window):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    if window.windowState() & Qt.WindowState.WindowMaximized:
        window.showMaximized()
    else:
        window.showNormal()
    window.raise_(); window.activateWindow()
    if sys.platform == "win32" and QApplication.platformName() == "windows":
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
            user32.ShowWindow.restype = wintypes.BOOL
            user32.SetForegroundWindow.argtypes = [wintypes.HWND]
            user32.SetForegroundWindow.restype = wintypes.BOOL
            handle = int(window.winId())
            # A hidden startup flag or native hide can disagree with Qt's
            # visibility state. Explicitly show the native window as well.
            user32.ShowWindow(handle, 3 if window.isMaximized() else 9)
            user32.SetForegroundWindow(handle)
        except (OSError, AttributeError):
            pass


def restore_application_window(main_window, app):
    # Restore the main window even when a modal dialog owns keyboard focus.
    if main_window is not None:
        show_window(main_window)
    dialog = app.activeModalWidget()
    if dialog is not None and dialog is not main_window:
        show_window(dialog)
    elif main_window is None and app.activeWindow() is not None:
        show_window(app.activeWindow())
