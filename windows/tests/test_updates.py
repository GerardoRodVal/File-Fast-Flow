import hashlib
from pathlib import Path

import httpx
import pytest
from PySide6.QtWidgets import QApplication

from devicedrop.updates import (API_URL, REPOSITORY_URL, check_latest, download_installer,
                               parse_release, require_https, verify_installer, version_tuple)
from devicedrop.ui.main_window import MainWindow
from devicedrop.runtime import Runtime
from devicedrop.storage.database import Database


def metadata(version="0.3.9", content=b"installer"):
    name = f"FileFastFlow-{version}-Setup.exe"
    return {"tag_name": f"v{version}", "draft": False, "prerelease": False, "body": "Cambios nuevos",
            "assets": [{"name": name, "state": "uploaded", "size": len(content),
                        "digest": "sha256:" + hashlib.sha256(content).hexdigest(),
                        "browser_download_url": f"{REPOSITORY_URL}/releases/download/v{version}/{name}"}]}


def test_numeric_versions_and_no_downgrades():
    assert version_tuple("v0.3.10") > version_tuple("0.3.9")
    assert parse_release(metadata("0.3.2"), "0.3.9") is None
    assert parse_release(metadata("0.3.9"), "0.3.9") is None
    for tag in ("main", "v0.3.9-beta", "../0.3.9", "0.3"):
        with pytest.raises(ValueError):
            version_tuple(tag)
    data = metadata(); data["prerelease"] = True
    assert parse_release(data, "0.3.0") is None


@pytest.mark.parametrize("field,value", [("browser_download_url", "http://example.com/setup.exe"),
    ("digest", None), ("size", 0), ("size", 1024**3 + 1), ("size", True)])
def test_reject_untrusted_or_incomplete_assets(field, value):
    data = metadata(); data["assets"][0][field] = value
    with pytest.raises(ValueError):
        parse_release(data, "0.3.0")


def test_missing_release_and_api_errors():
    for status in (404, 403, 500):
        with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(status))) as client:
            if status == 404:
                assert check_latest(client, "0.3.0") is None
            elif status == 403:
                with pytest.raises(ValueError, match="limitó"):
                    check_latest(client, "0.3.0")
            else:
                with pytest.raises(httpx.HTTPStatusError):
                    check_latest(client, "0.3.0")


def test_check_download_redirect_verify_and_reuse(tmp_path):
    data = metadata(); release = parse_release(data, "0.3.0")
    requests = []
    def respond(request):
        requests.append(str(request.url))
        if str(request.url) == API_URL:
            return httpx.Response(200, json=data)
        if request.url.host == "github.com":
            return httpx.Response(302, headers={"Location": "https://release-assets.githubusercontent.com/test"})
        return httpx.Response(200, content=b"installer")
    with httpx.Client(transport=httpx.MockTransport(respond), event_hooks={"request": [require_https]}) as client:
        assert check_latest(client, "0.3.0") == release
        destination = tmp_path / release.filename
        progress = []
        assert download_installer(client, release, destination, progress.append) == destination
        verify_installer(destination, release)
        assert progress[-1] == 100
        count = len(requests)
        assert download_installer(client, release, destination) == destination
        assert len(requests) == count
        destination.write_bytes(b"tampering")
        with pytest.raises(ValueError, match="SHA-256"):
            verify_installer(destination, release)


@pytest.mark.parametrize("content", [b"wronghash", b"short", b"far too many bytes"])
def test_failed_download_preserves_existing_installer(tmp_path, content):
    release = parse_release(metadata(), "0.3.0")
    destination = tmp_path / release.filename; destination.write_bytes(b"previous")
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=content))) as client:
        with pytest.raises(ValueError):
            download_installer(client, release, destination)
    assert destination.read_bytes() == b"previous"
    assert not list(tmp_path.glob(".filefastflow-update-*"))


def test_cancel_download_and_reject_insecure_redirect(tmp_path):
    release = parse_release(metadata(), "0.3.0")
    destination = tmp_path / release.filename
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"installer"))) as client:
        with pytest.raises(ValueError, match="cancelada"):
            download_installer(client, release, destination, cancelled=lambda: True)
    assert not destination.exists()
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(302, headers={"Location": "http://example.com/setup.exe"})), event_hooks={"request": [require_https]}) as client:
        with pytest.raises(ValueError, match="no permitido"):
            download_installer(client, release, destination)
    assert not destination.exists()


def test_upgrade_reuses_legacy_identity_history_and_folders(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv("DEVICEDROP_DATA_ROOT", raising=False)
    monkeypatch.delenv("FILEFASTFLOW_DATA_ROOT", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    legacy = tmp_path / "DeviceDrop"
    db = Database(legacy / "devicedrop.db")
    identity = db.identity()
    db.set_setting("receive_folder", str(tmp_path / "existing-received"))
    db.set_setting("sync_folder", str(tmp_path / "existing-shared"))
    db.set_setting("onboarded", True)
    db.close()
    runtime = Runtime()
    try:
        assert runtime.root == legacy and runtime.device_id == identity
        assert runtime.db.setting("receive_folder") == str(tmp_path / "existing-received")
        assert runtime.db.setting("sync_folder") == str(tmp_path / "existing-shared")
        assert runtime.db.setting("onboarded") and runtime.db.setting("auto_updates")
        assert not (tmp_path / "FileFastFlow" / "devicedrop.db").exists()
    finally:
        runtime.db.close()


def test_update_ui_notifies_once_and_can_disable(runtime, monkeypatch):
    app = QApplication.instance() or QApplication([])
    window = MainWindow(runtime)
    window.initial_update_timer.stop(); window.update_timer.stop()
    notifications = []
    monkeypatch.setattr(window.tray, "showMessage", lambda *args: notifications.append(args))
    release = parse_release(metadata(), "0.3.0")
    try:
        assert window.windowTitle() == "FileFastFlow"
        assert window.nav.item(6).text() == "Actualizaciones"
        window.update_checked(release); window.update_checked(release)
        assert len(notifications) == 1
        assert runtime.db.setting("last_update_notified") == release.version
        assert not window.download_update_button.isHidden()
        assert "0.3.9" in window.update_status.text()
        checked = []
        monkeypatch.setattr(window, "check_updates", lambda: checked.append(True))
        runtime.db.set_setting("auto_updates", False); window.auto_check_updates()
        assert not checked
        runtime.db.set_setting("auto_updates", True); window.auto_check_updates()
        assert checked
        window.update_failed("sin conexión")
        assert "intentarlo de nuevo" in window.update_status.text()
    finally:
        window.timer.stop(); window.tray.hide(); runtime.bus.listeners.clear()
        window.deleteLater(); app.processEvents()
