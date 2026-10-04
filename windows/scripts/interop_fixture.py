"""Real TCP fixture for Android Robolectric interoperability tests.

Run this alongside the Android InteropTest with DEVICEDROP_INTEROP_DIR set.
Pairing secrets exist only in a temporary work folder, removed on exit.
"""
import argparse
import json
from pathlib import Path
import time
from PIL import Image
from devicedrop.runtime import Runtime
from devicedrop.security.files import sha256_file

parser = argparse.ArgumentParser()
parser.add_argument("folder", type=Path)
args = parser.parse_args()
folder = args.folder.resolve(); folder.mkdir(parents=True, exist_ok=True)
for stale in ("android-ready.json", "windows-sent.json", "android-sent.json", "finished.json"):
    (folder / stale).unlink(missing_ok=True)
runtime = Runtime(folder / "windows", port=45833)
runtime.start(discovery=False, watching=False)
try:
    if not runtime.ready.wait(10) or runtime.start_error:
        raise RuntimeError("WINDOWS_SERVER_START_FAILED")
    files = folder / "fixtures"; files.mkdir(exist_ok=True)
    (files / "small.txt").write_text("DeviceDrop interoperability\n", encoding="utf-8")
    Image.new("RGB", (800, 600), (8, 127, 105)).save(files / "photo.jpg")
    with (files / "100MB.bin").open("wb") as output:
        block = bytes(range(256)) * 4096
        for _ in range(100): output.write(block)
    hashes = {file.name: sha256_file(file) for file in files.iterdir()}
    window = runtime.pairing.open()
    (folder / "config.json").write_text(json.dumps({"device_id": runtime.device_id, "code": window["code"], "hashes": hashes}), encoding="utf-8")
    deadline = time.monotonic() + 300
    while not (folder / "android-ready.json").exists():
        if time.monotonic() > deadline: raise TimeoutError("Android test did not start")
        time.sleep(.2)
    android = json.loads((folder / "android-ready.json").read_text(encoding="utf-8"))
    runtime.db.execute("UPDATE trusted_devices SET ip='127.0.0.1',port=? WHERE device_id=?", (android["port"], android["device_id"]))
    connection = runtime.submit(runtime.connections.check(android["device_id"])).result(timeout=30)
    assert connection["forward_online"] and connection["reverse_online"], connection
    runtime.send_files(list(files.iterdir()), [android["device_id"]]).result(timeout=180)
    outbound = [t for t in runtime.db.history() if t["direction"] == "outgoing" and t["destination_device"] == android["device_id"]]
    assert len(outbound) == 3 and all(t["status"] == "completed" for t in outbound), outbound
    (folder / "windows-sent.json").write_text(json.dumps({"status": "completed"}), encoding="utf-8")
    while not (folder / "android-sent.json").exists():
        if time.monotonic() > deadline: raise TimeoutError("Android return transfers did not finish")
        time.sleep(.2)
    incoming = [t for t in runtime.db.history() if t["direction"] == "incoming" and t["source_device"] == android["device_id"]]
    assert len(incoming) == 3 and all(t["status"] == "completed" for t in incoming), incoming
    for row in incoming:
        assert sha256_file(Path(row["saved_path"])) == hashes[row["filename"]]
    result = {"status": "passed", "files": list(hashes), "directions": 2, "transfers": 6, "sha256": "all_match", "connection_validation": "both_directions_passed", "environment": "Windows Python and Android Kotlin under Robolectric, real TCP loopback"}
    (folder / "finished.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result), flush=True)
finally:
    (folder / "config.json").unlink(missing_ok=True)
    runtime.stop()
