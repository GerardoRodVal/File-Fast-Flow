import threading
import time
import os
from pathlib import Path
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer


def readable_without_writer(path: Path) -> bool:
    if os.name != "nt":
        with path.open("rb"):
            return True
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                  wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateFileW(str(path), 0x80000000, 0, None, 3, 0x80, None)
    if handle == ctypes.c_void_p(-1).value:
        return False
    kernel.CloseHandle(handle)
    return True


def wait_stable(path: Path, stop: threading.Event, interval: float = 1, samples: int = 3, timeout: float = 300) -> bool:
    previous = None; equal = 0; deadline = time.monotonic() + timeout
    while not stop.wait(interval) and time.monotonic() < deadline:
        try:
            stat = path.stat()
            current = stat.st_size, stat.st_mtime_ns
            if not readable_without_writer(path):
                equal = 0
                continue
            equal = equal + 1 if current == previous else 0
            if equal >= samples:
                return True
            previous = current
        except (OSError, PermissionError):
            equal = 0
    return False


class FolderWatcher(FileSystemEventHandler):
    def __init__(self, folder: Path, on_created, on_event=None):
        self.folder, self._callback, self.on_event = folder.resolve(), on_created, on_event
        self.stop_event = threading.Event(); self.pending = set(); self.lock = threading.Lock()
        self.workers = set(); self.observer = Observer()

    def start(self):
        self.folder.mkdir(parents=True, exist_ok=True)
        self.observer.schedule(self, str(self.folder), recursive=True)
        self.observer.start()

    def on_any_event(self, event):
        if self.on_event and event.event_type in {"created", "modified", "moved", "deleted"}:
            self.on_event(event.event_type, event.src_path)

    def on_created(self, event):
        if event.is_directory or event.src_path.endswith(".devicedrop-part"):
            return
        path = Path(event.src_path).resolve()
        if not path.is_relative_to(self.folder):
            return
        with self.lock:
            if path in self.pending:
                return
            self.pending.add(path)
        def work():
            try:
                if wait_stable(path, self.stop_event):
                    self.on_created_callback(path)
            finally:
                with self.lock:
                    self.pending.discard(path); self.workers.discard(threading.current_thread())
        thread = threading.Thread(target=work, name="folder-stability", daemon=True)
        with self.lock:
            self.workers.add(thread)
        thread.start()

    # Keep watchdog handler method distinct from callback.
    @property
    def on_created_callback(self):
        return self._callback

    def stop(self):
        self.stop_event.set(); self.observer.stop(); self.observer.join(timeout=5)
        for thread in tuple(self.workers):
            thread.join(timeout=2)
