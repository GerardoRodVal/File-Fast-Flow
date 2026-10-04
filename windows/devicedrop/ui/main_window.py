import io
import json
import os
from pathlib import Path
import sys

import qrcode
from PySide6.QtCore import Qt, QTimer, Signal, QObject, QUrl, QSize
from PySide6.QtGui import QDesktopServices, QIcon, QPixmap, QColor, QPainter
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QListWidget, QListWidgetItem, QStackedWidget, QFileDialog, QMessageBox,
    QDialog, QLineEdit, QFormLayout, QCheckBox, QSpinBox, QComboBox, QSystemTrayIcon,
    QMenu, QScrollArea, QProgressBar, QFrame, QInputDialog)
from devicedrop.packages import PackageWorker, default_filename
from devicedrop.network.connectivity import report_text
from devicedrop import __version__
from devicedrop.updates import UpdateWorker, REPOSITORY_URL, RELEASES_URL, verify_installer

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
QListWidget::item:selected { background: #d0e7df; color: #075c4c; }
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


class MainWindow(QMainWindow):
    def __init__(self, runtime):
        super().__init__()
        self.runtime = runtime; self.quitting = False; self.last_preview = None
        self.package_worker = None; self.last_package = None
        self.update_worker = None; self.available_update = None; self.downloaded_update = None
        self.exit_after_update = False; self.manual_update_check = False
        self.tray_notification_page = 0
        self.checking_connections = set()
        self.bridge = Bridge(); self.bridge.event.connect(self.event_received); self.bridge.result.connect(self.result_received)
        self.bridge.connection_result.connect(self.connections_received)
        self.runtime.bus.listeners.append(self.bridge.event.emit)
        self.setWindowTitle("FileFastFlow"); self.setWindowIcon(app_icon()); self.resize(1120, 800); self.setMinimumSize(820, 650)
        self.setAcceptDrops(True)
        root = QWidget(); self.setCentralWidget(root); outer = QHBoxLayout(root); outer.setContentsMargins(24, 24, 24, 24); outer.setSpacing(28)
        side = QVBoxLayout(); side.addWidget(label("⇄  FileFastFlow", "brand")); side.addWidget(label("Tus archivos, cerca de ti.", "muted")); side.addSpacing(26)
        self.nav = QListWidget(); self.nav.setFixedWidth(205)
        self.nav.addItems(["Inicio", "Dispositivos", "Compartidos", "Historial", "Configuración", "Instaladores", "Actualizaciones"]); side.addWidget(self.nav)
        side.addWidget(label("LOCAL · SIN CUENTAS\nHTTP LAN · sin cifrado TLS", "muted")); outer.addLayout(side)
        self.pages = QStackedWidget(); outer.addWidget(self.pages, 1)
        self.home = self.page("Comparte sin complicaciones", "Envía archivos entre tus dispositivos en la misma red.")
        self.home_devices = QVBoxLayout(); self.home.addLayout(self.home_devices)
        drop, box = card(); box.addWidget(label("↓   Arrastra archivos aquí", "brand")); box.addWidget(label("Fotos, documentos o archivos grandes. Elige a quién enviarlos.", "muted"))
        box.addWidget(button("Seleccionar archivos", self.select_files)); self.home.addWidget(drop)
        self.status = label("Iniciando servicio local…", "muted"); self.home.addWidget(self.status)
        self.recent = QVBoxLayout(); self.home.addWidget(label("Transferencias recientes", "brand")); self.home.addLayout(self.recent); self.home.addStretch()
        self.devices_page = self.page("Tus dispositivos", "Vincula una vez y comparte cuando estén conectados.")
        row = QHBoxLayout(); row.addWidget(button("Mostrar código / QR", self.show_pairing)); row.addWidget(button("Vincular por IP o QR", self.connect_pairing, True)); self.devices_page.addLayout(row)
        self.validate_connections_button = button("Validar conexiones", lambda: self.validate_connections(), True)
        self.devices_page.addWidget(self.validate_connections_button)
        self.devices_list = QVBoxLayout(); self.devices_page.addLayout(self.devices_list)
        self.discovered = QVBoxLayout(); self.devices_page.addWidget(label("Cerca de ti", "brand")); self.devices_page.addLayout(self.discovered); self.devices_page.addStretch()
        self.shared_page = self.page("Carpeta compartida", "Los archivos nuevos se envían a los dispositivos con Auto Sync.")
        folder, box = card(); self.shared_path = label(self.runtime.db.setting("sync_folder")); box.addWidget(self.shared_path)
        box.addWidget(button("Abrir carpeta compartida", lambda: self.open_path(self.runtime.db.setting("sync_folder"))))
        box.addWidget(label("Espera 3 segundos de estabilidad. Los cambios y eliminaciones se detectan, pero no se sincronizan en V1.", "muted")); self.shared_page.addWidget(folder); self.shared_page.addStretch()
        self.history_page = self.page("Historial", "Tus envíos y archivos recibidos se guardan en este dispositivo.")
        self.history_list = QVBoxLayout(); self.history_page.addLayout(self.history_list); self.history_page.addStretch()
        self.settings_page = self.page("Configuración", "Personaliza este dispositivo.")
        self.make_settings()
        self.make_packages()
        self.make_updates()
        self.nav.currentRowChanged.connect(self.pages.setCurrentIndex); self.nav.setCurrentRow(0)
        self.tray = QSystemTrayIcon(app_icon(), self); self.tray.setToolTip("FileFastFlow · LAN")
        menu = QMenu(); menu.addAction("Abrir FileFastFlow", self.showNormal); menu.addAction("Pausar / activar recepción", self.toggle_receive)
        menu.addAction("Abrir recibidos", lambda: self.open_path(self.runtime.db.setting("receive_folder"))); menu.addSeparator(); menu.addAction("Salir", self.quit)
        self.tray.setContextMenu(menu); self.tray.activated.connect(lambda reason: self.showNormal() if reason == QSystemTrayIcon.ActivationReason.DoubleClick else None); self.tray.show()
        self.tray.messageClicked.connect(self.open_notification)
        menu.insertAction(menu.actions()[-1], menu.addAction("Buscar actualizaciones", lambda: self.check_updates(True)))
        self.timer = QTimer(self); self.timer.timeout.connect(self.refresh); self.timer.start(700)
        self.apply_theme(); self.refresh()
        self.update_timer = QTimer(self); self.update_timer.timeout.connect(self.auto_check_updates); self.update_timer.start(30 * 60 * 1000)
        self.initial_update_timer = QTimer(self); self.initial_update_timer.setSingleShot(True)
        self.initial_update_timer.timeout.connect(self.auto_check_updates); self.initial_update_timer.start(8000)

    def page(self, title, subtitle):
        content = QWidget(); layout = QVBoxLayout(content); layout.setSpacing(16); layout.setContentsMargins(0, 0, 8, 8)
        layout.addWidget(label(title, "title")); layout.addWidget(label(subtitle, "muted"))
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(content); self.pages.addWidget(scroll)
        return layout

    def make_settings(self):
        frame, layout = card(); form = QFormLayout()
        self.name_input = QLineEdit(self.runtime.db.setting("device_name")); form.addRow("Nombre", self.name_input)
        self.receive_input = QLineEdit(self.runtime.db.setting("receive_folder")); form.addRow("Carpeta recibidos", self.receive_input)
        self.sync_input = QLineEdit(self.runtime.db.setting("sync_folder")); form.addRow("Carpeta sincronizada", self.sync_input)
        self.port_input = QSpinBox(); self.port_input.setRange(45000, 45999); self.port_input.setValue(self.runtime.db.setting("port")); form.addRow("Puerto LAN", self.port_input)
        self.theme_input = QComboBox(); self.theme_input.addItems(["Light", "Dark", "System"]); self.theme_input.setCurrentText(self.runtime.db.setting("theme")); form.addRow("Tema", self.theme_input)
        layout.addLayout(form); self.checks = {}
        for key, text in [("allow_receive", "Permitir recepción"), ("minimize_tray", "Minimizar a bandeja al cerrar"), ("notifications", "Mostrar notificaciones"), ("start_windows", "Iniciar con Windows"), ("auto_updates", "Buscar actualizaciones y avisar automáticamente")]:
            check = QCheckBox(text); check.setChecked(self.runtime.db.setting(key)); self.checks[key] = check; layout.addWidget(check)
        layout.addWidget(button("Guardar configuración", self.save_settings)); layout.addWidget(label("Si el firewall bloquea la conexión, permite FileFastFlow en redes privadas. Los cambios de puerto o carpeta compartida se aplican al reiniciar.", "muted"))
        self.settings_page.addWidget(frame); self.settings_page.addStretch()

    def make_packages(self):
        page = self.page("Instaladores", "Lleva esta versión de FileFastFlow a otra PC o a tu Android.")
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
        page.addStretch()

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

    def make_updates(self):
        page = self.page("Actualizaciones", "Recibe los cambios publicados desde main en GitHub.")
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
        page.addWidget(frame); page.addStretch()

    def show_updates(self):
        self.showNormal(); self.raise_(); self.activateWindow(); self.nav.setCurrentRow(6)

    def open_notification(self):
        self.showNormal(); self.raise_(); self.activateWindow(); self.nav.setCurrentRow(self.tray_notification_page)

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
            self.tray_notification_page = 6
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
            receive, shared = Path(self.receive_input.text()).resolve(), Path(self.sync_input.text()).resolve()
            if receive == shared or receive.is_relative_to(shared) or shared.is_relative_to(receive):
                raise ValueError("Las carpetas de recibidos y sincronización deben estar separadas para evitar ciclos.")
            receive.mkdir(parents=True, exist_ok=True); shared.mkdir(parents=True, exist_ok=True)
            self.configure_startup(self.checks["start_windows"].isChecked())
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "Configuración", str(error)); return
        for key, value in {"device_name": name, "receive_folder": str(receive), "sync_folder": str(shared), "port": self.port_input.value(), "theme": self.theme_input.currentText(), **{k: c.isChecked() for k, c in self.checks.items()}}.items():
            self.runtime.db.set_setting(key, value)
        self.apply_theme(); self.shared_path.setText(str(shared)); QMessageBox.information(self, "Guardado", "Configuración guardada. Reinicia para actualizar anuncio LAN, puerto y carpeta compartida.")

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
                launcher = Path(__file__).resolve().parents[2] / "scripts" / "run_dev.py"
                command = f'"{sys.executable}"' if getattr(sys, "frozen", False) else f'"{sys.executable}" "{launcher}"'
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
            for src, dst in [("#f5f8f7", "#15221f"), ("#18312e", "#e6eee9"), ("background: white", "background: #22342e"), ("#eaf1ee", "#1d2c27"), ("#e0e8e5", "#354b41"), ("#d0e7df", "#37574a")]:
                style = style.replace(src, dst)
        self.setStyleSheet(style)

    @staticmethod
    def clear(layout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            if item.layout():
                MainWindow.clear(item.layout())

    def refresh(self):
        if self.runtime.start_error:
            self.status.setText("No se pudo iniciar el servicio. Revisa si el puerto está ocupado.")
        elif self.runtime.server and self.runtime.server.started:
            self.status.setText(f"● LAN activa   ·   {self.runtime.device()['ip']}:{self.runtime.port}   ·   {'Listo para recibir' if self.runtime.db.setting('allow_receive') else 'Recepción pausada'}")
        peers = self.runtime.db.trusted()
        self.clear(self.home_devices)
        if not peers:
            self.home_devices.addWidget(button("+ Vincula tu primer dispositivo", self.show_pairing, True))
        else:
            self.home_devices.addWidget(label("Tus dispositivos", "brand"))
            for peer in peers:
                self.home_devices.addWidget(label(f"{'●' if self.runtime.online.get(peer['device_id']) else '○'}   {peer['name']}   ·   {self.connection_label(peer['device_id'])}"))
        # Avoid rebuilding focused device controls every timer tick.
        signature = [(p["device_id"], p["auto_sync"], p["auto_accept"], p["ip"], p["port"], self.runtime.online.get(p["device_id"]), p["device_id"] in self.checking_connections, self.runtime.connections.results.get(p["device_id"], {}).get("checked_at")) for p in peers]
        if getattr(self, "device_signature", None) != signature:
            self.device_signature = signature; self.clear(self.devices_list)
            for peer in peers:
                frame, layout = card(); layout.addWidget(label(peer["name"], "brand")); layout.addWidget(label(f"{peer['platform']} · {self.connection_label(peer['device_id'])}", "muted"))
                layout.addWidget(label(f"IP guardada: {peer['ip']}:{peer['port']}", "muted"))
                controls = QHBoxLayout()
                validate = button("Validar conexión", lambda checked=False, d=peer["device_id"]: self.validate_connections(d), True)
                validate.setEnabled(peer["device_id"] not in self.checking_connections); controls.addWidget(validate)
                controls.addWidget(button("Corregir IP / puerto", lambda checked=False, p=peer: self.correct_peer_address(p), True)); layout.addLayout(controls)
                result = self.runtime.connections.results.get(peer["device_id"])
                if result and (result.get("code") or result.get("reverse_online") is not None):
                    layout.addWidget(label(report_text(result), "muted"))
                for key, text in [("auto_accept", "Aceptar archivos automáticamente"), ("auto_sync", "Auto Sync de carpeta compartida")]:
                    check = QCheckBox(text); check.setChecked(bool(peer[key])); check.toggled.connect(lambda enabled, d=peer["device_id"], k=key: self.runtime.db.execute(f"UPDATE trusted_devices SET {k}=? WHERE device_id=?", (int(enabled), d))); layout.addWidget(check)
                layout.addWidget(button("Desvincular", lambda checked=False, d=peer["device_id"]: self.unpair(d), True)); self.devices_list.addWidget(frame)
        self.clear(self.discovered)
        nearby = [p for p in self.runtime.discovery.snapshot() if p.get("online") and p["device_id"] not in {d["device_id"] for d in peers}]
        self.discovered.addWidget(label("No hay dispositivos nuevos. Abre FileFastFlow en tu Android." if not nearby else "", "muted"))
        for peer in nearby:
            self.discovered.addWidget(button(f"Vincular {peer['device_name']} · {peer['ip']}", lambda checked=False, p=peer: self.connect_pairing(p)))
        rows = self.runtime.db.history(); self.clear(self.recent); self.clear(self.history_list)
        for layout, records in [(self.recent, rows[:3]), (self.history_list, rows)]:
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
                if record["error"]:
                    box.addWidget(label(record["error"], "muted"))
                layout.addWidget(frame)

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

    def validate_connections(self, device_id=None, ip=None, port=None):
        peers = self.runtime.db.trusted(device_id)
        peers = [p for p in peers if p["device_id"] not in self.checking_connections]
        if not peers:
            if not self.checking_connections:
                QMessageBox.information(self, "Conexión", "Vincula primero un dispositivo.")
            return
        if not self.runtime.server or not self.runtime.server.started or self.runtime.start_error:
            QMessageBox.warning(self, "Servicio local", "El servicio local no está disponible. Si hay otra copia de FileFastFlow abierta, sal de ella desde la bandeja y vuelve a iniciar esta. Revisa también el puerto en Configuración.")
            return
        ids = [p["device_id"] for p in peers]
        self.checking_connections.update(ids); self.refresh()
        async def check():
            import asyncio
            return await asyncio.gather(*(self.runtime.connections.check(d, ip=ip, port=port) for d in ids))
        def finished(future):
            try:
                self.bridge.connection_result.emit({"ids": ids, "results": future.result()})
            except Exception:
                self.bridge.connection_result.emit({"ids": ids, "error": "No se pudo completar la validación. Comprueba que el servicio local esté activo."})
        self.runtime.submit(check()).add_done_callback(finished)

    def connections_received(self, data):
        self.checking_connections.difference_update(data["ids"]); self.refresh()
        if data.get("error"):
            QMessageBox.warning(self, "Validar conexión", data["error"]); return
        results = data["results"]
        text = "\n\n".join(report_text(item) for item in results)
        ok = all(item["forward_online"] and item.get("reverse_online") is True for item in results)
        (QMessageBox.information if ok else QMessageBox.warning)(self, "Validar conexión", text)

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

    def show_pairing(self):
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

    def select_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Seleccionar archivos")
        if paths:
            self.choose_target(paths)

    def choose_target(self, paths):
        peers = self.runtime.db.trusted()
        if not peers:
            QMessageBox.information(self, "Vincula un dispositivo", "Vincula primero un dispositivo desde Dispositivos."); return
        dialog = QDialog(self); dialog.setWindowTitle("Enviar a"); layout = QVBoxLayout(dialog); checks = []
        layout.addWidget(label(f"{len(paths)} archivos seleccionados", "brand"))
        for peer in peers:
            check = QCheckBox(peer["name"]); check.setChecked(len(peers) == 1); layout.addWidget(check); checks.append((check, peer["device_id"]))
        layout.addWidget(button("Seleccionar todos", lambda: [c.setChecked(True) for c, _ in checks], True))
        def send():
            destinations = [d for c, d in checks if c.isChecked()]
            if destinations:
                self.runtime.send_files(paths, destinations); dialog.accept()
        layout.addWidget(button("Enviar archivos", send)); dialog.exec()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile() and Path(u.toLocalFile()).is_file()]
        if paths:
            self.choose_target(paths); event.acceptProposedAction()

    def event_received(self, event):
        if event["type"] == "transfer_offer":
            result = QMessageBox.question(self, "Recibir archivo", f"{event['sender']} quiere enviarte {event['filename']} ({size_text(event['size'])}).")
            self.runtime.approve(event["transfer_id"], result == QMessageBox.StandardButton.Yes)
        if event["type"] == "transfer_completed" and event.get("saved_path"):
            if self.runtime.db.setting("notifications"):
                self.tray_notification_page = 3
                self.tray.showMessage("Archivo recibido", event["filename"], QSystemTrayIcon.MessageIcon.Information, 5000)
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
        if not self.quitting and self.runtime.db.setting("minimize_tray") and self.tray.isSystemTrayAvailable():
            self.hide(); event.ignore()
        else:
            self.quit()
            if self.quitting:
                event.accept()
            else:
                event.ignore()

    def quit(self):
        if self.quitting:
            return
        if self.package_worker is not None:
            QMessageBox.information(self, "Generando instalador", "Espera a que termine la generación del archivo antes de salir.")
            return
        self.update_timer.stop(); self.initial_update_timer.stop()
        if self.update_worker is not None:
            self.exit_after_update = True; self.update_worker.requestInterruption()
            self.update_status.setText("Cerrando la consulta o descarga de actualización…")
            return
        from PySide6.QtWidgets import QApplication
        self.quitting = True; self.timer.stop(); self.tray.hide(); self.runtime.bus.listeners.clear()
        self.runtime.stop(); QApplication.instance().quit()
