package devicedrop.updates

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.provider.Settings
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.FileProvider
import devicedrop.BuildConfig
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.launch
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File

@Composable
fun UpdatesScreen(context: Context, updates: AppUpdates) {
    val state by updates.state.collectAsState()
    val localPackage by updates.localPackage.collectAsState()
    val scope = rememberCoroutineScope()
    var automatic by remember { mutableStateOf(updates.enabled) }
    var downloading by remember { mutableStateOf(false) }
    var downloaded by remember(state.release) { mutableStateOf<File?>(null) }
    var message by remember { mutableStateOf("") }
    Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Text("Actualizaciones", style = MaterialTheme.typography.headlineMedium)
        Text("Versión instalada: ${BuildConfig.VERSION_NAME}")
        Text("Se buscan versiones al abrir la aplicación y aproximadamente cada 30 minutos en segundo plano. Necesitas Internet; el ahorro de batería puede retrasar el aviso.")
        Row { Text("Buscar y avisar automáticamente", Modifier.weight(1f)); Switch(automatic, { automatic = it; updates.setEnabled(it) }) }
        if (!NotificationManagerCompat.from(context).areNotificationsEnabled()) {
            Text("Permite las notificaciones para recibir avisos de nuevas versiones.")
            TextButton(onClick = { context.startActivity(Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(Settings.EXTRA_APP_PACKAGE, context.packageName)) }) { Text("Permitir notificaciones") }
        }
        Button(enabled = !state.checking && !downloading, onClick = {
            message = ""
            scope.launch { try { updates.check() } catch (error: CancellationException) { throw error } catch (_: Exception) { } }
        }) { Text("Buscar actualizaciones") }
        Text(state.message)
        localPackage?.let { (file, release) ->
            Text("Cambios locales de tu PC recibidos. Listos para instalar.")
            Button(onClick = {
                scope.launch { try {
                    withContext(Dispatchers.IO) { verifyApk(file, release) }
                    if (!context.packageManager.canRequestPackageInstalls()) {
                        context.startActivity(Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:${context.packageName}")))
                        message = "Permite instalar desde FileFastFlow y vuelve a pulsar Instalar."
                    } else {
                        val uri = FileProvider.getUriForFile(context, "${context.packageName}.files", file)
                        context.startActivity(Intent(Intent.ACTION_VIEW).setDataAndType(uri, "application/vnd.android.package-archive")
                            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION))
                    }
                } catch (error: CancellationException) { throw error }
                catch (_: Exception) { message = "No se pudo verificar o abrir el instalador local." } }
            }) { Text("Instalar cambios de mi PC") }
        }
        if (state.checking || downloading) LinearProgressIndicator(Modifier.fillMaxWidth())
        state.release?.let { release ->
            if (release.notes.isNotBlank()) Text(release.notes)
            if (downloaded == null) Button(enabled = !downloading && !state.checking, onClick = {
                downloading = true; message = "Descargando actualización…"
                scope.launch {
                    try { downloaded = updates.download(release); message = "Descarga verificada. Pulsa Instalar actualización." }
                    catch (error: CancellationException) { throw error }
                    catch (_: Exception) { message = "No se pudo descargar y verificar el APK. Inténtalo de nuevo." }
                    finally { downloading = false }
                }
            }) { Text("Descargar actualización") }
            downloaded?.let { file -> Button(onClick = {
                scope.launch { try {
                    withContext(Dispatchers.IO) { verifyApk(file, release) }
                    if (!context.packageManager.canRequestPackageInstalls()) {
                        context.startActivity(Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:${context.packageName}")))
                        message = "Permite instalar desde FileFastFlow y vuelve a pulsar Instalar actualización."
                    } else {
                        val uri = FileProvider.getUriForFile(context, "${context.packageName}.files", file)
                        context.startActivity(Intent(Intent.ACTION_VIEW).setDataAndType(uri, "application/vnd.android.package-archive")
                            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION))
                    }
                } catch (error: CancellationException) { throw error }
                catch (_: Exception) { downloaded = null; message = "No se pudo abrir el instalador. Vuelve a descargar la actualización." } }
            }) { Text("Instalar actualización") } }
        }
        if (message.isNotEmpty()) Text(message)
        TextButton(onClick = {
            try { context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(RELEASES_URL))) }
            catch (_: Exception) { message = "No se encontró un navegador para abrir las versiones publicadas." }
        }) { Text("Ver versiones publicadas") }
    }
}
