import asyncio
import ipaddress
import json
import logging
from logging.handlers import RotatingFileHandler
import os
import shutil
import socket
import threading
import time
from pathlib import Path
from uuid import uuid4

import httpx
import uvicorn
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat, PrivateFormat, NoEncryption

from .network.discovery import DiscoveryService, local_ip
from .network.connectivity import ConnectionService
from .network.server import create_app
from .network.transfer import TransferError, TransferService
from .network.websocket import EventBus
from .pairing.manager import PairingService
from .storage.database import Database
from .sync.watcher import FolderWatcher
from .sync.watcher import readable_without_writer
from .storage.spaces import FileSpaces
from .fleet import FleetUpdates
from .local_build import installed_revision
from . import __version__


class Runtime:
    @staticmethod
    def data_root(root: Path | None = None):
        configured = os.getenv("FILEFASTFLOW_DATA_ROOT") or os.getenv("DEVICEDROP_DATA_ROOT")
        explicit = root or (Path(configured) if configured else None)
        local = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
        # Reuse existing identities, trusted devices and history on upgrade.
        legacy = local / "DeviceDrop"
        return explicit or (legacy if (legacy / "devicedrop.db").is_file() else local / "FileFastFlow")

    def __init__(self, root: Path | None = None, port: int | None = None):
        self.root = self.data_root(root)
        configured = os.getenv("FILEFASTFLOW_DATA_ROOT") or os.getenv("DEVICEDROP_DATA_ROOT")
        explicit = root or (Path(configured) if configured else None)
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = Database(self.root / "devicedrop.db")
        self.device_id = self.db.identity()
        defaults = {"device_name": socket.gethostname(), "port": port or 45832,
            "receive_folder": str(explicit / "shared" if explicit else Path.home() / "filefastflow"),
            "sync_folder": str(explicit / "shared" if explicit else Path.home() / "filefastflow"),
            "allow_receive": True, "minimize_tray": True, "notifications": True,
            "start_windows": False, "theme": "Light", "onboarded": False, "auto_updates": True,
            "widget_enabled": True, "widget_theme": "classic"}
        for key, value in defaults.items():
            self.db.setting(key, value)
        old_receive = self.db.setting("receive_folder")
        migrate_received = self.db.setting("reception_layout_version", 0) < 2
        if migrate_received:
            self.db.set_setting("receive_folder", self.db.setting("sync_folder"))
        reception = Path(self.db.setting("receive_folder"))
        if not explicit and reception == Path.home() / "FileFastFlow":
            reception = Path.home() / "filefastflow"
            self.db.set_setting("receive_folder", str(reception))
        self.db.set_setting("sync_folder", str(reception))
        if port:
            self.db.set_setting("port", port)
        self.port = self.db.setting("port")
        key = self.db.setting("identity_key")
        if not key:
            private = Ed25519PrivateKey.generate()
            self.db.set_setting("identity_key", private.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption()).hex())
        else:
            private = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(key))
        self.public_key = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()
        for field in ("receive_folder", "sync_folder"):
            Path(self.db.setting(field)).mkdir(parents=True, exist_ok=True)
        self.spaces = FileSpaces(self.root, self.db)
        self.spaces.migrate_legacy()
        if migrate_received:
            self.spaces.migrate_received(old_receive)
            self.db.set_setting("reception_layout_version", 2)
        for peer in self.db.trusted():
            self.spaces.folder(peer["device_id"])
        for partial in reception.rglob(".*.devicedrop-part"):
            if not partial.is_symlink() and partial.resolve().is_relative_to(reception.resolve()):
                partial.unlink(missing_ok=True)
        logs = self.root / "logs"; logs.mkdir(exist_ok=True)
        self.logger = logging.getLogger("devicedrop")
        if not self.logger.handlers:
            handler = RotatingFileHandler(logs / "devicedrop.log", maxBytes=2 * 1024**2, backupCount=3, encoding="utf-8")
            handler.setFormatter(logging.Formatter('{"time":"%(asctime)s","level":"%(levelname)s","message":"%(message)s"}'))
            self.logger.addHandler(handler); self.logger.setLevel(logging.INFO)
        self.bus = EventBus(); self.offers = {}; self.cancelled = set(); self.active_uploads = set()
        self.pairing = PairingService(self.db, self.device)
        self.discovery = DiscoveryService(self)
        self.loop = None; self.server = None; self.thread = None; self.watcher = None
        self.sender = None; self.ready = threading.Event(); self.stopped = threading.Event(); self.start_error = None
        self.online = {}; self.children = set(); self.accept_lock = threading.RLock()
        self.connections = ConnectionService(self)
        self.check_requested = None
        self.pending_shares = set()
        self.sharing_task = None
        self.fleet = FleetUpdates(self)

    def configure_reception_folder(self, path):
        path = Path(path).resolve(); path.mkdir(parents=True, exist_ok=True)
        self.db.set_setting("receive_folder", str(path))
        self.db.set_setting("sync_folder", str(path))
        self.spaces = FileSpaces(self.root, self.db)
        for peer in self.db.trusted():
            self.spaces.folder(peer["device_id"])

    def receiving_folder(self, meta, peer):
        return self.spaces.folder(None if meta.share_scope == "general" else peer["device_id"])

    def device(self):
        return {"device_id": self.device_id, "device_name": self.db.setting("device_name"),
            "device_type": "desktop", "platform": "windows", "ip": local_ip(),
            "port": self.port, "public_key": self.public_key, "protocol_version": 1, "app_version": __version__, "local_revision": installed_revision()}

    @staticmethod
    def endpoint(peer):
        address = ipaddress.ip_address(peer["ip"])
        if not (address.is_private or address.is_loopback) or address.is_multicast or address.is_unspecified:
            raise TransferError("INVALID_LAN_ADDRESS")
        port = int(peer["port"])
        if not 45000 <= port <= 45999:
            raise TransferError("INVALID_PORT")
        host = f"[{address}]" if address.version == 6 else str(address)
        return f"http://{host}:{port}"

    def require_reception(self):
        if not self.db.setting("allow_receive"):
            raise TransferError("RECEPTION_PAUSED", 503)

    def offer(self, meta, peer):
        self.require_reception()
        tid = str(meta.transfer_id)
        if str(meta.sender_device_id) != peer["device_id"]:
            raise TransferError("UNAUTHORIZED_DEVICE", 403)
        existing = self.db.execute("SELECT * FROM transfers WHERE transfer_id=?", (tid,))
        if existing and (existing[0]["source_device"] != peer["device_id"] or existing[0]["sha256"] != meta.sha256 or existing[0]["size"] != meta.size or existing[0]["share_scope"] != meta.share_scope):
            raise TransferError("TRANSFER_CONFLICT", 409)
        if existing and existing[0]["status"] == "completed":
            return {"status": "completed", "sha256": meta.sha256, "protocol_version": 1}
        with self.accept_lock:
            self.offers = {k: v for k, v in self.offers.items() if v["expires"] > time.monotonic() or k in self.active_uploads}
            reserved = sum(o["meta"].size for k, o in self.offers.items() if k != tid)
            if shutil.disk_usage(self.db.setting("receive_folder")).free < meta.size + reserved + 1024**2:
                raise TransferError("NOT_ENOUGH_SPACE", 507)
            if tid in self.offers:
                if self.offers[tid]["meta"] != meta:
                    raise TransferError("TRANSFER_CONFLICT", 409)
                return self.offer_status(tid, peer)
            if len(self.offers) >= 64:
                raise TransferError("TOO_MANY_TRANSFERS", 429)
            self.cancelled.discard(tid)
            status = "accepted" if peer["auto_accept"] else "pending"
            self.offers[tid] = {"meta": meta, "peer": peer["device_id"], "status": status, "expires": time.monotonic() + 120}
            self.db.transfer(meta.model_dump(mode="json"), "incoming", self.device_id)
            self.db.update_transfer(tid, status="queued", error=None)
            if status == "pending":
                self.bus.emit("transfer_offer", peer=peer["device_id"], transfer_id=tid, filename=meta.filename, size=meta.size, sender=peer["name"])
            return {"status": status, "protocol_version": 1}

    def offer_status(self, tid, peer):
        offer = self.offers.get(tid)
        if not offer or offer["peer"] != peer["device_id"]:
            raise TransferError("OFFER_EXPIRED", 410)
        if time.monotonic() > offer["expires"]:
            raise TransferError("OFFER_EXPIRED", 410)
        if offer["status"] == "rejected":
            raise TransferError("TRANSFER_REJECTED", 403)
        return {"status": offer["status"], "protocol_version": 1}

    def approve(self, tid, accept):
        with self.accept_lock:
            if tid in self.offers:
                self.offers[tid]["status"] = "accepted" if accept else "rejected"

    def validate_upload(self, meta, peer):
        self.require_reception()
        tid = str(meta.transfer_id)
        with self.accept_lock:
            status = self.offer_status(tid, peer)
            if status["status"] != "accepted" or self.offers[tid]["meta"] != meta:
                raise TransferError("OFFER_REQUIRED", 403)
            if tid in self.active_uploads:
                raise TransferError("TRANSFER_BUSY", 409)
            self.active_uploads.add(tid)

    def check_cancelled(self, tid):
        if tid in self.cancelled:
            raise TransferError("TRANSFER_CANCELLED", 409)

    def cancel(self, tid):
        self.cancelled.add(tid)
        if self.sender and tid in self.sender.tasks:
            self.loop.call_soon_threadsafe(self.sender.tasks[tid].cancel)
        self.db.update_transfer(tid, status="cancelled", error="TRANSFER_CANCELLED")

    def progress(self, meta, peer, status, done, speed):
        tid = str(meta.transfer_id)
        values = {"status": status, "bytes_done": done, "speed": speed}
        if status == "completed":
            values["completed_at"] = time.time()
        self.db.update_transfer(tid, **values)
        kind = {"completed": "transfer_completed", "verifying": "transfer_verifying", "connecting": "transfer_started"}.get(status, "transfer_progress")
        self.bus.emit(kind, peer=peer, transfer_id=tid, filename=meta.filename, size=meta.size, bytes_done=done,
            speed=speed, progress=round(done * 100 / max(meta.size, 1)), status=status)

    async def pair(self, ip, port, code):
        host = self.endpoint({"ip": ip, "port": port})
        async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
            response = await client.post(host + "/api/v1/pair/request", json={"device": self.device(), "code": code})
            TransferService.check(response); result = response.json()
            response = await client.post(host + "/api/v1/pair/confirm", json={"request_id": result["request_id"], "confirmation_token": result["confirmation_token"]})
            TransferService.check(response)
            device = result["device"]; device["ip"] = ip
            self.db.trust(device, result["shared_token"])
            self.wake_checks()
            self.bus.emit("devices_changed")
            return device

    def submit(self, coroutine):
        if not self.loop or not self.loop.is_running():
            coroutine.close()
            raise RuntimeError("SERVER_NOT_READY")
        return asyncio.run_coroutine_threadsafe(coroutine, self.loop)

    def send_files(self, paths, device_ids, force=True):
        paths = list(map(Path, paths))
        for path in paths:
            context = self.spaces.sharing_context(path)
            if context and context[0] == "device" and any(d != context[1] for d in device_ids):
                raise ValueError("Los archivos de una carpeta individual solo pueden enviarse a su dispositivo.")
        batch = str(uuid4())
        async def batch_send():
            return await asyncio.gather(*(self.send_shared(path, device, batch, force) for device in device_ids for path in paths))
        return self.submit(batch_send())

    async def send_shared(self, path, device_id, batch=None, force=False):
        path = Path(path).resolve()
        context = self.spaces.sharing_context(path)
        scope = context[0] if context else "device"
        if context and scope == "device" and context[1] != device_id:
            return False
        if not context:
            return await self.sender.send(path, device_id, batch, share_scope=scope)
        key = (str(path), device_id)
        if key in self.pending_shares or not path.is_file():
            return False
        try:
            stat = path.stat()
        except OSError:
            return False
        rows = self.db.execute("SELECT * FROM space_deliveries WHERE path=? AND device_id=?", key)
        if not force and rows and rows[0]["status"] == "completed" and (rows[0]["size"], rows[0]["mtime_ns"]) == (stat.st_size, stat.st_mtime_ns):
            return True
        self.pending_shares.add(key)
        self.db.execute("INSERT OR REPLACE INTO space_deliveries VALUES (?,?,?,?,?)", (*key, stat.st_size, stat.st_mtime_ns, "queued"))
        try:
            success = await self.sender.send(path, device_id, batch, share_scope=scope)
            self.db.execute("UPDATE space_deliveries SET status=? WHERE path=? AND device_id=?", ("completed" if success else "failed", *key))
            return success
        finally:
            self.pending_shares.discard(key)

    def is_received_file(self, path):
        return bool(self.db.execute("SELECT 1 FROM processed_files WHERE path=?", (str(Path(path).resolve()),)))

    async def reconcile_sharing(self):
        peers = [p for p in self.db.trusted() if self.online.get(p["device_id"]) and self.connections.results.get(p["device_id"], {}).get("remote_receiving") is not False]
        jobs = []
        for peer in peers:
            try:
                paths = [*self.spaces.files(), *self.spaces.files(peer["device_id"])]
            except (OSError, ValueError):
                continue
            for path in paths:
                try:
                    # Let copies settle before a periodic scan sends them.
                    if not self.is_received_file(path) and time.time() - path.stat().st_mtime >= 3 and readable_without_writer(path):
                        jobs.append(self.send_shared(path, peer["device_id"]))
                except OSError:
                    continue
        await asyncio.gather(*jobs, return_exceptions=True)

    def sync_created(self, path):
        # Received paths must never be re-exported, even if folders overlap.
        if self.is_received_file(path) or path.name.startswith(".") or path.is_symlink() or not path.is_file():
            return
        if self.spaces.is_managed(path):
            return
        context = self.spaces.sharing_context(path)
        if context is None:
            return
        scope, owner = context
        devices = [d["device_id"] for d in self.db.trusted() if self.online.get(d["device_id"], False) and (scope == "general" or d["device_id"] == owner)]
        if devices:
            self.send_files([path], devices, force=False)

    async def heartbeat(self):
        self.check_requested = asyncio.Event()
        limit = asyncio.Semaphore(4)
        async def check(peer):
            async with limit:
                try:
                    await self.connections.check(peer["device_id"], full=False)
                except ValueError:
                    # The peer may have been unpaired while this check waited.
                    pass
        while True:
            self.check_requested.clear()
            await asyncio.gather(*(check(peer) for peer in self.db.trusted()))
            if self.sharing_task is None or self.sharing_task.done():
                self.sharing_task = asyncio.create_task(self.reconcile_sharing())
            if self.fleet.task is None or self.fleet.task.done():
                self.fleet.task = asyncio.create_task(self.fleet.deliver_pending())
            try:
                await asyncio.wait_for(self.check_requested.wait(), 12)
            except TimeoutError:
                pass

    def wake_checks(self):
        if self.check_requested and self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self.check_requested.set)

    def start(self, discovery=True, watching=True):
        def run():
            try:
                asyncio.run(self.serve(discovery, watching))
            except BaseException as error:
                self.start_error = "PORT_IN_USE" if isinstance(error, OSError) and (error.errno == 98 or getattr(error, "winerror", None) == 10048 or error.errno == 10048) else type(error).__name__
                self.logger.error("server_start_failed %s", self.start_error)
                self.ready.set()
            finally:
                self.stopped.set()
        self.thread = threading.Thread(target=run, name="DeviceDrop-server", daemon=False)
        self.thread.start()

    async def serve(self, discovery, watching):
        self.loop = asyncio.get_running_loop(); self.bus.loop = self.loop
        self.sender = TransferService(self)
        self.server = uvicorn.Server(uvicorn.Config(create_app(self), host="0.0.0.0", port=self.port,
            log_level="warning", log_config=None, access_log=False, timeout_graceful_shutdown=5))
        # Bind explicitly so a port conflict is reported as OSError instead of
        # Uvicorn's SystemExit, and Windows cannot bind a second LAN receiver.
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            if os.name == "nt":
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            else:
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(("0.0.0.0", self.port))
            listener.listen(socket.SOMAXCONN); listener.setblocking(False)
        except BaseException:
            listener.close(); raise
        server_task = asyncio.create_task(self.server.serve(sockets=[listener]))
        try:
            while not self.server.started:
                if server_task.done():
                    await server_task
                    raise RuntimeError("SERVER_START_FAILED")
                await asyncio.sleep(.05)
            if discovery:
                try:
                    await asyncio.to_thread(self.discovery.start)
                except Exception as error:
                    self.logger.warning("discovery_unavailable %s", type(error).__name__)
                    self.bus.emit("discovery_error", error="Usa vinculación manual por IP; mDNS no está disponible.")
            if watching:
                self.watcher = FolderWatcher(Path(self.db.setting("sync_folder")), self.sync_created)
                self.watcher.start()
            heartbeat = asyncio.create_task(self.heartbeat())
            self.ready.set(); self.bus.emit("server_ready", port=self.db.setting("port"))
            await server_task
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)
        finally:
            listener.close()
            if self.fleet.task:
                self.fleet.task.cancel()
                await asyncio.gather(self.fleet.task, return_exceptions=True)
            if self.sharing_task:
                self.sharing_task.cancel()
                await asyncio.gather(self.sharing_task, return_exceptions=True)
            if self.sender:
                for task in tuple(self.sender.tasks.values()):
                    task.cancel()
                await asyncio.gather(*tuple(self.sender.tasks.values()), return_exceptions=True)
            if self.watcher:
                await asyncio.to_thread(self.watcher.stop)
            await asyncio.to_thread(self.discovery.stop)
            self.ready.set()

    def stop(self):
        if self.server and self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(setattr, self.server, "should_exit", True)
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=12)
            if self.thread.is_alive():
                raise RuntimeError("SERVER_STOP_TIMEOUT")
        self.db.close()
