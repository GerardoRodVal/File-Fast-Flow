package devicedrop.network

import org.json.JSONObject
import java.io.File
import java.net.InetAddress
import java.security.MessageDigest
import java.util.UUID

data class Device(val deviceId: String, val name: String, val platform: String, val ip: String, val port: Int = 45832, val publicKey: String = "") {
    fun json() = JSONObject().put("device_id", deviceId).put("device_name", name).put("platform", platform)
        .put("device_type", if (platform == "android") "phone" else "desktop").put("ip", ip).put("port", port)
        .put("public_key", publicKey).put("protocol_version", 1)
    companion object {
        fun parse(j: JSONObject): Device {
            require(j.getInt("protocol_version") == 1) { "PROTOCOL_UNSUPPORTED" }
            UUID.fromString(j.getString("device_id"))
            require(j.getString("device_name").length in 1..80)
            require(j.getString("platform") in setOf("windows", "android"))
            require(j.getInt("port") in 45000..45999)
            return Device(j.getString("device_id"), j.getString("device_name"), j.getString("platform"), j.optString("ip"), j.getInt("port"), j.optString("public_key"))
        }
    }
}

data class Metadata(val transferId: String, val filename: String, val size: Long, val sha256: String,
    val mimeType: String, val sender: String, val origin: String, val batch: String = "") {
    fun json() = JSONObject().put("transfer_id", transferId).put("filename", filename).put("size", size)
        .put("sha256", sha256).put("mime_type", mimeType).put("sender_device_id", sender).put("origin_device_id", origin)
        .put("protocol_version", 1).apply { if (batch.isNotEmpty()) put("batch_id", batch) }
    companion object {
        fun parse(j: JSONObject): Metadata {
            require(j.getInt("protocol_version") == 1)
            listOf("transfer_id", "sender_device_id", "origin_device_id").forEach { UUID.fromString(j.getString(it)) }
            if (j.optString("batch_id").isNotEmpty() && j.optString("batch_id") != "null") UUID.fromString(j.getString("batch_id"))
            safeName(j.getString("filename"))
            require(j.getLong("size") in 0..16L * 1024 * 1024 * 1024) { "INVALID_SIZE" }
            require(j.getString("sha256").matches(Regex("[a-f0-9]{64}"))) { "INVALID_HASH" }
            require(j.getString("mime_type").length <= 120)
            return Metadata(j.getString("transfer_id"), j.getString("filename"), j.getLong("size"), j.getString("sha256"),
                j.getString("mime_type"), j.getString("sender_device_id"), j.getString("origin_device_id"), j.optString("batch_id").takeUnless { it == "null" } ?: "")
        }
    }
}

fun safeName(name: String): String {
    val reserved = setOf("CON", "PRN", "AUX", "NUL") + (1..9).flatMap { listOf("COM$it", "LPT$it") }
    require(name.length in 1..240 && name !in setOf(".", "..") && !name.endsWith('.') && !name.endsWith(' ') &&
        name.none { it < ' ' || it in "<>:\"/\\|?*" } && name.substringBefore('.').uppercase() !in reserved) { "INVALID_FILE" }
    return name
}

fun hashFile(file: File): String {
    val hash = MessageDigest.getInstance("SHA-256")
    file.inputStream().use { stream ->
        val buffer = ByteArray(1024 * 1024)
        while (true) { val n = stream.read(buffer); if (n < 0) break; hash.update(buffer, 0, n) }
    }
    return hash.digest().joinToString("") { "%02x".format(it) }
}

fun endpoint(ip: String, port: Int): String {
    require(port in 45000..45999) { "INVALID_PORT" }
    require(ip.matches(Regex("[0-9a-fA-F:.]+"))) { "INVALID_LAN_ADDRESS" }
    val address = InetAddress.getByName(ip)
    require((address.isSiteLocalAddress || address.isLinkLocalAddress || address.isLoopbackAddress) && !address.isAnyLocalAddress && !address.isMulticastAddress) { "INVALID_LAN_ADDRESS" }
    return "http://${if (ip.contains(':')) "[$ip]" else ip}:$port"
}

class ProtocolError(val code: String, val status: Int = 400): Exception(code)
