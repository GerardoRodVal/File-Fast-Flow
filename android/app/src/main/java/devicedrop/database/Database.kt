package devicedrop.database

import androidx.room.*
import kotlinx.coroutines.flow.Flow

@Entity(tableName = "devices")
data class SeenDevice(@PrimaryKey val deviceId: String, val data: String, val lastSeen: Long)
@Entity(tableName = "trusted_devices")
data class TrustedDevice(@PrimaryKey val deviceId: String, val name: String, val platform: String, val publicKey: String,
    val token: String, val ip: String, val port: Int, val createdAt: Long = System.currentTimeMillis(), val lastSeen: Long = 0,
    val autoAccept: Boolean = true, val autoSync: Boolean = false)
@Entity(tableName = "transfers")
data class Transfer(@PrimaryKey val transferId: String, val direction: String, val filename: String, val size: Long,
    val sha256: String, val mimeType: String, val sourceDevice: String, val destinationDevice: String,
    val originDeviceId: String, val batchId: String = "", val originalPath: String = "", val savedPath: String = "",
    val status: String = "queued", val startedAt: Long = System.currentTimeMillis(), val completedAt: Long = 0,
    val error: String = "", val bytesDone: Long = 0, val speed: Double = 0.0)
@Entity(tableName = "settings")
data class Setting(@PrimaryKey val key: String, val value: String)
@Entity(tableName = "processed_files", primaryKeys = ["originDeviceId", "contentHash", "path"])
data class ProcessedFile(val originDeviceId: String, val contentHash: String, val path: String, val transferId: String)

@Dao
interface DropDao {
    @Query("SELECT * FROM trusted_devices") fun observeTrusted(): Flow<List<TrustedDevice>>
    @Query("SELECT * FROM trusted_devices") suspend fun trusted(): List<TrustedDevice>
    @Query("SELECT * FROM trusted_devices WHERE deviceId=:id") suspend fun peer(id: String): TrustedDevice?
    @Insert(onConflict = OnConflictStrategy.REPLACE) suspend fun trust(peer: TrustedDevice)
    @Query("UPDATE trusted_devices SET ip=:ip,port=:port,lastSeen=:seen WHERE deviceId=:id") suspend fun location(id: String, ip: String, port: Int, seen: Long)
    @Query("DELETE FROM trusted_devices WHERE deviceId=:id") suspend fun unpair(id: String)
    @Query("SELECT * FROM transfers ORDER BY startedAt DESC LIMIT 300") fun observeHistory(): Flow<List<Transfer>>
    @Query("SELECT * FROM transfers ORDER BY startedAt DESC LIMIT 300") suspend fun history(): List<Transfer>
    @Query("SELECT * FROM transfers WHERE transferId=:id") suspend fun transfer(id: String): Transfer?
    @Insert(onConflict = OnConflictStrategy.REPLACE) suspend fun save(transfer: Transfer)
    @Query("UPDATE transfers SET status=:status,bytesDone=:done,speed=:speed,error=:error WHERE transferId=:id") suspend fun progress(id: String, status: String, done: Long, speed: Double = 0.0, error: String = "")
    @Query("UPDATE transfers SET status='failed',error='INTERRUPTED' WHERE status NOT IN ('completed','failed','cancelled')") suspend fun recover()
    @Insert(onConflict = OnConflictStrategy.REPLACE) suspend fun setting(setting: Setting)
    @Query("SELECT value FROM settings WHERE `key`=:key") suspend fun setting(key: String): String?
    @Insert(onConflict = OnConflictStrategy.IGNORE) suspend fun processed(file: ProcessedFile)
    @Insert(onConflict = OnConflictStrategy.REPLACE) suspend fun seen(device: SeenDevice)
}

@Database(entities = [SeenDevice::class, TrustedDevice::class, Transfer::class, Setting::class, ProcessedFile::class], version = 1, exportSchema = false)
abstract class DropDatabase: RoomDatabase() { abstract fun dao(): DropDao }
