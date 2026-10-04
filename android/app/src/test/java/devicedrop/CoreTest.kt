package devicedrop

import devicedrop.network.*
import io.ktor.utils.io.ByteReadChannel
import kotlinx.coroutines.runBlocking
import org.junit.Test
import org.junit.Assert.*
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.json.JSONObject
import java.io.File
import java.util.UUID

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class CoreTest {
    @Test fun filenames() {
        listOf("../file", "..\\file", "CON.txt", "a:stream", "name.", "NUL", "a\u0000b").forEach { name ->
            assertThrows(IllegalArgumentException::class.java) { safeName(name) }
        }
        assertEquals("Fotografía.png", safeName("Fotografía.png"))
    }
    @Test fun metadataAndVersion() {
        val id = UUID.randomUUID().toString()
        val meta = Metadata(id, "a.txt", 5, "a".repeat(64), "text/plain", id, id)
        assertEquals(meta, Metadata.parse(meta.json()))
        assertThrows(IllegalArgumentException::class.java) { Metadata.parse(meta.json().put("size", -1)) }
        assertThrows(IllegalArgumentException::class.java) { Metadata.parse(meta.json().put("protocol_version", 2)) }
    }
    @Test fun discoveryContract() {
        val device = Device(UUID.randomUUID().toString(), "Windows PC", "windows", "192.168.1.2")
        assertEquals(device, Device.parse(device.json()))
        assertEquals("http://192.168.1.2:45832", endpoint(device.ip, device.port))
        assertThrows(IllegalArgumentException::class.java) { endpoint("8.8.8.8", 45832) }
        assertThrows(IllegalArgumentException::class.java) { endpoint("example.com", 45832) }
    }
    @Test fun hash() {
        val file = File.createTempFile("drop", ".txt")
        try { file.writeText("abc"); assertEquals("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad", hashFile(file)) } finally { file.delete() }
    }
    @Test fun multipartStreamingAndMetadataBound() = runBlocking {
        val data = "--test\r\nContent-Disposition: form-data; name=\"metadata\"\r\n\r\n{\"size\":5}\r\n--test\r\nContent-Disposition: form-data; name=\"file\"\r\n\r\nhello\r\n--test--\r\n"
        val reader = MultipartReader(ByteReadChannel(data.toByteArray()))
        assertEquals("--test", reader.line()); assertTrue(reader.headers().contains("metadata"))
        var first = ""; assertTrue(reader.part("test") { bytes, count -> first += String(bytes, 0, count) }); assertEquals("{\"size\":5}", first)
        assertTrue(reader.headers().contains("file"))
        var second = ""; assertFalse(reader.part("test") { bytes, count -> second += String(bytes, 0, count) }); assertEquals("hello", second)
    }
    @Test fun multipartTruncation() = runBlocking {
        val reader = MultipartReader(ByteReadChannel("payload-with-no-boundary".toByteArray()))
        try { reader.part("test") { _, _ -> }; fail("Truncated body accepted") } catch (error: ProtocolError) { assertEquals("INCOMPLETE_TRANSFER", error.code) }
    }
}
