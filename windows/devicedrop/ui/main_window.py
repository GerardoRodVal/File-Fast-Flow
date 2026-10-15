import io
import json
import os
from pathlib import Path
import sys

import qrcode
from PySide6.QtCore import Qt, QTimer, Signal, QObject, QUrl, QSize
from PySide6.QtGui import QDesktopServices, QIcon, QPixmap, QColor, QPainter, QShortcut, QKeySequence
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QListWidget, QListWidgetItem, QStackedWidget, QFileDialog, QMessageBox,
    QDialog, QLineEdit, QFormLayout, QCheckBox, QSpinBox, QComboBox, QSystemTrayIcon,
    QMenu, QScrollArea, QProgressBar, QFrame, QInputDialog)
from devicedrop.packages import PackageWorker, default_filename
from devicedrop.network.connectivity import report_text
from devicedrop import __version__
from devicedrop.updates import UpdateWorker, REPOSITORY_URL, RELEASES_URL, verify_installer
from devicedrop.storage.spaces import SpaceStoreWorker
from devicedrop.ui.desktop_widget import DesktopWidget
from devicedrop.ui.device_map import DeviceMap
from devicedrop.window_activation import restore_application_window
from devicedrop.ui.widget_themes import WidgetThemeGrid
from devicedrop.ui.receipt_notifications import ReceiptNotifier
from devicedrop.ui.clipboard import copy_file
from devicedrop.local_build import LocalBuildWorker, project_root, artifact_valid, installed_revision

LIGHT = """QWidget { font-family: 'Segoe UI'; font-size: 14px; color: #18312e; background: #f5f8f7; }
QMainWindow { background: #f5f8f7; }
QLabel#brand { font-size: 26px; font-weight: 700; }
QLabel#title { font-size: 30px; font-weight: 700; }
QLabel#muted { color: #6c807b; }
QFrame#card { background: white; border: 1px solid #e0e8e5; border-radius: 16px; }
QFrame#card QLabel, QFrame#card QCheckBox { background: transparent; }
QPushButton { background: #087f69; color: white; border: 0; border-radius: 9px; padding: 11px 18px; font-weight: 600; }
QPushButton:hover { background: #096d5c; }
QPushButton:disabled { background: #b8c8c3; }
QPushButton#secondary { background: #e8f2ee; color: #096d5c; }
QListWidget { border: 0; background: #eaf1ee; padding: 9px; border-radius: 12px; }
QListWidget::item { padding: 16px; border-radius: 9px; }
QListWidget::item:selected { background: #d0e7df; color: #18312e; }
QListWidget#navigation { background: #1d2c27; color: #ffffff; }
QListWidget#navigation::item { color: #ffffff; }
QListWidget#navigation::item:selected { background: #37574a; color: #ffffff; }
QLabel#spaceTitle { font-size: 22px; font-weight: 700; }
QFrame#dropZone { background: transparent; border: 2px dashed #b8c8c3; border-radius: 12px; }
QFrame#card[dragActive="true"] { border: 2px solid #087f69; }
QListWidget#spaceFiles { background: transparent; padding: 0; }
QListWidget#spaceFiles::item { padding: 6px 8px; }
QLineEdit,QSpinBox,QComboBox { border: 1px solid #d5dfdb; border-radius: 7px; background: white; padding: 9px; }
QProgressBar { border: 0; background: #e8efec; border-radius: 5px; height: 10px; }
QProgressBar::chunk { background: #087f69; border-radius: 5px; }
QScrollArea { border: 0; }
"""


class Bridge(QObject):
    event = Signal(dict)
    result = Signal(bool, str)
    connection_result = Signal(dict)


def label(text, role=""):
    widget = QLabel(text)
    if role:
        widget.setObjectName(role)
    widget.setWordWrap(True)
    return widget


def button(text, callback, secondary=False):
    widget = QPushButton(text); widget.clicked.connect(callback)
    if secondary:
        widget.setObjectName("secondary")
    return widget


def card():
    frame = QFrame(); frame.setObjectName("card")
    layout = QVBoxLayout(frame); layout.setContentsMargins(22, 20, 22, 20); layout.setSpacing(12)
    return frame, layout


def size_text(value):
    size = float(value)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}"
        size /= 1024


def app_icon():
    pix = QPixmap(64, 64); pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix); painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor("#087f69")); painter.setPen(Qt.PenStyle.NoPen); painter.drawRoundedRect(0, 0, 64, 64, 15, 15)
    painter.setPen(QColor("white")); painter.drawRoundedRect(10, 17, 22, 28, 3, 3); painter.drawRoundedRect(42, 21, 12, 24, 2, 2)
    painter.drawText(28, 34, "⇄"); painter.end()
    return QIcon(pix)


class FileSpaceCard(QFrame):
    files_dropped = Signal(list)

    def __init__(self, title, description, select, open_folder, send):
        super().__init__()
        self.setObjectName("card"); self.setAcceptDrops(True)
        layout = QVBoxLayout(self); layout.setContentsMargins(22, 20, 22, 20); layout.setSpacing(10)
        header = QHBoxLayout(); header.addWidget(label(title, "spaceTitle"), 1)
        self.connection = label("", "muted"); header.addWidget(self.connection); layout.addLayout(header)
        layout.addWidget(label(description, "muted"))
        self.folder_path = label("", "muted"); self.folder_path.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.folder_path)
        drop = QFrame(); drop.setObjectName("dropZone")
        box = QHBoxLayout(drop); box.setContentsMargins(16, 14, 16, 14)
        prompt = label("↓  Arrastra archivos aquí"); box.addWidget(prompt, 1)
        self.select_button = button("Seleccionar archivos", select); box.addWidget(self.select_button)
        layout.addWidget(drop)
        self.file_list = QListWidget(); self.file_list.setObjectName("spaceFiles")
        self.file_list.setMaximumHeight(110); self.file_list.hide(); layout.addWidget(self.file_list)
        self.file_list.itemDoubleClicked.connect(lambda item: MainWindow.open_path(item.data(Qt.ItemDataRole.UserRole)))
        self.summary = label("Aún no hay archivos guardados.", "muted"); layout.addWidget(self.summary)
        controls = QHBoxLayout(); controls.addWidget(button("Abrir carpeta", open_folder, True))
        self.send_button = button("Enviar guardados", send, True); controls.addWidget(self.send_button)
        controls.addStretch(); layout.addLayout(controls)
        self.activity = label("", "muted"); self.activity.hide(); layout.addWidget(self.activity)
        self.file_signature = None

    @staticmethod
    def local_files(event):
        return [u.toLocalFile() for u in event.mimeData().urls()
                if u.isLocalFile() and Path(u.toLocalFile()).is_file()]

    def highlight(self, active):
        self.setProperty("dragActive", "true" if active else "false")
        self.style().unpolish(self); self.style().polish(self); self.update()

    def dragEnterEvent(self, event):
        if self.select_button.isEnabled() and self.local_files(event):
            self.highlight(True); event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self.highlight(False); event.accept()

    def dropEvent(self, event):
        self.highlight(False)
        paths = self.local_files(event)
        if self.select_button.isEnabled() and paths:
            self.files_dropped.emit(paths); event.acceptProposedAction()
        else:
            event.ignore()

    def update_files(self, files):
        signature = [(str(p), p.stat().st_size, p.stat().st_mtime_ns) for p in files]
        if signature == self.file_signature:
            return
        self.file_signature = signature; self.file_list.clear()
        for path, size, _ in signature:
            item = QListWidgetItem(f"{Path(path).name}  ·  {size_text(size)}")
            item.setData(Qt.ItemDataRole.UserRole, path); item.setToolTip(path); self.file_list.addItem(item)
        self.file_list.setFixedHeight(min(110, max(34, self.file_list.sizeHintForRow(0) * len(files) + 4)))
        self.file_list.setVisible(bool(files))
        count = "1 archivo guardado" if len(files) == 1 else f"{len(files)} archivos guardados"
        self.summary.setText(f"{count} · Doble clic para abrir" if files else "Aún no hay archivos guardados.")


class MainWindow(QMainWindow):
    HOME_PAGE = 0
    SOFTWARE_PAGE = 3
    WIDGET_PAGE = 4

    def __init__(self, runtime):
        super().__init__()
        self.runtime = runtime; self.quitting = False; self.last_preview = None
        self.package_worker = None; self.last_package = None
        self.update_worker = None; self.available_update = None; self.downloaded_update = None
        self.exit_after_update = False; self.manual_update_check = False
        self.tray_notification_page = 0
        self.tray_copy_path = None
        self.local_build_worker = None
        self.receipt_notifier = ReceiptNotifier(runtime.logger)
        self.checking_connections = set()
        self.connection_dialog_parents = {}
        self.spaces = runtime.spaces; self.space_workers = {}; self.space_messages = {}
        self.bridge = Bridge(); self.bridge.event.connect(self.event_received); self.bridge.result.connect(self.result_received)
        self.bridge.connection_result.connect(self.connections_received)
        self.runtime.bus.listeners.append(self.bridge.event.emit)
        self.setWindowTitle("FileFastFlow"); self.setWindowIcon(app_icon()); self.resize(1120, 800); self.setMinimumSize(820, 650)
        root = QWidget(); self.setCentralWidget(root); outer = QHBoxLayout(root); outer.setContentsMargins(24, 24, 24, 24); outer.setSpacing(28)
        side = QVBoxLayout(); side.addWidget(label("⇄  FileFastFlow", "brand")); side.addWidget(label("Tus archivos, cerca de ti.", "muted")); side.addSpacing(26)
        self.nav = QListWidget(); self.nav.setObjectName("navigation"); self.nav.setFixedWidth(205)
        self.nav.addItems(["Inicio", "Dispositivos", "Configuración", "Instaladores y actualizaciones", "Widget"]); side.addWidget(self.nav)
        self.nav.setTextElideMode(Qt.TextElideMode.ElideNone); self.nav.setWordWrap(True)
        self.nav.item(self.SOFTWARE_PAGE).setText("Instaladores y\nactualizaciones")
        self.nav.item(self.SOFTWARE_PAGE).setToolTip("Instaladores y actualizaciones")
        self.nav.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        side.addWidget(label("LOCAL · SIN CUENTAS\nHTTP LAN · sin cifrado TLS", "muted")); outer.addLayout(side)
        self.pages = QStackedWidget(); outer.addWidget(self.pages, 1)
        self.home = self.page("Tus espacios de archivos", "Un espacio para todos y uno para cada dispositivo.")
        self.general_space = self.make_file_space("General", "Guarda aquí los archivos que compartes con todos tus dispositivos vinculados.")
        self.home.addWidget(self.general_space)
        self.home.addWidget(label("Por dispositivo", "spaceTitle"))
        self.home_devices = QVBoxLayout(); self.home.addLayout(self.home_devices)
        self.device_spaces = {}
        self.status = label("Iniciando servicio local…", "muted"); self.home.addWidget(self.status)
        self.recent = QVBoxLayout(); self.home.addWidget(label("Transferencias recientes", "brand")); self.home.addLayout(self.recent); self.home.addStretch()
        self.devices_page = self.page("Tus dispositivos", "Tu equipo al centro. El color de cada burbuja indica su conexión.")
        self.pairing_status = label("Iniciando servicio local…", "muted"); self.devices_page.addWidget(self.pairing_status)
        self.pairing_button = button("Mostrar código / QR", self.show_pairing)
        self.validate_connections_button = button("Validar todas", lambda: self.validate_connections(), True)
        self.validate_connections_button.setToolTip("Validar conexiones de todos los dispositivos")
        pair_button = button("Vincular", self.connect_pairing, True); pair_button.setToolTip("Vincular por IP o QR")
        row = QHBoxLayout(); row.addWidget(self.pairing_button); row.addWidget(pair_button); row.addWidget(self.validate_connections_button); self.devices_page.addLayout(row)
        legend = label("● Conectado   ·   ● Sin conexión   ·   ● Atención / validación   ·   ● Sin comprobar / sin vincular", "muted")
        legend.setTextFormat(Qt.TextFormat.RichText)
        legend.setText('<span style="color:#169b73">●</span> Conectado &nbsp; <span style="color:#d84a4a">●</span> Sin conexión &nbsp; <span style="color:#d08a16">●</span> Atención / validación &nbsp; <span style="color:#87958f">●</span> Sin comprobar / sin vincular')
        self.devices_page.addWidget(legend)
        self.device_map = DeviceMap(); self.devices_page.addWidget(self.device_map)
        self.device_map.validate_requested.connect(self.validate_connections)
        self.device_map.options_requested.connect(self.show_device_options)
        self.device_map.pair_requested.connect(self.connect_pairing)
        self.devices_empty = label("Vincula un dispositivo o abre FileFastFlow en otro equipo de tu red para verlo aquí.", "muted")
        self.devices_page.addWidget(self.devices_empty); self.devices_page.addStretch()
        self.settings_page = self.page("Configuración", "Personaliza este dispositivo.")
        self.make_settings()
        self.software_page = self.page("Instaladores y actualizaciones", "Mantén FileFastFlow al día y llévalo a tus otros dispositivos.")
        self.make_fleet_updates(self.software_page)
        self.make_updates(self.software_page)
        self.software_page.addWidget(label("Instaladores", "spaceTitle"))
        self.make_packages(self.software_page); self.software_page.addStretch()
        self.make_widget_settings()
        self.device_widget = DesktopWidget(runtime.db)
        self.device_widget.setWindowIcon(self.windowIcon())
        self.device_widget.validate_requested.connect(self.validate_connections)
        self.widget_send_device = None
        self.device_widget.send_requested.connect(self.send_from_widget)
        self.device_widget.folder_requested.connect(lambda device_id: self.open_path(self.spaces.folder(device_id)))
        self.device_widget.settings_requested.connect(self.show_widget_settings)
        self.device_widget.open_requested.connect(self.open_from_widget)
        self.device_widget.disable_requested.connect(lambda: self.set_widget_enabled(False))
        self.destroyed.connect(self.device_widget.deleteLater)
        self.nav.currentRowChanged.connect(self.pages.setCurrentIndex); self.nav.setCurrentRow(0)
        self.tray = QSystemTrayIcon(app_icon(), self); self.tray.setToolTip("FileFastFlow · LAN")
        menu = QMenu(); menu.addAction("Abrir FileFastFlow", self.restore_window); menu.addAction("Pausar / activar recepción", self.toggle_receive)
        menu.addAction("Abrir recibidos", lambda: self.open_path(self.runtime.db.setting("receive_folder")))
        self.copy_received_action = menu.addAction("Copiar último archivo recibido", self.copy_last_received)
        self.copy_received_action.setToolTip("Copiar el archivo al portapapeles · Ctrl+Shift+C en FileFastFlow")
        self.copy_received_shortcut = QShortcut(QKeySequence("Ctrl+Shift+C"), self)
        self.copy_received_shortcut.activated.connect(self.copy_last_received)
        self.tray.setContextMenu(menu); self.tray.activated.connect(self.tray_activated); self.tray.show()
        self.tray.messageClicked.connect(self.open_notification)
        widget_menu = menu.addMenu("Widget")
        self.widget_action = widget_menu.addAction("Activar widget")
        self.widget_action.setCheckable(True)
        self.widget_action.toggled.connect(self.set_widget_enabled)
        widget_menu.addAction("Configuración del widget", self.show_widget_settings)
        menu.addAction("Buscar actualizaciones", lambda: self.check_updates(True))
        menu.addSeparator(); menu.addAction("Salir", self.quit)
        self.timer = QTimer(self); self.timer.timeout.connect(self.refresh); self.timer.start(700)
        self.apply_theme(); self.refresh()
        self.set_widget_enabled(self.runtime.db.setting("widget_enabled"))
        self.update_timer = QTimer(self); self.update_timer.timeout.connect(self.auto_check_updates); self.update_timer.start(30 * 60 * 1000)
        self.initial_update_timer = QTimer(self); self.initial_update_timer.setSingleShot(True)
        self.initial_update_timer.timeout.connect(self.auto_check_updates); self.initial_update_timer.start(8000)
        self.local_build_timer = QTimer(self); self.local_build_timer.timeout.connect(self.poll_local_changes); self.local_build_timer.start(30000)

    def make_fleet_updates(self, page):
        frame, layout = card()
        layout.addWidget(label("Actualizar todos los dispositivos", "spaceTitle"))
        layout.addWidget(label("Prepara los instaladores con los cambios de esta PC y envía a cada equipo su versión de Windows o Android. Los equipos desconectados quedan pendientes. Cada equipo confirma la instalación.", "muted"))
        self.fleet_update_button = button("Actualizar todos los dispositivos", self.start_local_update)
        self.fleet_update_button.setEnabled(project_root() is not None)
        layout.addWidget(self.fleet_update_button)
        self.fleet_auto = QCheckBox("Preparar y enviar automáticamente cuando cambie el código")
        self.fleet_auto.setChecked(self.runtime.db.setting("fleet_auto", False))
        self.fleet_auto.setEnabled(project_root() is not None)
        self.fleet_auto.toggled.connect(lambda enabled: self.runtime.db.set_setting("fleet_auto", enabled))
        layout.addWidget(self.fleet_auto)
        self.fleet_progress = QProgressBar(); self.fleet_progress.setRange(0, 0); self.fleet_progress.hide(); layout.addWidget(self.fleet_progress)
        self.fleet_status = label("Los cambios automáticos se preparan después de 30 segundos sin modificaciones." if project_root() else "Recibe las actualizaciones preparadas desde la PC que contiene el proyecto.", "muted")
        self.fleet_status.setTextFormat(Qt.TextFormat.PlainText); layout.addWidget(self.fleet_status)
        self.fleet_devices = label(""); self.fleet_devices.setTextFormat(Qt.TextFormat.PlainText); layout.addWidget(self.fleet_devices)
        self.install_local_button = button("Instalar cambios recibidos de mi PC", self.install_local_update)
        self.install_local_button.hide(); layout.addWidget(self.install_local_button)
        page.addWidget(frame)

    def poll_local_changes(self):
        if self.runtime.db.setting("fleet_auto", False):
            self.start_local_update(automatic=True)

    def start_local_update(self, checked=False, automatic=False):
        if self.local_build_worker is not None:
            return
        if not self.runtime.db.trusted():
            if not automatic:
                self.fleet_status.setText("Vincula un dispositivo antes de distribuir una actualización.")
            return
        self.fleet_update_button.setEnabled(False); self.fleet_progress.show()
        self.fleet_status.setText("Revisando los cambios de esta PC…")
        self.local_build_worker = LocalBuildWorker(self.runtime, automatic, self)
        self.local_build_worker.progress.connect(self.fleet_status.setText)
        def complete(manifest):
            if manifest:
                self.runtime.fleet.queue(manifest)
                self.fleet_status.setText("Instaladores preparados. Se enviarán a los dispositivos conectados; los demás quedan pendientes.")
            else:
                self.fleet_status.setText("Esperando a que terminen los cambios antes de compilar…")
        self.local_build_worker.completed.connect(complete)
        self.local_build_worker.failed.connect(lambda error: self.fleet_status.setText(error))
        self.local_build_worker.finished.connect(self.local_build_finished)
        self.local_build_worker.start()

    def local_build_finished(self):
        self.local_build_worker.deleteLater(); self.local_build_worker = None
        self.fleet_progress.hide(); self.fleet_update_button.setEnabled(project_root() is not None)

    def refresh_fleet(self):
        states = self.runtime.db.setting("fleet_states", {})
        captions = {"pending": "Pendiente de conexión", "sending": "Enviando instalador…", "received": "Recibido · falta instalar", "installed": "Actualizado", "failed": "Error · se reintentará"}
        self.fleet_devices.setText("\n".join(f"{peer['name']}: {captions.get(states.get(peer['device_id'], {}).get('status'), 'Sin actualización preparada')}" + (f" · {states[peer['device_id']]['error']}" if states.get(peer['device_id'], {}).get('error') else "") for peer in self.runtime.db.trusted()))
        pending = self.runtime.db.setting("local_update_pending", {})
        self.install_local_button.setVisible(bool(pending) and pending.get("revision") != installed_revision())

    def install_local_update(self):
        pending = self.runtime.db.setting("local_update_pending", {})
        if not pending:
            return
        if self.space_workers or self.local_build_worker is not None or self.package_worker is not None or (self.runtime.sender and self.runtime.sender.tasks) or self.runtime.active_uploads:
            QMessageBox.information(self, "Actualización", "Espera a que terminen las compilaciones y transferencias antes de instalar."); return
        try:
            if not artifact_valid(pending):
                raise ValueError("El instalador cambió o ya no existe. Solicita de nuevo la actualización.")
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(pending["path"])):
                raise ValueError("No se pudo abrir el instalador local.")
            self.quit()
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "Actualización local", str(error))

    def page(self, title, subtitle):
        content = QWidget(); layout = QVBoxLayout(content); layout.setSpacing(16); layout.setContentsMargins(0, 0, 8, 8)
        layout.addWidget(label(title, "title")); layout.addWidget(label(subtitle, "muted"))
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(content); self.pages.addWidget(scroll)
        return layout

    def make_file_space(self, title, description, device_id=None):
        space = FileSpaceCard(title, description,
            lambda: self.select_space_files(device_id),
            lambda: self.open_path(self.spaces.folder(device_id)),
            lambda: self.send_space_files(self.spaces.files(device_id), device_id))
        space.files_dropped.connect(lambda paths: self.store_space_files(paths, device_id))
        space.folder_path.setText(str(self.spaces.folder(device_id)))
        return space

    def make_settings(self):
        frame, layout = card(); form = QFormLayout()
        self.name_input = QLineEdit(self.runtime.db.setting("device_name")); form.addRow("Nombre", self.name_input)
        self.receive_input = QLineEdit(self.runtime.db.setting("receive_folder")); form.addRow("Carpeta recepción", self.receive_input)
        form.addRow(label("Los archivos de esta carpeta se comparten con todos. Dentro de cada subcarpeta, los archivos son solo para el dispositivo correspondiente.", "muted"))
        self.port_input = QSpinBox(); self.port_input.setRange(45000, 45999); self.port_input.setValue(self.runtime.db.setting("port")); form.addRow("Puerto LAN", self.port_input)
        self.theme_input = QComboBox(); self.theme_input.addItems(["Light", "Dark", "System"]); self.theme_input.setCurrentText(self.runtime.db.setting("theme")); form.addRow("Tema", self.theme_input)
        layout.addLayout(form); self.checks = {}
        for key, text in [("allow_receive", "Permitir recepción"), ("notifications", "Mostrar notificaciones"), ("start_windows", "Iniciar con Windows"), ("auto_updates", "Buscar actualizaciones y avisar automáticamente")]:
            check = QCheckBox(text); check.setChecked(self.runtime.db.setting(key)); self.checks[key] = check; layout.addWidget(check)
        layout.addWidget(button("Guardar configuración", self.save_settings)); layout.addWidget(label("Si el firewall bloquea la conexión, permite FileFastFlow en redes privadas. Los cambios de puerto o carpeta recepción se aplican al reiniciar.", "muted"))
        self.settings_page.addWidget(frame); self.settings_page.addStretch()

    def make_widget_settings(self):
        page = self.page("Configuración del widget", "Accede a tus dispositivos sin abrir la ventana principal.")
        frame, layout = card()
        self.widget_enabled_check = QCheckBox("Activar widget de escritorio")
        self.widget_enabled_check.setChecked(self.runtime.db.setting("widget_enabled"))
        self.widget_enabled_check.toggled.connect(self.set_widget_enabled)
        layout.addWidget(self.widget_enabled_check)
        layout.addWidget(label("Tema del widget", "spaceTitle"))
        self.widget_theme_grid = WidgetThemeGrid()
        self.widget_theme_grid.select_theme(self.runtime.db.setting("widget_theme"))
        self.widget_theme_grid.theme_changed.connect(self.set_widget_theme)
        layout.addWidget(self.widget_theme_grid)
        layout.addWidget(label("Clásico sigue los colores de la app. Minimalista usa un panel oscuro translúcido, con una fila por dispositivo. En este estilo, haz doble clic en el encabezado para abrir la app y pasa el cursor sobre la bolita para ver el estado.", "muted"))
        layout.addWidget(label("El cambio se guarda y aplica al instante. El widget vive únicamente en el escritorio: las demás aplicaciones quedan por encima. Sigue disponible al ocultar la app en la bandeja.", "muted"))
        layout.addWidget(label("Arrastra el encabezado para moverlo. Usa el icono de validación para comprobar la conexión y la flecha de envío para elegir archivos para ese dispositivo.", "muted"))
        layout.addWidget(label("● Verde: conectado · Rojo: sin conexión\n● Ámbar: validando, conexión parcial o recepción pausada\n● Gris: sin comprobar", "muted"))
        layout.addWidget(button("Restablecer posición", lambda: self.device_widget.reset_position(), True))
        page.addWidget(frame); page.addStretch()

    def set_widget_theme(self, theme):
        theme = theme if theme in {"classic", "minimal"} else "classic"
        self.runtime.db.set_setting("widget_theme", theme)
        self.device_widget.set_theme(theme)
        self.device_widget.save_position()

    def set_widget_enabled(self, enabled):
        enabled = bool(enabled)
        self.runtime.db.set_setting("widget_enabled", enabled)
        for control in (self.widget_enabled_check, self.widget_action):
            control.blockSignals(True)
            control.setChecked(enabled)
            control.blockSignals(False)
        if enabled:
            self.device_widget.keep_on_screen()
            self.device_widget.show_on_desktop()
        else:
            self.device_widget.save_position()
            self.device_widget.hide()

    def open_from_widget(self):
        self.showNormal(); self.raise_(); self.activateWindow()

    def send_from_widget(self, device_id):
        self.widget_send_device = device_id
        self.select_space_files(device_id)

    def show_widget_settings(self):
        self.nav.setCurrentRow(self.WIDGET_PAGE)
        self.open_from_widget()

    def make_packages(self, page):
        frame, layout = card()
        layout.addWidget(label("Windows 10 / 11 · 64 bits", "brand"))
        layout.addWidget(label("Crea un instalador EXE con asistente de instalación, accesos directos y desinstalación. Funciona sin Internet.", "muted"))
        self.windows_package_button = button("Generar instalador EXE para Windows", lambda: self.generate_package("windows"))
        layout.addWidget(self.windows_package_button); page.addWidget(frame)
        frame, layout = card()
        layout.addWidget(label("Android 8.0 o posterior", "brand"))
        layout.addWidget(label("Guarda el APK incluido de esta versión para instalarlo en tu teléfono. Es una versión de desarrollo firmada con clave debug.", "muted"))
        self.android_package_button = button("Generar APK para Android", lambda: self.generate_package("android"))
        layout.addWidget(self.android_package_button); page.addWidget(frame)
        self.package_status = label("Elige un formato y dónde guardar el archivo.", "muted"); page.addWidget(self.package_status)
        self.package_progress = QProgressBar(); self.package_progress.hide(); page.addWidget(self.package_progress)
        self.package_folder_button = button("Abrir carpeta del archivo generado", lambda: self.open_path(self.last_package.parent), True)
        self.package_folder_button.hide(); page.addWidget(self.package_folder_button)

    def generate_package(self, kind, destination=None):
        if self.package_worker is not None:
            return
        extension = ".exe" if kind == "windows" else ".apk"
        if destination is None:
            path, _ = QFileDialog.getSaveFileName(self, "Guardar instalador Windows" if kind == "windows" else "Guardar APK Android",
                str(Path.home() / "Downloads" / default_filename(kind)), "Instalador Windows (*.exe)" if kind == "windows" else "Aplicación Android (*.apk)")
        else:
            path = str(destination)
        if not path:
            return
        if not path.lower().endswith(extension):
            path += extension
            if Path(path).exists() and QMessageBox.question(self, "Reemplazar archivo", f"{path}\n¿Quieres reemplazarlo?") != QMessageBox.StandardButton.Yes:
                return
        self.windows_package_button.setEnabled(False); self.android_package_button.setEnabled(False)
        self.package_folder_button.hide(); self.package_progress.setRange(0, 0 if kind == "windows" else 100)
        self.package_progress.setValue(0); self.package_progress.show()
        self.package_status.setText("Generando instalador Windows… Puede tardar un minuto." if kind == "windows" else "Guardando y verificando el APK Android…")
        self.package_worker = PackageWorker(kind, path, self)
        self.package_worker.progress.connect(self.package_progress.setValue)
        self.package_worker.completed.connect(self.package_completed)
        self.package_worker.finished.connect(self.package_finished)
        self.package_worker.start()

    def make_updates(self, page):
        frame, layout = card()
        layout.addWidget(label(f"FileFastFlow · versión {__version__}", "brand"))
        layout.addWidget(label("Con la aplicación abierta, se consulta GitHub al iniciar y cada 30 minutos. Necesitas Internet para buscar y descargar actualizaciones.", "muted"))
        layout.addWidget(button("Abrir repositorio en GitHub", lambda: QDesktopServices.openUrl(QUrl(REPOSITORY_URL)), True))
        layout.addWidget(button("Ver versiones publicadas", lambda: QDesktopServices.openUrl(QUrl(RELEASES_URL)), True))
        self.check_update_button = button("Buscar actualizaciones", lambda: self.check_updates(True))
        layout.addWidget(self.check_update_button)
        self.update_status = label("Las actualizaciones automáticas están activadas. Puedes cambiarlas en Configuración." if self.runtime.db.setting("auto_updates") else "La búsqueda automática está desactivada.", "muted")
        layout.addWidget(self.update_status)
        self.update_notes = label(""); self.update_notes.setTextFormat(Qt.TextFormat.PlainText); layout.addWidget(self.update_notes)
        self.update_progress = QProgressBar(); self.update_progress.hide(); layout.addWidget(self.update_progress)
        self.download_update_button = button("Descargar actualización", self.download_update); self.download_update_button.hide(); layout.addWidget(self.download_update_button)
        self.install_update_button = button("Instalar actualización descargada", self.install_update); self.install_update_button.hide(); layout.addWidget(self.install_update_button)
        layout.addWidget(label("La descarga se verifica con SHA-256. El instalador se abre cuando pulses Instalar; conserva los vínculos, el historial y las carpetas existentes.", "muted"))
        page.addWidget(frame)

    def show_updates(self):
        self.restore_window(); self.nav.setCurrentRow(self.SOFTWARE_PAGE)

    def open_notification(self):
        if self.tray_copy_path:
            self.copy_received_file(self.tray_copy_path); return
        self.showNormal(); self.raise_(); self.activateWindow(); self.nav.setCurrentRow(self.tray_notification_page)

    def copy_received_file(self, path):
        try:
            copy_file(path)
            self.statusBar().showMessage("Archivo copiado. Pégalo con Ctrl+V.", 5000)
        except (OSError, ValueError) as error:
            self.tray_copy_path = None
            self.tray.showMessage("No se pudo copiar", str(error), QSystemTrayIcon.MessageIcon.Warning, 5000)

    def last_received(self):
        rows = self.runtime.db.execute("SELECT saved_path FROM transfers WHERE direction='incoming' AND status='completed' AND saved_path IS NOT NULL ORDER BY completed_at DESC, id DESC LIMIT 1")
        return rows[0]["saved_path"] if rows else None

    def copy_last_received(self):
        path = self.last_received()
        if path:
            self.copy_received_file(path)

    def handle_receipt_action(self, action, transfer_id):
        rows = self.runtime.db.execute("SELECT saved_path FROM transfers WHERE transfer_id=? AND direction='incoming' AND status='completed' AND saved_path IS NOT NULL", (transfer_id,))
        if not rows or action not in {"copy", "open"}:
            return
        if action == "copy":
            self.copy_received_file(rows[0]["saved_path"])
        else:
            self.nav.setCurrentRow(self.HOME_PAGE); self.restore_window()

    def auto_check_updates(self):
        if self.runtime.db.setting("auto_updates"):
            self.check_updates()

    def check_updates(self, manual=False):
        if self.update_worker is not None or self.quitting:
            return
        self.manual_update_check = manual
        if manual:
            self.show_updates()
        self.update_status.setText("Buscando actualizaciones en GitHub…")
        self.start_update_worker(UpdateWorker(parent=self))

    def start_update_worker(self, worker):
        self.update_worker = worker
        self.check_update_button.setEnabled(False); self.download_update_button.setEnabled(False); self.install_update_button.setEnabled(False)
        worker.checked.connect(self.update_checked); worker.downloaded.connect(self.update_downloaded)
        worker.failed.connect(self.update_failed); worker.progress.connect(self.update_progress.setValue)
        worker.finished.connect(self.update_finished); worker.start()

    def update_checked(self, release):
        if self.exit_after_update:
            return
        self.available_update = release
        if release is None:
            self.download_update_button.hide(); self.install_update_button.hide(); self.update_notes.setText("")
            self.update_status.setText("Tienes la versión más reciente disponible. Si aún no hay publicaciones, vuelve a buscar más tarde.")
            return
        self.update_status.setText(f"Nueva versión disponible: {release.version}. Puedes descargarla aquí.")
        self.update_notes.setText(release.notes); self.download_update_button.show(); self.install_update_button.hide()
        # Remind once per version on each PC; the update card always stays available.
        if self.runtime.db.setting("notifications") and self.runtime.db.setting("last_update_notified") != release.version:
            self.tray_copy_path = None
            self.tray_notification_page = self.SOFTWARE_PAGE
            self.tray.showMessage("FileFastFlow · actualización disponible", f"La versión {release.version} está lista. Haz clic para descargarla.", QSystemTrayIcon.MessageIcon.Information, 10000)
            self.runtime.db.set_setting("last_update_notified", release.version)

    def download_update(self):
        if self.available_update is None or self.update_worker is not None:
            return
        destination = self.runtime.root / "updates" / self.available_update.filename
        self.update_status.setText(f"Descargando FileFastFlow {self.available_update.version}…")
        self.update_progress.setValue(0); self.update_progress.show()
        self.start_update_worker(UpdateWorker(self.available_update, destination, self))

    def update_downloaded(self, path):
        self.downloaded_update = Path(path)
        self.update_status.setText("Descarga verificada. Pulsa Instalar para abrir el asistente de actualización.")
        self.download_update_button.hide(); self.install_update_button.show()

    def install_update(self):
        if self.downloaded_update is None or self.available_update is None or self.update_worker is not None:
            return
        if self.package_worker is not None:
            QMessageBox.information(self, "Actualización", "Espera a que termine la generación del instalador."); return
        try:
            verify_installer(self.downloaded_update, self.available_update)
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.downloaded_update))):
                raise ValueError("No se pudo abrir el instalador.")
        except (ValueError, OSError) as error:
            self.update_failed(str(error)); return
        self.quit()

    def update_failed(self, message):
        self.update_status.setText(f"No se pudo completar la actualización: {message}\nPuedes intentarlo de nuevo.")

    def update_finished(self):
        self.update_worker.deleteLater(); self.update_worker = None; self.update_progress.hide()
        self.check_update_button.setEnabled(True); self.download_update_button.setEnabled(True); self.install_update_button.setEnabled(True)
        if self.exit_after_update:
            self.quit()

    def package_completed(self, success, message):
        self.package_progress.hide()
        if success:
            self.last_package = Path(message)
            self.package_status.setText(f"Listo. Archivo guardado en:\n{message}")
            self.package_folder_button.show()
        else:
            self.package_status.setText("No se pudo generar el archivo. Puedes intentarlo de nuevo.")
            QMessageBox.warning(self, "Instalador", message)

    def package_finished(self):
        self.package_worker.deleteLater(); self.package_worker = None
        self.windows_package_button.setEnabled(True); self.android_package_button.setEnabled(True)

    def save_settings(self):
        name = self.name_input.text().strip()
        if not name or len(name) > 80:
            QMessageBox.warning(self, "Nombre", "Usa un nombre de 1 a 80 caracteres."); return
        try:
            if not self.receive_input.text().strip():
                raise ValueError("Elige una carpeta recepción.")
            receive = Path(self.receive_input.text().strip()).resolve()
            receive.mkdir(parents=True, exist_ok=True)
            self.configure_startup(self.checks["start_windows"].isChecked())
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "Configuración", str(error)); return
        for key, value in {"device_name": name, "receive_folder": str(receive), "sync_folder": str(receive), "port": self.port_input.value(), "theme": self.theme_input.currentText(), **{k: c.isChecked() for k, c in self.checks.items()}}.items():
            self.runtime.db.set_setting(key, value)
        self.apply_theme(); QMessageBox.information(self, "Guardado", "Configuración guardada. Reinicia para actualizar anuncio LAN, puerto y carpeta recepción.")

    def configure_startup(self, enabled):
        if sys.platform != "win32":
            return
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE) as registry:
            try:
                winreg.DeleteValue(registry, "DeviceDrop")
            except FileNotFoundError:
                pass
            if enabled:
                launcher = Path(__file__).resolve().parents[2] / "scripts" / "launch_desktop.pyw"
                command = f'"{sys.executable}"' if getattr(sys, "frozen", False) else f'"{Path(sys._base_executable).with_name("pythonw.exe")}" -S "{launcher}"'
                winreg.SetValueEx(registry, "FileFastFlow", 0, winreg.REG_SZ, command)
            else:
                try:
                    winreg.DeleteValue(registry, "FileFastFlow")
                except FileNotFoundError:
                    pass

    def apply_theme(self):
        theme = self.runtime.db.setting("theme")
        dark = theme == "Dark" or (theme == "System" and self.palette().window().color().lightness() < 128)
        style = LIGHT
        if dark:
            for src, dst in [("#f5f8f7", "#15221f"), ("#18312e", "#e6eee9"), ("#6c807b", "#a8bcb4"), ("background: white", "background: #22342e"), ("#eaf1ee", "#1d2c27"), ("#e0e8e5", "#354b41"), ("#d0e7df", "#37574a")]:
                style = style.replace(src, dst)
        self.setStyleSheet(style)
        self.widget_theme_grid.apply_theme(dark)
        self.device_widget.apply_theme(dark)

    @staticmethod
    def clear(layout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().hide(); item.widget().deleteLater()
            if item.layout():
                MainWindow.clear(item.layout())

    def refresh(self):
        if self.runtime.start_error:
            self.status.setText(self.service_error_text())
        elif self.runtime.server and self.runtime.server.started:
            self.status.setText(f"● LAN activa   ·   {self.runtime.device()['ip']}:{self.runtime.port}   ·   {'Listo para recibir' if self.runtime.db.setting('allow_receive') else 'Recepción pausada'}")
        self.pairing_status.setText(self.status.text())
        self.pairing_button.setEnabled(bool(self.runtime.server and self.runtime.server.started and not self.runtime.start_error))
        peers = self.runtime.db.trusted()
        self.device_widget.refresh(peers, self.runtime.online, self.runtime.connections.results,
                                   self.checking_connections, self.space_messages, self.space_workers)
        if self.runtime.db.setting("widget_enabled"):
            self.device_widget.show_on_desktop()
        if self.widget_send_device is not None:
            self.device_widget.show_activity(self.space_messages.get(self.widget_send_device, ""))
        home_signature = [(p["device_id"], p["name"]) for p in peers]
        if getattr(self, "home_signature", None) != home_signature:
            self.home_signature = home_signature; self.clear(self.home_devices); self.device_spaces = {}
            if not peers:
                self.home_devices.addWidget(label("Agrega dispositivos para tener un espacio individual para cada uno.", "muted"))
                self.home_devices.addWidget(button("+ Vincular dispositivo", self.show_pairing, True))
            for peer in peers:
                space = self.make_file_space(peer["name"], "Los archivos de este espacio se envían solo a este dispositivo.", peer["device_id"])
                self.device_spaces[peer["device_id"]] = space; self.home_devices.addWidget(space)
        self.general_space.connection.setText("1 dispositivo" if len(peers) == 1 else f"{len(peers)} dispositivos")
        for device_id, space in [(None, self.general_space), *self.device_spaces.items()]:
            if device_id:
                space.connection.setText(self.connection_label(device_id))
            try:
                files = self.spaces.files(device_id); space.update_files(files)
            except OSError:
                files = []; self.space_messages[device_id] = "No se pudo leer la carpeta de este espacio."
            busy = device_id in self.space_workers
            space.select_button.setEnabled(not busy); space.send_button.setEnabled(bool(files) and not busy)
            message = self.space_messages.get(device_id, "")
            space.activity.setText(message); space.activity.setVisible(bool(message))
        nearby = [p for p in self.runtime.discovery.snapshot() if p.get("online") and p["device_id"] not in {d["device_id"] for d in peers}]
        self.device_map.update_devices(self.runtime.device(), peers, nearby, self.runtime.online,
            self.runtime.connections.results, self.checking_connections,
            self.pairing_button.isEnabled(), self.runtime.db.setting("allow_receive"), bool(self.runtime.start_error))
        self.devices_empty.setVisible(not peers and not nearby)
        rows = self.runtime.db.history(); self.clear(self.recent)
        self.refresh_fleet()
        self.copy_received_action.setEnabled(self.last_received() is not None)
        for layout, records in [(self.recent, rows[:3])]:
            if not records:
                layout.addWidget(label("Aquí aparecerán tus transferencias.", "muted"))
            for record in records:
                frame, box = card(); peer_id = record["source_device"] if record["direction"] == "incoming" else record["destination_device"]
                peer_name = next((p["name"] for p in peers if p["device_id"] == peer_id), peer_id[:8])
                from datetime import datetime
                stamp = datetime.fromtimestamp(record["started_at"]).strftime("%d/%m %H:%M")
                box.addWidget(label(record["filename"])); box.addWidget(label(f"{'←' if record['direction'] == 'incoming' else '→'} {peer_name} · {size_text(record['size'])} · {record['status']} · {stamp}", "muted"))
                if record["status"] not in {"completed", "failed", "cancelled"}:
                    bar = QProgressBar(); bar.setValue(int(record["bytes_done"] * 100 / max(record["size"], 1))); box.addWidget(bar)
                    box.addWidget(label(f"{size_text(record['speed'])}/s", "muted")); box.addWidget(button("Cancelar", lambda checked=False, tid=record["transfer_id"]: self.runtime.cancel(tid), True))
                elif record["saved_path"] and record["status"] == "completed":
                    saved = Path(record["saved_path"])
                    if record["mime_type"].startswith("image/") and saved.exists():
                        pix = QPixmap(str(saved))
                        thumb = QLabel(); thumb.setPixmap(pix.scaled(180, 110, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)); box.addWidget(thumb)
                        box.addWidget(label(f"{pix.width()} × {pix.height()} px", "muted"))
                    box.addWidget(button("Abrir archivo", lambda checked=False, p=str(saved), m=record["mime_type"]: self.preview(p) if m.startswith("image/") else self.open_path(p), True))
                    box.addWidget(button("Copiar", lambda checked=False, p=str(saved): self.copy_received_file(p), True))
                if record["error"]:
                    box.addWidget(label(record["error"], "muted"))
                layout.addWidget(frame)

    def show_device_options(self, device_id):
        peers = self.runtime.db.trusted(device_id)
        if not peers:
            return
        peer = peers[0]
        dialog = QDialog(self); dialog.setWindowTitle(f"Opciones · {peer['name']}"); dialog.resize(440, 350)
        layout = QVBoxLayout(dialog)
        title = label(peer["name"], "spaceTitle"); title.setTextFormat(Qt.TextFormat.PlainText); layout.addWidget(title)
        layout.addWidget(label(f"{peer['platform']} · {self.connection_label(device_id)}", "muted"))
        layout.addWidget(label(f"IP guardada: {peer['ip']}:{peer['port']}", "muted"))
        result = self.runtime.connections.results.get(device_id)
        if result and "forward_online" in result:
            layout.addWidget(label(report_text(result), "muted"))
        layout.addWidget(button("Corregir IP / puerto", lambda: self.correct_peer_address(peer), True))
        for key, text in [("auto_accept", "Aceptar archivos automáticamente")]:
            check = QCheckBox(text); check.setChecked(bool(peer[key]))
            check.toggled.connect(lambda enabled, k=key: self.runtime.db.execute(f"UPDATE trusted_devices SET {k}=? WHERE device_id=?", (int(enabled), device_id)))
            layout.addWidget(check)
        def remove():
            self.unpair(device_id); dialog.accept()
        layout.addWidget(button("Desvincular", remove, True)); dialog.exec()

    def unpair(self, device_id):
        self.runtime.db.execute("DELETE FROM trusted_devices WHERE device_id=?", (device_id,)); self.refresh()

    def connection_label(self, device_id):
        if device_id in self.checking_connections:
            return "Validando conexión…"
        result = self.runtime.connections.results.get(device_id, {})
        if not self.runtime.online.get(device_id):
            return "Sin conexión" if device_id in self.runtime.online else "Sin comprobar"
        if result.get("reverse_online") is False:
            return "Conexión en un solo sentido"
        if result.get("reverse_online") is True:
            return "Conectado · ida y vuelta"
        return "Conectado · retorno sin comprobar"

    def validate_connections(self, device_id=None, ip=None, port=None, dialog_parent=None):
        parent = dialog_parent or self
        peers = self.runtime.db.trusted(device_id)
        peers = [p for p in peers if p["device_id"] not in self.checking_connections]
        if not peers:
            if not self.checking_connections:
                QMessageBox.information(parent, "Conexión", "Vincula primero un dispositivo.")
            return
        if not self.runtime.server or not self.runtime.server.started or self.runtime.start_error:
            QMessageBox.warning(parent, "Servicio local", "El servicio local no está disponible. Si hay otra copia de FileFastFlow abierta, sal de ella desde la bandeja y vuelve a iniciar esta. Revisa también el puerto en Configuración.")
            return
        ids = [p["device_id"] for p in peers]
        self.connection_dialog_parents.update({d: parent for d in ids})
        self.checking_connections.update(ids); self.refresh()
        async def check():
            import asyncio
            return await asyncio.gather(*(self.runtime.connections.check(d, ip=ip, port=port) for d in ids))
        def finished(future):
            try:
                self.bridge.connection_result.emit({"ids": ids, "results": future.result()})
            except Exception:
                self.bridge.connection_result.emit({"ids": ids, "error": "No se pudo completar la validación. Comprueba que el servicio local esté activo."})
        try:
            self.runtime.submit(check()).add_done_callback(finished)
        except RuntimeError:
            for d in ids:
                self.connection_dialog_parents.pop(d, None)
            self.checking_connections.difference_update(ids); self.refresh()
            QMessageBox.warning(parent, "Servicio local", "El servicio local todavía no está listo. Inténtalo de nuevo.")

    def connections_received(self, data):
        parents = [self.connection_dialog_parents.pop(d, self) for d in data["ids"]]
        parent = parents[0] if parents else self
        self.checking_connections.difference_update(data["ids"]); self.refresh()
        if data.get("error"):
            QMessageBox.warning(parent, "Validar conexión", data["error"]); return
        results = data["results"]
        text = "\n\n".join(report_text(item) for item in results)
        ok = all(item["forward_online"] and item.get("reverse_online") is True for item in results)
        (QMessageBox.information if ok else QMessageBox.warning)(parent, "Validar conexión", text)

    def correct_peer_address(self, peer):
        dialog = QDialog(self); dialog.setWindowTitle(f"Dirección de {peer['name']}"); layout = QFormLayout(dialog)
        address = QLineEdit(peer["ip"]); port = QSpinBox(); port.setRange(45000, 45999); port.setValue(peer["port"])
        layout.addRow(label("Consulta la IP y el puerto mostrados en el otro dispositivo. Se guardarán solo si responde el dispositivo vinculado.", "muted"))
        layout.addRow("IP local", address); layout.addRow("Puerto", port)
        def validate():
            try:
                self.runtime.endpoint({"ip": address.text().strip(), "port": port.value()})
            except Exception:
                QMessageBox.warning(dialog, "Dirección", "Escribe una IP local y un puerto válido."); return
            self.validate_connections(peer["device_id"], address.text().strip(), port.value()); dialog.accept()
        layout.addRow(button("Validar y guardar dirección", validate)); dialog.exec()

    def service_error_text(self):
        if self.runtime.start_error in {"PORT_IN_USE", "SystemExit"}:
            return f"El puerto LAN {self.runtime.port} está ocupado. Sal de las copias anteriores de FileFastFlow desde la bandeja y vuelve a abrir la aplicación."
        return f"No se pudo iniciar el servicio LAN ({self.runtime.start_error}). Revisa el puerto {self.runtime.port} y los permisos de red."

    def show_pairing(self):
        if self.runtime.start_error:
            QMessageBox.warning(self, "Servicio LAN", self.service_error_text()); return
        if not self.runtime.server or not self.runtime.server.started:
            QMessageBox.information(self, "Servicio", "Espera a que el servicio LAN esté listo."); return
        data = self.runtime.pairing.open(); dialog = QDialog(self); dialog.setWindowTitle("Vincular dispositivo"); layout = QVBoxLayout(dialog)
        layout.addWidget(label("En Android, elige vincular y escanea este QR.", "brand")); layout.addWidget(label(f"Código: {data['code']}", "title")); countdown = label("Caduca en 120 segundos", "muted"); layout.addWidget(countdown)
        image = qrcode.make(json.dumps(data["qr"])); buffer = io.BytesIO(); image.save(buffer, format="PNG"); pix = QPixmap(); pix.loadFromData(buffer.getvalue()); qr = QLabel(); qr.setPixmap(pix.scaled(290, 290)); layout.addWidget(qr)
        layout.addWidget(label(f"IP: {data['qr']['ip']}   Puerto: {data['qr']['port']}", "muted")); counter = [120]; timer = QTimer(dialog)
        def tick():
            counter[0] -= 1; countdown.setText(f"Caduca en {max(0, counter[0])} segundos")
            if counter[0] <= 0 or self.runtime.pairing.code is None:
                timer.stop(); countdown.setText("Código caducado o utilizado"); qr.clear()
        timer.timeout.connect(tick); timer.start(1000); dialog.exec()

    def connect_pairing(self, peer=None):
        if not isinstance(peer, dict):
            peer = {}
        dialog = QDialog(self); dialog.setWindowTitle("Vincular por IP o QR"); layout = QFormLayout(dialog)
        ip = QLineEdit(peer.get("ip", "")); port = QSpinBox(); port.setRange(45000, 45999); port.setValue(int(peer.get("port", 45832))); code = QLineEdit(); qr = QLineEdit()
        layout.addRow("IP local", ip); layout.addRow("Puerto", port); layout.addRow("Código de 6 dígitos", code); layout.addRow("O pega el contenido JSON del QR", qr)
        def connect():
            try:
                address, number, token = ip.text().strip(), port.value(), code.text().strip()
                if qr.text().strip():
                    data = json.loads(qr.text()); address, number, token = data["ip"], data["port"], data["pairing_token"]
                self.runtime.endpoint({"ip": address, "port": number})
                future = self.runtime.submit(self.runtime.pair(address, number, token))
                def result(done):
                    try:
                        device = done.result(); self.bridge.result.emit(True, f"Vinculado con {device['device_name']}")
                    except Exception as error:
                        self.bridge.result.emit(False, getattr(error, "code", "NETWORK_ERROR"))
                future.add_done_callback(result); dialog.accept()
            except (ValueError, KeyError):
                QMessageBox.warning(dialog, "Datos", "Revisa la IP, el puerto y el QR.")
        layout.addRow(button("Vincular", connect)); dialog.exec()

    def result_received(self, ok, text):
        (QMessageBox.information if ok else QMessageBox.warning)(self, "FileFastFlow", text)

    def select_space_files(self, device_id=None, parent=None):
        paths, _ = QFileDialog.getOpenFileNames(parent or self, "Seleccionar archivos")
        if paths:
            self.store_space_files(paths, device_id)

    def store_space_files(self, paths, device_id=None):
        if device_id in self.space_workers:
            return
        if device_id and not self.runtime.db.trusted(device_id):
            return
        worker = SpaceStoreWorker(self.spaces, paths, device_id, self)
        self.space_workers[device_id] = worker; self.space_messages[device_id] = "Guardando archivos…"
        worker.completed.connect(lambda saved, error: self.space_stored(saved, error, device_id))
        worker.finished.connect(lambda: self.space_store_finished(device_id))
        worker.finished.connect(worker.deleteLater)
        self.refresh(); worker.start()

    def space_stored(self, paths, error, device_id):
        if paths:
            self.send_space_files(paths, device_id)
        if error:
            self.space_messages[device_id] = "No se pudieron guardar todos los archivos. Los ya guardados se conservan."
            QMessageBox.warning(self, "Guardar archivos", f"No se pudieron guardar todos los archivos.\n{error}")
        self.refresh()

    def space_store_finished(self, device_id):
        self.space_workers.pop(device_id, None); self.refresh()

    def send_space_files(self, paths, device_id=None):
        if not paths:
            return
        destinations = [p["device_id"] for p in self.runtime.db.trusted(device_id)]
        if not destinations:
            self.space_messages[device_id] = "Archivos guardados. Vincula un dispositivo para enviarlos."
        else:
            try:
                self.runtime.send_files(paths, destinations)
                self.space_messages[device_id] = "Archivos guardados. Envío iniciado; consulta las transferencias recientes en Inicio."
            except RuntimeError:
                self.space_messages[device_id] = "Archivos guardados. Cuando el servicio esté listo, pulsa Enviar guardados."
        self.refresh()

    def event_received(self, event):
        if event["type"] == "local_update_received":
            self.refresh_fleet()
            if self.runtime.db.setting("notifications"):
                self.tray_copy_path = None; self.tray_notification_page = self.SOFTWARE_PAGE
                self.tray.showMessage("Actualización local recibida", "Abre Instaladores y actualizaciones para instalar los cambios de tu PC.", QSystemTrayIcon.MessageIcon.Information, 10000)
        if event["type"] == "transfer_offer":
            result = QMessageBox.question(self, "Recibir archivo", f"{event['sender']} quiere enviarte {event['filename']} ({size_text(event['size'])}).")
            self.runtime.approve(event["transfer_id"], result == QMessageBox.StandardButton.Yes)
        if event["type"] == "transfer_completed" and event.get("saved_path") and not event.get("update_revision"):
            if self.runtime.db.setting("notifications"):
                self.tray_notification_page = self.HOME_PAGE
                self.tray_copy_path = None
                if not self.receipt_notifier.show(event["transfer_id"], event["filename"]):
                    self.tray_copy_path = event["saved_path"]
                    self.tray.showMessage("Archivo recibido", event["filename"] + " · Haz clic para copiar.", QSystemTrayIcon.MessageIcon.Information, 5000)
            if event.get("mime_type", "").startswith("image/"):
                self.last_preview = event["saved_path"]
        if event["type"] == "discovery_error":
            QMessageBox.information(self, "Descubrimiento", event["error"])

    def preview(self, path):
        dialog = QDialog(self); dialog.setWindowTitle(Path(path).name); layout = QVBoxLayout(dialog); pix = QPixmap(path); view = QLabel(); view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        view.setPixmap(pix.scaled(1100, 750, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)); layout.addWidget(view); dialog.showMaximized(); dialog.exec()

    @staticmethod
    def open_path(path):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def toggle_receive(self):
        value = not self.runtime.db.setting("allow_receive"); self.runtime.db.set_setting("allow_receive", value); self.checks["allow_receive"].setChecked(value)

    def closeEvent(self, event):
        if not self.quitting:
            self.hide(); event.ignore()
        else:
            event.accept()

    def restore_window(self):
        from PySide6.QtWidgets import QApplication
        restore_application_window(self, QApplication.instance())

    def tray_activated(self, reason):
        if reason in {QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick}:
            self.restore_window()

    def quit(self):
        if self.quitting:
            return
        if self.local_build_worker is not None:
            QMessageBox.information(self, "Preparando actualización", "Espera a que termine la compilación antes de salir."); return
        if self.space_workers:
            QMessageBox.information(self, "Guardando archivos", "Espera a que termine la copia de los archivos antes de salir.")
            return
        if self.package_worker is not None:
            QMessageBox.information(self, "Generando instalador", "Espera a que termine la generación del archivo antes de salir.")
            return
        self.update_timer.stop(); self.initial_update_timer.stop()
        self.local_build_timer.stop()
        if self.update_worker is not None:
            self.exit_after_update = True; self.update_worker.requestInterruption()
            self.update_status.setText("Cerrando la consulta o descarga de actualización…")
            return
        from PySide6.QtWidgets import QApplication
        self.quitting = True; self.timer.stop(); self.tray.hide(); self.runtime.bus.listeners.clear()
        self.device_widget.save_position(); self.device_widget.hide()
        self.runtime.stop(); QApplication.instance().quit()
