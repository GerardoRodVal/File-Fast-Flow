import time
from uuid import uuid4
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QCloseEvent
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox, QDialog, QLabel

from devicedrop.ui.main_window import MainWindow


@pytest.fixture
def window(runtime, monkeypatch):
    app = QApplication.instance() or QApplication([])
    window = MainWindow(runtime)
    window.timer.stop(); window.initial_update_timer.stop(); window.update_timer.stop()
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: QMessageBox.StandardButton.Ok)
    yield window
    for worker in list(window.space_workers.values()):
        worker.wait(10000)
    app.processEvents()
    window.device_widget.hide()
    window.device_widget.deleteLater()
    window.tray.hide(); runtime.bus.listeners.clear(); window.deleteLater(); app.processEvents()


def wait_for_copy(window):
    deadline = time.monotonic() + 5
    while window.space_workers and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(.01)
    assert not window.space_workers


def drop_files(space, urls):
    mime = QMimeData(); mime.setUrls(urls)
    enter = QDragEnterEvent(QPoint(10, 10), Qt.DropAction.CopyAction, mime,
                          Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(space, enter)
    drop = QDropEvent(QPointF(10, 10), Qt.DropAction.CopyAction, mime,
                     Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(space, drop)
    return enter, drop


def add_peer(runtime, name="Otra PC"):
    device_id = str(uuid4())
    runtime.db.trust({"device_id": device_id, "device_name": name, "platform": "windows",
                      "ip": "127.0.0.1", "port": 45834}, "t" * 32)
    return device_id


def test_settings_use_one_reception_folder(window, runtime, tmp_path, monkeypatch):
    assert not hasattr(window, "sync_input")
    assert "Carpeta recepción" in {item.text() for item in window.findChildren(QLabel)}
    assert window.receive_input.text() == str(runtime.spaces.root)
    monkeypatch.setattr(window, "configure_startup", lambda enabled: None)
    monkeypatch.setattr(QMessageBox, "information", lambda *args: QMessageBox.StandardButton.Ok)
    folder = tmp_path / "reception"
    window.receive_input.setText(str(folder)); window.save_settings()
    assert runtime.db.setting("receive_folder") == runtime.db.setting("sync_folder") == str(folder)
    assert folder.is_dir()


def test_general_drop_saves_and_sends_to_all_linked_devices(window, runtime, peer, tmp_path):
    second = add_peer(runtime); window.refresh()
    sent = []; runtime.send_files = lambda paths, ids: sent.append((paths, ids))
    source = tmp_path / "drag.txt"; source.write_text("drop")
    enter, drop = drop_files(window.general_space, [QUrl.fromLocalFile(str(source)),
        QUrl("https://example.invalid/remote"), QUrl.fromLocalFile(str(tmp_path))])
    assert enter.isAccepted() and drop.isAccepted()
    wait_for_copy(window)
    saved = window.spaces.files()
    assert len(saved) == 1 and saved[0].read_text() == "drop"
    assert source.exists() and saved[0] != source
    assert sent == [(saved, [peer["device_id"], second])]
    assert window.general_space.file_list.count() == 1


def test_individual_drop_and_file_picker_only_send_to_that_device(window, runtime, peer, tmp_path, monkeypatch):
    second = add_peer(runtime); window.refresh()
    sent = []; runtime.send_files = lambda paths, ids: sent.append((paths, ids))
    source = tmp_path / "private.txt"; source.write_text("solo este dispositivo")
    _, drop = drop_files(window.device_spaces[peer["device_id"]], [QUrl.fromLocalFile(str(source))])
    assert drop.isAccepted(); wait_for_copy(window)
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", lambda *args: ([str(source)], ""))
    window.device_spaces[second].select_button.click(); wait_for_copy(window)
    assert [ids for _, ids in sent] == [[peer["device_id"]], [second]]
    assert len(window.spaces.files(peer["device_id"])) == len(window.spaces.files(second)) == 1
    assert window.spaces.files() == []
    assert sent[0][0][0].parent != sent[1][0][0].parent


def test_space_controls_survive_refresh_and_follow_pairing(window, runtime, peer):
    window.refresh(); space = window.device_spaces[peer["device_id"]]
    runtime.online[peer["device_id"]] = True; window.refresh()
    assert window.device_spaces[peer["device_id"]] is space
    assert "Conectado" in space.connection.text()
    second = add_peer(runtime); window.refresh()
    assert set(window.device_spaces) == {peer["device_id"], second}
    window.unpair(second)
    assert set(window.device_spaces) == {peer["device_id"]}


def test_empty_general_space_can_store_without_devices_and_resend_later(window, runtime, tmp_path):
    source = tmp_path / "later.txt"; source.write_text("para después")
    window.store_space_files([str(source)]); wait_for_copy(window)
    saved = window.spaces.files()
    assert len(saved) == 1 and "Vincula" in window.general_space.activity.text()
    device_id = add_peer(runtime); window.refresh()
    sent = []; runtime.send_files = lambda paths, ids: sent.append((paths, ids))
    window.general_space.send_button.click()
    assert sent == [(saved, [device_id])]


def test_invalid_drops_are_rejected(window, tmp_path):
    for urls in [[QUrl("https://example.invalid/remote")], [QUrl.fromLocalFile(str(tmp_path))]]:
        enter, drop = drop_files(window.general_space, urls)
        assert not enter.isAccepted() and not drop.isAccepted()
    assert not window.space_workers


@pytest.mark.parametrize("theme", ["Light", "Dark"])
def test_menu_text_stays_white_when_selected(window, runtime, theme):
    runtime.db.set_setting("theme", theme); window.apply_theme()
    window.nav.ensurePolished()
    window.nav.setCurrentRow(1)
    assert window.nav.palette().text().color().name() == "#ffffff"
    selected_style = window.styleSheet().split("QListWidget#navigation::item:selected", 1)[1].split("}", 1)[0]
    assert "color: #ffffff" in selected_style


def test_close_keeps_background_service_even_with_old_setting_disabled(window, runtime, monkeypatch):
    runtime.db.set_setting("minimize_tray", False)
    window.tray.isSystemTrayAvailable = lambda: False
    stopped = []; monkeypatch.setattr(runtime, "stop", lambda: stopped.append(True))
    window.show()
    close = QCloseEvent(); window.closeEvent(close)
    assert not close.isAccepted() and not window.isVisible()
    assert not stopped and not window.quitting
    window.restore_window()
    assert window.isVisible()


@pytest.mark.parametrize("reason", ["Trigger", "DoubleClick"])
def test_tray_click_restores_hidden_main_window(window, reason):
    from PySide6.QtWidgets import QSystemTrayIcon
    window.show(); window.closeEvent(QCloseEvent())
    assert not window.isVisible()
    window.tray.activated.emit(getattr(QSystemTrayIcon.ActivationReason, reason))
    assert window.isVisible() and not window.isMinimized()


def test_tray_context_click_does_not_open_main_window(window):
    from PySide6.QtWidgets import QSystemTrayIcon
    window.hide()
    window.tray.activated.emit(QSystemTrayIcon.ActivationReason.Context)
    assert not window.isVisible()


def test_restore_main_window_preserves_maximization_and_raises_modal_dialog(window):
    window.showMaximized(); window.hide()
    dialog = QDialog(window); dialog.setModal(True); dialog.show()
    try:
        QApplication.processEvents()
        window.restore_window()
        assert window.isVisible() and window.isMaximized()
        assert dialog.isVisible()
    finally:
        dialog.close()


def test_qr_button_tracks_server_startup_and_reports_port_conflicts(window, runtime, monkeypatch):
    window.refresh()
    assert not window.pairing_button.isEnabled()
    runtime.server = SimpleNamespace(started=True); window.refresh()
    assert window.pairing_button.isEnabled()
    runtime.start_error = "PORT_IN_USE"; runtime.server.started = False; window.refresh()
    messages = []; monkeypatch.setattr(QMessageBox, "warning", lambda *args: messages.append(args[-1]))
    window.show_pairing()
    assert not window.pairing_button.isEnabled()
    assert str(runtime.port) in messages[-1] and "ocupado" in messages[-1]
    assert "Espera" not in messages[-1]
    assert window.pairing_status.text() == window.status.text()


def test_ready_service_displays_real_qr_and_pairing_code(window, runtime, monkeypatch):
    runtime.server = SimpleNamespace(started=True)
    dialogs = []
    def inspect(dialog):
        labels = dialog.findChildren(QLabel)
        dialogs.append(dialog.windowTitle())
        assert any(item.text().startswith("Código:") for item in labels)
        assert any(not item.pixmap().isNull() for item in labels)
        return 0
    monkeypatch.setattr(QDialog, "exec", inspect)
    window.refresh(); window.pairing_button.click()
    assert dialogs == ["Vincular dispositivo"]


def test_widget_toggle_syncs_menu_tray_and_persisted_preference(window, runtime):
    assert window.device_widget.isVisible()
    window.widget_enabled_check.click()
    assert not window.device_widget.isVisible()
    assert runtime.db.setting("widget_enabled") is False
    assert not window.widget_action.isChecked()
    window.widget_action.trigger()
    assert window.device_widget.isVisible()
    assert window.widget_enabled_check.isChecked()
    assert runtime.db.setting("widget_enabled") is True
    window.device_widget.close()
    assert not window.device_widget.isVisible()
    assert not window.widget_enabled_check.isChecked()
    assert not window.widget_action.isChecked()
    assert runtime.db.setting("widget_enabled") is False


def test_widget_remains_available_when_main_window_hides(window, runtime):
    window.show()
    window.tray.isSystemTrayAvailable = lambda: True
    window.closeEvent(QCloseEvent())
    assert not window.isVisible()
    assert window.device_widget.isVisible()
    window.device_widget.settings_requested.emit()
    assert window.isVisible()
    assert window.pages.currentIndex() == window.WIDGET_PAGE


@pytest.mark.parametrize("online,reverse,receiving,checking,status,color", [
    (None, None, None, False, "Sin comprobar", "#87958f"),
    (False, None, None, False, "Sin conexión", "#d84a4a"),
    (True, True, True, False, "Conectado", "#169b73"),
    (True, False, True, False, "Conexión en un solo sentido", "#d08a16"),
    (True, True, False, False, "Recepción remota pausada", "#d08a16"),
    (True, True, True, True, "Validando conexión…", "#d08a16"),
])
def test_widget_connection_states(window, runtime, peer, online, reverse, receiving, checking, status, color):
    device_id = peer["device_id"]
    if online is not None:
        runtime.online[device_id] = online
    runtime.connections.results[device_id] = {**peer, "forward_online": bool(online),
        "reverse_online": reverse, "remote_receiving": receiving}
    if checking:
        window.checking_connections.add(device_id)
    window.refresh()
    row = window.device_widget.rows[device_id]
    assert row.status.toolTip() == status
    assert color in row.dot.styleSheet()
    assert row.validate.isEnabled() is not checking
    assert row.send.isEnabled()


def test_widget_rows_follow_pairing_and_keep_controls_during_refresh(window, runtime, peer):
    window.refresh()
    row = window.device_widget.rows[peer["device_id"]]
    window.refresh()
    assert window.device_widget.rows[peer["device_id"]] is row
    runtime.db.execute("UPDATE trusted_devices SET name=? WHERE device_id=?", ("Nuevo nombre", peer["device_id"]))
    window.refresh()
    assert row.name.text() == "Nuevo nombre"
    window.unpair(peer["device_id"])
    assert not window.device_widget.rows
    assert not window.device_widget.empty.isHidden()


@pytest.mark.parametrize("widget_theme", ["classic", "minimal"])
def test_widget_send_uses_selected_device_and_survives_picker_cancel(window, runtime, peer, tmp_path, monkeypatch, widget_theme):
    window.widget_theme_grid.tiles[widget_theme].click()
    add_peer(runtime)
    window.refresh()
    sent = []
    runtime.send_files = lambda paths, ids: sent.append((paths, ids))
    row = window.device_widget.rows[peer["device_id"]]
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", lambda *args: ([], ""))
    row.send.click()
    assert not sent and not window.space_workers
    source = tmp_path / "widget.txt"
    source.write_text("solo el equipo elegido")
    parents = []
    def choose(parent, title):
        parents.append(parent)
        return [str(source)], ""
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", choose)
    row.send.click()
    assert not row.send.isEnabled()
    wait_for_copy(window)
    assert parents == [window]
    assert len(sent) == 1 and sent[0][1] == [peer["device_id"]]
    assert sent[0][0][0].read_text() == source.read_text()
    assert row.send.isEnabled()
    assert "Envío iniciado" in window.device_widget.activity.text()


@pytest.mark.parametrize("widget_theme", ["classic", "minimal"])
def test_widget_validate_uses_existing_service_and_reenables_button(window, runtime, peer, monkeypatch, widget_theme):
    window.widget_theme_grid.tiles[widget_theme].click()
    from concurrent.futures import Future
    from types import SimpleNamespace
    runtime.server = SimpleNamespace(started=True)
    future = Future()
    submitted = []
    def submit(coroutine):
        submitted.append(coroutine)
        coroutine.close()
        return future
    runtime.submit = submit
    reports = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args: reports.append(args[2]))
    window.refresh()
    row = window.device_widget.rows[peer["device_id"]]
    row.validate.click()
    assert submitted and peer["device_id"] in window.checking_connections
    assert not row.validate.isEnabled()
    result = {**peer, "forward_online": True, "reverse_online": True}
    runtime.online[peer["device_id"]] = True
    runtime.connections.results[peer["device_id"]] = result
    future.set_result([result])
    QApplication.processEvents()
    assert row.validate.isEnabled()
    assert not window.checking_connections
    assert row.status.text() == "Conectado"
    assert len(reports) == 1 and peer["name"] in reports[0]


def test_widget_restores_position_and_recovers_from_removed_screen(window, runtime):
    widget = window.device_widget
    area = QApplication.primaryScreen().availableGeometry()
    widget.move(area.left() + 25, area.top() + 25)
    widget.save_position()
    expected = widget.pos()
    widget.move(area.left() + 50, area.top() + 50)
    widget.restore_position()
    assert widget.pos() == expected
    runtime.db.set_setting("widget_position", [100000, -100000])
    widget.restore_position()
    assert area.contains(widget.frameGeometry())


def test_widget_stays_disabled_on_next_window_creation(window, runtime):
    window.widget_theme_grid.tiles["minimal"].click()
    window.set_widget_enabled(False)
    second = MainWindow(runtime)
    try:
        assert not second.device_widget.isVisible()
        assert not second.widget_enabled_check.isChecked()
        assert not second.widget_action.isChecked()
        assert second.widget_theme_grid.current_theme == "minimal"
        assert second.device_widget.theme == "minimal"
        assert second.device_widget.width() == 280
    finally:
        second.timer.stop(); second.update_timer.stop(); second.initial_update_timer.stop()
        second.device_widget.deleteLater()
        second.tray.hide(); second.deleteLater()
        QApplication.processEvents()


def test_simplified_menu_has_one_software_page_and_notifications_route_to_it(window):
    assert [window.nav.item(index).text().replace("\n", " ") for index in range(window.nav.count())] == [
        "Inicio", "Dispositivos", "Configuración", "Instaladores y actualizaciones", "Widget"]
    assert window.pages.count() == 5
    window.show_updates()
    assert window.pages.currentIndex() == window.SOFTWARE_PAGE
    assert window.pages.currentWidget().isAncestorOf(window.android_package_button)
    assert window.pages.currentWidget().isAncestorOf(window.check_update_button)
    window.tray_notification_page = window.SOFTWARE_PAGE; window.open_notification()
    assert window.nav.currentRow() == window.SOFTWARE_PAGE


def test_widget_theme_grid_has_actual_previews_and_selection_persists(window, runtime):
    from PySide6.QtTest import QTest
    grid = window.widget_theme_grid
    assert set(grid.tiles) == {"classic", "minimal"}
    for tile in grid.tiles.values():
        assert not tile.image.isNull()
        assert tile.preview.rows["example"].name.toolTip().startswith("Mi teléfono")
    grid.tiles["minimal"].click()
    assert runtime.db.setting("widget_theme") == "minimal"
    assert grid.tiles["minimal"].isChecked() and not grid.tiles["classic"].isChecked()
    assert window.device_widget.theme == "minimal"
    grid.tiles["classic"].setFocus(); QTest.keyClick(grid.tiles["classic"], Qt.Key.Key_Space)
    assert runtime.db.setting("widget_theme") == "classic"
    window.nav.setCurrentRow(window.WIDGET_PAGE); window.resize(820, 650); window.show()
    QApplication.processEvents()
    assert grid.columns == 1
    assert not grid.tiles["classic"].geometry().intersects(grid.tiles["minimal"].geometry())
    window.resize(1280, 1000); QApplication.processEvents()
    assert grid.columns == 2
    assert not grid.tiles["classic"].geometry().intersects(grid.tiles["minimal"].geometry())


@pytest.mark.parametrize("online,reverse,receiving,checking,status,color", [
    (None, None, None, False, "Sin comprobar", "#87958f"),
    (False, None, None, False, "Sin conexión", "#d84a4a"),
    (True, True, True, False, "Conectado", "#169b73"),
    (True, False, True, False, "Un solo sentido", "#d08a16"),
    (True, True, False, False, "Recepción pausada", "#d08a16"),
    (True, True, True, True, "Validando…", "#d08a16"),
])
def test_device_bubbles_update_status_and_keep_controls(window, runtime, peer, online, reverse, receiving, checking, status, color):
    device_id = peer["device_id"]
    window.refresh(); bubble = window.device_map.bubbles[device_id]
    if online is not None:
        runtime.online[device_id] = online
    runtime.connections.results[device_id] = {"reverse_online": reverse, "remote_receiving": receiving}
    if checking:
        window.checking_connections.add(device_id)
    window.refresh()
    assert window.device_map.bubbles[device_id] is bubble
    assert bubble.status.text() == status and bubble.color == color
    assert bubble.validate.isEnabled() is not checking
    assert peer["name"] == bubble.name.toolTip()
    assert peer["ip"] in bubble.address.toolTip()


@pytest.mark.parametrize("count", [0, 1, 2, 4, 6, 9])
def test_device_map_centers_local_computer_and_fits_bubbles_at_minimum_window_size(window, runtime, count):
    from pathlib import Path
    from PySide6.QtGui import QFontDatabase
    font = Path("C:/Windows/Fonts/segoeui.ttf")
    if font.exists():
        QFontDatabase.addApplicationFont(str(font))
    for index in range(count):
        add_peer(runtime, f"Dispositivo {index + 1}")
    window.refresh(); window.nav.setCurrentRow(1); window.resize(820, 650); window.show()
    QApplication.processEvents()
    diagram = window.device_map
    assert len(diagram.bubbles) == count
    assert diagram.primary.name.toolTip() == runtime.db.setting("device_name")
    assert "Principal" in diagram.primary.platform.text()
    assert abs(diagram.primary.geometry().center().x() - diagram.rect().center().x()) <= 1
    assert abs(diagram.primary.geometry().center().y() - diagram.rect().center().y()) <= 1
    nodes = [diagram.primary, *diagram.bubbles.values()]
    for index, node in enumerate(nodes):
        assert diagram.rect().contains(node.geometry())
        for other in nodes[index + 1:]:
            dx = node.geometry().center().x() - other.geometry().center().x()
            dy = node.geometry().center().y() - other.geometry().center().y()
            assert dx * dx + dy * dy >= ((node.width() + other.width()) / 2) ** 2


def test_bubble_options_preserve_address_accept_and_unpair_controls(window, runtime, peer, monkeypatch):
    window.refresh()
    corrected = []; monkeypatch.setattr(window, "correct_peer_address", lambda item: corrected.append(item["device_id"]))
    def inspect(dialog):
        from PySide6.QtWidgets import QCheckBox, QPushButton
        checks = dialog.findChildren(QCheckBox)
        assert len(checks) == 1
        checks[0].setChecked(False)
        updated = runtime.db.trusted(peer["device_id"])[0]
        assert updated["auto_accept"] == 0
        buttons = {item.text(): item for item in dialog.findChildren(QPushButton)}
        buttons["Corregir IP / puerto"].click()
        buttons["Desvincular"].click()
        return 0
    monkeypatch.setattr(QDialog, "exec", inspect)
    window.device_map.bubbles[peer["device_id"]].actions.itemAt(1).widget().click()
    assert corrected == [peer["device_id"]]
    assert peer["device_id"] not in window.device_map.bubbles


def test_nearby_unpaired_device_appears_as_bubble_and_opens_pairing(window, runtime, monkeypatch):
    device_id = str(uuid4())
    runtime.discovery.snapshot = lambda: [{"device_id": device_id, "device_name": "Cerca de ti",
        "ip": "192.168.1.44", "port": 45833, "platform": "android", "online": True}]
    window.refresh()
    bubble = window.device_map.bubbles[device_id]
    assert bubble.status.text() == "Sin vincular" and bubble.color == "#87958f"
    dialogs = []
    def inspect(dialog):
        from PySide6.QtWidgets import QLineEdit
        dialogs.append(dialog.windowTitle())
        assert any(item.text() == "192.168.1.44" for item in dialog.findChildren(QLineEdit))
        return 0
    monkeypatch.setattr(QDialog, "exec", inspect)
    bubble.actions.itemAt(0).widget().click()
    assert dialogs == ["Vincular por IP o QR"]


def test_widget_theme_switch_preserves_devices_state_controls_and_position(window, runtime, peer):
    window.refresh()
    widget = window.device_widget
    row = widget.rows[peer["device_id"]]
    position = widget.pos()
    classic_height = widget.height()
    window.widget_theme_grid.tiles["minimal"].click()
    QApplication.processEvents()
    assert runtime.db.setting("widget_theme") == "minimal"
    assert widget.width() == 280 and widget.height() < classic_height
    assert widget.pos() == position
    assert widget.rows[peer["device_id"]] is row
    assert row.status.isHidden() and not row.dot.isHidden()
    assert "Sin comprobar" in row.dot.toolTip()
    assert not row.validate.isHidden() and not row.send.isHidden()
    assert widget.summary.isHidden() and widget.open_button.isHidden()
    runtime.online[peer["device_id"]] = True
    window.refresh()
    assert row.dot.toolTip() == "Conectado"
    assert "#169b73" in row.dot.styleSheet()
    runtime.db.set_setting("theme", "Light"); window.apply_theme()
    assert widget.theme == "minimal" and "rgba(16, 15, 13, 220)" in widget.styleSheet()
    window.widget_theme_grid.tiles["classic"].click()
    QApplication.processEvents()
    assert widget.width() == 390 and widget.height() == classic_height
    assert not row.status.isHidden() and row.status.text() == "Conectado"
    assert not widget.summary.isHidden() and not widget.open_button.isHidden()
    assert runtime.db.setting("widget_theme") == "classic"


def test_minimal_widget_handles_empty_and_scrollable_device_lists(window, runtime):
    window.widget_theme_grid.tiles["minimal"].click()
    widget = window.device_widget
    assert not widget.empty.isHidden()
    assert "Doble clic" in widget.empty.text()
    for index in range(15):
        add_peer(runtime, f"Dispositivo {index}")
    window.refresh(); QApplication.processEvents()
    assert len(widget.rows) == 15
    assert widget.scroll.verticalScrollBar().maximum() > 0
    assert widget.scroll.height() <= 280
    assert not widget.scroll.horizontalScrollBar().isVisible()


def test_minimal_widget_opens_main_window_from_header(window):
    from PySide6.QtTest import QTest
    window.widget_theme_grid.tiles["minimal"].click()
    window.hide()
    QTest.mouseDClick(window.device_widget.header, Qt.MouseButton.LeftButton)
    assert window.isVisible()


def test_widget_position_stays_global_when_desktop_host_has_an_offset(window, runtime):
    widget = window.device_widget
    widget.desktop_host = SimpleNamespace(valid=lambda: True, origin=lambda: QPoint(-1280, -100))
    try:
        widget.move_on_desktop(QPoint(30, 40))
        assert widget.desktop_position() == QPoint(30, 40)
        assert widget.pos() == QPoint(1310, 140)
        widget.save_position()
        assert runtime.db.setting("widget_position") == [30, 40]
        widget.move_on_desktop(QPoint(50, 60))
        widget.restore_position()
        assert widget.desktop_position() == QPoint(30, 40)
    finally:
        widget.desktop_host = None


def test_widget_waits_for_desktop_instead_of_floating_when_explorer_is_unavailable(window, runtime, monkeypatch):
    from devicedrop.ui.desktop_host import DesktopHost
    monkeypatch.setattr(QApplication, "platformName", lambda: "windows")
    monkeypatch.setattr(DesktopHost, "attach", lambda widget: None)
    window.set_widget_enabled(True)
    assert not window.device_widget.isVisible()
    assert runtime.db.setting("widget_enabled") is True
    host = SimpleNamespace(valid=lambda: True, origin=lambda: QPoint())
    monkeypatch.setattr(DesktopHost, "attach", lambda widget: host)
    window.refresh()
    assert window.device_widget.isVisible()
    assert window.device_widget.desktop_host is host
    assert not window.device_widget.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
    window.device_widget.desktop_host = None


def test_receipt_notification_uses_copy_action_and_respects_disabled_notifications(window, runtime, monkeypatch):
    shown = []; monkeypatch.setattr(window.receipt_notifier, "show", lambda tid, name: shown.append((tid, name)) or True)
    tid = str(uuid4())
    event = {"type": "transfer_completed", "transfer_id": tid, "filename": "image.png", "saved_path": "C:/received/image.png", "mime_type": "image/png"}
    window.event_received(event)
    assert shown == [(tid, "image.png")] and window.tray_copy_path is None
    assert window.last_preview == event["saved_path"]
    runtime.db.set_setting("notifications", False); window.event_received(event)
    assert len(shown) == 1


def test_copy_shortcut_and_receipt_actions_use_only_completed_incoming_files(window, runtime, tmp_path, monkeypatch):
    from devicedrop.storage.models import Metadata
    copied = []; monkeypatch.setattr("devicedrop.ui.main_window.copy_file", copied.append)
    incoming = str(uuid4()); outgoing = str(uuid4())
    for tid, direction in [(incoming, "incoming"), (outgoing, "outgoing")]:
        meta = Metadata(transfer_id=tid, filename="a.txt", size=0, sha256="0" * 64, sender_device_id=runtime.device_id, origin_device_id=runtime.device_id)
        runtime.db.transfer(meta.model_dump(mode="json"), direction, runtime.device_id)
        runtime.db.update_transfer(tid, status="completed", saved_path=str(tmp_path / f"{tid}.txt"), completed_at=time.time())
    window.hide()
    window.refresh()
    window.handle_receipt_action("copy", outgoing); window.handle_receipt_action("copy", str(uuid4()))
    assert not copied
    window.handle_receipt_action("copy", incoming)
    assert copied == [str(tmp_path / f"{incoming}.txt")] and not window.isVisible()
    assert window.copy_received_shortcut.key().toString() == "Ctrl+Shift+C"
    window.copy_received_shortcut.activated.emit(); window.copy_received_action.trigger()
    assert copied == [str(tmp_path / f"{incoming}.txt")] * 3


def test_update_all_devices_controls_and_persisted_status(window, runtime, peer, monkeypatch):
    assert window.fleet_update_button.text() == "Actualizar todos los dispositivos"
    window.fleet_auto.setChecked(True)
    assert runtime.db.setting("fleet_auto") is True
    checks = []; monkeypatch.setattr(window, "start_local_update", lambda **kwargs: checks.append(kwargs))
    window.poll_local_changes()
    assert checks == [{"automatic": True}]
    runtime.fleet.status(peer["device_id"], status="received", revision="a" * 64)
    window.refresh_fleet()
    assert peer["name"] in window.fleet_devices.text() and "falta instalar" in window.fleet_devices.text()
