import hashlib
import secrets
import threading
from pathlib import Path
from uuid import uuid4
import pytest
from pydantic import ValidationError
from devicedrop.security.files import sha256_file, validate_filename, reserve_destination
from devicedrop.network.transfer import publish, TransferError
from devicedrop.storage.database import Database
from devicedrop.storage.models import Metadata
from devicedrop.sync.watcher import wait_stable, FolderWatcher, readable_without_writer

def test_hash_streaming(tmp_path):
    file = tmp_path / "binary"; file.write_bytes(b"abc" * 1000000)
    assert sha256_file(file) == hashlib.sha256(b"abc" * 1000000).hexdigest()

@pytest.mark.parametrize("name", ["../evil", "..\\evil", "CON.txt", "NUL", "COM1.zip", "bad:stream", "name.", "name ", "a\0b", "", ".", "..", "a/b"])
def test_names_rejected(name):
    with pytest.raises(ValueError): validate_filename(name)

def test_unicode_and_collisions(tmp_path):
    assert validate_filename("Fotografía 🎉.png")
    assert reserve_destination(tmp_path, "foto.png").name == "foto.png"
    assert reserve_destination(tmp_path, "foto.png").name == "foto (1).png"
    part = tmp_path / "part"; part.write_bytes(b"verified")
    dest = publish(part, tmp_path, "foto.png")
    assert dest.name == "foto (2).png" and dest.read_bytes() == b"verified" and not part.exists()

def test_identity_and_trust_persist(runtime, peer):
    clone = Database(runtime.root / "devicedrop.db")
    assert clone.identity() == runtime.device_id
    assert clone.authenticate(peer["token"])["device_id"] == peer["device_id"]
    assert clone.authenticate(secrets.token_urlsafe(32)) is None
    clone.close()

def test_pairing_consumed_only_after_code(runtime, peer):
    window = runtime.pairing.open()
    device = {"device_id": str(uuid4()), "device_name": "New", "platform": "android", "port": 45832}
    with pytest.raises(ValueError, match="PAIRING_INVALID"):
        runtime.pairing.request(device, "wrongcode", "127.0.0.1")
    result = runtime.pairing.request(device, window["code"], "127.0.0.1")
    assert not runtime.db.trusted(device["device_id"])
    with pytest.raises(ValueError, match="PAIRING_EXPIRED"):
        runtime.pairing.request(device, window["code"], "127.0.0.1")
    runtime.pairing.confirm(result["request_id"], result["confirmation_token"])
    assert runtime.db.authenticate(result["shared_token"])
    with pytest.raises(ValueError): runtime.pairing.confirm(result["request_id"], result["confirmation_token"])
    assert runtime.db.setting("pairing_token") is None

def test_pairing_expiry_and_rate_limit(runtime):
    window = runtime.pairing.open(); runtime.pairing.expires = 0
    d = {"device_id": str(uuid4()), "device_name": "New", "platform": "android", "port": 45832}
    with pytest.raises(ValueError, match="EXPIRED"): runtime.pairing.request(d, window["code"], "local")
    runtime.pairing.open()
    for _ in range(5):
        with pytest.raises(ValueError): runtime.pairing.request(d, "notright", "attacker")
    with pytest.raises(ValueError, match="RATE_LIMIT"): runtime.pairing.request(d, window["code"], "attacker")

def test_metadata_validation():
    base = dict(transfer_id=str(uuid4()), filename="a.txt", size=10, sha256="a" * 64, sender_device_id=str(uuid4()), origin_device_id=str(uuid4()))
    assert Metadata(**base).protocol_version == 1
    for changes in [{"size": -1}, {"sha256": "nope"}, {"filename": "../../a"}, {"protocol_version": 2}, {"size": 17 * 1024**3}]:
        with pytest.raises(ValidationError): Metadata(**(base | changes))

def test_stability_and_stop(tmp_path):
    file = tmp_path / "new.txt"; file.write_text("ready")
    stop = threading.Event()
    assert wait_stable(file, stop, interval=.01, samples=2, timeout=1)
    stop.set(); assert not wait_stable(file, stop, interval=.01)

def test_windows_open_writer_is_not_stable(tmp_path):
    import os
    if os.name != "nt":
        pytest.skip("Windows sharing modes")
    file = tmp_path / "copy.bin"
    with file.open("wb") as writer:
        writer.write(b"still copying"); writer.flush()
        assert not readable_without_writer(file)
    assert readable_without_writer(file)

def test_actual_folder_watcher(tmp_path):
    received = threading.Event(); watcher = FolderWatcher(tmp_path, lambda path: received.set())
    watcher.start()
    try:
        (tmp_path / "new.txt").write_text("copied")
        assert received.wait(8)
    finally: watcher.stop()
    assert not watcher.observer.is_alive()

def test_received_files_not_synced(runtime):
    path = Path(runtime.db.setting("sync_folder")) / "received.txt"; path.write_text("incoming")
    runtime.db.execute("INSERT INTO processed_files VALUES (?,?,?,?)", (str(uuid4()), "a" * 64, str(path), str(uuid4())))
    runtime.send_files = lambda *args: pytest.fail("Sync loop")
    runtime.sync_created(path)
