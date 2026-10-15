"""Connection bubbles arranged around this computer."""
import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout, QSizePolicy


CONNECTED = "#169b73"
WARNING = "#d08a16"
OFFLINE = "#d84a4a"
UNKNOWN = "#87958f"


def connection_state(device_id, online, results, checking):
    result = results.get(device_id, {})
    if device_id in checking:
        return "Validando…", WARNING
    if not online.get(device_id):
        return ("Sin conexión", OFFLINE) if device_id in online else ("Sin comprobar", UNKNOWN)
    if result.get("reverse_online") is False:
        return "Un solo sentido", WARNING
    if result.get("remote_receiving") is False:
        return "Recepción pausada", WARNING
    return "Conectado", CONNECTED


class DeviceBubble(QWidget):
    def __init__(self, parent, primary=False):
        super().__init__(parent)
        self.primary = primary; self.color = UNKNOWN; self.full_name = ""
        self.setObjectName("deviceBubble")
        self.setStyleSheet("""
            QWidget#deviceBubble { background: transparent; }
            QLabel { background: transparent; color: white; }
            QPushButton { background: rgba(255,255,255,35); color: white;
                border: 1px solid rgba(255,255,255,70); border-radius: 10px;
                padding: 2px 7px; font-size: 11px; }
            QPushButton:hover { background: rgba(255,255,255,70); }
            QPushButton:disabled { color: #dce5e0; background: transparent; }
        """)
        self.box = QVBoxLayout(self); self.box.setSpacing(3)
        self.box.addStretch()
        self.name = QLabel(); self.name.setTextFormat(Qt.TextFormat.PlainText)
        self.platform = QLabel(); self.status = QLabel(); self.address = QLabel()
        for text in (self.name, self.platform, self.status, self.address):
            text.setTextFormat(Qt.TextFormat.PlainText)
            text.setAlignment(Qt.AlignmentFlag.AlignCenter)
            text.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            self.box.addWidget(text)
        self.platform.setWordWrap(True); self.status.setWordWrap(True)
        self.actions = QHBoxLayout(); self.actions.setSpacing(4)
        self.box.addLayout(self.actions); self.box.addStretch()

    def add_action(self, text, callback):
        control = QPushButton(text); control.setCursor(Qt.CursorShape.PointingHandCursor)
        control.clicked.connect(callback); self.actions.addWidget(control)
        return control

    def update_device(self, name, platform, address, status, color):
        self.full_name = name; self.platform.setText(platform)
        self.address.setText(address); self.status.setText(status); self.color = color
        self.status.setToolTip(status); self.address.setToolTip(address)
        self.setAccessibleName(f"{name}, {platform}, {status}, {address}")
        self.fit_text(); self.update()

    def fit_text(self):
        compact = self.width() < 175
        self.box.setContentsMargins(int(self.width() * .13), int(self.height() * .15),
                                   int(self.width() * .13), int(self.height() * .15))
        self.box.setSpacing(2 if compact else 4)
        self.name.setStyleSheet(f"font-size: {13 if compact else 16}px; font-weight: 700;")
        for text in (self.platform, self.status, self.address):
            text.setStyleSheet(f"font-size: {10 if compact else 12}px;")
        available = int(self.width() * .74)
        self.name.setText(self.name.fontMetrics().elidedText(self.full_name, Qt.TextElideMode.ElideRight, available))
        self.name.setToolTip(self.full_name)
        for text in (self.platform, self.status, self.address):
            text.setMaximumWidth(available)
        for index in range(self.actions.count()):
            self.actions.itemAt(index).widget().setStyleSheet(f"font-size: {10 if compact else 11}px; padding: 2px {4 if compact else 7}px;")
        self.address.setText(self.address.fontMetrics().elidedText(self.address.toolTip(), Qt.TextElideMode.ElideRight, available))

    def resizeEvent(self, event):
        super().resizeEvent(event); self.fit_text()

    def paintEvent(self, event):
        painter = QPainter(self); painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(self.color)
        painter.setBrush(color.darker(145))
        painter.setPen(QPen(color.lighter(125), 2 if not self.primary else 3))
        painter.drawEllipse(QRectF(self.rect()).adjusted(3, 3, -3, -3))
        if self.primary:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor("#ffffff"), 1))
            painter.drawEllipse(QRectF(self.rect()).adjusted(9, 9, -9, -9))


class DeviceMap(QWidget):
    validate_requested = Signal(str)
    options_requested = Signal(str)
    pair_requested = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("deviceMap"); self.setStyleSheet("QWidget#deviceMap { background: transparent; }")
        self.bubbles = {}; self.primary = DeviceBubble(self, primary=True)
        self.setMinimumHeight(300)

    def update_devices(self, local, peers, nearby, online, results, checking, ready, receiving, failed):
        ids = {p["device_id"] for p in peers} | {p["device_id"] for p in nearby}
        for device_id in self.bubbles.keys() - ids:
            bubble = self.bubbles.pop(device_id); bubble.hide(); bubble.deleteLater()
        local_status = "Servicio no disponible" if failed else "Iniciando LAN…" if not ready else "Listo para recibir" if receiving else "Recepción pausada"
        local_color = OFFLINE if failed else UNKNOWN if not ready else CONNECTED if receiving else WARNING
        self.primary.update_device(local["device_name"], "Este equipo · Principal", f"{local['ip']}:{local['port']}", local_status, local_color)
        for peer, trusted in [(p, True) for p in peers] + [(p, False) for p in nearby]:
            device_id = peer["device_id"]
            bubble = self.bubbles.get(device_id)
            if bubble is None or bubble.property("trusted") != trusted:
                if bubble is not None:
                    bubble.hide(); bubble.deleteLater()
                bubble = DeviceBubble(self); bubble.setProperty("trusted", trusted)
                if trusted:
                    bubble.validate = bubble.add_action("Validar", lambda checked=False, d=device_id: self.validate_requested.emit(d))
                    bubble.add_action("Opciones", lambda checked=False, d=device_id: self.options_requested.emit(d))
                else:
                    bubble.peer = peer
                    bubble.add_action("Vincular", lambda checked=False, b=bubble: self.pair_requested.emit(b.peer))
                self.bubbles[device_id] = bubble; bubble.show()
            if trusted:
                status, color = connection_state(device_id, online, results, checking)
                bubble.validate.setEnabled(device_id not in checking)
            else:
                bubble.peer = peer; status, color = "Sin vincular", UNKNOWN
            bubble.update_device(peer.get("name", peer.get("device_name", "Dispositivo")),
                                 peer.get("platform", "LAN").capitalize(), f"{peer['ip']}:{peer['port']}", status, color)
        self.arrange(); self.update()

    def arrange(self):
        width = self.width(); count = len(self.bubbles)
        diameter = min(190, max(140, (width - 80) // 3)); hub = diameter + 10
        radius_x = max((width - diameter) / 2 - 18, diameter + 12)
        radius_y = (diameter + hub) / 2 + 22
        rows = max(1, math.ceil(count / 4))
        height = 300 if not count else int(2 * (radius_y + diameter / 2 + 18))
        if count > 6:
            height += 2 * (rows - 1) * (diameter + 18)
        self.setFixedHeight(height)
        center = QPointF(width / 2, height / 2)
        self.primary.setGeometry(int(center.x() - hub / 2), int(center.y() - hub / 2), hub, hub)
        for index, bubble in enumerate(self.bubbles.values()):
            if count <= 6:
                angle = -math.pi / 2 + 2 * math.pi * index / count
                x = center.x() + radius_x * math.cos(angle)
                y = center.y() + radius_y * math.sin(angle)
            else:
                top_count = math.ceil(count / 2)
                top = index < top_count; slot = index if top else index - top_count
                x = center.x() + (-1 if slot % 2 == 0 else 1) * (width - diameter - 36) / 2
                y = center.y() + (-1 if top else 1) * (radius_y + (slot // 2) * (diameter + 18))
            bubble.setGeometry(int(x - diameter / 2), int(y - diameter / 2), diameter, diameter)
        self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event); self.arrange()

    def paintEvent(self, event):
        painter = QPainter(self); painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        center = QPointF(self.primary.geometry().center())
        for bubble in self.bubbles.values():
            color = QColor(bubble.color); color.setAlpha(130)
            painter.setPen(QPen(color, 2, Qt.PenStyle.DashLine))
            painter.drawLine(center, QPointF(bubble.geometry().center()))
