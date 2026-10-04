package devicedrop

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import devicedrop.database.*
import devicedrop.network.*
import kotlinx.coroutines.*
import org.junit.Test
import org.junit.Assert.*
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import java.util.UUID

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class RepositoryTest {
    @Test fun databaseIdentityTrustAndTransferState() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<Context>(); context.deleteDatabase("devicedrop.db")
        val repo = DropRepository(context); repo.ready.await()
        try {
            val id = repo.deviceId
            val peer = Device(UUID.randomUUID().toString(), "PC", "windows", "127.0.0.1")
            repo.trust(peer, "a".repeat(43))
            assertNotNull(repo.authenticate("Bearer " + "a".repeat(43)))
            assertNull(repo.authenticate("Bearer wrong"))
            val meta = Metadata(UUID.randomUUID().toString(), "a.txt", 0, "a".repeat(64), "text/plain", peer.deviceId, peer.deviceId)
            assertEquals("accepted", repo.offer(meta, repo.dao.peer(peer.deviceId)!!).getString("status"))
            repo.cancel(meta.transferId); assertEquals("cancelled", repo.dao.transfer(meta.transferId)!!.status)
            assertEquals(id, repo.dao.setting("device_id"))
            repo.dao.location(peer.deviceId, "192.168.1.88", 45833, 1234)
            assertEquals("192.168.1.88", repo.dao.peer(peer.deviceId)!!.ip)
        } finally { repo.scope.cancel(); repo.database.close() }
    }
    @Test fun pairingSingleUseAndApproval() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<Context>(); context.deleteDatabase("devicedrop.db")
        val repo = DropRepository(context); repo.ready.await()
        try {
            val window = repo.openPairing(); val device = Device(UUID.randomUUID().toString(), "PC", "windows", "127.0.0.1")
            val request = org.json.JSONObject().put("device", device.json()).put("code", window.code)
            val result = repo.pairRequest(request, "127.0.0.1")
            assertNull(repo.dao.peer(device.deviceId))
            repo.pairConfirm(org.json.JSONObject().put("request_id", result.getString("request_id")).put("confirmation_token", result.getString("confirmation_token")))
            val peer = repo.dao.peer(device.deviceId)!!; assertEquals(result.getString("shared_token"), peer.token)
            try { repo.pairRequest(request, "127.0.0.1"); fail("Pairing reused") } catch (e: ProtocolError) { assertEquals("PAIRING_EXPIRED", e.code) }
            repo.dao.trust(peer.copy(autoAccept = false))
            val meta = Metadata(UUID.randomUUID().toString(), "a.txt", 0, "a".repeat(64), "text/plain", device.deviceId, device.deviceId)
            assertEquals("pending", repo.offer(meta, repo.dao.peer(device.deviceId)!!).getString("status"))
            repo.approve(meta.transferId, false)
            try { repo.offerStatus(meta.transferId, peer); fail("Rejected offer accepted") } catch (e: ProtocolError) { assertEquals("TRANSFER_REJECTED", e.code) }
        } finally { repo.scope.cancel(); repo.database.close() }
    }
}
