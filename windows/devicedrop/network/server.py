import asyncio
import time
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from ..storage.models import Metadata, PairRequest, PairConfirm
from .transfer import MultipartReceiver, TransferError


def create_app(runtime) -> FastAPI:
    app = FastAPI(title="FileFastFlow", docs_url=None, redoc_url=None, openapi_url=None)

    @app.exception_handler(TransferError)
    async def transfer_error(request, error):
        return JSONResponse({"error": error.code, "protocol_version": 1}, status_code=error.status)

    @app.exception_handler(ValueError)
    async def value_error(request, error):
        return JSONResponse({"error": "INVALID_REQUEST", "protocol_version": 1}, status_code=400)

    @app.middleware("http")
    async def authenticate(request, call_next):
        public = {"/api/v1/device", "/api/v1/ping", "/api/v1/pair/request", "/api/v1/pair/confirm"}
        if request.url.path not in public:
            peer = runtime.db.authenticate(request.headers.get("authorization", "").removeprefix("Bearer "))
            if not peer:
                return JSONResponse({"error": "UNAUTHORIZED_DEVICE", "protocol_version": 1}, status_code=401)
            request.state.peer = peer
        if request.url.path != "/api/v1/files":
            length = request.headers.get("content-length")
            if length and (not length.isdigit() or int(length) > 32768):
                return JSONResponse({"error": "INVALID_REQUEST", "protocol_version": 1}, status_code=413)
        return await call_next(request)

    async def small_json(request):
        buffer = bytearray()
        async for chunk in request.stream():
            buffer.extend(chunk)
            if len(buffer) > 32768:
                raise TransferError("INVALID_REQUEST", 413)
        import json
        return json.loads(buffer)

    @app.get("/api/v1/device")
    async def device():
        return runtime.device()

    @app.get("/api/v1/ping")
    async def ping():
        return {"status": "online", "device_id": runtime.device_id, "protocol_version": 1}

    @app.get("/api/v1/connection")
    async def connection(request: Request):
        peer = request.state.peer
        if request.headers.get("x-devicedrop-port"):
            runtime.connections.observe(peer, request.client.host, int(request.headers["x-devicedrop-port"]))
        return {"status": "online", "device_id": runtime.device_id, "protocol_version": 1,
                "receiving": runtime.db.setting("allow_receive")}

    @app.post("/api/v1/connection/check")
    async def connection_check(request: Request):
        peer = request.state.peer
        data = await small_json(request)
        if data.get("device_id") != peer["device_id"]:
            raise TransferError("UNAUTHORIZED_DEVICE", 403)
        if data.get("protocol_version") != 1 or type(data.get("port")) is not int or not 45000 <= data["port"] <= 45999:
            raise ValueError("INVALID_REQUEST")
        reverse, error = await runtime.connections.reverse(peer, request.client.host, data["port"])
        return {"status": "online", "device_id": runtime.device_id, "protocol_version": 1,
                "reverse_online": reverse, "reverse_error": error}

    @app.post("/api/v1/pair/request")
    async def pair_request(request: Request):
        data = PairRequest.model_validate(await small_json(request))
        try:
            return runtime.pairing.request(data.device.model_dump(mode="json"), data.code, request.client.host)
        except ValueError as error:
            code = str(error)
            raise TransferError(code, 429 if code == "PAIRING_RATE_LIMIT" else 410 if code == "PAIRING_EXPIRED" else 403)

    @app.post("/api/v1/pair/confirm")
    async def pair_confirm(request: Request):
        data = PairConfirm.model_validate(await small_json(request))
        try:
            result = runtime.pairing.confirm(str(data.request_id), data.confirmation_token)
            runtime.wake_checks()
            runtime.bus.emit("devices_changed")
            return result
        except ValueError as error:
            raise TransferError(str(error), 403)

    @app.get("/api/v1/devices")
    async def devices(request: Request):
        peer = request.state.peer
        return {"devices": [{k: v for k, v in peer.items() if k not in {"token", "ip"}}], "protocol_version": 1}

    @app.post("/api/v1/offers")
    async def offer(request: Request):
        meta = Metadata.model_validate(await small_json(request))
        return runtime.offer(meta, request.state.peer)

    @app.get("/api/v1/offers/{tid}")
    async def offer_status(tid: str, request: Request):
        return runtime.offer_status(tid, request.state.peer)

    @app.post("/api/v1/files")
    async def files(request: Request):
        runtime.require_reception()
        receiver = MultipartReceiver(runtime, request.state.peer, request.headers.get("content-type", ""))
        try:
            async with asyncio.timeout(3600):
                async for chunk in request.stream():
                    await asyncio.to_thread(receiver.parser.write, chunk)
                result = await asyncio.to_thread(receiver.complete)
                runtime.offers.pop(result["transfer_id"], None)
                return result
        except BaseException as error:
            if receiver.meta and receiver.claimed:
                tid = str(receiver.meta.transfer_id)
                code = error.code if isinstance(error, TransferError) else "NETWORK_ERROR"
                runtime.db.update_transfer(tid, status="cancelled" if code == "TRANSFER_CANCELLED" else "failed", error=code)
                runtime.bus.emit("transfer_failed", peer=request.state.peer["device_id"], transfer_id=tid, error=code)
            raise
        finally:
            await asyncio.to_thread(receiver.cleanup)
            if receiver.meta and receiver.claimed:
                runtime.active_uploads.discard(str(receiver.meta.transfer_id))

    def owned(tid, peer):
        rows = runtime.db.execute("SELECT * FROM transfers WHERE transfer_id=? AND (source_device=? OR destination_device=?)", (tid, peer["device_id"], peer["device_id"]))
        if not rows:
            raise TransferError("FILE_NOT_FOUND", 404)
        return rows[0]

    @app.get("/api/v1/files/{tid}")
    async def file_status(tid: str, request: Request):
        row = owned(tid, request.state.peer)
        return {**{k: v for k, v in row.items() if k not in {"original_path", "saved_path"}}, "protocol_version": 1}

    @app.get("/api/v1/transfers")
    async def transfers(request: Request):
        peer = request.state.peer["device_id"]
        return {"transfers": [{k: v for k, v in row.items() if k not in {"original_path", "saved_path"}} for row in runtime.db.history() if peer in (row["source_device"], row["destination_device"])], "protocol_version": 1}

    @app.delete("/api/v1/transfers/{tid}")
    async def cancel(tid: str, request: Request):
        owned(tid, request.state.peer)
        runtime.cancel(tid)
        return {"status": "cancelled", "protocol_version": 1}

    @app.websocket("/ws")
    async def websocket(socket: WebSocket):
        peer = runtime.db.authenticate(socket.headers.get("authorization", "").removeprefix("Bearer "))
        if not peer:
            await socket.close(code=1008); return
        await socket.accept()
        queue = asyncio.Queue(maxsize=128)
        runtime.bus.queues[queue] = peer["device_id"]
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), 15)
                except TimeoutError:
                    event = {"type": "heartbeat", "protocol_version": 1}
                await socket.send_json(event)
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            runtime.bus.queues.pop(queue, None)

    return app
