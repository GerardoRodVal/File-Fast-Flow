from pathlib import Path
from uuid import uuid4
from types import SimpleNamespace
import logging
import sys

import pytest
from PySide6.QtGui import QImage, QColor
from PySide6.QtWidgets import QApplication

from devicedrop.ui.clipboard import copy_file
from devicedrop.ui.receipt_notifications import notification_url, parse_notification_url, ReceiptNotifier


@pytest.fixture
def clipboard():
    app = QApplication.instance() or QApplication([])
    app.clipboard().clear()
    yield app.clipboard()
    app.clipboard().clear()


def test_copy_file_offers_file_drop_without_moving_original(clipboard, tmp_path):
    source = tmp_path / "Documento español.txt"; source.write_text("contents")
    copy_file(source)
    mime = clipboard.mimeData()
    assert Path(mime.urls()[0].toLocalFile()) == source
    assert bytes(mime.data('application/x-qt-windows-mime;value="Preferred DropEffect"')) == b"\x01\0\0\0"
    assert not mime.hasImage() and source.read_text() == "contents"


def test_copy_image_offers_pixels_and_file(clipboard, tmp_path):
    source = tmp_path / "image.png"
    image = QImage(3, 2, QImage.Format.Format_ARGB32); image.fill(QColor("#087f69")); image.save(str(source))
    copy_file(source)
    mime = clipboard.mimeData()
    assert Path(mime.urls()[0].toLocalFile()) == source
    assert mime.hasImage() and clipboard.image().pixelColor(0, 0) == QColor("#087f69")


def test_missing_file_keeps_clipboard(clipboard, tmp_path):
    clipboard.setText("previous")
    with pytest.raises(FileNotFoundError):
        copy_file(tmp_path / "missing.txt")
    assert clipboard.text() == "previous"


def test_notification_url_contains_only_action_and_transfer_id():
    tid = str(uuid4())
    assert parse_notification_url(notification_url("copy", tid)) == ("copy", tid)
    for value in ["filefastflow://copy/C:/secret.txt", f"filefastflow://copy/{tid}?path=C:/secret", f"filefastflow://other/{tid}", f"https://copy/{tid}", f"filefastflow://copy/{tid}/", f"filefastflow://open/{tid}#x"]:
        with pytest.raises(ValueError):
            parse_notification_url(value)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows toast library")
def test_receipt_has_durable_copy_and_open_buttons(clipboard, monkeypatch):
    shown = []
    notifier = ReceiptNotifier(logging.getLogger("test"))
    notifier.toaster = SimpleNamespace(show_toast=shown.append)
    monkeypatch.setattr(QApplication, "platformName", lambda: "windows")
    tid = str(uuid4())
    assert notifier.show(tid, "a & b.txt")
    toast = shown[0]
    assert toast.launch_action == notification_url("open", tid)
    assert [(button.content, button.launch) for button in toast.actions] == [
        ("Copiar", notification_url("copy", tid)), ("Abrir FileFastFlow", notification_url("open", tid))]
