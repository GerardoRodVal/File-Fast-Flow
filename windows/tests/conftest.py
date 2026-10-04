from pathlib import Path
from uuid import uuid4
import secrets
import pytest
from devicedrop.runtime import Runtime

@pytest.fixture
def runtime(tmp_path):
    app = Runtime(tmp_path / "runtime")
    yield app
    app.db.close()

@pytest.fixture
def peer(runtime):
    device = {"device_id": str(uuid4()), "device_name": "Android test", "platform": "android", "ip": "127.0.0.1", "port": 45833}
    runtime.db.trust(device, secrets.token_urlsafe(32))
    return runtime.db.trusted(device["device_id"])[0]
