package devicedrop.discovery

import android.content.Context
import android.net.nsd.NsdManager
import android.net.nsd.NsdServiceInfo
import android.net.wifi.WifiManager
import devicedrop.DropRepository
import devicedrop.database.SeenDevice
import devicedrop.network.Device
import kotlinx.coroutines.launch
import java.util.concurrent.ConcurrentHashMap

class DiscoveryService(context: Context, private val repo: DropRepository) {
    private val nsd = context.getSystemService(Context.NSD_SERVICE) as NsdManager
    private val wifi = context.applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager
    private val peers = ConcurrentHashMap<String, Device>()
    private val lock = wifi.createMulticastLock("DeviceDrop").apply { setReferenceCounted(false) }
    private var stopped = false
    private val registration = object: NsdManager.RegistrationListener {
        override fun onServiceRegistered(info: NsdServiceInfo) {}
        override fun onRegistrationFailed(info: NsdServiceInfo, code: Int) { repo.error.value = "DISCOVERY_UNAVAILABLE" }
        override fun onServiceUnregistered(info: NsdServiceInfo) {}
        override fun onUnregistrationFailed(info: NsdServiceInfo, code: Int) {}
    }
    private val listener = object: NsdManager.DiscoveryListener {
        override fun onDiscoveryStarted(type: String) {}
        override fun onDiscoveryStopped(type: String) {}
        override fun onStartDiscoveryFailed(type: String, code: Int) { repo.error.value = "DISCOVERY_UNAVAILABLE" }
        override fun onStopDiscoveryFailed(type: String, code: Int) {}
        override fun onServiceLost(info: NsdServiceInfo) {
            peers.remove(info.serviceName)
            repo.nearby.value = peers.values.toList()
            repo.wakeConnections()
        }
        @Suppress("DEPRECATION")
        override fun onServiceFound(info: NsdServiceInfo) {
            if (stopped || !info.serviceType.contains("_devicedrop._tcp")) return
            nsd.resolveService(info, object: NsdManager.ResolveListener {
                override fun onResolveFailed(service: NsdServiceInfo, code: Int) {}
                override fun onServiceResolved(service: NsdServiceInfo) {
                    if (stopped) return
                    try {
                        val values = service.attributes.mapValues { it.value.toString(Charsets.UTF_8) }
                        if (values["protocol_version"] != "1" || values["device_id"] == repo.deviceId) return
                        val id = values["device_id"] ?: return; java.util.UUID.fromString(id)
                        val device = Device(id, values["device_name"] ?: service.serviceName, values["platform"] ?: "windows", service.host.hostAddress ?: return, service.port)
                        devicedrop.network.endpoint(device.ip, device.port)
                        peers[service.serviceName] = device; repo.nearby.value = peers.values.toList()
                        repo.scope.launch { repo.dao.seen(SeenDevice(id, device.json().toString(), System.currentTimeMillis())); repo.wakeConnections() }
                    } catch (_: Exception) {}
                }
            })
        }
    }
    fun start() {
        lock.acquire()
        val device = repo.device()
        val service = NsdServiceInfo().apply {
            serviceName = device.deviceId; serviceType = "_devicedrop._tcp."; port = device.port
            setAttribute("device_id", device.deviceId); setAttribute("device_name", device.name)
            setAttribute("platform", "android"); setAttribute("port", device.port.toString()); setAttribute("protocol_version", "1")
        }
        nsd.registerService(service, NsdManager.PROTOCOL_DNS_SD, registration)
        nsd.discoverServices("_devicedrop._tcp.", NsdManager.PROTOCOL_DNS_SD, listener)
    }
    fun stop() {
        stopped = true
        try { nsd.stopServiceDiscovery(listener) } catch (_: Exception) {}
        try { nsd.unregisterService(registration) } catch (_: Exception) {}
        if (lock.isHeld) lock.release()
    }
}
