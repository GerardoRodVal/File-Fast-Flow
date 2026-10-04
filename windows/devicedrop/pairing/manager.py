import secrets
import threading
import time
from uuid import uuid4


class PairingService:
    def __init__(self, db, device):
        self.db, self.device = db, device
        self.lock = threading.Lock()
        self.code = self.qr_token = None
        self.expires = 0.0
        self.pending = {}
        self.attempts = {}

    def open(self) -> dict:
        with self.lock:
            self.code = f"{secrets.randbelow(1000000):06d}"
            self.qr_token = secrets.token_urlsafe(32)
            self.expires = time.monotonic() + 120
            return {"code": self.code, "expires_in": 120, "qr": {
                "protocol": "devicedrop", "version": 1, **self.device(), "pairing_token": self.qr_token}}

    def request(self, device: dict, code: str, address: str) -> dict:
        with self.lock:
            now = time.monotonic()
            self.attempts = {ip: v for ip, v in self.attempts.items() if v[1] > now}
            count, until = self.attempts.get(address, (0, now + 120))
            if count >= 5:
                raise ValueError("PAIRING_RATE_LIMIT")
            self.attempts[address] = (count + 1, until)
            if now > self.expires or self.code is None:
                raise ValueError("PAIRING_EXPIRED")
            if not (secrets.compare_digest(code, self.code) or secrets.compare_digest(code, self.qr_token)):
                raise ValueError("PAIRING_INVALID")
            if device["device_id"] == self.device()["device_id"]:
                raise ValueError("PAIRING_SELF")
            self.pending = {k: v for k, v in self.pending.items() if v[3] > now}
            request_id, confirmation, token = str(uuid4()), secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            device["ip"] = address  # never trust a remotely supplied address
            self.pending[request_id] = (device, confirmation, token, now + 120)
            self.code = self.qr_token = None  # single use; never persisted
            return {"request_id": request_id, "confirmation_token": confirmation,
                    "shared_token": token, "device": self.device(), "protocol_version": 1}

    def confirm(self, request_id: str, confirmation: str) -> dict:
        with self.lock:
            item = self.pending.get(request_id)
            if not item or time.monotonic() > item[3]:
                self.pending.pop(request_id, None)
                raise ValueError("PAIRING_EXPIRED")
            if not secrets.compare_digest(confirmation, item[1]):
                raise ValueError("PAIRING_INVALID")
            self.db.trust(item[0], item[2])
            del self.pending[request_id]
            return {"status": "paired", "protocol_version": 1}
