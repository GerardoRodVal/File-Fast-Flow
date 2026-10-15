"""Persist per-device delivery state; reuse authenticated file transfers."""
import asyncio
from pathlib import Path
import time

from .local_build import artifact_valid


class FleetUpdates:
    def __init__(self, runtime):
        self.runtime = runtime
        self.task = None
        self.lock = asyncio.Lock()
        states = runtime.db.setting("fleet_states", {})
        if any(state.get("status") == "sending" for state in states.values()):
            for state in states.values():
                if state.get("status") == "sending":
                    state["status"] = "pending"
            runtime.db.set_setting("fleet_states", states)

    def status(self, device_id, **values):
        with self.runtime.db.lock:
            states = self.runtime.db.setting("fleet_states", {})
            states[device_id] = {**states.get(device_id, {}), **values}
            self.runtime.db.set_setting("fleet_states", states)

    def queue(self, manifest):
        self.runtime.db.set_setting("fleet_manifest", manifest)
        self.runtime.db.set_setting("fleet_distribution_enabled", True)
        for peer in self.runtime.db.trusted():
            if self.runtime.db.setting("fleet_manifest", {}).get("revision") != manifest["revision"]:
                return
            states = self.runtime.db.setting("fleet_states", {})
            previous = states.get(peer["device_id"], {})
            if previous.get("revision") != manifest["revision"] or previous.get("status") == "failed":
                self.status(peer["device_id"], revision=manifest["revision"], status="pending", error="", retry_at=0)
        self.runtime.wake_checks()

    async def deliver_pending(self):
        async with self.lock:
            await self._deliver_pending()

    async def _deliver_pending(self):
        manifest = self.runtime.db.setting("fleet_manifest", {})
        if not self.runtime.db.setting("fleet_distribution_enabled", False) or not manifest:
            return
        for peer in self.runtime.db.trusted():
            if self.runtime.db.setting("fleet_manifest", {}).get("revision") != manifest["revision"]:
                return
            device_id = peer["device_id"]
            previous = self.runtime.db.setting("fleet_states", {}).get(device_id, {})
            if previous.get("revision") != manifest["revision"]:
                self.status(device_id, revision=manifest["revision"], status="pending", retry_at=0)
                previous = self.runtime.db.setting("fleet_states", {})[device_id]
            if self.runtime.connections.results.get(device_id, {}).get("remote_revision") == manifest["revision"]:
                self.status(device_id, status="installed", error=""); continue
            if previous.get("status") in {"received", "installed"} or previous.get("retry_at", 0) > time.time() or not self.runtime.online.get(device_id):
                continue
            artifact = manifest["artifacts"].get(peer["platform"])
            if artifact is None:
                self.status(device_id, status="failed", error="Plataforma sin instalador.", retry_at=time.time() + 60); continue
            if not await asyncio.to_thread(artifact_valid, artifact):
                self.status(device_id, status="failed", error="El instalador cambió o ya no existe. Prepara otra compilación.", retry_at=time.time() + 60); continue
            self.status(device_id, status="sending", error="")
            success = await self.runtime.sender.send(Path(artifact["path"]), device_id,
                update_revision=manifest["revision"], app_version=manifest["version"])
            if asyncio.current_task().cancelling():
                self.status(device_id, status="pending"); return
            if self.runtime.db.setting("fleet_manifest", {}).get("revision") == manifest["revision"]:
                self.status(device_id, status="received" if success else "failed", error="" if success else "No se pudo enviar. Se reintentará al conectar.", retry_at=time.time() + 30)
