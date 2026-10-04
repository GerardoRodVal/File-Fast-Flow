import ipaddress
import socket
import threading
from zeroconf import ServiceBrowser, ServiceInfo, Zeroconf

SERVICE = "_devicedrop._tcp.local."


def local_ip() -> str:
    """Choose LAN route without sending Internet traffic."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("192.0.2.1", 9))
            return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"


class DiscoveryService:
    def __init__(self, runtime):
        self.runtime = runtime
        self.zc = None; self.browser = None; self.info = None
        self.lock = threading.Lock()
        self.peers = {}

    def start(self):
        self.zc = Zeroconf()
        device = self.runtime.device()
        self.info = ServiceInfo(SERVICE, f"{device['device_id']}.{SERVICE}",
            addresses=[socket.inet_aton(device["ip"])], port=device["port"],
            properties={k: str(device[k]) for k in ("device_id", "device_name", "platform", "port", "protocol_version")})
        self.zc.register_service(self.info)
        self.browser = ServiceBrowser(self.zc, SERVICE, listener=self)

    def add_service(self, zc, service_type, name):
        self.update_service(zc, service_type, name)

    def update_service(self, zc, service_type, name):
        info = zc.get_service_info(service_type, name, timeout=2000)
        if not info or not info.parsed_addresses():
            return
        props = {k.decode(): v.decode(errors="replace") for k, v in info.properties.items() if v}
        device_id = props.get("device_id")
        if not device_id or device_id == self.runtime.device_id or props.get("protocol_version") != "1":
            return
        try:
            from uuid import UUID
            UUID(device_id)
            address = info.parsed_addresses()[0]
            if not ipaddress.ip_address(address).is_private:
                return
            device = {**props, "ip": address, "port": info.port, "service": name, "online": True}
            with self.lock:
                self.peers[device_id] = device
            self.runtime.wake_checks()
        except (ValueError, OSError):
            return

    def remove_service(self, zc, service_type, name):
        with self.lock:
            for device_id, peer in self.peers.items():
                if peer["service"] == name:
                    peer["online"] = False
                    self.runtime.wake_checks()

    def snapshot(self):
        with self.lock:
            return [dict(p) for p in self.peers.values()]

    def stop(self):
        if self.browser:
            self.browser.cancel()
        if self.zc:
            if self.info:
                self.zc.unregister_service(self.info)
            self.zc.close()
