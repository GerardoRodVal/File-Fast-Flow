package devicedrop

import android.content.Context
import android.net.Uri
import android.os.Build
import android.provider.OpenableColumns
import androidx.room.Room
import devicedrop.database.*
import devicedrop.discovery.DiscoveryService
import devicedrop.network.*
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.*
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.sync.withPermit
import kotlinx.coroutines.channels.Channel
import okhttp3.*
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.toRequestBody
import okio.BufferedSink
import org.json.JSONObject
import java.io.File
import java.net.NetworkInterface
import java.security.KeyPairGenerator
import java.security.MessageDigest
import java.security.SecureRandom
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.TimeUnit

data class DropEvent(val type: String, val peer: String = "", val data: JSONObject = JSONObject())
data class Offer(val meta: Metadata, val peer: String, var status: String, val expires: Long)
data class PairWindow(val code: String, val token: String, val expires: Long, val qr: String)
data class PendingPair(val device: Device, val confirmation: String, val shared: String, val expires: Long)

class DropRepository(val context: Context, val port: Int = 45832) {
    val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    val database = Room.databaseBuilder(context, DropDatabase::class.java, "devicedrop.db").build()
    val dao = database.dao()
    val trusted = dao.observeTrusted().stateIn(scope, SharingStarted.Eagerly, emptyList())
    val history = dao.observeHistory().stateIn(scope, SharingStarted.Eagerly, emptyList())
    val events = MutableSharedFlow<DropEvent>(extraBufferCapacity = 256)
    val online = MutableStateFlow<Map<String, Boolean>>(emptyMap())
    val connectionReports = MutableStateFlow<Map<String, ConnectionReport>>(emptyMap())
    val checkingConnections = MutableStateFlow<Set<String>>(emptySet())
    private val connectionValidator = ConnectionValidator(port)
    private val connectionLocks = ConcurrentHashMap<String, Mutex>()
    private val checkRequested = Channel<Unit>(Channel.CONFLATED)
    val nearby = MutableStateFlow<List<Device>>(emptyList())
    val active = MutableStateFlow(false)
    val error = MutableStateFlow("")
    val name = MutableStateFlow(Build.MODEL.take(80))
    val receiving = MutableStateFlow(true)
    val ready = CompletableDeferred<Unit>()
    lateinit var deviceId: String
    private var publicKey = ""
    val folder = File(context.filesDir, "received").apply { mkdirs() }
    val offers = ConcurrentHashMap<String, Offer>()
    val cancelled = ConcurrentHashMap.newKeySet<String>()
    val uploads = ConcurrentHashMap.newKeySet<String>()
    private val calls = ConcurrentHashMap<String, Call>()
    private val jobs = ConcurrentHashMap<String, Job>()
    private val offerLock = Mutex()
    private val sendLimit = kotlinx.coroutines.sync.Semaphore(2)
    private var server: DropServer? = null
    private var discovery: DiscoveryService? = null
    private var heartbeat: Job? = null
    private var pairing: PairWindow? = null
    private val pendingPairs = mutableMapOf<String, PendingPair>()
    private val attempts = mutableMapOf<String, Pair<Int, Long>>()
    private val pairLock = Mutex()
    val client = OkHttpClient.Builder().connectTimeout(5, TimeUnit.SECONDS).readTimeout(120, TimeUnit.SECONDS)
        .writeTimeout(120, TimeUnit.SECONDS).retryOnConnectionFailure(false).build()

    init {
        scope.launch {
            try {
                deviceId = dao.setting("device_id") ?: UUID.randomUUID().toString().also { dao.setting(Setting("device_id", it)) }
                name.value = dao.setting("device_name") ?: Build.MODEL.take(80)
                receiving.value = dao.setting("allow_receive") != "false"
                publicKey = dao.setting("public_key") ?: run {
                    val keys = KeyPairGenerator.getInstance("EC").apply { initialize(256) }.generateKeyPair()
                    android.util.Base64.encodeToString(keys.public.encoded, android.util.Base64.NO_WRAP).also {
                        dao.setting(Setting("public_key", it))
                        dao.setting(Setting("identity_key", android.util.Base64.encodeToString(keys.private.encoded, android.util.Base64.NO_WRAP)))
                    }
                }
                dao.recover(); folder.listFiles()?.filter { it.name.endsWith(".devicedrop-part") }?.forEach { it.delete() }
                ready.complete(Unit)
            } catch (e: Exception) { error.value = "STORAGE_ERROR"; ready.completeExceptionally(e) }
        }
    }

    fun device(): Device = Device(deviceId, name.value, "android", lanIp(), port, publicKey = publicKey)
    fun lanIp(): String = try {
        NetworkInterface.getNetworkInterfaces().toList().flatMap { it.inetAddresses.toList() }
            .firstOrNull { !it.isLoopbackAddress && it.isSiteLocalAddress && it.hostAddress?.contains(':') == false }?.hostAddress ?: "127.0.0.1"
    } catch (_: Exception) { "127.0.0.1" }

    suspend fun start() {
        ready.await()
        if (active.value) return
        try {
            server = DropServer(this).also { it.start() }
            discovery = DiscoveryService(context, this).also { it.start() }
            heartbeat = scope.launch { heartbeatLoop() }
            active.value = true; error.value = ""
        } catch (_: Exception) { error.value = "SERVER_START_FAILED"; stop() }
    }

    suspend fun stop() {
        heartbeat?.cancelAndJoin(); heartbeat = null
        discovery?.stop(); discovery = null
        server?.stop(); server = null
        active.value = false
    }

    suspend fun rename(value: String) {
        require(value.trim().length in 1..80)
        name.value = value.trim(); dao.setting(Setting("device_name", name.value))
        if (active.value) { stop(); start() }
    }

    suspend fun authenticate(header: String?): TrustedDevice? {
        val token = header?.removePrefix("Bearer ") ?: return null
        if (token.length < 32) return null
        return dao.trusted().firstOrNull { MessageDigest.isEqual(it.token.toByteArray(), token.toByteArray()) }
    }

    private fun secret(): String {
        val bytes = ByteArray(32); SecureRandom().nextBytes(bytes)
        return android.util.Base64.encodeToString(bytes, android.util.Base64.NO_WRAP or android.util.Base64.URL_SAFE or android.util.Base64.NO_PADDING)
    }

    suspend fun openPairing(): PairWindow = pairLock.withLock {
        ready.await()
        val code = "%06d".format(SecureRandom().nextInt(1000000)); val token = secret()
        val qr = device().json().put("protocol", "devicedrop").put("version", 1).put("pairing_token", token).toString()
        PairWindow(code, token, System.currentTimeMillis() + 120000, qr).also { pairing = it }
    }

    suspend fun pairRequest(json: JSONObject, address: String): JSONObject = pairLock.withLock {
        val now = System.currentTimeMillis()
        attempts.entries.removeAll { it.value.second < now }
        val attempt = attempts[address] ?: (0 to now + 120000)
        if (attempt.first >= 5) throw ProtocolError("PAIRING_RATE_LIMIT", 429)
        attempts[address] = attempt.first + 1 to attempt.second
        val window = pairing ?: throw ProtocolError("PAIRING_EXPIRED", 410)
        if (now > window.expires) { pairing = null; throw ProtocolError("PAIRING_EXPIRED", 410) }
        val code = json.getString("code")
        if (!MessageDigest.isEqual(code.toByteArray(), window.code.toByteArray()) && !MessageDigest.isEqual(code.toByteArray(), window.token.toByteArray())) throw ProtocolError("PAIRING_INVALID", 403)
        val remote = Device.parse(json.getJSONObject("device")).copy(ip = address)
        if (remote.deviceId == deviceId) throw ProtocolError("PAIRING_SELF", 403)
        pendingPairs.entries.removeAll { it.value.expires < now }
        val id = UUID.randomUUID().toString(); val confirmation = secret(); val token = secret()
        pendingPairs[id] = PendingPair(remote, confirmation, token, now + 120000); pairing = null
        JSONObject().put("request_id", id).put("confirmation_token", confirmation).put("shared_token", token).put("device", device().json()).put("protocol_version", 1)
    }

    suspend fun pairConfirm(json: JSONObject): JSONObject = pairLock.withLock {
        val id = json.getString("request_id")
        val pending = pendingPairs[id] ?: throw ProtocolError("PAIRING_EXPIRED", 410)
        if (System.currentTimeMillis() > pending.expires) { pendingPairs.remove(id); throw ProtocolError("PAIRING_EXPIRED", 410) }
        if (!MessageDigest.isEqual(pending.confirmation.toByteArray(), json.getString("confirmation_token").toByteArray())) throw ProtocolError("PAIRING_INVALID", 403)
        trust(pending.device, pending.shared); pendingPairs.remove(id)
        JSONObject().put("status", "paired").put("protocol_version", 1)
    }

    suspend fun trust(device: Device, token: String) {
        val existing = dao.peer(device.deviceId)
        dao.trust(TrustedDevice(device.deviceId, device.name, device.platform, device.publicKey, token, device.ip, device.port,
            autoAccept = existing?.autoAccept ?: true, autoSync = existing?.autoSync ?: false))
        wakeConnections()
    }

    suspend fun pair(ip: String, port: Int, code: String) = withContext(Dispatchers.IO) {
        ready.await(); val base = endpoint(ip, port)
        val result = request(base + "/api/v1/pair/request", "POST", JSONObject().put("device", device().json()).put("code", code))
        request(base + "/api/v1/pair/confirm", "POST", JSONObject().put("request_id", result.getString("request_id")).put("confirmation_token", result.getString("confirmation_token")))
        trust(Device.parse(result.getJSONObject("device")).copy(ip = ip), result.getString("shared_token"))
        wakeConnections()
    }

    fun wakeConnections() { checkRequested.trySend(Unit) }

    private suspend fun recordConnection(peer: TrustedDevice, forward: Boolean, reverse: Boolean? = null,
        code: String = "", remoteReceiving: Boolean? = null): ConnectionReport {
        val report = ConnectionReport(peer.deviceId, peer.name, peer.ip, peer.port, forward, reverse, code, remoteReceiving, receiving.value)
        connectionReports.update { it + (peer.deviceId to report) }
        online.update { it + (peer.deviceId to forward) }
        if (forward) dao.location(peer.deviceId, peer.ip, peer.port, System.currentTimeMillis())
        return report
    }

    suspend fun observeConnection(peer: TrustedDevice, address: String, port: Int): TrustedDevice {
        endpoint(address, port)
        dao.location(peer.deviceId, address, port, peer.lastSeen)
        return peer.copy(ip = address, port = port)
    }

    suspend fun reverseConnection(peer: TrustedDevice, address: String, port: Int): Pair<Boolean, String> {
        val remote = observeConnection(peer, address, port)
        return try {
            val probe = connectionValidator.probe(remote)
            recordConnection(remote, true, true, remoteReceiving = probe.receiving)
            true to ""
        } catch (e: CancellationException) { throw e }
        catch (e: Exception) {
            val code = connectionError(e)
            recordConnection(remote, false, true, code)
            false to code
        }
    }

    suspend fun validateConnection(id: String, full: Boolean = true, ipOverride: String? = null, portOverride: Int? = null): ConnectionReport = withContext(Dispatchers.IO) {
        ready.await()
        connectionLocks.getOrPut(id) { Mutex() }.withLock {
            if (full) checkingConnections.update { it + id }
            try {
                val original = dao.peer(id) ?: throw ProtocolError("UNAUTHORIZED_DEVICE", 403)
                val candidates = if (ipOverride != null) listOf(ipOverride to (portOverride ?: original.port)) else
                    (nearby.value.filter { it.deviceId == id }.map { it.ip to it.port } + (original.ip to original.port)).distinct().take(4)
                var peer = original
                var probe: ConnectionProbe? = null
                var code = "UNREACHABLE"
                for ((address, port) in candidates) {
                    peer = original.copy(ip = address, port = port)
                    try { probe = connectionValidator.probe(peer); break }
                    catch (e: CancellationException) { throw e }
                    catch (e: Exception) { code = connectionError(e) }
                }
                if (probe == null) return@withLock recordConnection(peer, false, code = code)
                dao.location(id, peer.ip, peer.port, System.currentTimeMillis())
                var reverse: Boolean? = null
                code = if (probe.legacy) "UPDATE_REQUIRED" else ""
                if (full && !probe.legacy) {
                    try {
                        val result = connectionValidator.checkReturn(peer, deviceId)
                        reverse = result.first; code = if (reverse == false) result.second else ""
                    } catch (e: CancellationException) { throw e }
                    catch (e: Exception) { code = if (e is ProtocolError && e.status == 404) "UPDATE_REQUIRED" else "CHECK_FAILED" }
                }
                if (!full) {
                    val previous = connectionReports.value[id]
                    reverse = previous?.reverseOnline
                    if (reverse == false && code.isEmpty()) code = previous?.code ?: ""
                }
                recordConnection(peer, true, reverse, code, probe.receiving)
            } finally { if (full) checkingConnections.update { it - id } }
        }
    }

    fun requireReception() { if (!receiving.value) throw ProtocolError("RECEPTION_PAUSED", 503) }

    suspend fun offer(meta: Metadata, peer: TrustedDevice): JSONObject = offerLock.withLock {
        requireReception()
        if (meta.sender != peer.deviceId) throw ProtocolError("UNAUTHORIZED_DEVICE", 403)
        val previous = dao.transfer(meta.transferId)
        if (previous != null && (previous.sourceDevice != peer.deviceId || previous.sha256 != meta.sha256 || previous.size != meta.size)) throw ProtocolError("TRANSFER_CONFLICT", 409)
        if (previous?.status == "completed") return@withLock JSONObject().put("status", "completed").put("sha256", meta.sha256).put("protocol_version", 1)
        offers.entries.removeAll { it.value.expires < System.currentTimeMillis() && it.key !in uploads }
        if (folder.usableSpace < meta.size + offers.filterKeys { it != meta.transferId }.values.sumOf { it.meta.size } + 1024 * 1024) throw ProtocolError("NOT_ENOUGH_SPACE", 507)
        offers[meta.transferId]?.let {
            if (it.meta != meta) throw ProtocolError("TRANSFER_CONFLICT", 409)
            return@withLock offerStatus(meta.transferId, peer)
        }
        if (offers.size >= 64) throw ProtocolError("TOO_MANY_TRANSFERS", 429)
        cancelled.remove(meta.transferId)
        val status = if (peer.autoAccept) "accepted" else "pending"
        offers[meta.transferId] = Offer(meta, peer.deviceId, status, System.currentTimeMillis() + 120000)
        dao.save(Transfer(meta.transferId, "incoming", meta.filename, meta.size, meta.sha256, meta.mimeType, meta.sender, deviceId, meta.origin, meta.batch))
        if (status == "pending") events.emit(DropEvent("transfer_offer", peer.deviceId, meta.json().put("sender_name", peer.name)))
        JSONObject().put("status", status).put("protocol_version", 1)
    }

    fun offerStatus(id: String, peer: TrustedDevice): JSONObject {
        val offer = offers[id] ?: throw ProtocolError("OFFER_EXPIRED", 410)
        if (offer.peer != peer.deviceId || offer.expires < System.currentTimeMillis()) throw ProtocolError("OFFER_EXPIRED", 410)
        if (offer.status == "rejected") throw ProtocolError("TRANSFER_REJECTED", 403)
        return JSONObject().put("status", offer.status).put("protocol_version", 1)
    }

    suspend fun approve(id: String, accepted: Boolean) = offerLock.withLock { offers[id]?.status = if (accepted) "accepted" else "rejected" }

    suspend fun validateUpload(meta: Metadata, peer: TrustedDevice) = offerLock.withLock {
        requireReception()
        if (offerStatus(meta.transferId, peer).getString("status") != "accepted" || offers[meta.transferId]?.meta != meta) throw ProtocolError("OFFER_REQUIRED", 403)
        if (!uploads.add(meta.transferId)) throw ProtocolError("TRANSFER_BUSY", 409)
    }

    suspend fun progress(meta: Metadata, peer: String, status: String, done: Long, speed: Double = 0.0) {
        dao.progress(meta.transferId, status, done, speed)
        val type = when (status) { "completed" -> "transfer_completed"; "verifying" -> "transfer_verifying"; "connecting" -> "transfer_started"; else -> "transfer_progress" }
        events.emit(DropEvent(type, peer, meta.json().put("bytes_done", done).put("speed", speed).put("status", status).put("progress", if (meta.size == 0L) 100 else done * 100 / meta.size)))
    }

    fun checkCancelled(id: String) { if (id in cancelled) throw ProtocolError("TRANSFER_CANCELLED", 409) }

    suspend fun cancel(id: String) {
        cancelled.add(id); calls[id]?.cancel(); jobs[id]?.cancel(); dao.progress(id, "cancelled", 0, error = "TRANSFER_CANCELLED")
        events.emit(DropEvent("transfer_cancelled", data = JSONObject().put("transfer_id", id).put("protocol_version", 1)))
    }

    suspend fun received(meta: Metadata, dest: File, peer: TrustedDevice) {
        dao.transfer(meta.transferId)?.let { dao.save(it.copy(status = "completed", savedPath = dest.absolutePath, bytesDone = meta.size, completedAt = System.currentTimeMillis())) }
        dao.processed(ProcessedFile(meta.origin, meta.sha256, dest.absolutePath, meta.transferId))
        offers.remove(meta.transferId)
        events.emit(DropEvent("transfer_completed", peer.deviceId, meta.json().put("saved_path", dest.absolutePath).put("sender_name", peer.name)))
    }

    fun request(url: String, method: String = "GET", json: JSONObject? = null, token: String? = null): JSONObject {
        val builder = Request.Builder().url(url)
        if (token != null) builder.header("Authorization", "Bearer $token")
        builder.method(method, if (method in setOf("POST", "PUT")) (json ?: JSONObject()).toString().toRequestBody("application/json".toMediaType()) else null)
        client.newCall(builder.build()).execute().use { response ->
            val text = response.body?.string() ?: "{}"; val result = try { JSONObject(text) } catch (_: Exception) { JSONObject() }
            if (!response.isSuccessful) throw ProtocolError(result.optString("error", "NETWORK_ERROR"), response.code)
            return result
        }
    }

    fun send(uris: List<Uri>, devices: List<String>) {
        val batch = UUID.randomUUID().toString()
        uris.forEach { uri -> devices.forEach { id ->
            val tid = UUID.randomUUID().toString()
            jobs[tid] = scope.launch { sendFile(uri, id, batch, tid) }
        } }
    }

    private suspend fun sendFile(uri: Uri, id: String, batch: String, tid: String) {
        var staged: File? = null
        try {
            sendLimit.acquire()
            try {
                ready.await(); val peer = dao.peer(id) ?: throw ProtocolError("UNAUTHORIZED_DEVICE", 401)
                val originalName = if (uri.scheme == "file") File(uri.path.orEmpty()).name else
                    (try { context.contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { if (it.moveToFirst()) it.getString(0) else null } } catch (_: Exception) { null }) ?: uri.lastPathSegment ?: "archivo"
                safeName(originalName)
                val cache = File(context.cacheDir, "$tid.devicedrop-part"); staged = cache
                var total = 0L
                context.contentResolver.openInputStream(uri)?.use { source -> cache.outputStream().use { output ->
                    val bytes = ByteArray(1024 * 1024)
                    while (true) {
                        currentCoroutineContext().ensureActive(); checkCancelled(tid)
                        val n = source.read(bytes); if (n < 0) break
                        total += n
                        if (total > 16L * 1024 * 1024 * 1024 || cache.parentFile!!.usableSpace < n + 1024 * 1024) throw ProtocolError("NOT_ENOUGH_SPACE", 507)
                        output.write(bytes, 0, n)
                    }
                } } ?: throw ProtocolError("FILE_NOT_FOUND", 404)
                val meta = Metadata(tid, originalName, total, hashFile(cache), context.contentResolver.getType(uri) ?: "application/octet-stream", deviceId, deviceId, batch)
                dao.save(Transfer(tid, "outgoing", originalName, total, meta.sha256, meta.mimeType, deviceId, id, deviceId, batch, originalPath = uri.toString()))
                val base = endpoint(peer.ip, peer.port)
                for (attempt in 0..3) {
                    currentCoroutineContext().ensureActive(); checkCancelled(tid); progress(meta, id, "connecting", 0)
                    try {
                        var status = request(base + "/api/v1/offers", "POST", meta.json(), peer.token).getString("status")
                        val deadline = System.currentTimeMillis() + 120000
                        while (status == "pending") {
                            if (System.currentTimeMillis() > deadline) throw ProtocolError("OFFER_EXPIRED", 410)
                            delay(1000); checkCancelled(tid)
                            status = request(base + "/api/v1/offers/$tid", token = peer.token).getString("status")
                        }
                        if (status == "completed") { progress(meta, id, "completed", total); break }
                        val fileBody = object: RequestBody() {
                            override fun contentType() = "application/octet-stream".toMediaType()
                            override fun contentLength() = total
                            override fun writeTo(sink: BufferedSink) {
                                var done = 0L; val start = System.nanoTime(); var last = 0L
                                cache.inputStream().use { input ->
                                    val bytes = ByteArray(1024 * 1024)
                                    while (true) {
                                        checkCancelled(tid); val n = input.read(bytes); if (n < 0) break
                                        sink.write(bytes, 0, n); done += n
                                        val now = System.nanoTime()
                                        if (now - last > 150000000) { last = now; runBlocking { progress(meta, id, "transferring", done, done * 1e9 / (now - start).coerceAtLeast(1)) } }
                                    }
                                }
                                runBlocking { progress(meta, id, "verifying", done) }
                            }
                        }
                        val body = MultipartBody.Builder().setType(MultipartBody.FORM).addFormDataPart("metadata", meta.json().toString()).addFormDataPart("file", "payload", fileBody).build()
                        val call = client.newCall(Request.Builder().url(base + "/api/v1/files").header("Authorization", "Bearer ${peer.token}").post(body).build()); calls[tid] = call
                        call.execute().use { response ->
                            val result = JSONObject(response.body?.string() ?: "{}")
                            if (!response.isSuccessful) throw ProtocolError(result.optString("error", "TRANSFER_FAILED"), response.code)
                            if (result.optString("sha256") != meta.sha256) throw ProtocolError("HASH_MISMATCH")
                        }
                        progress(meta, id, "completed", total)
                        dao.transfer(tid)?.let { dao.save(it.copy(status = "completed", bytesDone = total, completedAt = System.currentTimeMillis())) }
                        break
                    } catch (e: Exception) {
                        if (e is CancellationException || e is ProtocolError && (e.status < 500 || e.status == 507) || attempt == 3) throw e
                        delay(listOf(1000L, 3000L, 7000L)[attempt])
                    } finally { calls.remove(tid) }
                }
            } finally { sendLimit.release() }
        } catch (e: Exception) {
            val code = if (e is CancellationException || tid in cancelled) "TRANSFER_CANCELLED" else (e as? ProtocolError)?.code
                ?: if (e is IllegalArgumentException && e.message in setOf("INVALID_FILE", "INVALID_LAN_ADDRESS", "INVALID_SIZE")) e.message!! else "NETWORK_ERROR"
            android.util.Log.e("DeviceDrop", "send_failed ${e.javaClass.simpleName}", e)
            withContext(NonCancellable) { dao.progress(tid, if (code == "TRANSFER_CANCELLED") "cancelled" else "failed", 0, error = code); error.value = code }
        } finally { staged?.delete(); calls.remove(tid); jobs.remove(tid) }
    }

    private suspend fun heartbeatLoop() {
        val limit = kotlinx.coroutines.sync.Semaphore(4)
        while (currentCoroutineContext().isActive) {
            coroutineScope {
                dao.trusted().map { peer -> async {
                    limit.withPermit { try { validateConnection(peer.deviceId, full = false) } catch (e: CancellationException) { throw e } catch (_: Exception) {} }
                } }.awaitAll()
            }
            withTimeoutOrNull(12000) { checkRequested.receive() }
        }
    }
}
