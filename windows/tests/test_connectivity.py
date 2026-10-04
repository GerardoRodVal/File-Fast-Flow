import asyncio
from concurrent.futures import Future
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from devicedrop.runtime import Runtime
from devicedrop.network.server import create_app
from devicedrop.network.transfer import TransferError
from devicedrop.ui.main_window import MainWindow


def mock_network(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))


async def test_two_way_real_tcp_repairs_stale_return_port_and_simultaneous_checks(tmp_path):
    a, b = Runtime(tmp_path / "a", 45987), Runtime(tmp_path / "b", 45988)
    a.start(discovery=False, watching=False); b.start(discovery=False, watching=False)
    try:
        assert await asyncio.to_thread(a.ready.wait, 10) and await asyncio.to_thread(b.ready.wait, 10)
        token = "x" * 43
        a.db.trust({**b.device(), "ip": "127.0.0.1"}, token)
        b.db.trust({**a.device(), "ip": "127.0.0.1", "port": 45998}, token)
        result = await asyncio.wrap_future(a.submit(a.connections.check(b.device_id)))
        assert result["forward_online"] and result["reverse_online"]
        assert b.db.trusted(a.device_id)[0]["port"] == a.port
        results = await asyncio.gather(asyncio.wrap_future(a.submit(a.connections.check(b.device_id))),
                                       asyncio.wrap_future(b.submit(b.connections.check(a.device_id))))
        assert all(r["forward_online"] and r["reverse_online"] for r in results)
        b.db.set_setting("allow_receive", False)
        result = await asyncio.wrap_future(a.submit(a.connections.check(b.device_id)))
        assert result["forward_online"] and result["reverse_online"] and result["remote_receiving"] is False
        original = b.connections.probe
        async def blocked(peer):
            raise TransferError("UNREACHABLE")
        b.connections.probe = blocked
        result = await asyncio.wrap_future(a.submit(a.connections.check(b.device_id)))
        assert result["forward_online"] and result["reverse_online"] is False and result["code"] == "UNREACHABLE"
        result = await asyncio.wrap_future(a.submit(a.connections.check(b.device_id, full=False)))
        assert result["reverse_online"] is False
        b.connections.probe = original
        result = await asyncio.wrap_future(a.submit(a.connections.check(b.device_id)))
        assert result["reverse_online"] is True
    finally:
        await asyncio.to_thread(a.stop); await asyncio.to_thread(b.stop)


async def test_authenticated_discovery_recovery_and_failed_override_preserves_ip(runtime, peer, monkeypatch):
    saved = peer["ip"]
    runtime.discovery.snapshot = lambda: [{"device_id": peer["device_id"], "ip": "192.168.1.20", "port": 45833, "online": True}]
    seen = []
    def handler(request):
        seen.append(request)
        device_id = peer["device_id"] if request.url.host == "192.168.1.20" else str(uuid4())
        return httpx.Response(200, json={"device_id": device_id, "protocol_version": 1, "receiving": True})
    mock_network(monkeypatch, handler)
    result = await runtime.connections.check(peer["device_id"], full=False)
    assert result["forward_online"] and runtime.db.trusted(peer["device_id"])[0]["ip"] == "192.168.1.20"
    assert saved != "192.168.1.20"
    result = await runtime.connections.check(peer["device_id"], ip="192.168.1.99", port=45833)
    assert not result["forward_online"] and result["code"] == "IDENTITY_MISMATCH"
    assert runtime.db.trusted(peer["device_id"])[0]["ip"] == "192.168.1.20"
    assert not any(r.headers.get("authorization") for r in seen if r.url.host == "192.168.1.99")


@pytest.mark.parametrize("failure,code", [(401, "AUTH_FAILED"), ("timeout", "TIMEOUT"), ("network", "UNREACHABLE")])
async def test_diagnostic_errors(runtime, peer, monkeypatch, failure, code):
    def handler(request):
        if failure == "timeout": raise httpx.ReadTimeout("test", request=request)
        if failure == "network": raise httpx.ConnectError("test", request=request)
        return httpx.Response(200 if request.url.path.endswith("ping") else failure,
                              json={"device_id": peer["device_id"], "protocol_version": 1})
    mock_network(monkeypatch, handler)
    result = await runtime.connections.check(peer["device_id"])
    assert not result["forward_online"] and result["code"] == code


async def test_legacy_device_stays_online_and_reports_update_required(runtime, peer, monkeypatch):
    def handler(request):
        if request.url.path.endswith("connection"): return httpx.Response(404)
        if request.url.path.endswith("devices"): assert request.headers["authorization"] == "Bearer " + peer["token"]
        return httpx.Response(200, json={"device_id": peer["device_id"], "protocol_version": 1})
    mock_network(monkeypatch, handler)
    result = await runtime.connections.check(peer["device_id"])
    assert result["forward_online"] and result["reverse_online"] is None and result["code"] == "UPDATE_REQUIRED"


async def test_connection_routes_auth_identity_port_and_observed_address(runtime, peer):
    transport = httpx.ASGITransport(app=create_app(runtime), client=("192.168.1.44", 12000))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get("/api/v1/connection")).status_code == 401
        assert (await client.post("/api/v1/connection/check", content=b"bad")).status_code == 401
        headers = {"Authorization": "Bearer " + peer["token"]}
        data = {"device_id": str(uuid4()), "port": 45833, "protocol_version": 1}
        assert (await client.post("/api/v1/connection/check", headers=headers, json=data)).status_code == 403
        data.update(device_id=peer["device_id"], port=80)
        assert (await client.post("/api/v1/connection/check", headers=headers, json=data)).status_code == 400
        assert runtime.db.trusted(peer["device_id"])[0]["ip"] == "127.0.0.1"
        response = await client.get("/api/v1/connection", headers={**headers, "X-DeviceDrop-Port": "45835"})
        assert response.status_code == 200 and response.json()["device_id"] == runtime.device_id
        saved = runtime.db.trusted(peer["device_id"])[0]
        assert saved["ip"] == "192.168.1.44" and saved["port"] == 45835


def test_validation_button_displays_both_directions_and_clears_progress(runtime, peer, monkeypatch):
    app = QApplication.instance() or QApplication([])
    window = MainWindow(runtime)
    runtime.server = SimpleNamespace(started=True)
    dialogs = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: dialogs.append(args[-1]))
    report = {"device_id": peer["device_id"], "name": peer["name"], "ip": peer["ip"], "port": peer["port"],
              "forward_online": True, "reverse_online": False, "code": "UNREACHABLE"}
    future = Future()
    def submit(coroutine):
        coroutine.close()
        return future
    monkeypatch.setattr(runtime, "submit", submit)
    try:
        window.validate_connections_button.click()
        assert peer["device_id"] in window.checking_connections
        future.set_result([report]); app.processEvents()
        assert not window.checking_connections
        assert "→" in dialogs[-1] and "Falló" in dialogs[-1] and peer["token"] not in dialogs[-1]
    finally:
        window.timer.stop(); window.tray.hide(); runtime.bus.listeners.clear(); window.deleteLater(); app.processEvents()
