import asyncio
import hashlib
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError
from devicedrop.local_build import source_revision, artifact_valid
from devicedrop.storage.models import Metadata


def manifest(tmp_path, revision="a" * 64):
    artifacts = {}
    for platform, suffix in [("windows", "Setup.exe"), ("android", "debug.apk")]:
        path = tmp_path / f"FileFastFlow-0.4.0-{suffix}"; path.write_bytes(b"package")
        artifacts[platform] = {"path": str(path), "size": 7, "sha256": hashlib.sha256(b"package").hexdigest()}
    return {"revision": revision, "version": "0.4.0", "version_code": 100101, "artifacts": artifacts}


def test_source_revision_detects_code_but_ignores_build_outputs(tmp_path):
    code = tmp_path / "windows/devicedrop/app.py"; code.parent.mkdir(parents=True); code.write_text("one")
    initial = source_revision(tmp_path)
    cache = code.parent / "__pycache__"; cache.mkdir(); (cache / "old.pyc").write_bytes(b"ignore")
    assert source_revision(tmp_path) == initial
    code.write_text("two")
    assert source_revision(tmp_path) != initial


async def test_fleet_queue_offline_retry_and_only_reports_installed_after_confirmation(runtime, peer, tmp_path):
    item = manifest(tmp_path); runtime.fleet.queue(item)
    sent = []
    async def send(path, device, **kwargs):
        sent.append((path, device, kwargs)); return True
    runtime.sender = type("Sender", (), {"send": staticmethod(send)})()
    await runtime.fleet.deliver_pending()
    assert not sent and runtime.db.setting("fleet_states")[peer["device_id"]]["status"] == "pending"
    runtime.online[peer["device_id"]] = True
    await asyncio.gather(runtime.fleet.deliver_pending(), runtime.fleet.deliver_pending())
    assert len(sent) == 1 and sent[0][0].suffix == ".apk"
    assert sent[0][2]["update_revision"] == item["revision"]
    assert runtime.db.setting("fleet_states")[peer["device_id"]]["status"] == "received"
    runtime.connections.results[peer["device_id"]] = {"remote_revision": item["revision"]}
    await runtime.fleet.deliver_pending()
    assert runtime.db.setting("fleet_states")[peer["device_id"]]["status"] == "installed"


async def test_corrupt_package_is_not_sent_and_new_revision_resets_queue(runtime, peer, tmp_path):
    item = manifest(tmp_path); runtime.fleet.queue(item); runtime.online[peer["device_id"]] = True
    Path(item["artifacts"]["android"]["path"]).write_bytes(b"damaged")
    assert not artifact_valid(item["artifacts"]["android"])
    await runtime.fleet.deliver_pending()
    assert runtime.db.setting("fleet_states")[peer["device_id"]]["status"] == "failed"
    runtime.fleet.queue(manifest(tmp_path, "b" * 64))
    assert runtime.db.setting("fleet_states")[peer["device_id"]]["revision"] == "b" * 64
    assert runtime.db.setting("fleet_states")[peer["device_id"]]["status"] == "pending"


async def test_local_installer_transfer_is_verified_and_staged_at_receiver(tmp_path):
    from devicedrop.runtime import Runtime
    a, b = Runtime(tmp_path / "a", 45986), Runtime(tmp_path / "b", 45987)
    a.db.trust({**b.device(), "ip": "127.0.0.1"}, "u" * 43)
    b.db.trust({**a.device(), "ip": "127.0.0.1"}, "u" * 43)
    a.start(discovery=False, watching=False); b.start(discovery=False, watching=False)
    try:
        for app in [a, b]:
            assert await asyncio.to_thread(app.ready.wait, 10) and not app.start_error
        item = manifest(tmp_path); a.online[b.device_id] = True; a.fleet.queue(item)
        await asyncio.wrap_future(a.submit(a.fleet.deliver_pending()))
        pending = b.db.setting("local_update_pending")
        assert pending["revision"] == item["revision"] and artifact_valid(pending)
        assert a.db.setting("fleet_states")[b.device_id]["status"] == "received"
        assert Path(pending["path"]).parent == b.spaces.folder(a.device_id)
        apk = Path(item["artifacts"]["android"]["path"])
        assert await asyncio.wrap_future(a.submit(a.sender.send(apk, b.device_id, update_revision=item["revision"], app_version=item["version"])))
        received_apk = next(row for row in b.db.history() if row["filename"].endswith(".apk"))
        assert received_apk["mime_type"] == "application/vnd.android.package-archive"
    finally:
        for app in [a, b]:
            await asyncio.to_thread(app.stop)


def test_update_metadata_rejects_incomplete_and_public_update_packages():
    base = dict(transfer_id=uuid4(), filename="a.exe", size=1, sha256="0" * 64, sender_device_id=uuid4(), origin_device_id=uuid4())
    for extra in [{"update_revision": "a" * 64}, {"app_version": "0.4.0"}, {"update_revision": "a" * 64, "app_version": "0.4.0", "share_scope": "general"}]:
        with pytest.raises(ValidationError):
            Metadata(**base, **extra)


def test_automatic_build_waits_for_stable_changes_and_reuses_verified_cache(runtime, tmp_path, monkeypatch):
    from devicedrop import local_build
    from types import SimpleNamespace
    now = [1000]
    monkeypatch.setattr(local_build, "project_root", lambda: tmp_path)
    monkeypatch.setattr(local_build, "source_revision", lambda root: "a" * 64)
    monkeypatch.setattr(local_build, "time", SimpleNamespace(time=lambda: now[0]))
    built = []
    item = manifest(tmp_path)
    monkeypatch.setattr(local_build, "build_local", lambda *args: built.append(args) or item)
    results = []
    worker = local_build.LocalBuildWorker(runtime, automatic=True)
    worker.completed.connect(results.append)
    worker.run()
    assert not built and results == [None]
    now[0] += 31; worker.run()
    assert len(built) == 1 and results[-1] == item
    runtime.fleet.queue(item)
    worker.run()
    assert len(built) == 1 and results[-1] == item


async def test_exit_cancels_distribution_without_starting_another_device(runtime, peer, tmp_path):
    other_id = str(uuid4())
    runtime.db.trust({"device_id": other_id, "device_name": "Other", "platform": "android", "ip": "127.0.0.1", "port": 45989}, "t" * 43)
    runtime.fleet.queue(manifest(tmp_path))
    runtime.online[peer["device_id"]] = runtime.online[other_id] = True
    started = asyncio.Event(); sent = []
    async def send(path, device, **kwargs):
        sent.append(device); started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            return False
    runtime.sender = type("Sender", (), {"send": staticmethod(send)})()
    task = asyncio.create_task(runtime.fleet.deliver_pending())
    await started.wait(); task.cancel(); await asyncio.wait_for(task, 1)
    assert sent == [peer["device_id"]]
    assert runtime.db.setting("fleet_states")[peer["device_id"]]["status"] == "pending"
