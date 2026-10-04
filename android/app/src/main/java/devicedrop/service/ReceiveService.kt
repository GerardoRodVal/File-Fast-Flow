package devicedrop.service

import android.app.*
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat
import devicedrop.DeviceDropApp
import devicedrop.MainActivity
import devicedrop.R
import kotlinx.coroutines.*

class ReceiveService: Service() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val repo get() = (application as DeviceDropApp).repository
    private fun pending(): PendingIntent = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
    override fun onCreate() {
        super.onCreate()
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(NotificationChannel("receiving", "FileFastFlow activo", NotificationManager.IMPORTANCE_LOW))
        manager.createNotificationChannel(NotificationChannel("files", "Archivos recibidos", NotificationManager.IMPORTANCE_DEFAULT))
        val notification = NotificationCompat.Builder(this, "receiving").setSmallIcon(R.drawable.ic_devicedrop).setContentTitle("FileFastFlow activo")
            .setContentText("Conexión local activa. Recepción controlada desde Ajustes.").setContentIntent(pending()).setOngoing(true)
            .addAction(0, "Detener", PendingIntent.getService(this, 1, Intent(this, ReceiveService::class.java).setAction("STOP"), PendingIntent.FLAG_IMMUTABLE)).build()
        if (Build.VERSION.SDK_INT >= 29) startForeground(1, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE) else startForeground(1, notification)
        scope.launch {
            repo.start()
            if (!repo.active.value) { stopSelf(); return@launch }
            repo.events.collect { event ->
                if (event.type == "transfer_completed" && event.data.has("saved_path")) {
                    val item = NotificationCompat.Builder(this@ReceiveService, "files").setSmallIcon(R.drawable.ic_devicedrop)
                        .setContentTitle("Archivo recibido").setContentText("${event.data.optString("filename")} desde ${event.data.optString("sender_name")}")
                        .setContentIntent(pending()).setAutoCancel(true).build()
                    try { manager.notify(event.data.optString("transfer_id").hashCode(), item) } catch (_: SecurityException) {}
                }
            }
        }
    }
    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == "STOP") {
            scope.launch { repo.receiving.value = false; repo.dao.setting(devicedrop.database.Setting("allow_receive", "false")); repo.stop(); stopSelf() }
        }
        return START_NOT_STICKY
    }
    override fun onDestroy() { scope.cancel(); repo.scope.launch { repo.stop() }; super.onDestroy() }
    override fun onBind(intent: Intent?): IBinder? = null
}
