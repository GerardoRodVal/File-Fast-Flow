import asyncio


class EventBus:
    def __init__(self):
        self.queues: dict[asyncio.Queue, str] = {}
        self.listeners = []
        self.loop = None

    def emit(self, kind: str, peer: str = "", **data):
        event = {"type": kind, "protocol_version": 1, **data}
        for callback in tuple(self.listeners):
            callback(event)
        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self._deliver, event, peer)

    def _deliver(self, event, peer):
        for queue, owner in tuple(self.queues.items()):
            if peer and owner != peer:
                continue
            if queue.full():
                queue.get_nowait()
            queue.put_nowait({k: v for k, v in event.items() if k not in {"saved_path", "original_path"}})
