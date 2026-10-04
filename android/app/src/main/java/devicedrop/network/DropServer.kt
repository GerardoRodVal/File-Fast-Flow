package devicedrop.network

import devicedrop.DropRepository
import devicedrop.database.TrustedDevice
import io.ktor.http.*
import io.ktor.server.application.*
import io.ktor.server.cio.*
import io.ktor.server.engine.*
import io.ktor.server.request.*
import io.ktor.server.response.*
import io.ktor.server.routing.*
import io.ktor.server.websocket.*
import io.ktor.utils.io.*
import io.ktor.websocket.*
import kotlinx.coroutines.*
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.filter
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.FileOutputStream
import java.security.MessageDigest
import java.nio.file.Files

class DropServer(private val repo: DropRepository) {
    private val server = embeddedServer(CIO, host = "0.0.0.0", port = repo.port) {
        install(WebSockets)
        routing {
            get("/api/v1/device") { safe(call) { call.reply(repo.device().json()) } }
            get("/api/v1/ping") { safe(call) { call.reply(JSONObject().put("status", "online").put("device_id", repo.deviceId).put("protocol_version", 1)) } }
            get("/api/v1/connection") { safe(call) {
                val peer = call.peer()
                call.request.headers["X-DeviceDrop-Port"]?.let { repo.observeConnection(peer, call.request.local.remoteHost, it.toInt()) }
                call.reply(JSONObject().put("status", "online").put("device_id", repo.deviceId).put("protocol_version", 1).put("receiving", repo.receiving.value))
            } }
            post("/api/v1/connection/check") { safe(call) {
                val peer = call.peer(); val data = call.smallJson()
                if (data.optString("device_id") != peer.deviceId) throw ProtocolError("UNAUTHORIZED_DEVICE", 403)
                if (data.optInt("protocol_version") != 1 || data.opt("port") !is Int || data.getInt("port") !in 45000..45999) throw ProtocolError("INVALID_REQUEST")
                val result = repo.reverseConnection(peer, call.request.local.remoteHost, data.getInt("port"))
                call.reply(JSONObject().put("status", "online").put("device_id", repo.deviceId).put("protocol_version", 1)
                    .put("reverse_online", result.first).put("reverse_error", result.second))
            } }
            post("/api/v1/pair/request") { safe(call) { call.reply(repo.pairRequest(call.smallJson(), call.request.local.remoteHost)) } }
            post("/api/v1/pair/confirm") { safe(call) { call.reply(repo.pairConfirm(call.smallJson())) } }
            get("/api/v1/devices") { safe(call) {
                val peer = call.peer()
                call.reply(JSONObject().put("devices", JSONArray().put(JSONObject().put("device_id", peer.deviceId).put("name", peer.name).put("platform", peer.platform))).put("protocol_version", 1))
            } }
            post("/api/v1/offers") { safe(call) { val peer = call.peer(); call.reply(repo.offer(Metadata.parse(call.smallJson()), peer)) } }
            get("/api/v1/offers/{id}") { safe(call) { call.reply(repo.offerStatus(call.parameters["id"]!!, call.peer())) } }
            post("/api/v1/files") { safe(call) { val peer = call.peer(); repo.requireReception(); call.reply(receive(call, peer)) } }
            get("/api/v1/files/{id}") { safe(call) {
                val peer = call.peer(); val transfer = repo.dao.transfer(call.parameters["id"]!!) ?: throw ProtocolError("FILE_NOT_FOUND", 404)
                if (peer.deviceId !in setOf(transfer.sourceDevice, transfer.destinationDevice)) throw ProtocolError("UNAUTHORIZED_DEVICE", 403)
                call.reply(JSONObject().put("transfer_id", transfer.transferId).put("filename", transfer.filename).put("sha256", transfer.sha256).put("size", transfer.size).put("status", transfer.status).put("protocol_version", 1))
            } }
            get("/api/v1/transfers") { safe(call) {
                val peer = call.peer(); val array = JSONArray()
                repo.dao.history().filter { peer.deviceId in setOf(it.sourceDevice, it.destinationDevice) }.forEach {
                    array.put(JSONObject().put("transfer_id", it.transferId).put("filename", it.filename).put("size", it.size).put("status", it.status).put("sha256", it.sha256))
                }
                call.reply(JSONObject().put("transfers", array).put("protocol_version", 1))
            } }
            delete("/api/v1/transfers/{id}") { safe(call) {
                val peer = call.peer(); val id = call.parameters["id"]!!
                val transfer = repo.dao.transfer(id) ?: throw ProtocolError("FILE_NOT_FOUND", 404)
                if (peer.deviceId !in setOf(transfer.sourceDevice, transfer.destinationDevice)) throw ProtocolError("UNAUTHORIZED_DEVICE", 403)
                repo.cancel(id); call.reply(JSONObject().put("status", "cancelled").put("protocol_version", 1))
            } }
            webSocket("/ws") {
                val peer = repo.authenticate(call.request.headers["Authorization"])
                if (peer == null) { close(CloseReason(CloseReason.Codes.VIOLATED_POLICY, "UNAUTHORIZED_DEVICE")); return@webSocket }
                val beats = launch { while (isActive) { delay(15000); send(JSONObject().put("type", "heartbeat").put("protocol_version", 1).toString()) } }
                try {
                    repo.events.filter { it.peer == peer.deviceId }.collect { event ->
                        val data = JSONObject(event.data.toString()); data.remove("saved_path")
                        data.put("type", event.type).put("protocol_version", 1); send(data.toString())
                    }
                } finally { beats.cancel() }
            }
        }
    }

    fun start() { server.start(wait = false) }
    fun stop() { server.stop(500, 3000) }

    private suspend fun ApplicationCall.peer(): TrustedDevice = repo.authenticate(request.headers["Authorization"]) ?: throw ProtocolError("UNAUTHORIZED_DEVICE", 401)
    private suspend fun ApplicationCall.reply(json: JSONObject, status: Int = 200) = respondText(json.toString(), ContentType.Application.Json, HttpStatusCode.fromValue(status))
    private suspend fun ApplicationCall.smallJson(): JSONObject {
        val channel = receiveChannel(); val buffer = ByteArray(4096); val bytes = java.io.ByteArrayOutputStream()
        while (true) { val n = channel.readAvailable(buffer); if (n < 0) break; if (bytes.size() + n > 32768) throw ProtocolError("INVALID_REQUEST", 413); bytes.write(buffer, 0, n) }
        return JSONObject(bytes.toString("UTF-8"))
    }
    private suspend fun safe(call: ApplicationCall, action: suspend () -> Unit) {
        try { withContext(Dispatchers.IO) { action() } }
        catch (e: CancellationException) { throw e }
        catch (e: Exception) {
            val code = (e as? ProtocolError)?.code ?: if (e is IllegalArgumentException || e is org.json.JSONException) "INVALID_REQUEST" else "TRANSFER_FAILED"
            call.reply(JSONObject().put("error", code).put("protocol_version", 1), (e as? ProtocolError)?.status ?: 400)
        }
    }

    private suspend fun receive(call: ApplicationCall, peer: TrustedDevice): JSONObject {
        // Parse the restricted v1 multipart shape incrementally. No FormItem can
        // allocate an attacker-controlled multi-GB metadata string.
        val type = ContentType.parse(call.request.headers["Content-Type"] ?: "")
        if (!type.match(ContentType.MultiPart.FormData)) throw ProtocolError("INVALID_MULTIPART")
        val boundary = type.parameter("boundary") ?: throw ProtocolError("INVALID_MULTIPART")
        if (boundary.length !in 1..200 || boundary.any { it == '\r' || it == '\n' }) throw ProtocolError("INVALID_MULTIPART")
        val reader = MultipartReader(call.receiveChannel())
        var meta: Metadata? = null; var temp: File? = null; var claimed = false
        try {
            if (reader.line(256) != "--$boundary") throw ProtocolError("INVALID_MULTIPART")
            val first = reader.headers()
            if (!first.contains("name=\"metadata\"")) throw ProtocolError("INVALID_MULTIPART")
            val metadata = java.io.ByteArrayOutputStream()
            val more = reader.part(boundary) { bytes, count ->
                if (metadata.size() + count > 16384) throw ProtocolError("INVALID_METADATA")
                metadata.write(bytes, 0, count)
            }
            if (!more) throw ProtocolError("INVALID_MULTIPART")
            meta = Metadata.parse(JSONObject(metadata.toString("UTF-8")))
            repo.validateUpload(meta, peer)
            claimed = true
            if (!reader.headers().contains("name=\"file\"")) throw ProtocolError("INVALID_MULTIPART")
            val partial = File(repo.folder, ".${meta.transferId}.devicedrop-part")
            if (!partial.createNewFile()) throw ProtocolError("TRANSFER_BUSY", 409)
            temp = partial
            val hash = MessageDigest.getInstance("SHA-256"); var total = 0L; val start = System.nanoTime(); var last = 0L
            repo.progress(meta, peer.deviceId, "transferring", 0)
            FileOutputStream(temp).use { output ->
                val extra = reader.part(boundary) { bytes, count ->
                    repo.checkCancelled(meta.transferId)
                    total += count
                    if (total > meta.size) throw ProtocolError("SIZE_MISMATCH")
                    output.write(bytes, 0, count); hash.update(bytes, 0, count)
                    val now = System.nanoTime()
                    if (now - last >= 150000000) { last = now; repo.progress(meta, peer.deviceId, "transferring", total, total * 1e9 / (now - start).coerceAtLeast(1)) }
                }
                if (extra || total != meta.size) throw ProtocolError("SIZE_MISMATCH")
                output.fd.sync()
            }
            repo.progress(meta, peer.deviceId, "verifying", total)
            val digest = hash.digest().joinToString("") { "%02x".format(it) }
            if (digest != meta.sha256) throw ProtocolError("TRANSFER_CORRUPTED")
            repo.checkCancelled(meta.transferId)
            val destination = publish(temp, meta.filename); temp = null
            repo.received(meta, destination, peer)
            return JSONObject().put("status", "completed").put("transfer_id", meta.transferId).put("sha256", digest).put("filename", destination.name).put("protocol_version", 1)
        } catch (e: Exception) {
            if (claimed) meta?.let {
                val code = (e as? ProtocolError)?.code ?: "NETWORK_ERROR"
                withContext(NonCancellable) { repo.dao.progress(it.transferId, if (code == "TRANSFER_CANCELLED") "cancelled" else "failed", 0, error = code) }
            }
            throw e
        } finally { temp?.delete(); if (claimed) meta?.let { repo.uploads.remove(it.transferId) } }
    }

    private fun publish(temp: File, name: String): File {
        val source = File(safeName(name)); val stem = source.nameWithoutExtension; val ext = source.extension.let { if (it.isEmpty()) "" else ".$it" }
        for (index in 0..9999) {
            val destination = File(repo.folder, if (index == 0) name else "$stem ($index)$ext")
            try { Files.move(temp.toPath(), destination.toPath()); return destination }
            catch (_: java.nio.file.FileAlreadyExistsException) { }
        }
        throw ProtocolError("TOO_MANY_COLLISIONS", 409)
    }
}

/** Bounded streaming MIME parser for exactly the two v1 parts. */
class MultipartReader(private val channel: ByteReadChannel) {
    private val buffer = ByteArray(64 * 1024)
    private var pos = 0; private var length = 0
    private suspend fun byte(): Int {
        if (pos == length) { length = channel.readAvailable(buffer); pos = 0; if (length < 0) return -1; if (length == 0) return byte() }
        return buffer[pos++].toInt() and 255
    }
    suspend fun line(limit: Int = 8192): String {
        val out = java.io.ByteArrayOutputStream()
        while (true) {
            val value = byte(); if (value < 0) throw ProtocolError("INVALID_MULTIPART")
            if (value == 13) { if (byte() != 10) throw ProtocolError("INVALID_MULTIPART"); return out.toString("UTF-8") }
            if (out.size() >= limit) throw ProtocolError("INVALID_MULTIPART")
            out.write(value)
        }
    }
    suspend fun headers(): String {
        val out = StringBuilder()
        repeat(16) { val line = line(4096); if (line.isEmpty()) return out.toString(); out.append(line).append('\n'); if (out.length > 8192) throw ProtocolError("INVALID_MULTIPART") }
        throw ProtocolError("INVALID_MULTIPART")
    }
    suspend fun part(boundary: String, write: suspend (ByteArray, Int) -> Unit): Boolean {
        val marker = "\r\n--$boundary".toByteArray(); val pending = ByteArray(marker.size); var matched = 0
        val out = ByteArray(64 * 1024); var used = 0
        suspend fun emit(value: Int) { out[used++] = value.toByte(); if (used == out.size) { write(out, used); used = 0 } }
        while (true) {
            val value = byte(); if (value < 0) throw ProtocolError("INCOMPLETE_TRANSFER")
            if (value == (marker[matched].toInt() and 255)) {
                pending[matched++] = value.toByte()
                if (matched == marker.size) {
                    if (used > 0) write(out, used)
                    val tail = line(8)
                    if (tail == "--") return false
                    if (tail.isEmpty()) return true
                    throw ProtocolError("INVALID_MULTIPART")
                }
            } else {
                for (i in 0 until matched) emit(pending[i].toInt() and 255)
                matched = 0
                if (value == (marker[0].toInt() and 255)) { pending[matched++] = value.toByte() } else emit(value)
            }
        }
    }
}
