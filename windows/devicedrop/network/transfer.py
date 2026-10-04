import asyncio
import hashlib
import json
import mimetypes
import os
import time
from pathlib import Path
from uuid import uuid4

import httpx
from python_multipart.multipart import MultipartParser, parse_options_header

from ..security.files import CHUNK, validate_filename
from ..storage.models import Metadata


class TransferError(Exception):
    def __init__(self, code: str, status: int = 400):
        super().__init__(code)
        self.code, self.status = code, status


def publish(temp: Path, folder: Path, name: str) -> Path:
    """Hard-link is atomic, same-volume and refuses existing destinations."""
    validate_filename(name)
    source = Path(name)
    for index in range(10000):
        dest = folder / (name if index == 0 else f"{source.stem} ({index}){source.suffix}")
        try:
            os.link(temp, dest)
            temp.unlink()
            return dest
        except FileExistsError:
            continue
    raise TransferError("TOO_MANY_COLLISIONS", 409)


class MultipartReceiver:
    """Incremental multipart parser: metadata <=16KiB, binary never buffered whole."""
    def __init__(self, runtime, peer, content_type: str):
        _, options = parse_options_header(content_type)
        boundary = options.get(b"boundary")
        if not boundary or len(boundary) > 200:
            raise TransferError("INVALID_MULTIPART")
        self.runtime, self.peer = runtime, peer
        self.headers = {}; self.field = b""; self.value = b""; self.name = ""
        self.metadata_buffer = bytearray(); self.meta = None; self.file = None
        self.temp = None; self.done = 0; self.digest = hashlib.sha256()
        self.finished = False; self.file_seen = False; self.last_progress = 0
        self.claimed = False
        self.started = time.monotonic()
        self.parser = MultipartParser(boundary, {"on_part_begin": self.part_begin,
            "on_header_field": self.header_field, "on_header_value": self.header_value,
            "on_header_end": self.header_end, "on_headers_finished": self.headers_finished,
            "on_part_data": self.part_data, "on_part_end": self.part_end, "on_end": self.end})

    def part_begin(self):
        self.headers = {}; self.field = self.value = b""

    def header_field(self, data, start, end):
        self.field += data[start:end]
        if len(self.field) > 1024:
            raise TransferError("INVALID_MULTIPART")

    def header_value(self, data, start, end):
        self.value += data[start:end]
        if len(self.value) > 4096:
            raise TransferError("INVALID_MULTIPART")

    def header_end(self):
        self.headers[self.field.lower()] = self.value
        self.field = self.value = b""

    def headers_finished(self):
        _, options = parse_options_header(self.headers.get(b"content-disposition", b""))
        self.name = options.get(b"name", b"").decode()
        if self.name == "metadata" and self.meta is None and not self.metadata_buffer:
            return
        if self.name != "file" or self.meta is None or self.file_seen:
            raise TransferError("INVALID_MULTIPART")
        self.file_seen = True
        folder = Path(self.runtime.db.setting("receive_folder"))
        folder.mkdir(parents=True, exist_ok=True)
        temp = folder / f".{self.meta.transfer_id}.devicedrop-part"
        try:
            self.file = temp.open("xb")
            self.temp = temp
        except FileExistsError:
            raise TransferError("TRANSFER_BUSY", 409)
        self.runtime.progress(self.meta, self.peer["device_id"], "transferring", 0, 0)

    def part_data(self, data, start, end):
        chunk = data[start:end]
        if self.name == "metadata":
            self.metadata_buffer.extend(chunk)
            if len(self.metadata_buffer) > 16384:
                raise TransferError("INVALID_METADATA")
        elif self.file:
            if str(self.meta.transfer_id) in self.runtime.cancelled:
                raise TransferError("TRANSFER_CANCELLED", 409)
            self.done += len(chunk)
            if self.done > self.meta.size:
                raise TransferError("SIZE_MISMATCH")
            self.file.write(chunk); self.digest.update(chunk)
            now = time.monotonic()
            if now - self.last_progress >= .15:
                self.last_progress = now
                self.runtime.progress(self.meta, self.peer["device_id"], "transferring", self.done, self.done / max(now - self.started, .001))

    def part_end(self):
        if self.name == "metadata":
            try:
                self.meta = Metadata.model_validate_json(self.metadata_buffer)
            except ValueError:
                raise TransferError("INVALID_METADATA")
            self.runtime.validate_upload(self.meta, self.peer)
            self.claimed = True
        elif self.file:
            self.file.flush(); os.fsync(self.file.fileno()); self.file.close(); self.file = None

    def end(self):
        self.finished = True

    def complete(self) -> dict:
        if not self.finished or not self.file_seen or self.meta is None or self.done != self.meta.size:
            raise TransferError("SIZE_MISMATCH")
        self.runtime.progress(self.meta, self.peer["device_id"], "verifying", self.done, 0)
        if self.digest.hexdigest() != self.meta.sha256:
            raise TransferError("TRANSFER_CORRUPTED")
        self.runtime.check_cancelled(str(self.meta.transfer_id))
        dest = publish(self.temp, self.temp.parent, self.meta.filename)
        self.temp = None
        tid = str(self.meta.transfer_id)
        self.runtime.db.execute("INSERT OR IGNORE INTO processed_files VALUES (?,?,?,?)",
            (str(self.meta.origin_device_id), self.meta.sha256, str(dest), tid))
        self.runtime.db.update_transfer(tid, status="completed", saved_path=str(dest), bytes_done=self.done, completed_at=time.time())
        self.runtime.bus.emit("transfer_completed", peer=self.peer["device_id"], transfer_id=tid, filename=dest.name, saved_path=str(dest), mime_type=self.meta.mime_type)
        return {"status": "completed", "transfer_id": tid, "sha256": self.meta.sha256, "filename": dest.name, "protocol_version": 1}

    def cleanup(self):
        if self.file:
            self.file.close()
        if self.temp:
            self.temp.unlink(missing_ok=True)


class TransferService:
    def __init__(self, runtime):
        self.runtime = runtime
        self.tasks = {}
        self.limit = asyncio.Semaphore(2)

    async def send(self, path: Path, device_id: str, batch_id: str | None = None):
        from ..security.files import sha256_file
        tid = str(uuid4())
        self.tasks[tid] = asyncio.current_task()
        try:
            async with self.limit:
                peers = self.runtime.db.trusted(device_id)
                if not peers or not path.is_file():
                    raise TransferError("FILE_NOT_FOUND" if not path.is_file() else "UNAUTHORIZED_DEVICE")
                peer = peers[0]
                before = path.stat()
                digest = await asyncio.to_thread(sha256_file, path)
                if (before.st_size, before.st_mtime_ns) != (path.stat().st_size, path.stat().st_mtime_ns):
                    raise TransferError("FILE_CHANGED")
                meta = Metadata(transfer_id=tid, batch_id=batch_id, filename=path.name, size=before.st_size,
                    sha256=digest, mime_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                    sender_device_id=self.runtime.device_id, origin_device_id=self.runtime.device_id)
                self.runtime.db.transfer(meta.model_dump(mode="json"), "outgoing", device_id, str(path))
                headers = {"Authorization": f"Bearer {peer['token']}"}
                host = self.runtime.endpoint(peer)
                async with httpx.AsyncClient(timeout=httpx.Timeout(30, write=120, read=120), trust_env=False) as client:
                    for attempt in range(4):
                        self.runtime.check_cancelled(tid)
                        self.runtime.progress(meta, device_id, "connecting", 0, 0)
                        try:
                            response = await client.post(host + "/api/v1/offers", json=meta.model_dump(mode="json"), headers=headers)
                            self.check(response)
                            status = response.json()["status"]
                            deadline = time.monotonic() + 120
                            while status == "pending":
                                self.runtime.check_cancelled(tid)
                                if time.monotonic() > deadline:
                                    raise TransferError("OFFER_EXPIRED", 410)
                                await asyncio.sleep(1)
                                response = await client.get(host + f"/api/v1/offers/{tid}", headers=headers)
                                self.check(response); status = response.json()["status"]
                            if status == "completed":
                                self.runtime.progress(meta, device_id, "completed", meta.size, 0)
                                return
                            boundary = "DeviceDrop" + uuid4().hex
                            prefix = (f'--{boundary}\r\nContent-Disposition: form-data; name="metadata"\r\n\r\n'
                                + meta.model_dump_json() + f'\r\n--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="payload"\r\nContent-Type: application/octet-stream\r\n\r\n').encode()
                            suffix = f"\r\n--{boundary}--\r\n".encode()
                            async def body():
                                yield prefix
                                done, start = 0, time.monotonic()
                                with path.open("rb") as stream:
                                    while chunk := await asyncio.to_thread(stream.read, CHUNK):
                                        self.runtime.check_cancelled(tid)
                                        done += len(chunk)
                                        self.runtime.progress(meta, device_id, "transferring", done, done / max(time.monotonic() - start, .001))
                                        yield chunk
                                yield suffix
                                self.runtime.progress(meta, device_id, "verifying", done, 0)
                            response = await client.post(host + "/api/v1/files", content=body(), headers={**headers,
                                "Content-Type": f"multipart/form-data; boundary={boundary}", "Content-Length": str(len(prefix) + meta.size + len(suffix))})
                            self.check(response)
                            if response.json().get("sha256") != meta.sha256:
                                raise TransferError("HASH_MISMATCH")
                            self.runtime.progress(meta, device_id, "completed", meta.size, 0)
                            return
                        except (httpx.TransportError, TransferError) as error:
                            if isinstance(error, TransferError) and error.status < 500:
                                raise
                            if attempt == 3 or (isinstance(error, TransferError) and error.status == 507):
                                raise
                            await asyncio.sleep((1, 3, 7)[attempt])
        except asyncio.CancelledError:
            self.runtime.db.update_transfer(tid, status="cancelled", error="TRANSFER_CANCELLED")
            self.runtime.bus.emit("transfer_cancelled", peer=device_id, transfer_id=tid)
        except Exception as error:
            code = error.code if isinstance(error, TransferError) else "NETWORK_ERROR"
            self.runtime.db.update_transfer(tid, status="failed", error=code)
            self.runtime.bus.emit("transfer_failed", peer=device_id, transfer_id=tid, filename=path.name, error=code)
        finally:
            self.tasks.pop(tid, None)

    @staticmethod
    def check(response):
        if not response.is_success:
            try:
                code = response.json().get("error", "TRANSFER_FAILED")
            except ValueError:
                code = "TRANSFER_FAILED"
            raise TransferError(code, response.status_code)
