package devicedrop

import android.content.Context
import android.net.Uri
import androidx.test.core.app.ApplicationProvider
import devicedrop.network.*
import kotlinx.coroutines.*
import org.junit.Test
import org.junit.Assert.*
import org.junit.Assume.assumeTrue
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.json.JSONObject
import java.io.File

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class InteropTest {
    @Test(timeout = 240000) fun windowsAndroidBothDirectionsOverTcp() = runBlocking {
        val directory = System.getenv("DEVICEDROP_INTEROP_DIR")
        assumeTrue("Set DEVICEDROP_INTEROP_DIR and run the Python interop fixture", !directory.isNullOrEmpty())
        val folder = File(directory!!)
        val configFile = File(folder, "config.json")
        withTimeout(60000) { while (!configFile.exists()) delay(200) }
        val config = JSONObject(configFile.readText())
        val context = ApplicationProvider.getApplicationContext<Context>(); context.deleteDatabase("devicedrop.db")
        val repo = DropRepository(context, port = 45920); repo.ready.await()
        org.robolectric.shadows.ShadowLog.stream = System.out
        repo.folder.listFiles()?.forEach { it.delete() }
        val server = DropServer(repo); server.start()
        try {
            repo.pair("127.0.0.1", 45833, config.getString("code"))
            assertEquals(1, repo.dao.trusted().size)
            // Unauthorized requests must fail before their payload is parsed.
            try { repo.request("http://127.0.0.1:${repo.port}/api/v1/transfers"); fail("Unauthorized request accepted") } catch (e: ProtocolError) { assertEquals(401, e.status) }
            val connection = repo.validateConnection(config.getString("device_id"))
            assertTrue(connection.summary(), connection.forwardOnline)
            assertEquals(connection.summary(), true, connection.reverseOnline)
            File(folder, "android-ready.json").writeText(JSONObject().put("device_id", repo.deviceId).put("port", repo.port).toString())
            withTimeout(180000) { while (!File(folder, "windows-sent.json").exists()) delay(200) }
            val incoming = repo.dao.history().filter { it.direction == "incoming" }
            assertEquals(3, incoming.size)
            incoming.forEach {
                assertEquals("completed", it.status)
                assertEquals(config.getJSONObject("hashes").getString(it.filename), hashFile(File(it.savedPath)))
            }
            repo.send(incoming.map { Uri.fromFile(File(it.savedPath)) }, listOf(config.getString("device_id")))
            withTimeout(180000) {
                while (true) {
                    if (repo.error.value.isNotEmpty()) fail("Sender error: ${repo.error.value}")
                    val outgoing = repo.dao.history().filter { it.direction == "outgoing" }
                    if (outgoing.any { it.status in listOf("failed", "cancelled") }) fail(outgoing.toString())
                    if (outgoing.size == 3 && outgoing.all { it.status == "completed" }) break
                    delay(200)
                }
            }
            File(folder, "android-sent.json").writeText("{}")
            withTimeout(10000) { while (!File(folder, "finished.json").exists()) delay(100) }
            assertEquals("passed", JSONObject(File(folder, "finished.json").readText()).getString("status"))
        } finally { server.stop(); repo.scope.cancel(); repo.database.close() }
    }
}
