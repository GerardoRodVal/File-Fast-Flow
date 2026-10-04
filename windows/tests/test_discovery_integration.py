import asyncio
from devicedrop.runtime import Runtime

async def test_mdns_peers_discover_each_other_on_local_host(tmp_path):
    a, b = Runtime(tmp_path / "a", port=45985), Runtime(tmp_path / "b", port=45986)
    a.start(watching=False); b.start(watching=False)
    try:
        assert await asyncio.to_thread(a.ready.wait, 12)
        assert await asyncio.to_thread(b.ready.wait, 12)
        assert not a.start_error and not b.start_error
        for _ in range(100):
            seen_a = any(d["device_id"] == b.device_id for d in a.discovery.snapshot())
            seen_b = any(d["device_id"] == a.device_id for d in b.discovery.snapshot())
            if seen_a and seen_b: break
            await asyncio.sleep(.1)
        assert seen_a and seen_b
    finally:
        await asyncio.to_thread(a.stop); await asyncio.to_thread(b.stop)
