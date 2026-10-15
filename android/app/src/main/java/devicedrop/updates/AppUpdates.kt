package devicedrop.updates

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.work.*
import devicedrop.BuildConfig
import devicedrop.DeviceDropApp
import devicedrop.MainActivity
import devicedrop.R
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONObject
import java.io.File
import java.io.IOException
import java.security.MessageDigest
import java.util.concurrent.TimeUnit

const val REPOSITORY_URL = "https://github.com/GerardoRodVal/File-Fast-Flow"
const val RELEASES_URL = "$REPOSITORY_URL/releases/latest"
const val API_URL = "https://api.github.com/repos/GerardoRodVal/File-Fast-Flow/releases/latest"
const val OPEN_UPDATES = "devicedrop.OPEN_UPDATES"
private const val CHANNEL = "updates"
private const val NOTICE_ID = 45834
private const val PERIODIC_WORK = "filefastflow-updates"
private const val STARTUP_WORK = "filefastflow-updates-startup"
private const val MAX_APK_SIZE = 256L * 1024 * 1024

data class AppRelease(val version: String, val filename: String, val url: String, val size: Long, val sha256: String, val notes: String)
data class UpdateState(val release: AppRelease? = null, val message: String = "Busca nuevas versiones o espera el aviso automático.", val checking: Boolean = false)

private fun versionParts(version: String): List<Int> {
    require(Regex("\\d{1,6}\\.\\d{1,6}\\.\\d{1,6}").matches(version)) { "Versión inválida." }
    return version.split('.').map { it.toInt() }
}

fun parseRelease(data: JSONObject, currentVersion: String = BuildConfig.VERSION_NAME): AppRelease? {
    if (data.optBoolean("draft") || data.optBoolean("prerelease")) return null
    val tag = data.getString("tag_name")
    val version = tag.removePrefix("v")
    val parts = versionParts(version); val current = versionParts(currentVersion)
    val first = parts.indices.firstOrNull { parts[it] != current[it] } ?: return null
    if (parts[first] < current[first]) return null
    val filename = "FileFastFlow-$version-debug.apk"
    val assets = data.getJSONArray("assets")
    val matches = (0 until assets.length()).map { assets.getJSONObject(it) }.filter { it.optString("name") == filename }
    require(matches.size == 1) { "La publicación no contiene un APK único." }
    val asset = matches.single()
    val url = "$REPOSITORY_URL/releases/download/$tag/$filename"
    require(asset.getString("browser_download_url") == url) { "URL del APK inválida." }
    val size = asset.getLong("size")
    require(size in 1..MAX_APK_SIZE) { "Tamaño del APK inválido." }
    val digest = asset.getString("digest")
    require(Regex("sha256:[0-9a-f]{64}").matches(digest)) { "La publicación no tiene un SHA-256 válido." }
    return AppRelease(version, filename, url, size, digest.removePrefix("sha256:"), data.optString("body").take(6000))
}

fun updateClient(): OkHttpClient = OkHttpClient.Builder()
    .connectTimeout(15, TimeUnit.SECONDS).readTimeout(30, TimeUnit.SECONDS).callTimeout(5, TimeUnit.MINUTES)
    .followSslRedirects(false)
    .addNetworkInterceptor { chain ->
        val url = chain.request().url
        require(url.isHttps && url.host in setOf("api.github.com", "github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com")) {
            "Servidor de actualización no permitido."
        }
        chain.proceed(chain.request())
    }.build()

fun fetchRelease(client: OkHttpClient, currentVersion: String = BuildConfig.VERSION_NAME): AppRelease? {
    val request = Request.Builder().url(API_URL).header("Accept", "application/vnd.github+json")
        .header("User-Agent", "FileFastFlow/$currentVersion").build()
    return client.newCall(request).execute().use { response ->
        if (response.code == 404) return@use null
        if (!response.isSuccessful) throw IOException("GitHub no está disponible (${response.code}).")
        parseRelease(JSONObject(response.body?.string() ?: throw IOException("Respuesta vacía.")), currentVersion)
    }
}

fun verifyApk(file: File, release: AppRelease) {
    require(file.isFile && file.length() == release.size) { "Tamaño del APK incorrecto." }
    val digest = MessageDigest.getInstance("SHA-256")
    file.inputStream().use { input ->
        val buffer = ByteArray(1024 * 1024)
        while (true) { val count = input.read(buffer); if (count < 0) break; digest.update(buffer, 0, count) }
    }
    require(digest.digest().joinToString("") { "%02x".format(it) } == release.sha256) { "SHA-256 del APK incorrecto." }
}

fun downloadApk(client: OkHttpClient, release: AppRelease, directory: File, cancelled: () -> Boolean = { false }): File {
    versionParts(release.version)
    require(release.filename == "FileFastFlow-${release.version}-debug.apk" &&
        release.url in listOf("$REPOSITORY_URL/releases/download/v${release.version}/${release.filename}",
            "$REPOSITORY_URL/releases/download/${release.version}/${release.filename}") &&
        release.size in 1..MAX_APK_SIZE && Regex("[0-9a-f]{64}").matches(release.sha256)) { "Metadatos del APK inválidos." }
    directory.mkdirs()
    val target = File(directory, release.filename)
    if (target.isFile && runCatching { verifyApk(target, release) }.isSuccess) return target
    val temporary = File.createTempFile("apk-", ".part", directory)
    try {
        client.newCall(Request.Builder().url(release.url).build()).execute().use { response ->
            if (!response.isSuccessful) throw IOException("No se pudo descargar el APK (${response.code}).")
            val body = response.body ?: throw IOException("Descarga vacía.")
            body.byteStream().use { input -> temporary.outputStream().use { output ->
                val buffer = ByteArray(1024 * 1024); var received = 0L
                while (true) {
                    check(!cancelled()) { "Descarga cancelada." }
                    val count = input.read(buffer); if (count < 0) break
                    received += count
                    require(received <= release.size) { "El APK supera el tamaño publicado." }
                    output.write(buffer, 0, count)
                }
            } }
        }
        verifyApk(temporary, release)
        check(!cancelled()) { "Descarga cancelada." }
        java.nio.file.Files.move(temporary.toPath(), target.toPath(), java.nio.file.StandardCopyOption.REPLACE_EXISTING)
        return target
    } finally { temporary.delete() }
}

class AppUpdates(private val context: Context, private val client: OkHttpClient = updateClient()) {
    private val preferences = context.getSharedPreferences("updates", Context.MODE_PRIVATE)
    private val lock = Mutex()
    val state = MutableStateFlow(UpdateState())
    val enabled get() = preferences.getBoolean("automatic", true)
    val localPackage = MutableStateFlow<Pair<File, AppRelease>?>(null)

    init {
        runCatching {
            val data = JSONObject(preferences.getString("local_package", "") ?: "")
            localPackage.value = File(data.getString("path")) to AppRelease(data.getString("version"), data.getString("filename"), "", data.getLong("size"), data.getString("sha256"), "Actualización local")
        }
    }

    fun acceptLocal(file: File, meta: devicedrop.network.Metadata) {
        val release = AppRelease(meta.appVersion, meta.filename, "", meta.size, meta.sha256, "Cambios locales de tu PC")
        verifyApk(file, release)
        localPackage.value = file to release
        preferences.edit().putString("local_package", JSONObject().put("path", file.absolutePath).put("version", meta.appVersion)
            .put("filename", meta.filename).put("size", meta.size).put("sha256", meta.sha256).toString()).apply()
        preferences.edit().remove("last_notified").apply()
        notifyRelease(release)
    }

    fun schedule(checkNow: Boolean = true) {
        val manager = WorkManager.getInstance(context)
        if (!enabled) { manager.cancelUniqueWork(PERIODIC_WORK); manager.cancelUniqueWork(STARTUP_WORK); return }
        val constraints = Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()
        manager.enqueueUniquePeriodicWork(PERIODIC_WORK, ExistingPeriodicWorkPolicy.KEEP,
            PeriodicWorkRequestBuilder<UpdateWorker>(30, TimeUnit.MINUTES).setConstraints(constraints).build())
        if (checkNow) manager.enqueueUniqueWork(STARTUP_WORK, ExistingWorkPolicy.KEEP,
            OneTimeWorkRequestBuilder<UpdateWorker>().setConstraints(constraints).build())
    }

    fun setEnabled(value: Boolean) {
        preferences.edit().putBoolean("automatic", value).apply()
        schedule()
    }

    suspend fun check(automatic: Boolean = false) = lock.withLock {
        if (automatic && !enabled) return@withLock
        state.value = state.value.copy(checking = true, message = "Buscando actualizaciones…")
        try {
            val release = withContext(Dispatchers.IO) { fetchRelease(client) }
            state.value = UpdateState(release, if (release == null) "Tienes la versión más reciente publicada." else "Nueva versión disponible: ${release.version}.")
            if (release != null && (!automatic || enabled)) notifyRelease(release)
            else if (release == null) NotificationManagerCompat.from(context).cancel(NOTICE_ID)
        } catch (error: Exception) {
            state.value = state.value.copy(checking = false, message = "No se pudo buscar. Comprueba Internet e inténtalo de nuevo.")
            throw error
        }
    }

    fun notifyRelease(release: AppRelease) {
        val manager = context.getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(NotificationChannel(CHANNEL, "Actualizaciones de FileFastFlow", NotificationManager.IMPORTANCE_DEFAULT))
        if (!NotificationManagerCompat.from(context).areNotificationsEnabled() || manager.getNotificationChannel(CHANNEL).importance == NotificationManager.IMPORTANCE_NONE ||
            preferences.getString("last_notified", null) == release.version) return
        val intent = Intent(context, MainActivity::class.java).setAction(OPEN_UPDATES)
            .addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP)
        val pending = PendingIntent.getActivity(context, NOTICE_ID, intent, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        val notice = NotificationCompat.Builder(context, CHANNEL).setSmallIcon(R.drawable.ic_devicedrop)
            .setContentTitle("FileFastFlow · actualización disponible")
            .setContentText("La versión ${release.version} está lista. Toca para actualizar.")
            .setContentIntent(pending).setAutoCancel(true).build()
        try {
            manager.notify(NOTICE_ID, notice)
            preferences.edit().putString("last_notified", release.version).apply()
        } catch (_: SecurityException) { /* Retry after the user grants notification permission. */ }
    }

    suspend fun download(release: AppRelease): File = withContext(Dispatchers.IO) {
        val job = kotlin.coroutines.coroutineContext[kotlinx.coroutines.Job]
        downloadApk(client, release, File(context.cacheDir, "updates")) { job?.isActive == false }
    }
}

class UpdateWorker(context: Context, parameters: WorkerParameters): CoroutineWorker(context, parameters) {
    override suspend fun doWork(): Result {
        val updates = (applicationContext as DeviceDropApp).updates
        return try { updates.check(automatic = true); Result.success() }
        catch (error: kotlinx.coroutines.CancellationException) { throw error }
        catch (_: IOException) { if (runAttemptCount < 3) Result.retry() else Result.failure() }
        catch (_: Exception) { Result.failure() }
    }
}
