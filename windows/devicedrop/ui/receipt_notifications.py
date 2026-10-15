"""Windows receipt actions use transfer IDs, never paths supplied by a URI."""
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlsplit
from uuid import UUID

APP_ID = "FileFastFlow.Desktop"


def notification_url(action, transfer_id):
    if action not in {"copy", "open"}:
        raise ValueError("Acción de notificación inválida.")
    return f"filefastflow://{action}/{UUID(str(transfer_id))}"


def parse_notification_url(value):
    parsed = urlsplit(value)
    if parsed.scheme != "filefastflow" or parsed.netloc not in {"copy", "open"} or parsed.query or parsed.fragment:
        raise ValueError("Notificación inválida.")
    transfer_id = str(UUID(parsed.path.removeprefix("/")))
    if parsed.path != "/" + transfer_id:
        raise ValueError("Notificación inválida.")
    return parsed.netloc, transfer_id


def register_notifications():
    import ctypes
    import winreg

    if getattr(sys, "frozen", False):
        command = subprocess.list2cmdline([sys.executable, "--notification-url"]) + ' "%1"'
        icon = Path(sys.executable)
    else:
        windows = Path(__file__).resolve().parents[2]
        launcher = windows / "scripts" / "launch_desktop.pyw"
        python = Path(sys._base_executable).with_name("pythonw.exe")
        command = subprocess.list2cmdline([str(python), "-S", str(launcher), "--notification-url"]) + ' "%1"'
        icon = windows.parent / "assets" / "FileFastFlow.ico"
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\AppUserModelId\{APP_ID}") as key:
        winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, "FileFastFlow")
        winreg.SetValueEx(key, "IconUri", 0, winreg.REG_SZ, str(icon))
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\filefastflow") as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "URL:FileFastFlow")
        winreg.SetValueEx(key, "URL Protocol", 0, winreg.REG_SZ, "")
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\filefastflow\shell\open\command") as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, command)
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)


class ReceiptNotifier:
    def __init__(self, logger):
        self.logger = logger
        self.toaster = None

    def show(self, transfer_id, filename):
        from PySide6.QtWidgets import QApplication
        if sys.platform != "win32" or QApplication.platformName() != "windows":
            return False
        try:
            from windows_toasts import InteractableWindowsToaster, Toast, ToastButton
            if self.toaster is None:
                register_notifications()
                self.toaster = InteractableWindowsToaster("FileFastFlow", APP_ID)
            toast = Toast(["Archivo recibido", filename, "Copia el archivo y pégalo donde lo necesites."],
                          launch_action=notification_url("open", transfer_id))
            toast.AddAction(ToastButton("Copiar", launch=notification_url("copy", transfer_id)))
            toast.AddAction(ToastButton("Abrir FileFastFlow", launch=notification_url("open", transfer_id)))
            self.toaster.show_toast(toast)
            return True
        except Exception:
            self.logger.exception("receipt_notification_failed")
            return False
