import json
import secrets
import sqlite3
import threading
import time
from pathlib import Path
from uuid import uuid4

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS devices (device_id TEXT PRIMARY KEY, data TEXT NOT NULL, last_seen REAL);
CREATE TABLE IF NOT EXISTS trusted_devices (
 device_id TEXT PRIMARY KEY, name TEXT, platform TEXT, public_key TEXT,
 token TEXT NOT NULL, created_at REAL, last_seen REAL, auto_accept INTEGER DEFAULT 1,
 auto_sync INTEGER DEFAULT 0, ip TEXT, port INTEGER);
CREATE TABLE IF NOT EXISTS transfers (
 id INTEGER PRIMARY KEY AUTOINCREMENT, transfer_id TEXT UNIQUE, direction TEXT,
 filename TEXT, original_path TEXT, saved_path TEXT, size INTEGER, sha256 TEXT,
 mime_type TEXT, source_device TEXT, destination_device TEXT, origin_device_id TEXT,
 batch_id TEXT, status TEXT, started_at REAL, completed_at REAL, error TEXT,
 bytes_done INTEGER DEFAULT 0, speed REAL DEFAULT 0);
CREATE TABLE IF NOT EXISTS processed_files (
 origin_device_id TEXT, content_hash TEXT, path TEXT, transfer_id TEXT,
 PRIMARY KEY(origin_device_id, content_hash, path));
"""


class Database:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript("PRAGMA journal_mode=WAL; PRAGMA busy_timeout=5000;" + SCHEMA)
        self.conn.execute("UPDATE transfers SET status='failed', error='INTERRUPTED' WHERE status NOT IN ('completed','failed','cancelled')")
        self.conn.commit()

    def execute(self, sql: str, args: tuple = ()) -> list[dict]:
        with self.lock:
            cursor = self.conn.execute(sql, args)
            rows = [dict(row) for row in cursor.fetchall()]
            self.conn.commit()
            return rows

    def setting(self, key: str, default=None):
        rows = self.execute("SELECT value FROM settings WHERE key=?", (key,))
        if rows:
            return json.loads(rows[0]["value"])
        if default is not None:
            self.set_setting(key, default)
        return default

    def set_setting(self, key: str, value):
        self.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, json.dumps(value)))

    def identity(self) -> str:
        return self.setting("device_id", str(uuid4()))

    def trust(self, device: dict, token: str):
        self.execute("""INSERT INTO trusted_devices
        (device_id,name,platform,public_key,token,created_at,last_seen,ip,port) VALUES (?,?,?,?,?,?,?,?,?)
        ON CONFLICT(device_id) DO UPDATE SET name=excluded.name,platform=excluded.platform,
        public_key=excluded.public_key,token=excluded.token,ip=excluded.ip,port=excluded.port""",
        (str(device["device_id"]), device["device_name"], device["platform"], device.get("public_key", ""),
         token, time.time(), time.time(), device.get("ip", ""), device["port"]))

    def trusted(self, device_id: str | None = None) -> list[dict]:
        return self.execute("SELECT * FROM trusted_devices" + (" WHERE device_id=?" if device_id else ""), (device_id,) if device_id else ())

    def authenticate(self, token: str) -> dict | None:
        if len(token) < 32:
            return None
        return next((d for d in self.trusted() if secrets.compare_digest(d["token"], token)), None)

    def history(self) -> list[dict]:
        return self.execute("SELECT * FROM transfers ORDER BY started_at DESC LIMIT 300")

    def transfer(self, meta: dict, direction: str, destination: str = "", original_path: str = ""):
        self.execute("""INSERT INTO transfers (transfer_id,direction,filename,size,sha256,mime_type,
        source_device,destination_device,origin_device_id,batch_id,status,started_at,original_path)
        VALUES (?,?,?,?,?,?,?,?,?,?, 'queued',?,?) ON CONFLICT(transfer_id) DO NOTHING""",
        (str(meta["transfer_id"]), direction, meta["filename"], meta["size"], meta["sha256"], meta["mime_type"],
         str(meta["sender_device_id"]), destination, str(meta["origin_device_id"]), str(meta.get("batch_id") or ""), time.time(), original_path))

    def update_transfer(self, transfer_id: str, **values):
        allowed = {"status", "bytes_done", "speed", "saved_path", "completed_at", "error"}
        if not values.keys() <= allowed:
            raise ValueError("Unknown transfer field")
        self.execute("UPDATE transfers SET " + ",".join(f"{k}=?" for k in values) + " WHERE transfer_id=?", (*values.values(), transfer_id))

    def close(self):
        with self.lock:
            self.conn.close()
