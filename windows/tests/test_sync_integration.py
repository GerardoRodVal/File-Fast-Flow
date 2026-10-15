import asyncio
from pathlib import Path
from devicedrop.runtime import Runtime
from devicedrop.security.files import sha256_file

async def test_new_shared_file_auto_syncs_once(tmp_path):
    a, b = Runtime(tmp_path / "a", port=45983), Runtime(tmp_path / "b", port=45984)
    a.start(discovery=False); b.start(discovery=False)
    try:
        assert await asyncio.to_thread(a.ready.wait, 10)
        assert await asyncio.to_thread(b.ready.wait, 10)
        window = b.pairing.open()
        await asyncio.wrap_future(a.submit(a.pair("127.0.0.1", 45984, window["code"])))
        a.db.execute("UPDATE trusted_devices SET ip='127.0.0.1', auto_sync=1")
        a.online[b.device_id] = True
        source = Path(a.db.setting("sync_folder")) / "shared.txt"; source.write_text("automatic")
        for _ in range(100):
            received = [r for r in b.db.history() if r["status"] == "completed"]
            if received: break
            await asyncio.sleep(.1)
        assert len(received) == 1
        assert sha256_file(Path(received[0]["saved_path"])) == sha256_file(source)
        await asyncio.sleep(1)
        assert len(b.db.history()) == 1
        assert not [r for r in b.db.history() if r["direction"] == "outgoing"]
    finally:
        await asyncio.to_thread(a.stop); await asyncio.to_thread(b.stop)


async def test_general_and_private_delivery_isolate_two_destinations_and_reconnect(tmp_path):
    a, b, c = (Runtime(tmp_path / name, port=port) for name, port in [("a", 45981), ("b", 45982), ("c", 45985)])
    token = "s" * 43
    for target in [b, c]:
        a.db.trust({**target.device(), "ip": "127.0.0.1"}, token)
        target.db.trust({**a.device(), "ip": "127.0.0.1"}, token)
        a.spaces.folder(target.device_id)
    for app in [a, b, c]:
        app.start(discovery=False)
    try:
        for app in [a, b, c]:
            assert await asyncio.to_thread(app.ready.wait, 10) and not app.start_error
        a.online[b.device_id] = a.online[c.device_id] = True
        source = tmp_path / "public.txt"; source.write_text("general")
        saved = a.spaces.store([source])
        await asyncio.wrap_future(a.send_files(saved, [b.device_id, c.device_id]))
        private = a.spaces.folder(b.device_id) / "private.txt"
        private.write_text("for this device only")
        for _ in range(100):
            if len([r for r in b.db.history() if r["status"] == "completed"]) == 2: break
            await asyncio.sleep(.1)
        assert (b.spaces.folder() / "public.txt").read_text() == "general"
        assert (c.spaces.folder() / "public.txt").read_text() == "general"
        received_private = b.spaces.folder(a.device_id) / "private.txt"
        assert received_private.read_text() == "for this device only"
        assert c.spaces.files(a.device_id) == []
        await asyncio.wrap_future(a.submit(a.reconcile_sharing()))
        assert len(b.db.history()) == 2 and len(c.db.history()) == 1
        assert len(a.db.history()) == 3
        assert not [r for target in [b, c] for r in target.db.history() if r["direction"] == "outgoing"]
        # A file placed while C is offline is picked up on reconnection.
        offline_mode = True
        original_check = a.connections.check
        async def check(device_id, **kwargs):
            if device_id == c.device_id and offline_mode:
                a.online[c.device_id] = False
                return {}
            return await original_check(device_id, **kwargs)
        a.connections.check = check
        a.online[c.device_id] = False
        offline = a.spaces.folder(c.device_id) / "offline.txt"; offline.write_text("later")
        await asyncio.sleep(4.5)
        assert not (c.spaces.folder(a.device_id) / "offline.txt").exists()
        offline_mode = False
        a.online[c.device_id] = True
        await asyncio.wrap_future(a.submit(a.reconcile_sharing()))
        assert (c.spaces.folder(a.device_id) / "offline.txt").read_text() == "later"
        assert not (b.spaces.folder(a.device_id) / "offline.txt").exists()
        await asyncio.wrap_future(a.submit(a.reconcile_sharing()))
        assert len(c.db.history()) == 2
    finally:
        for app in [a, b, c]:
            await asyncio.to_thread(app.stop)
