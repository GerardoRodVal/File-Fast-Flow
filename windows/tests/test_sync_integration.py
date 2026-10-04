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
