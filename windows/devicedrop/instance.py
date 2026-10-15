"""Keep one desktop instance per data folder and reactivate it on relaunch."""
import hashlib
from pathlib import Path
import time

from PySide6.QtCore import QObject, QLockFile, QThread, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from devicedrop.window_activation import grant_foreground_permission


class SingleInstance(QObject):
    activated = Signal()
    notification_requested = Signal(str, str)

    def __init__(self, root, parent=None):
        super().__init__(parent)
        root = Path(root).resolve(); root.mkdir(parents=True, exist_ok=True)
        key = hashlib.sha256(str(root).casefold().encode()).hexdigest()[:24]
        self.name = f"FileFastFlow-{key}"
        self.lock = QLockFile(str(root / "desktop.lock"))
        self.lock.setStaleLockTime(0)
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self.server.newConnection.connect(self.accept_connections)
        self.sockets = set()
        self.primary = False

    def start_or_activate(self, timeout_ms=5000, notification=None):
        deadline = time.monotonic() + timeout_ms / 1000
        while True:
            if self.lock.tryLock(0):
                self.primary = True
                QLocalServer.removeServer(self.name)
                if not self.server.listen(self.name):
                    self.close()
                    raise RuntimeError(f"No se pudo preparar la instancia: {self.server.errorString()}")
                return True
            if self.lock.error() != QLockFile.LockError.LockFailedError:
                raise RuntimeError("No se pudo acceder al control de la instancia de FileFastFlow.")
            socket = QLocalSocket()
            socket.connectToServer(self.name)
            if socket.waitForConnected(300):
                info = self.lock.getLockInfo()
                if info and info[0] > 0:
                    grant_foreground_permission(info[0])
                request = f"notification {notification[0]} {notification[1]}\n".encode("ascii") if notification else b"activate\n"
                socket.write(request)
                socket.flush()
                if socket.waitForReadyRead(1000) and bytes(socket.readAll()) == b"ok\n":
                    socket.disconnectFromServer()
                    return False
            socket.abort()
            if time.monotonic() >= deadline:
                raise RuntimeError("FileFastFlow ya está abierto, pero no responde. Espera a que termine de iniciar e inténtalo otra vez.")
            QThread.msleep(50)

    def accept_connections(self):
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            self.sockets.add(socket)
            socket.readyRead.connect(lambda s=socket: self.read_request(s))
            socket.disconnected.connect(lambda s=socket: self.release_socket(s))
            self.read_request(socket)

    def read_request(self, socket):
        if socket.canReadLine():
            request = bytes(socket.readLine(64))
            if request == b"activate\n":
                self.activated.emit()
                socket.write(b"ok\n"); socket.flush()
            elif request.startswith(b"notification "):
                from devicedrop.ui.receipt_notifications import parse_notification_url
                try:
                    _, action, transfer_id = request.decode("ascii").strip().split(" ")
                    action, transfer_id = parse_notification_url(f"filefastflow://{action}/{transfer_id}")
                except ValueError:
                    socket.disconnectFromServer(); return
                socket.write(b"ok\n"); socket.flush()
                self.notification_requested.emit(action, transfer_id)
            socket.disconnectFromServer()
        elif socket.bytesAvailable() > 64:
            socket.abort()

    def release_socket(self, socket):
        self.sockets.discard(socket); socket.deleteLater()

    def close(self):
        if self.primary:
            self.server.close()
            for socket in list(self.sockets):
                socket.abort()
            self.lock.unlock(); self.primary = False
