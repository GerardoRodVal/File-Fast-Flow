import asyncio
import hashlib
import json
import time
from pathlib import Path
from uuid import uuid4
import httpx
import pytest
from devicedrop.network.server import create_app
from devicedrop.storage.models import Metadata

def metadata(peer, content=b"hello", name="hello.txt"):
    return Metadata(transfer_id=str(uuid4()), filename=name, size=len(content), sha256=hashlib.sha256(content).hexdigest(), sender_device_id=peer["device_id"], origin_device_id=peer["device_id"])

@pytest.fixture
async def client(runtime):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(runtime)), base_url="http://test") as client:
        yield client

async def test_auth_before_reading_upload(client):
    response = await client.post("/api/v1/files", content=b"not multipart")
    assert response.status_code == 401
    assert (await client.get("/api/v1/ping")).status_code == 200
    assert (await client.get("/api/v1/transfers")).status_code == 401

async def upload(client, peer, meta, content):
    return await client.post("/api/v1/files", headers={"Authorization": "Bearer " + peer["token"]},
        data={"metadata": meta.model_dump_json()}, files={"file": ("payload", content)})

async def offer(client, peer, meta):
    return await client.post("/api/v1/offers", headers={"Authorization": "Bearer " + peer["token"]}, json=meta.model_dump(mode="json"))

async def test_upload_hash_collision_and_idempotence(client, runtime, peer):
    for n in range(2):
        meta = metadata(peer)
        assert (await offer(client, peer, meta)).json()["status"] == "accepted"
        response = await upload(client, peer, meta, b"hello")
        assert response.status_code == 200, response.text
        assert response.json()["filename"] == ("hello.txt" if n == 0 else "hello (1).txt")
        assert (await offer(client, peer, meta)).json()["status"] == "completed"
    assert len(list(Path(runtime.db.setting("receive_folder")).glob("*.txt"))) == 2

async def test_corruption_cleanup(client, runtime, peer):
    meta = metadata(peer); await offer(client, peer, meta)
    response = await upload(client, peer, meta, b"WRONG")
    assert response.json()["error"] == "TRANSFER_CORRUPTED"
    assert list(Path(runtime.db.setting("receive_folder")).iterdir()) == []
    assert runtime.db.history()[0]["status"] == "failed"

async def test_upload_without_offer(client, runtime, peer):
    response = await upload(client, peer, metadata(peer), b"hello")
    assert response.status_code == 410
    assert not list(Path(runtime.db.setting("receive_folder")).iterdir())

async def test_manual_approval_and_reception_pause(client, runtime, peer):
    runtime.db.execute("UPDATE trusted_devices SET auto_accept=0")
    meta = metadata(peer); response = await offer(client, peer, meta)
    assert response.json()["status"] == "pending"
    assert (await upload(client, peer, meta, b"hello")).status_code == 403
    runtime.approve(str(meta.transfer_id), True)
    assert (await upload(client, peer, meta, b"hello")).status_code == 200
    runtime.db.set_setting("allow_receive", False)
    assert (await offer(client, peer, metadata(peer))).status_code == 503

async def test_size_cancel_space_and_metadata_conflict(client, runtime, peer, monkeypatch):
    meta = metadata(peer); await offer(client, peer, meta)
    assert (await upload(client, peer, meta, b"toolong")).json()["error"] == "SIZE_MISMATCH"
    meta = metadata(peer); await offer(client, peer, meta); runtime.cancel(str(meta.transfer_id))
    assert (await upload(client, peer, meta, b"hello")).json()["error"] == "TRANSFER_CANCELLED"
    import shutil
    monkeypatch.setattr(shutil, "disk_usage", lambda path: type("Space", (), {"free": 0})())
    assert (await offer(client, peer, metadata(peer))).status_code == 507

async def test_transfer_metadata_scoped_to_peer(client, runtime, peer):
    meta = metadata(peer); await offer(client, peer, meta); await upload(client, peer, meta, b"hello")
    headers = {"Authorization": "Bearer " + peer["token"]}
    rows = (await client.get("/api/v1/transfers", headers=headers)).json()["transfers"]
    assert rows and "saved_path" not in rows[0]

async def test_actual_tcp_bidirectional_transfer_and_shutdown(tmp_path):
    from devicedrop.runtime import Runtime
    from devicedrop.security.files import sha256_file
    a, b = Runtime(tmp_path / "a", port=45981), Runtime(tmp_path / "b", port=45982)
    a.start(discovery=False, watching=False); b.start(discovery=False, watching=False)
    try:
        assert await asyncio.to_thread(a.ready.wait, 10)
        assert await asyncio.to_thread(b.ready.wait, 10)
        assert not a.start_error and not b.start_error
        window = b.pairing.open()
        await asyncio.wrap_future(a.submit(a.pair("127.0.0.1", 45982, window["code"])))
        # Initiator address becomes loopback on B; update A manually for loopback test.
        a.db.execute("UPDATE trusted_devices SET ip='127.0.0.1'")
        for source, target in [(a, b), (b, a)]:
            file = source.root / "test.bin"; file.write_bytes(b"DeviceDrop\0" * 200000)
            await asyncio.wrap_future(source.send_files([file], [target.device_id]))
            records = target.db.history()
            assert records[0]["status"] == "completed", records
            assert sha256_file(Path(records[0]["saved_path"])) == sha256_file(file)
    finally:
        await asyncio.to_thread(a.stop); await asyncio.to_thread(b.stop)
    assert not a.thread.is_alive() and not b.thread.is_alive()
