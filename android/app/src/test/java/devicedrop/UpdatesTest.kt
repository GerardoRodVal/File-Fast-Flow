package devicedrop

import android.app.NotificationManager
import android.content.Context
import androidx.test.core.app.ApplicationProvider
import androidx.work.Configuration
import androidx.work.WorkManager
import androidx.work.testing.WorkManagerTestInitHelper
import devicedrop.updates.*
import kotlinx.coroutines.runBlocking
import okhttp3.*
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.ResponseBody.Companion.toResponseBody
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import java.io.File
import java.security.MessageDigest

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [32])
class UpdatesTest {
    @Test fun localUpdateMetadataSurvivesProtocolAndStagesVerifiedPackage() {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val file = File(context.filesDir, "received/FileFastFlow-0.4.0-debug.apk")
        file.parentFile!!.mkdirs(); file.writeBytes("local apk".toByteArray())
        val id = java.util.UUID.randomUUID().toString()
        val hash = devicedrop.network.hashFile(file)
        val meta = devicedrop.network.Metadata(id, file.name, file.length(), hash, "application/vnd.android.package-archive", id, id,
            updateRevision = "a".repeat(64), appVersion = "0.4.0")
        val parsed = devicedrop.network.Metadata.parse(meta.json())
        assertEquals(meta.updateRevision, parsed.updateRevision)
        val updates = AppUpdates(context)
        updates.acceptLocal(file, parsed)
        assertEquals(file, updates.localPackage.value!!.first)
        assertEquals(hash, updates.localPackage.value!!.second.sha256)
        assertEquals(file, AppUpdates(context).localPackage.value!!.first)
    }
    private val payload = "APK test bytes".toByteArray()
    private fun metadata(version: String = "0.4.9"): JSONObject {
        val name = "FileFastFlow-$version-debug.apk"
        val digest = MessageDigest.getInstance("SHA-256").digest(payload).joinToString("") { "%02x".format(it) }
        return JSONObject().put("tag_name", "v$version").put("body", "Cambios de prueba")
            .put("assets", JSONArray().put(JSONObject().put("name", name).put("size", payload.size)
                .put("browser_download_url", "$REPOSITORY_URL/releases/download/v$version/$name").put("digest", "sha256:$digest")))
    }
    private fun client(data: ByteArray, code: Int = 200): OkHttpClient = OkHttpClient.Builder().addInterceptor { chain ->
        Response.Builder().request(chain.request()).protocol(Protocol.HTTP_1_1).code(code).message("Test")
            .body(data.toResponseBody("application/octet-stream".toMediaType())).build()
    }.build()

    @Test fun comparesNumericVersionsAndRejectsIncompleteOrUntrustedReleases() {
        assertEquals("0.4.10", parseRelease(metadata("0.4.10"), "0.4.9")!!.version)
        assertNull(parseRelease(metadata("0.3.99"), "0.4.0"))
        assertNull(parseRelease(metadata("0.4.0"), "0.4.0"))
        assertNull(parseRelease(metadata().put("draft", true), "0.4.0"))
        assertNull(parseRelease(metadata().put("prerelease", true), "0.4.0"))
        for (tag in listOf("main", "v0.4.9-beta", "../0.4.9")) {
            assertThrows(IllegalArgumentException::class.java) { parseRelease(metadata().put("tag_name", tag), "0.4.0") }
        }
        for (change in listOf("browser_download_url" to "https://example.com/app.apk", "size" to 0, "digest" to "sha256:abc")) {
            val json = metadata(); json.getJSONArray("assets").getJSONObject(0).put(change.first, change.second)
            assertThrows(IllegalArgumentException::class.java) { parseRelease(json, "0.4.0") }
        }
        assertThrows(IllegalArgumentException::class.java) { parseRelease(metadata().put("assets", JSONArray()), "0.4.0") }
    }

    @Test fun downloadVerifiesBytesAndPreservesPreviousFileOnFailure() {
        val folder = File.createTempFile("updates", "test").apply { delete(); mkdirs() }
        try {
            val release = parseRelease(metadata(), "0.4.0")!!
            val target = File(folder, release.filename).apply { writeText("previous") }
            for (bytes in listOf("APK bad bytes!".toByteArray(), byteArrayOf(1), ByteArray(100))) {
                assertThrows(IllegalArgumentException::class.java) { downloadApk(client(bytes), release, folder) }
                assertEquals("previous", target.readText())
            }
            assertThrows(IllegalStateException::class.java) { downloadApk(client(payload), release, folder) { true } }
            assertEquals("previous", target.readText())
            assertEquals(listOf(target.name), folder.listFiles()!!.map { it.name })
            assertEquals(target, downloadApk(client(payload), release, folder))
            assertArrayEquals(payload, target.readBytes())
            verifyApk(target, release)
        } finally { folder.deleteRecursively() }
    }

    @Test fun checksMissingReleasesAndNetworkErrorsWithoutFalseUpdate() = runBlocking {
        assertNull(fetchRelease(client(byteArrayOf(), 404)))
        val context = ApplicationProvider.getApplicationContext<Context>()
        val updates = AppUpdates(context, client(byteArrayOf(), 503))
        try { updates.check(); fail("Accepted unavailable GitHub") } catch (_: java.io.IOException) { }
        assertNull(updates.state.value.release)
        assertFalse(updates.state.value.checking)
        assertTrue(updates.state.value.message.contains("Internet"))
    }

    @Test fun backgroundSchedulingIsUniqueAndCanBeDisabled() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        context.getSharedPreferences("updates", Context.MODE_PRIVATE).edit().clear().commit()
        WorkManagerTestInitHelper.initializeTestWorkManager(context, Configuration.Builder().build())
        val updates = AppUpdates(context)
        updates.schedule(checkNow = false); updates.schedule(checkNow = false)
        val manager = WorkManager.getInstance(context)
        val before = manager.getWorkInfosForUniqueWork("filefastflow-updates").get()
        assertEquals(1, before.size)
        assertFalse(before.single().state.isFinished)
        updates.setEnabled(false)
        assertFalse(updates.enabled)
        assertTrue(manager.getWorkInfosForUniqueWork("filefastflow-updates").get().all { it.state.isFinished })
    }

    @Test fun notifiesOnceAndDoesNotConsumeNoticeWhenChannelIsBlocked() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val preferences = context.getSharedPreferences("updates", Context.MODE_PRIVATE)
        preferences.edit().clear().commit()
        val manager = context.getSystemService(NotificationManager::class.java)
        val updates = AppUpdates(context)
        val release = parseRelease(metadata(), "0.4.0")!!
        updates.notifyRelease(release)
        assertEquals(release.version, preferences.getString("last_notified", null))
        manager.cancelAll(); updates.notifyRelease(release)
        assertEquals(0, manager.activeNotifications.size)
        manager.deleteNotificationChannel("updates")
        manager.createNotificationChannel(android.app.NotificationChannel("updates", "Updates", NotificationManager.IMPORTANCE_NONE))
        preferences.edit().clear().commit()
        updates.notifyRelease(release)
        assertNull(preferences.getString("last_notified", null))
    }
}
