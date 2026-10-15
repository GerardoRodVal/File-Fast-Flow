"""Selectable theme cards rendered from the actual desktop widget."""
from PySide6.QtCore import Qt, QRectF, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap, QFont
from PySide6.QtWidgets import QWidget, QAbstractButton, QButtonGroup, QGridLayout, QSizePolicy

from devicedrop.ui.desktop_widget import DesktopWidget


class PreviewSettings:
    def __init__(self, theme):
        self.values = {"widget_theme": theme, "widget_enabled": False}

    def setting(self, key, default=None):
        return self.values.get(key, default)

    def set_setting(self, key, value):
        self.values[key] = value


class ThemeTile(QAbstractButton):
    def __init__(self, key, title, description, parent):
        super().__init__(parent)
        self.key, self.title, self.description = key, title, description
        self.dark = False
        self.setCheckable(True); self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName(f"Tema {title}")
        self.setToolTip(f"Seleccionar tema {title}")
        self.setMinimumWidth(220); self.setFixedHeight(290)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.image = QPixmap()
        self.preview = DesktopWidget(PreviewSettings(key))
        self.preview.setParent(self, Qt.WindowType.Widget)
        self.preview.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        self.preview.hide()
        peer = {"device_id": "example", "name": "Mi teléfono", "platform": "android", "ip": "192.168.1.20", "port": 45832}
        self.preview.refresh([peer], {"example": True}, {"example": {"reverse_online": True}}, set(), {}, {})
        self.apply_theme(False)
        self.toggled.connect(lambda: self.update())

    def apply_theme(self, dark):
        self.dark = dark; self.preview.apply_theme(dark)
        self.preview.ensurePolished(); self.preview.layout().activate()
        self.image = QPixmap(self.preview.size()); self.image.fill(Qt.GlobalColor.transparent)
        self.preview.render(self.image)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self); painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        foreground = QColor("#e6eee9" if self.dark else "#18312e")
        background = QColor("#22342e" if self.dark else "#ffffff")
        border = QColor("#58d7b2" if self.isChecked() else "#354b41" if self.dark else "#d5dfdb")
        painter.setBrush(background); painter.setPen(QPen(border, 3 if self.isChecked() else 1))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(3, 3, -3, -3), 14, 14)
        font = QFont("Segoe UI"); font.setPixelSize(18); font.setBold(True)
        painter.setFont(font); painter.setPen(foreground)
        painter.drawText(QRectF(16, 12, self.width() - 60, 28), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.title)
        if self.isChecked():
            painter.setPen(QPen(border, 3))
            x = self.width() - 30
            painter.drawLine(x - 6, 25, x - 1, 30); painter.drawLine(x - 1, 30, x + 8, 19)
        available = QRectF(16, 52, self.width() - 32, 176)
        pixmap = self.image.scaled(min(self.image.width(), int(available.width())), min(self.image.height(), int(available.height())),
            Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        painter.drawPixmap(int(available.center().x() - pixmap.width() / 2),
                           int(available.center().y() - pixmap.height() / 2), pixmap)
        font.setPixelSize(12); font.setBold(False); painter.setFont(font)
        painter.setPen(QColor("#a8bcb4" if self.dark else "#6c807b"))
        painter.drawText(QRectF(16, 242, self.width() - 32, 36), Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap, self.description)
        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush); painter.setPen(QPen(border, 1, Qt.PenStyle.DotLine))
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(7, 7, -7, -7), 11, 11)


class WidgetThemeGrid(QWidget):
    theme_changed = Signal(str)

    def __init__(self):
        super().__init__()
        self.grid = QGridLayout(self); self.grid.setContentsMargins(0, 0, 0, 0); self.grid.setSpacing(14)
        self.group = QButtonGroup(self); self.group.setExclusive(True)
        self.tiles = {}
        self.current_theme = "classic"
        self.columns = 0; self.building = True
        for key, title, description in [("classic", "Clásico", "Tarjeta completa con el estado y los controles visibles."),
                                        ("minimal", "Minimalista", "Panel compacto con una fila por dispositivo.")]:
            tile = ThemeTile(key, title, description, self)
            self.tiles[key] = tile; self.group.addButton(tile)
        self.group.buttonClicked.connect(self.chosen)
        self.building = False; self.arrange()

    def chosen(self, tile):
        self.current_theme = tile.key; self.theme_changed.emit(tile.key)

    def select_theme(self, theme):
        self.current_theme = theme if theme in self.tiles else "classic"
        self.tiles[self.current_theme].setChecked(True)

    def apply_theme(self, dark):
        for tile in self.tiles.values():
            tile.apply_theme(dark)

    def arrange(self):
        if self.building:
            return
        columns = 2 if self.width() >= 560 else 1
        if columns == self.columns:
            return
        self.columns = columns
        for index, tile in enumerate(self.tiles.values()):
            self.grid.removeWidget(tile); self.grid.addWidget(tile, index // columns, index % columns)
        for column in range(2):
            self.grid.setColumnStretch(column, 1 if column < columns else 0)
        rows = (len(self.tiles) + columns - 1) // columns
        self.setFixedHeight(rows * 290 + (rows - 1) * 14)
        self.updateGeometry()

    def resizeEvent(self, event):
        super().resizeEvent(event); self.arrange()
