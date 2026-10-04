package devicedrop

import android.Manifest
import android.content.ContentValues
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.MediaStore
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.Alignment
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.core.content.ContextCompat
import androidx.core.content.FileProvider
import coil.compose.AsyncImage
import com.google.zxing.BarcodeFormat
import com.journeyapps.barcodescanner.ScanContract
import com.journeyapps.barcodescanner.ScanOptions
import devicedrop.database.Transfer
import devicedrop.network.ProtocolError
import devicedrop.database.TrustedDevice
import devicedrop.network.ConnectionReport
import devicedrop.service.ReceiveService
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.first
import org.json.JSONObject
import java.io.File

class MainActivity: ComponentActivity() {
    private val shared = MutableStateFlow<List<Uri>>(emptyList())
    private val repo get() = (application as DeviceDropApp).repository
    override fun onCreate(state: Bundle?) {
        super.onCreate(state); readShare(intent)
        val notifications = registerForActivityResult(ActivityResultContracts.RequestPermission()) { }
        if (Build.VERSION.SDK_INT >= 33) notifications.launch(Manifest.permission.POST_NOTIFICATIONS)
        setContent {
            MaterialTheme(colorScheme = lightColorScheme(primary = Color(0xFF087F69), background = Color(0xFFF5F8F7), surface = Color.White)) {
                DropScreen()
            }
        }
    }
    override fun onNewIntent(intent: Intent) { super.onNewIntent(intent); setIntent(intent); readShare(intent) }
    @Suppress("DEPRECATION")
    private fun readShare(intent: Intent?) {
        shared.value = when (intent?.action) {
            Intent.ACTION_SEND -> listOfNotNull(intent.getParcelableExtra<Uri>(Intent.EXTRA_STREAM))
            Intent.ACTION_SEND_MULTIPLE -> intent.getParcelableArrayListExtra<Uri>(Intent.EXTRA_STREAM)?.toList() ?: emptyList()
            else -> emptyList()
        }
    }
    private fun startService() {
        ContextCompat.startForegroundService(this, Intent(this, ReceiveService::class.java))
    }

    @OptIn(ExperimentalMaterial3Api::class)
    @Composable
    private fun DropScreen() {
        val scope = rememberCoroutineScope()
        val trusted by repo.trusted.collectAsState(); val history by repo.history.collectAsState(); val nearby by repo.nearby.collectAsState()
        val online by repo.online.collectAsState(); val active by repo.active.collectAsState(); val receiving by repo.receiving.collectAsState()
        val connectionReports by repo.connectionReports.collectAsState(); val checkingConnections by repo.checkingConnections.collectAsState()
        val name by repo.name.collectAsState(); val message by repo.error.collectAsState(); val selections by shared.collectAsState()
        var tab by remember { mutableIntStateOf(0) }; var manual by remember { mutableStateOf(false) }; var qr by remember { mutableStateOf<PairWindow?>(null) }
        var ip by remember { mutableStateOf("") }; var port by remember { mutableStateOf("45832") }; var code by remember { mutableStateOf("") }
        var rename by remember { mutableStateOf(false) }; var editedName by remember { mutableStateOf("") }
        var preview by remember { mutableStateOf<Transfer?>(null) }; var approving by remember { mutableStateOf<Offer?>(null) }
        var onboarding by remember { mutableStateOf(false) }; var pendingExport by remember { mutableStateOf<Transfer?>(null) }
        var validatingPeer by remember { mutableStateOf<TrustedDevice?>(null) }
        var connectionIp by remember { mutableStateOf("") }; var connectionPort by remember { mutableStateOf("45832") }
        var validationReport by remember { mutableStateOf<ConnectionReport?>(null) }
        val snackbar = remember { SnackbarHostState() }
        fun work(action: suspend () -> Unit) { scope.launch { try { action() } catch (e: CancellationException) { throw e } catch (e: Exception) { repo.error.value = (e as? ProtocolError)?.code ?: "NETWORK_ERROR" } } }
        fun connectionLabel(id: String): String = when {
            id in checkingConnections -> "Validando conexión…"
            online[id] == null -> "Sin comprobar"
            online[id] != true -> "Sin conexión"
            connectionReports[id]?.reverseOnline == false -> "Conexión en un solo sentido"
            connectionReports[id]?.reverseOnline == true -> "Conectado · ida y vuelta"
            else -> "Conectado · retorno sin comprobar"
        }
        fun openValidation(peer: TrustedDevice) {
            validatingPeer = peer; connectionIp = peer.ip; connectionPort = peer.port.toString(); validationReport = null
        }
        val picker = androidx.activity.compose.rememberLauncherForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) { shared.value = it }
        val export = androidx.activity.compose.rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("application/octet-stream")) { uri ->
            val transfer = pendingExport; if (uri != null && transfer != null) work { withContext(Dispatchers.IO) { contentResolver.openOutputStream(uri)?.use { out -> File(transfer.savedPath).inputStream().use { it.copyTo(out, 1024 * 1024) } } }; snackbar.showSnackbar("Archivo guardado") }
        }
        val scanner = androidx.activity.compose.rememberLauncherForActivityResult(ScanContract()) { result ->
            result.contents?.let { text -> work {
                val json = JSONObject(text); require(json.getString("protocol") == "devicedrop" && json.getInt("version") == 1)
                withContext(Dispatchers.IO) { repo.pair(json.getString("ip"), json.getInt("port"), json.getString("pairing_token")) }
                snackbar.showSnackbar("Dispositivo vinculado")
            } }
        }
        LaunchedEffect(Unit) {
            repo.ready.await()
            onboarding = repo.dao.setting("onboarded") != "true"
            if (!onboarding) startService()
            while (true) { approving = repo.offers.values.firstOrNull { it.status == "pending" && it.expires > System.currentTimeMillis() }; delay(1000) }
        }
        LaunchedEffect(message) { if (message.isNotEmpty()) { snackbar.showSnackbar(message); repo.error.value = "" } }
        Scaffold(topBar = { TopAppBar(title = { Text("⇄  FileFastFlow") }, actions = { Text(if (active) "● LAN" else "○ LAN detenida", style = MaterialTheme.typography.labelLarge, modifier = Modifier.padding(16.dp)) }) },
            snackbarHost = { SnackbarHost(snackbar) }, bottomBar = {
                NavigationBar {
                    listOf("Inicio" to Icons.Outlined.Home, "Dispositivos" to Icons.Outlined.Devices, "Historial" to Icons.Outlined.History, "Ajustes" to Icons.Outlined.Settings).forEachIndexed { index, pair ->
                        NavigationBarItem(selected = tab == index, onClick = { tab = index }, icon = { Icon(pair.second, pair.first) }, label = { Text(pair.first) })
                    }
                }
            }, floatingActionButton = { if (tab == 0) ExtendedFloatingActionButton(onClick = { picker.launch(arrayOf("*/*")) }, icon = { Icon(Icons.Outlined.UploadFile, null) }, text = { Text("Enviar archivo") }) }
        ) { padding ->
            LazyColumn(modifier = Modifier.fillMaxSize().padding(padding), contentPadding = PaddingValues(20.dp, 12.dp, 20.dp, 100.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
                when (tab) {
                    0 -> {
                        item { Text("Tus archivos, cerca de ti.", style = MaterialTheme.typography.headlineMedium); Text("Comparte en tu red local, sin cuentas.", color = Color(0xFF6C807B)) }
                        item { Text("Tus dispositivos", style = MaterialTheme.typography.titleLarge) }
                        if (trusted.isEmpty()) item { OutlinedButton(onClick = { tab = 1 }) { Text("+ Vincular dispositivo") } }
                        items(trusted, key = { it.deviceId }) { peer ->
                            Card(Modifier.fillMaxWidth()) { Row(Modifier.padding(18.dp), verticalAlignment = Alignment.CenterVertically) { Icon(Icons.Outlined.Devices, null); Spacer(Modifier.width(14.dp)); Column { Text(peer.name); Text(connectionLabel(peer.deviceId), style = MaterialTheme.typography.bodySmall); TextButton(onClick = { openValidation(peer) }) { Text("Validar conexión") } } } }
                        }
                        item { Text("Archivos recientes", style = MaterialTheme.typography.titleLarge) }
                        if (history.isEmpty()) item { Text("Aquí aparecerán tus archivos recibidos y enviados.") }
                        items(history.take(10), key = { it.transferId }) { transfer ->
                            TransferCard(transfer, trusted.firstOrNull { it.deviceId in listOf(transfer.sourceDevice, transfer.destinationDevice) }?.name ?: "Dispositivo", { preview = transfer }, { openFile(transfer) }, { work { repo.cancel(transfer.transferId) } }, {
                                if (Build.VERSION.SDK_INT >= 29) work { saveDownloads(transfer); snackbar.showSnackbar("Guardado en Downloads/FileFastFlow") } else { pendingExport = transfer; export.launch(transfer.filename) }
                            })
                        }
                    }
                    1 -> {
                        item { Text("Vincula tus dispositivos", style = MaterialTheme.typography.headlineMedium) }
                        item { Button(onClick = { scanner.launch(ScanOptions().setDesiredBarcodeFormats(ScanOptions.QR_CODE).setPrompt("Escanea el QR de FileFastFlow").setBeepEnabled(false)) }, Modifier.fillMaxWidth()) { Text("Escanear QR") } }
                        item { Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) { OutlinedButton(onClick = { work { qr = repo.openPairing() } }) { Text("Mi código / QR") }; OutlinedButton(onClick = { manual = true }) { Text("Vincular por IP") } } }
                        items(trusted, key = { it.deviceId }) { peer ->
                            Card(Modifier.fillMaxWidth()) { Column(Modifier.padding(18.dp)) {
                                Text(peer.name, style = MaterialTheme.typography.titleLarge); Text(connectionLabel(peer.deviceId))
                                Text("IP guardada: ${peer.ip}:${peer.port}", style = MaterialTheme.typography.bodySmall)
                                connectionReports[peer.deviceId]?.let { report -> if (report.code.isNotEmpty() || report.reverseOnline != null) Text(report.summary(), style = MaterialTheme.typography.bodySmall) }
                                OutlinedButton(onClick = { openValidation(peer) }, enabled = peer.deviceId !in checkingConnections) { Text("Validar conexión / corregir IP") }
                                Row(verticalAlignment = Alignment.CenterVertically) { Text("Aceptar automáticamente", Modifier.weight(1f)); Switch(peer.autoAccept, { value -> work { repo.dao.trust(peer.copy(autoAccept = value)) } }) }
                                TextButton(onClick = { work { repo.dao.unpair(peer.deviceId) } }) { Text("Desvincular") }
                            } }
                        }
                        item { Text("Cerca de ti", style = MaterialTheme.typography.titleLarge) }
                        if (nearby.isEmpty()) item { Text("Abre FileFastFlow en tu PC. Si no aparece, usa su IP local.") }
                        items(nearby.filter { device -> trusted.none { it.deviceId == device.deviceId } }, key = { it.deviceId }) { device ->
                            OutlinedButton(onClick = { ip = device.ip; port = device.port.toString(); manual = true }, Modifier.fillMaxWidth()) { Text("${device.name} · ${device.ip}") }
                        }
                    }
                    2 -> {
                        item { Text("Historial", style = MaterialTheme.typography.headlineMedium) }
                        items(history, key = { it.transferId }) { transfer ->
                            TransferCard(transfer, trusted.firstOrNull { it.deviceId in listOf(transfer.sourceDevice, transfer.destinationDevice) }?.name ?: "Dispositivo", { preview = transfer }, { openFile(transfer) }, { work { repo.cancel(transfer.transferId) } }, {
                                if (Build.VERSION.SDK_INT >= 29) work { saveDownloads(transfer); snackbar.showSnackbar("Archivo guardado") } else { pendingExport = transfer; export.launch(transfer.filename) }
                            })
                        }
                    }
                    3 -> {
                        item { Text("Este dispositivo", style = MaterialTheme.typography.headlineMedium) }
                        item { ListItem(headlineContent = { Text(name) }, supportingContent = { Text("Nombre del dispositivo") }, modifier = Modifier.clickable { editedName = name; rename = true }) }
                        item { Row(verticalAlignment = Alignment.CenterVertically) { Text("Permitir recepción", Modifier.weight(1f)); Switch(receiving, { value -> work {
                            repo.receiving.value = value; repo.dao.setting(devicedrop.database.Setting("allow_receive", value.toString()))
                            if (!active) startService()
                        } }) } }
                        item { Text("Pausar recepción mantiene la conexión y las comprobaciones activas.", style = MaterialTheme.typography.bodySmall) }
                        if (!active) item { Button(onClick = { startService() }) { Text("Activar conexión local") } }
                        item { Text("Dirección local: ${repo.lanIp()}:${repo.port}"); Text("Archivos en almacenamiento privado. Puedes guardarlos en Descargas.") }
                        item { Text("V1 usa HTTP local con autenticación por dispositivo. Las transferencias todavía no están cifradas con TLS.", style = MaterialTheme.typography.bodySmall) }
                    }
                }
            }
        }
        validatingPeer?.let { peer -> AlertDialog(onDismissRequest = { if (peer.deviceId !in checkingConnections) validatingPeer = null },
            title = { Text("Validar conexión con ${peer.name}") }, text = {
                Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    Text("Se comprueban ambos sentidos. Puedes corregir la dirección usando la IP que muestra el otro equipo; se guardará solo si corresponde al vínculo.")
                    OutlinedTextField(connectionIp, { connectionIp = it }, label = { Text("IP local del otro equipo") }, enabled = peer.deviceId !in checkingConnections)
                    OutlinedTextField(connectionPort, { connectionPort = it }, label = { Text("Puerto") }, enabled = peer.deviceId !in checkingConnections)
                    if (peer.deviceId in checkingConnections) { LinearProgressIndicator(Modifier.fillMaxWidth()); Text("Comprobando conexión…") }
                    validationReport?.let { Text(it.summary()) }
                }
            }, confirmButton = { TextButton(enabled = peer.deviceId !in checkingConnections, onClick = { work {
                val portValue = connectionPort.toIntOrNull() ?: throw ProtocolError("INVALID_PORT")
                devicedrop.network.endpoint(connectionIp.trim(), portValue)
                if (!repo.active.value) { startService(); withTimeout(10000) { repo.active.first { it } } }
                validationReport = repo.validateConnection(peer.deviceId,
                    ipOverride = connectionIp.trim().takeUnless { it == peer.ip && portValue == peer.port }, portOverride = portValue)
                repo.dao.peer(peer.deviceId)?.let { connectionIp = it.ip; connectionPort = it.port.toString() }
            } }) { Text("Validar ahora") } }, dismissButton = {
                TextButton(enabled = peer.deviceId !in checkingConnections, onClick = { validatingPeer = null }) { Text("Cerrar") }
            }) }
        if (manual) AlertDialog(onDismissRequest = { manual = false }, title = { Text("Vincular por IP") }, text = { Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedTextField(ip, { ip = it }, label = { Text("IP de tu dispositivo") }); OutlinedTextField(port, { port = it }, label = { Text("Puerto") }); OutlinedTextField(code, { code = it }, label = { Text("Código de 6 dígitos") })
        } }, confirmButton = { TextButton(onClick = { manual = false; work { withContext(Dispatchers.IO) { repo.pair(ip, port.toInt(), code) }; snackbar.showSnackbar("Dispositivo vinculado") } }) { Text("Vincular") } }, dismissButton = { TextButton(onClick = { manual = false }) { Text("Cancelar") } })
        qr?.let { window ->
            var remaining by remember(window) { mutableIntStateOf(120) }
            LaunchedEffect(window) { while (remaining > 0) { delay(1000); remaining = ((window.expires - System.currentTimeMillis()) / 1000).toInt().coerceAtLeast(0) } }
            val bitmap = remember(window) { com.journeyapps.barcodescanner.BarcodeEncoder().encodeBitmap(window.qr, BarcodeFormat.QR_CODE, 500, 500) }
            AlertDialog(onDismissRequest = { qr = null }, title = { Text("Código: ${window.code}") }, text = { Column {
                if (remaining > 0) androidx.compose.foundation.Image(bitmap.asImageBitmap(), "QR de vinculación", Modifier.fillMaxWidth())
                Text("${repo.lanIp()}:45832 · Caduca en ${remaining}s")
            } }, confirmButton = { TextButton(onClick = { qr = null }) { Text("Cerrar") } })
        }
        if (selections.isNotEmpty()) {
            var checked by remember(selections) { mutableStateOf(setOf<String>()) }
            AlertDialog(onDismissRequest = { shared.value = emptyList() }, title = { Text("Enviar ${selections.size} archivos a") }, text = { Column {
                if (trusted.isEmpty()) Text("Vincula primero un dispositivo.")
                trusted.forEach { peer -> Row(verticalAlignment = Alignment.CenterVertically) { Checkbox(peer.deviceId in checked, { yes -> checked = if (yes) checked + peer.deviceId else checked - peer.deviceId }); Text(peer.name) } }
            } }, confirmButton = { TextButton(enabled = checked.isNotEmpty(), onClick = { repo.send(selections, checked.toList()); shared.value = emptyList() }) { Text("Enviar") } }, dismissButton = { TextButton(onClick = { shared.value = emptyList() }) { Text("Cancelar") } })
        }
        approving?.let { offer -> AlertDialog(onDismissRequest = {}, title = { Text("Recibir archivo") }, text = { Text("${trusted.firstOrNull { it.deviceId == offer.peer }?.name ?: "Dispositivo"} quiere enviarte ${offer.meta.filename} (${formatSize(offer.meta.size)}).") },
            confirmButton = { TextButton(onClick = { work { repo.approve(offer.meta.transferId, true) }; approving = null }) { Text("Recibir") } },
            dismissButton = { TextButton(onClick = { work { repo.approve(offer.meta.transferId, false) }; approving = null }) { Text("Rechazar") } }) }
        if (rename || onboarding) AlertDialog(onDismissRequest = { if (!onboarding) rename = false }, title = { Text(if (onboarding) "Bienvenido a FileFastFlow" else "Nombre del dispositivo") }, text = {
            OutlinedTextField(if (onboarding && editedName.isEmpty()) name else editedName, { editedName = it }, label = { Text("Nombre") })
        }, confirmButton = { TextButton(onClick = { work { repo.rename(editedName.ifBlank { name }); repo.dao.setting(devicedrop.database.Setting("onboarded", "true")); onboarding = false; rename = false; startService() } }) { Text(if (onboarding) "Buscar dispositivos" else "Guardar") } })
        preview?.let { transfer -> Dialog(onDismissRequest = { preview = null }, properties = DialogProperties(usePlatformDefaultWidth = false)) {
            Surface(Modifier.fillMaxSize(), color = Color.Black) { Column {
                TextButton(onClick = { preview = null }) { Text("Cerrar · ${transfer.filename}", color = Color.White) }
                AsyncImage(File(transfer.savedPath), transfer.filename, Modifier.fillMaxSize())
            } }
        } }
    }

    private fun openFile(transfer: Transfer) {
        val file = File(transfer.savedPath)
        if (!file.isFile) return
        val uri = FileProvider.getUriForFile(this, "$packageName.files", file)
        try { startActivity(Intent(Intent.ACTION_VIEW).setDataAndType(uri, transfer.mimeType).addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)) }
        catch (_: Exception) { repo.error.value = "No hay una aplicación para abrir este formato." }
    }

    private suspend fun saveDownloads(transfer: Transfer) = withContext(Dispatchers.IO) {
        if (Build.VERSION.SDK_INT < 29) return@withContext
        val values = ContentValues().apply { put(MediaStore.Downloads.DISPLAY_NAME, transfer.filename); put(MediaStore.Downloads.MIME_TYPE, transfer.mimeType); put(MediaStore.Downloads.RELATIVE_PATH, "Download/FileFastFlow"); put(MediaStore.Downloads.IS_PENDING, 1) }
        val uri = contentResolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values) ?: throw ProtocolError("STORAGE_ERROR")
        try {
            contentResolver.openOutputStream(uri)?.use { output -> File(transfer.savedPath).inputStream().use { it.copyTo(output, 1024 * 1024) } } ?: throw ProtocolError("STORAGE_ERROR")
            contentResolver.update(uri, ContentValues().apply { put(MediaStore.Downloads.IS_PENDING, 0) }, null, null)
        } catch (e: Exception) { contentResolver.delete(uri, null, null); throw e }
    }
}

@Composable
private fun TransferCard(transfer: Transfer, peer: String, preview: () -> Unit, open: () -> Unit, cancel: () -> Unit, export: () -> Unit) {
    Card(Modifier.fillMaxWidth()) { Column(Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            if (transfer.mimeType.startsWith("image/") && transfer.savedPath.isNotEmpty() && transfer.status == "completed") {
                AsyncImage(File(transfer.savedPath), transfer.filename, Modifier.size(72.dp).clickable(onClick = preview)); Spacer(Modifier.width(12.dp))
            } else { Icon(Icons.Outlined.InsertDriveFile, null); Spacer(Modifier.width(12.dp)) }
            Column { Text(transfer.filename, style = MaterialTheme.typography.titleMedium); Text("${formatSize(transfer.size)} · ${if (transfer.direction == "incoming") "←" else "→"} $peer", style = MaterialTheme.typography.bodySmall) }
        }
        Text("${transfer.status} · ${java.text.SimpleDateFormat("dd/MM HH:mm", java.util.Locale.getDefault()).format(java.util.Date(transfer.startedAt))}", style = MaterialTheme.typography.bodySmall)
        if (transfer.status !in listOf("completed", "failed", "cancelled")) {
            LinearProgressIndicator(progress = { if (transfer.size == 0L) 0f else transfer.bytesDone.toFloat() / transfer.size }, modifier = Modifier.fillMaxWidth())
            Text("${formatSize(transfer.speed.toLong())}/s"); TextButton(onClick = cancel) { Text("Cancelar") }
        }
        if (transfer.savedPath.isNotEmpty() && transfer.status == "completed") {
            if (transfer.mimeType.startsWith("image/")) {
                val dimensions = remember(transfer.savedPath) { android.graphics.BitmapFactory.Options().apply { inJustDecodeBounds = true; android.graphics.BitmapFactory.decodeFile(transfer.savedPath, this) } }
                Text("${dimensions.outWidth} × ${dimensions.outHeight} px", style = MaterialTheme.typography.bodySmall)
            }
            Row { TextButton(onClick = if (transfer.mimeType.startsWith("image/")) preview else open) { Text("Abrir") }; TextButton(onClick = export) { Text("Guardar en Descargas") } }
        }
        if (transfer.error.isNotEmpty()) Text(transfer.error, color = MaterialTheme.colorScheme.error)
    } }
}

fun formatSize(bytes: Long): String {
    var number = bytes.toDouble()
    for (unit in listOf("B", "KB", "MB", "GB")) { if (number < 1024 || unit == "GB") return "%.1f %s".format(number, unit); number /= 1024 }
    return "$bytes B"
}
