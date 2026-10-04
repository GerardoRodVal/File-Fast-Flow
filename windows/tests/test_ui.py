from pathlib import Path
from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QCloseEvent
from PySide6.QtWidgets import QApplication
from devicedrop.ui.main_window import MainWindow

def test_drag_drop_routes_local_files_to_destination_selector(runtime, tmp_path):
    app = QApplication.instance() or QApplication([])
    window = MainWindow(runtime)
    selected = []
    window.choose_target = lambda paths: selected.extend(paths)
    path = tmp_path / "drag.txt"; path.write_text("drop")
    mime = QMimeData(); mime.setUrls([QUrl.fromLocalFile(str(path)), QUrl("https://example.invalid/remote")])
    drop = QDropEvent(QPointF(10, 10), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    window.dropEvent(drop)
    assert drop.isAccepted() and [Path(p) for p in selected] == [path]
    runtime.db.set_setting("minimize_tray", True)
    window.tray.isSystemTrayAvailable = lambda: True
    close = QCloseEvent(); window.closeEvent(close)
    assert not close.isAccepted() and not window.isVisible()
    window.timer.stop(); window.tray.hide(); runtime.bus.listeners.clear(); window.deleteLater(); app.processEvents()
