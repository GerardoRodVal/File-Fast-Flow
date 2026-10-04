package devicedrop.network

import devicedrop.database.TrustedDevice
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.io.IOException
import java.io.InterruptedIOException
import java.util.concurrent.TimeUnit

data class ConnectionReport(val deviceId: String, val name: String, val ip: String, val port: Int,
    val forwardOnline: Boolean, val reverseOnline: Boolean? = null, val code: String = "",
    val remoteReceiving: Boolean? = null, val localReceiving: Boolean = true, val checkedAt: Long = System.currentTimeMillis()) {
    fun summary(): String = listOf(
        "Este equipo → $name: ${if (forwardOnline) "Correcta" else "Falló"}",
        "$name → este equipo: ${when (reverseOnline) { true -> "Correcta"; false -> "Falló"; null -> "Sin comprobar" }}",
        "Dirección comprobada: $ip:$port",
        when (code) {
            "TIMEOUT" -> "La otra aplicación no respondió a tiempo. Revisa Wi-Fi, firewall y VPN."
            "UNREACHABLE" -> "No se pudo llegar a la IP y al puerto. Abre FileFastFlow en el otro equipo y revisa la red privada."
            "IDENTITY_MISMATCH" -> "Esta IP pertenece a otro dispositivo. Corrige la IP; el vínculo se conserva."
            "AUTH_FAILED" -> "El vínculo no fue aceptado. Vuelve a vincular ambos dispositivos."
            "UPDATE_REQUIRED" -> "Actualiza FileFastFlow en el otro dispositivo para comprobar el camino de vuelta."
            "INVALID_LAN_ADDRESS", "INVALID_PORT" -> "Revisa la IP local y el puerto (45000–45999)."
            "INVALID_RESPONSE" -> "La respuesta no corresponde al protocolo de FileFastFlow."
            "CHECK_FAILED" -> "La comprobación de retorno no terminó. Inténtalo de nuevo."
            else -> ""
        },
        if (remoteReceiving == false) "La recepción de archivos está pausada en el otro dispositivo." else "",
        if (!localReceiving) "La recepción de archivos está pausada en este equipo." else ""
    ).filter { it.isNotEmpty() }.joinToString("\n")
}

data class ConnectionProbe(val legacy: Boolean, val receiving: Boolean?)

fun connectionError(error: Exception): String = when (error) {
    is InterruptedIOException -> "TIMEOUT"
    is IOException -> "UNREACHABLE"
    is ProtocolError -> error.code
    is IllegalArgumentException -> if (error.message in setOf("INVALID_LAN_ADDRESS", "INVALID_PORT")) error.message!! else "INVALID_RESPONSE"
    else -> "INVALID_RESPONSE"
}

class ConnectionValidator(private val localPort: Int = 45832) {
    private val client = OkHttpClient.Builder().connectTimeout(3, TimeUnit.SECONDS).readTimeout(3, TimeUnit.SECONDS)
        .writeTimeout(3, TimeUnit.SECONDS).callTimeout(4, TimeUnit.SECONDS).retryOnConnectionFailure(false).build()
    private val returnClient = client.newBuilder().readTimeout(12, TimeUnit.SECONDS).callTimeout(12, TimeUnit.SECONDS).build()

    private suspend fun request(peer: TrustedDevice, path: String, authenticated: Boolean = true, body: JSONObject? = null): JSONObject = withContext(Dispatchers.IO) {
        val request = Request.Builder().url(endpoint(peer.ip, peer.port) + path)
        if (authenticated) request.header("Authorization", "Bearer ${peer.token}").header("X-DeviceDrop-Port", localPort.toString())
        if (body != null) request.post(body.toString().toRequestBody("application/json".toMediaType()))
        (if (body == null) client else returnClient).newCall(request.build()).execute().use { response ->
            if (response.code in setOf(401, 403)) throw ProtocolError("AUTH_FAILED", response.code)
            if (!response.isSuccessful) throw ProtocolError("UNREACHABLE", response.code)
            val bytes = java.io.ByteArrayOutputStream()
            response.body?.byteStream()?.use { input ->
                val buffer = ByteArray(4096)
                while (true) {
                    val n = input.read(buffer); if (n < 0) break
                    if (bytes.size() + n > 32768) throw ProtocolError("INVALID_RESPONSE")
                    bytes.write(buffer, 0, n)
                }
            }
            JSONObject(bytes.toString("UTF-8"))
        }
    }

    suspend fun probe(peer: TrustedDevice): ConnectionProbe {
        val ping = request(peer, "/api/v1/ping", authenticated = false)
        if (ping.optString("device_id") != peer.deviceId) throw ProtocolError("IDENTITY_MISMATCH")
        if (ping.optInt("protocol_version") != 1) throw ProtocolError("INVALID_RESPONSE")
        val data = try { request(peer, "/api/v1/connection") } catch (e: ProtocolError) {
            if (e.status != 404) throw e
            val legacy = request(peer, "/api/v1/devices")
            if (legacy.optInt("protocol_version") != 1) throw ProtocolError("INVALID_RESPONSE")
            return ConnectionProbe(true, null)
        }
        if (data.optString("device_id") != peer.deviceId || data.optInt("protocol_version") != 1) throw ProtocolError("INVALID_RESPONSE")
        return ConnectionProbe(false, data.opt("receiving") as? Boolean)
    }

    suspend fun checkReturn(peer: TrustedDevice, localDeviceId: String): Pair<Boolean, String> {
        val body = JSONObject().put("device_id", localDeviceId).put("port", localPort).put("protocol_version", 1)
        val result = request(peer, "/api/v1/connection/check", body = body)
        if (result.optString("device_id") != peer.deviceId || result.optInt("protocol_version") != 1 || result.opt("reverse_online") !is Boolean)
            throw ProtocolError("INVALID_RESPONSE")
        return result.getBoolean("reverse_online") to result.optString("reverse_error")
    }
}
