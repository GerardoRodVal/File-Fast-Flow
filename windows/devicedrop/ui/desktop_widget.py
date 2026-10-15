"""Compact desktop controls sharing the main window's devices and services."""
import logging
from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel,
                               QLayout, QScrollArea, QToolButton, QVBoxLayout, QWidget)
from devicedrop.ui.desktop_host import DesktopHost


def action_icon(kind, color="#087f69"):
    pixmap = QPixmap(24, 24)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor(color), 2))
    if kind == "validate":
        painter.drawEllipse(3, 3, 18, 18)
        painter.drawLine(7, 12, 10, 15)
        painter.drawLine(10, 15, 17, 8)
    elif kind == "send":
        painter.drawLine(12, 17, 12, 3)
        painter.drawLine(12, 3, 6, 9)
        painter.drawLine(12, 3, 18, 9)
        painter.drawPolyline([QPoint(4, 15), QPoint(4, 21), QPoint(20, 21), QPoint(20, 15)])
    elif kind == "folder":
        painter.drawPolyline([QPoint(3, 8), QPoint(3, 4), QPoint(9, 4), QPoint(12, 7),
                              QPoint(21, 7), QPoint(21, 20), QPoint(3, 20), QPoint(3, 8), QPoint(21, 8)])
    else:
        painter.drawEllipse(10, 4, 3, 3)
        painter.drawEllipse(10, 11, 3, 3)
        painter.drawEllipse(10, 18, 3, 3)
    painter.end()
    return QIcon(pixmap)


def quick_button(kind, text, callback):
    control = QToolButton()
    control.setIcon(action_icon(kind))
    control.setToolTip(text)
    control.setAccessibleName(text)
    control.setCursor(Qt.CursorShape.PointingHandCursor)
    control.setFixedSize(34, 34)
    control.clicked.connect(callback)
    return control


class DragHeader(QFrame):
    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.window().open_requested.emit()
            event.accept()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.offset = event.globalPosition().toPoint() - self.window().desktop_position()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton and hasattr(self, "offset"):
            self.window().move_on_desktop(event.globalPosition().toPoint() - self.offset)
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.window().keep_on_screen()
            self.window().save_position()
            event.accept()


class DeviceRow(QFrame):
    def __init__(self, device_id, validate, send, open_folder):
        super().__init__()
        self.setObjectName("deviceRow")
        layout = QHBoxLayout(self)
        self.compact = False
        self.full_name = self.full_status = ""
        self.status_color = "#87958f"
        layout.setContentsMargins(12, 10, 10, 10)
        self.dot = QLabel()
        self.dot.setFixedSize(10, 10)
        layout.addWidget(self.dot)
        text = QVBoxLayout()
        text.setSpacing(3)
        self.name = QLabel()
        self.name.setTextFormat(Qt.TextFormat.PlainText)
        self.name.setObjectName("deviceName")
        self.status = QLabel()
        self.status.setObjectName("deviceStatus")
        text.addWidget(self.name)
        text.addWidget(self.status)
        layout.addLayout(text, 1)
        self.validate = quick_button("validate", "Validar conexión", lambda: validate(device_id))
        self.send = quick_button("send", "Enviar archivo", lambda: send(device_id))
        self.folder = quick_button("folder", "Abrir carpeta compartida", lambda: open_folder(device_id))
        layout.addWidget(self.validate)
        layout.addWidget(self.send)
        layout.addWidget(self.folder)

    def set_compact(self, compact):
        self.compact = compact
        self.layout().setContentsMargins(*((7, 2, 5, 2) if compact else (12, 10, 10, 10)))
        self.layout().setSpacing(5 if compact else 6)
        self.status.setVisible(not compact)
        self.dot.setFixedSize(6 if compact else 10, 6 if compact else 10)
        for control in (self.validate, self.send, self.folder):
            control.setFixedSize(22 if compact else 34, 22 if compact else 34)
            control.setIconSize(QSize(14, 14) if compact else QSize(16, 16))
        self.setFixedHeight(28 if compact else 74)
        self.update_text()

    def update_text(self):
        width = 145 if self.compact else 180
        self.ensurePolished()
        self.name.setText(self.name.fontMetrics().elidedText(self.full_name, Qt.TextElideMode.ElideRight, width))
        self.status.setText(self.status.fontMetrics().elidedText(self.full_status, Qt.TextElideMode.ElideRight, width))
        radius = 3 if self.compact else 5
        self.dot.setStyleSheet(f"background: {self.status_color}; border-radius: {radius}px;")

    def update_device(self, peer, status, color, checking, busy, message):
        self.full_name, self.full_status, self.status_color = peer["name"], status, color
        self.update_text()
        self.name.setToolTip(f"{peer['name']} · {status}\n{peer['platform']} · {peer['ip']}:{peer['port']}")
        self.status.setToolTip(status)
        self.dot.setToolTip(status)
        self.dot.setAccessibleName(status)
        self.validate.setEnabled(not checking)
        self.send.setEnabled(not busy)
        self.send.setToolTip(message or "Enviar archivo")
        self.folder.setToolTip(f"Abrir archivos compartidos de {peer['name']}")
        self.folder.setAccessibleName(self.folder.toolTip())
        self.setToolTip(f"{status}\n{message}" if message else status)


class DesktopWidget(QWidget):
    validate_requested = Signal(str)
    send_requested = Signal(str)
    folder_requested = Signal(str)
    settings_requested = Signal()
    open_requested = Signal()
    disable_requested = Signal()

    def __init__(self, db):
        # The native window is embedded in Explorer, independently of the app.
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self.db = db
        self.desktop_host = None
        self.desktop_attach_failed = False
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.rows = {}
        self.dark = False
        self.theme = "minimal" if db.setting("widget_theme") == "minimal" else "classic"
        self.setWindowTitle("File Fast Flow · Widget")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(390)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.surface = QFrame()
        self.surface.setObjectName("widgetSurface")
        outer.addWidget(self.surface)
        layout = QVBoxLayout(self.surface)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        header = DragHeader()
        header.setCursor(Qt.CursorShape.SizeAllCursor)
        header.setToolTip("Arrastra para mover el widget · Doble clic para abrir FileFastFlow")
        self.header = header
        controls = QHBoxLayout(header)
        controls.setContentsMargins(4, 0, 0, 0)
        title = QLabel("File Fast Flow")
        title.setObjectName("widgetTitle")
        title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.title = title
        controls.addWidget(title, 1)
        self.settings_button = quick_button("settings", "Configuración del widget", self.settings_requested.emit)
        controls.addWidget(self.settings_button)
        layout.addWidget(header)
        self.summary = QLabel("Dispositivos vinculados")
        self.summary.setObjectName("deviceStatus")
        layout.addWidget(self.summary)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        self.devices = QVBoxLayout(content)
        self.devices.setSizeConstraint(QLayout.SizeConstraint.SetMinAndMaxSize)
        self.devices.setContentsMargins(0, 0, 0, 0)
        self.devices.setSpacing(6)
        self.empty = QLabel("Aún no hay dispositivos vinculados.\nAbre la app para agregar uno.")
        self.empty.setWordWrap(True)
        self.devices.addWidget(self.empty)
        self.scroll.setWidget(content)
        layout.addWidget(self.scroll)
        self.activity = QLabel()
        self.activity.setObjectName("deviceStatus")
        self.activity.setWordWrap(True)
        self.activity.hide()
        layout.addWidget(self.activity)
        self.open_button = QToolButton()
        self.open_button.setText("Abrir FileFastFlow  →")
        self.open_button.clicked.connect(self.open_requested.emit)
        layout.addWidget(self.open_button)
        self.restore_position()

    def show_activity(self, text):
        self.activity.setText(text)
        self.activity.setVisible(bool(text))
        self.adjustSize()
        self.keep_on_screen()

    def refresh(self, peers, online, results, checking, messages, busy):
        ids = {peer["device_id"] for peer in peers}
        for device_id in self.rows.keys() - ids:
            row = self.rows.pop(device_id)
            self.devices.removeWidget(row)
            row.hide()
            row.deleteLater()
        self.empty.setVisible(not peers)
        connected = sum(bool(online.get(device_id)) for device_id in ids)
        self.summary.setText(f"{connected} de {len(peers)} conectados")
        self.title.setToolTip(self.summary.text())
        for peer in peers:
            device_id = peer["device_id"]
            if device_id not in self.rows:
                row = DeviceRow(device_id, self.validate_requested.emit, self.send_requested.emit,
                                self.folder_requested.emit)
                self.rows[device_id] = row
                self.devices.addWidget(row)
                row.set_compact(self.theme == "minimal")
                self.apply_row_icons(row)
            result = results.get(device_id, {})
            if device_id in checking:
                status, color = "Validando conexión…", "#d08a16"
            elif not online.get(device_id):
                status, color = ("Sin conexión", "#d84a4a") if device_id in online else ("Sin comprobar", "#87958f")
            elif result.get("reverse_online") is False:
                status, color = "Conexión en un solo sentido", "#d08a16"
            elif result.get("remote_receiving") is False:
                status, color = "Recepción remota pausada", "#d08a16"
            else:
                status, color = "Conectado", "#169b73"
            self.rows[device_id].update_device(peer, status, color, device_id in checking,
                                               device_id in busy, messages.get(device_id, ""))
        self.resize_for_devices()

    def resize_for_devices(self):
        compact = self.theme == "minimal"
        self.scroll.setFixedHeight(min(280, len(self.rows) * 28) if compact and self.rows
                                   else (48 if compact else min(310, max(76, len(self.rows) * 78))))
        self.devices.invalidate()
        self.devices.activate()
        self.surface.layout().invalidate()
        self.surface.layout().activate()
        self.layout().invalidate()
        self.layout().activate()
        self.adjustSize()
        self.keep_on_screen()

    def set_theme(self, theme):
        self.theme = theme if theme in {"classic", "minimal"} else "classic"
        self.apply_theme(self.dark)

    def apply_theme(self, dark):
        self.dark = dark
        compact = self.theme == "minimal"
        background, foreground, card, muted = (("#15221f", "#e6eee9", "#22342e", "#a8bcb4")
            if dark else ("#f5f8f7", "#18312e", "#ffffff", "#6c807b"))
        self.setStyleSheet(f"""
            QWidget {{ background: transparent; color: {foreground}; font-family: 'Segoe UI'; font-size: 12px; }}
            QFrame#widgetSurface {{ background: {background}; }}
            QFrame#deviceRow {{ background: {card}; border-radius: 10px; }}
            QFrame#deviceRow QLabel {{ background: transparent; }}
            QLabel#widgetTitle {{ font-size: 17px; font-weight: 700; }}
            QLabel#deviceName {{ font-size: 13px; font-weight: 600; }}
            QLabel#deviceStatus {{ color: {muted}; font-size: 11px; }}
            QScrollArea {{ border: 0; }}
            QToolButton {{ border: 0; border-radius: 7px; padding: 5px; }}
            QToolButton:hover {{ background: {'#37574a' if dark else '#cce6dc'}; }}
            QToolButton:disabled {{ background: {background}; color: {muted}; }}
        """)
        if compact:
            self.setStyleSheet("""
                QWidget { background: transparent; color: #ece9e3; font-family: 'Segoe UI'; font-size: 11px; }
                QFrame#widgetSurface { background: rgba(16, 15, 13, 220); border: 1px solid #615b50; border-radius: 6px; }
                QFrame#deviceRow { border: 0; border-bottom: 1px solid #8a6a24; border-radius: 0; }
                QLabel#widgetTitle { color: #e3dfd6; font-size: 11px; font-weight: 600; }
                QLabel#deviceName { font-size: 11px; font-weight: 400; }
                QLabel#deviceStatus { color: #bcb6a8; font-size: 10px; }
                QScrollArea { border: 0; }
                QToolButton { border: 0; border-radius: 3px; padding: 0; }
                QToolButton:hover { background: rgba(255, 255, 255, 28); }
                QToolButton:disabled { color: #7d786f; }
                QScrollBar:vertical { width: 6px; background: transparent; }
                QScrollBar::handle:vertical { background: #615b50; min-height: 16px; }
                QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
            """)
        self.setFixedWidth(280 if compact else 390)
        self.surface.layout().setContentsMargins(*((5, 3, 5, 5) if compact else (10, 10, 10, 10)))
        self.surface.layout().setSpacing(2 if compact else 8)
        self.devices.setSpacing(0 if compact else 6)
        self.header.layout().setContentsMargins(20 if compact else 4, 0, 0, 0)
        self.title.setText("File Fast Flow")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter if compact else Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.settings_button.setFixedSize(20 if compact else 34, 20 if compact else 34)
        self.settings_button.setIconSize(QSize(12, 12) if compact else QSize(16, 16))
        self.summary.setVisible(not compact)
        self.open_button.setVisible(not compact)
        self.empty.setText("Sin dispositivos vinculados.\nDoble clic para abrir FileFastFlow." if compact
                           else "Aún no hay dispositivos vinculados.\nAbre la app para agregar uno.")
        color = "#d4c3a1" if compact else ("#58d7b2" if dark else "#087f69")
        self.settings_button.setIcon(action_icon("settings", color))
        for row in self.rows.values():
            row.set_compact(compact)
            self.apply_row_icons(row)
        self.resize_for_devices()

    def apply_row_icons(self, row):
        color = "#d4c3a1" if self.theme == "minimal" else ("#58d7b2" if self.dark else "#087f69")
        row.validate.setIcon(action_icon("validate", color))
        row.send.setIcon(action_icon("send", color))
        row.folder.setIcon(action_icon("folder", color))

    def show_on_desktop(self):
        if QApplication.platformName() == "windows":
            if self.desktop_host is None or not self.desktop_host.valid():
                position = self.desktop_position()
                if self.desktop_host is not None:
                    position = QPoint(*self.db.setting("widget_position", [position.x(), position.y()]))
                self.hide()
                if self.desktop_host is not None:
                    self.windowHandle().setParent(None)
                    self.desktop_host.window.deleteLater()
                    self.desktop_host = None
                self.desktop_host = DesktopHost.attach(self)
                if self.desktop_host is None:
                    if not self.desktop_attach_failed:
                        logging.getLogger("devicedrop").warning("desktop_widget_attach_failed")
                    self.desktop_attach_failed = True
                    return False
                self.desktop_attach_failed = False
                self.move_on_desktop(position)
                self.keep_on_screen()
        if not self.isVisible():
            self.show()
        return True

    def desktop_position(self):
        origin = self.desktop_host.origin() if self.desktop_host and self.desktop_host.valid() else QPoint()
        return self.pos() + origin

    def move_on_desktop(self, point):
        origin = self.desktop_host.origin() if self.desktop_host and self.desktop_host.valid() else QPoint()
        self.move(point - origin)

    def keep_on_screen(self):
        screens = QApplication.screens()
        position = self.desktop_position()
        screen = next((s for s in screens if s.availableGeometry().contains(QRect(position, self.size()).center())),
                      QApplication.primaryScreen())
        if screen:
            area = screen.availableGeometry()
            self.move_on_desktop(QPoint(max(area.left(), min(position.x(), area.right() - self.width() + 1)),
                                       max(area.top(), min(position.y(), area.bottom() - self.height() + 1))))

    def restore_position(self):
        position = self.db.setting("widget_position")
        if isinstance(position, list) and len(position) == 2 and all(type(v) is int for v in position):
            self.move_on_desktop(QPoint(*position))
        else:
            self.reset_position()
        self.keep_on_screen()

    def reset_position(self):
        screen = QApplication.primaryScreen()
        if screen:
            area = screen.availableGeometry()
            self.move_on_desktop(QPoint(area.right() - self.width() - 18, area.top() + 40))
        self.save_position()

    def save_position(self):
        position = self.desktop_position()
        self.db.set_setting("widget_position", [position.x(), position.y()])

    def closeEvent(self, event):
        self.disable_requested.emit()
        event.accept()
