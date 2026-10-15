from pathlib import Path

from PySide6.QtCore import QMimeData, QUrl
from PySide6.QtGui import QImageReader
from PySide6.QtWidgets import QApplication


def copy_file(path):
    """Offer a file drop for Explorer and image pixels for image-aware apps."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError("El archivo ya no está en su carpeta de recepción.")
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path.resolve()))])
    mime.setData('application/x-qt-windows-mime;value="Preferred DropEffect"', b"\x01\x00\x00\x00")
    reader = QImageReader(str(path))
    if reader.canRead():
        image = reader.read()
        if not image.isNull():
            mime.setImageData(image)
    QApplication.clipboard().setMimeData(mime)
