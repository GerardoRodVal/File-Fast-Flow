"""Bounded, authenticated LAN checks, including a non-recursive return probe."""
import asyncio
import time

import httpx

from .transfer import TransferError


MESSAGES = {
    "TIMEOUT": "La otra aplicación no respondió a tiempo. Revisa Wi-Fi, firewall y VPN.",
    "UNREACHABLE": "No se pudo llegar a la IP y al puerto. Abre FileFastFlow en el otro equipo y revisa la red privada.",
    "IDENTITY_MISMATCH": "Esta IP pertenece a otro dispositivo. Corrige la IP; el vínculo se conserva.",
    "AUTH_FAILED": "El vínculo no fue aceptado. Vuelve a vincular ambos dispositivos.",
    "UPDATE_REQUIRED": "Actualiza FileFastFlow en el otro dispositivo para comprobar el camino de vuelta.",
    "INVALID_LAN_ADDRESS": "Revisa la IP local y el puerto (45000–45999).",
    "INVALID_PORT": "El puerto debe estar entre 45000 y 45999.",
    "INVALID_RESPONSE": "La respuesta no corresponde al protocolo de FileFastFlow.",
    "CHECK_FAILED": "La comprobación de retorno no terminó. Inténtalo de nuevo.",
}


def error_code(error):
    if isinstance(error, httpx.TimeoutException):
        return "TIMEOUT"
    if isinstance(error, httpx.HTTPError):
        return "UNREACHABLE"
    return getattr(error, "code", "INVALID_RESPONSE")


def report_text(result):
    forward = "Correcta" if result["forward_online"] else "Falló"
    reverse = "Correcta" if result.get("reverse_online") is True else "Falló" if result.get("reverse_online") is False else "Sin comprobar"
    lines = [f"Este equipo → {result['name']}: {forward}", f"{result['name']} → este equipo: {reverse}",
             f"Dirección comprobada: {result.get('ip', '')}:{result.get('port', '')}"]
    if result.get("code"):
        lines.append(MESSAGES.get(result["code"], MESSAGES["CHECK_FAILED"]))
    if result.get("remote_receiving") is False:
        lines.append("La recepción de archivos está pausada en el otro dispositivo.")
    if result.get("local_receiving") is False:
        lines.append("La recepción de archivos está pausada en este equipo.")
    return "\n".join(lines)


class ConnectionService:
    def __init__(self, runtime):
        self.runtime = runtime
        self.results = {}
        self.locks = {}

    async def probe(self, peer):
        base = self.runtime.endpoint(peer)
        headers = {"Authorization": "Bearer " + peer["token"], "X-DeviceDrop-Port": str(self.runtime.port)}
        async with httpx.AsyncClient(timeout=3, trust_env=False) as client:
            ping = await client.get(base + "/api/v1/ping")
            if not ping.is_success:
                raise TransferError("UNREACHABLE")
            body = ping.json()
            if not isinstance(body, dict):
                raise ValueError("INVALID_RESPONSE")
            if body.get("device_id") != peer["device_id"]:
                raise TransferError("IDENTITY_MISMATCH")
            if body.get("protocol_version") != 1:
                raise TransferError("INVALID_RESPONSE")
            response = await client.get(base + "/api/v1/connection", headers=headers)
            legacy = response.status_code == 404
            if legacy:
                response = await client.get(base + "/api/v1/devices", headers=headers)
            if response.status_code in {401, 403}:
                raise TransferError("AUTH_FAILED")
            if not response.is_success:
                raise TransferError("UNREACHABLE")
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError("INVALID_RESPONSE")
            if data.get("protocol_version") != 1 or (not legacy and data.get("device_id") != peer["device_id"]):
                raise TransferError("INVALID_RESPONSE")
            return {"legacy": legacy, "receiving": data.get("receiving")}

    def observe(self, peer, ip, port):
        # Address changes are accepted only on an authenticated request.
        self.runtime.endpoint({"ip": ip, "port": port})
        self.runtime.db.execute("UPDATE trusted_devices SET ip=?,port=? WHERE device_id=?", (ip, port, peer["device_id"]))

    def store(self, peer, forward, reverse=None, code="", **extra):
        result = {"device_id": peer["device_id"], "name": peer["name"], "ip": peer["ip"], "port": peer["port"],
                  "forward_online": forward, "reverse_online": reverse, "code": code, "checked_at": time.time(),
                  "local_receiving": self.runtime.db.setting("allow_receive"), **extra}
        self.results[peer["device_id"]] = result
        self.runtime.online[peer["device_id"]] = forward
        if forward:
            self.runtime.db.execute("UPDATE trusted_devices SET ip=?,port=?,last_seen=? WHERE device_id=?",
                                    (peer["ip"], peer["port"], time.time(), peer["device_id"]))
        self.runtime.bus.emit("connection_checked", peer=peer["device_id"], device_id=peer["device_id"])
        return result

    async def reverse(self, peer, ip, port):
        self.observe(peer, ip, port)
        peer = {**peer, "ip": ip, "port": port}
        try:
            data = await self.probe(peer)
            self.store(peer, True, True, remote_receiving=data.get("receiving"))
            return True, ""
        except (httpx.HTTPError, ValueError, TransferError, KeyError) as error:
            code = error_code(error)
            self.store(peer, False, True, code)
            return False, code

    async def check(self, device_id, full=True, ip=None, port=None):
        lock = self.locks.setdefault(device_id, asyncio.Lock())
        async with lock:
            rows = self.runtime.db.trusted(device_id)
            if not rows:
                raise ValueError("Dispositivo no vinculado.")
            original = rows[0]
            candidates = [(ip, port or original["port"])] if ip is not None else [
                (p["ip"], p["port"]) for p in self.runtime.discovery.snapshot()
                if p["device_id"] == device_id and p.get("online")]
            if ip is None:
                candidates.append((original["ip"], original["port"]))
            last_code = "UNREACHABLE"
            peer = original
            for address, number in list(dict.fromkeys(candidates))[:4]:
                peer = {**original, "ip": address, "port": number}
                try:
                    data = await self.probe(peer)
                    break
                except (httpx.HTTPError, ValueError, TransferError, KeyError) as error:
                    last_code = error_code(error)
            else:
                # A failed override must never replace the saved endpoint.
                return self.store({**original, "ip": peer["ip"], "port": peer["port"]}, False, code=last_code)
            reverse, code = None, "UPDATE_REQUIRED" if data["legacy"] else ""
            self.runtime.db.execute("UPDATE trusted_devices SET ip=?,port=? WHERE device_id=?", (peer["ip"], peer["port"], device_id))
            if full and not data["legacy"]:
                try:
                    async with httpx.AsyncClient(timeout=12, trust_env=False) as client:
                        response = await client.post(self.runtime.endpoint(peer) + "/api/v1/connection/check",
                            headers={"Authorization": "Bearer " + peer["token"]}, json={"device_id": self.runtime.device_id,
                            "port": self.runtime.port, "protocol_version": 1})
                    response.raise_for_status()
                    body = response.json()
                    if not isinstance(body, dict):
                        raise ValueError("INVALID_RESPONSE")
                    if body.get("device_id") != device_id or body.get("protocol_version") != 1 or not isinstance(body.get("reverse_online"), bool):
                        raise ValueError("INVALID_RESPONSE")
                    reverse = body["reverse_online"]
                    code = body.get("reverse_error", "") if not reverse else ""
                except (httpx.HTTPError, ValueError, TransferError) as error:
                    code = "UPDATE_REQUIRED" if isinstance(error, httpx.HTTPStatusError) and error.response.status_code == 404 else "CHECK_FAILED"
            if not full:
                previous = self.results.get(device_id, {})
                # Do not erase a manual return diagnosis on the next heartbeat.
                reverse = previous.get("reverse_online")
                if reverse is False and not code:
                    code = previous.get("code", "")
            return self.store(peer, True, reverse, code, remote_receiving=data.get("receiving"))
