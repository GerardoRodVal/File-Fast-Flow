# FileFastFlow · LAN v0.3.0

Aplicaciones nativas para compartir archivos entre Windows y Android en la misma
red. Sin cuentas, nube ni servidor externo. Ambas aplicaciones pueden enviar y
recibir; cada una ejecuta su propio servidor HTTP.

**Estado:** implementación funcional de V1 con pruebas automatizadas y compilación
Android. La aceptación final en un teléfono físico sigue pendiente; no se declara
cerrada la Definition of Done completa sin esa prueba. El tráfico usa **HTTP sin
cifrado TLS**, protegido por una credencial distinta para cada vínculo.

## Actualizaciones entre PCs

Instala FileFastFlow en ambas PCs. En **Actualizaciones** puedes buscar, descargar e instalar nuevas versiones. **Configuración → Buscar actualizaciones y avisar automáticamente** está activado por defecto: la aplicación consulta GitHub al iniciar y cada 30 minutos mientras esté abierta o en la bandeja.

Cada `git push origin main` ejecuta las pruebas, compila los paquetes y publica una nueva [versión descargable](https://github.com/GerardoRodVal/File-Fast-Flow/releases/latest). Los cambios locales llegan a las otras PCs después de publicarse. Necesitas Internet para recibir el aviso y descargar. Consulta [el flujo de actualización y compatibilidad](docs/updates.md).

## Ejecutar Windows desde el código

Requisitos: Windows 10/11 x64 y Python 3.12 o posterior.
Desde la carpeta `windows`:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m devicedrop.main
```

Alternativa sin activar el entorno:

```powershell
.venv\Scripts\python.exe -m devicedrop.main
```

PySide6 se fija en 6.8.3 para mantener una versión estable de Qt al empaquetar.
Las versiones exactas probadas están en `windows/requirements.lock.txt`.

La primera ejecución pide nombre y carpeta de recibidos. Por defecto:

| Uso | Ubicación |
|---|---|
| Recibidos | `%USERPROFILE%\Downloads\FileFastFlow` |
| Carpeta compartida | `%USERPROFILE%\FileFastFlow` |
| Base de datos | `%LOCALAPPDATA%\FileFastFlow\devicedrop.db` |
| Logs con rotación | `%LOCALAPPDATA%\FileFastFlow\logs\devicedrop.log` |

Para aislar una ejecución de desarrollo sin escribir en esas carpetas:

```powershell
python -m devicedrop.main --data-dir C:\ruta\de\pruebas --port 45832
```

`--headless` ejecuta únicamente los servicios; Ctrl+C los cierra.
`--smoke-test --data-dir <carpeta>` abre la UI, comprueba el servidor, guarda
`smoke_result.json` y una captura, y cierra la aplicación.

## Compilar e instalar Android

Abre `android/` en Android Studio. Usa su JDK integrado y un SDK Android 35.
La aplicación requiere **Android 8.0/API 26 o posterior**.

```powershell
cd android
.\gradlew.bat assembleDebug
.\gradlew.bat testDebugUnitTest
```

En Linux/macOS: `chmod +x gradlew` y `./gradlew assembleDebug`.
La primera compilación descarga herramientas y dependencias; el funcionamiento
de la aplicación no requiere Internet.

APK generado: `android/app/build/outputs/apk/debug/app-debug.apk`.
Una copia de entrega se guarda en `releases/FileFastFlow-0.3.0-debug.apk`.
Es un APK de desarrollo firmado con la clave debug, no una publicación en Play.

Con un teléfono conectado y depuración USB autorizada:

```powershell
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

Permite notificaciones y cámara cuando uses el escáner. La recepción mantiene
una notificación de servicio activo. Desde Ajustes puedes detenerla.

## Vincular y compartir

1. Conecta ambos dispositivos a la misma LAN y abre FileFastFlow en ambos.
2. En Windows entra en Dispositivos → Mostrar código / QR.
3. En Android escanea el QR, o elige la PC descubierta e introduce el código.
   También puedes indicar manualmente la IP y el puerto mostrados por Windows.
4. El código/QR caduca en 120 segundos y sirve una sola vez. El vínculo persiste.
5. En Windows selecciona o arrastra archivos y elige uno o varios destinos.
   En Android usa Enviar archivo o Compartir → FileFastFlow desde otra aplicación.
6. El historial muestra estado, tamaño y progreso. Los archivos de imagen tienen
   miniatura, resolución y vista ampliada.

Android puede mostrar su propio código/QR para que Windows inicie la vinculación.
Windows permite introducir el código por IP o pegar el JSON del QR.
Al desactivar Aceptar automáticamente en un vínculo, el receptor solicita
aprobación antes de recibir el contenido.

En Android los archivos quedan inicialmente en almacenamiento privado. Guardar
en Descargas usa MediaStore en Android 10+; Android 8/9 usa el selector de
documentos del sistema, sin permisos de almacenamiento obsoletos.

## Sincronizar una carpeta

Activa Auto Sync en el dispositivo confiable dentro de Windows. Un archivo nuevo
en la carpeta compartida se envía cuando el destino está online y se han observado
3 segundos de tamaño y fecha estables. En Windows se comprueba también que no
haya un escritor manteniendo el archivo abierto.

V1 sincroniza únicamente eventos `created`. Registra los demás eventos del
watcher, pero no replica modificaciones, movimientos ni eliminaciones. Si el
destino está offline cuando se detecta el archivo, el archivo no se encola para
sincronización futura: puedes enviarlo manualmente cuando vuelva a conectarse.
La carpeta compartida y la de recibidos deben estar separadas. El registro
processed_files evita volver a exportar archivos recibidos.

## Compilar el EXE

Desde `windows/`, con el entorno instalado, prepara el APK de esta versión y una
copia portátil de Inno Setup 6.7.3 (consulta `docs/installers.md`):

```powershell
python scripts/build_windows.py --apk ../releases/FileFastFlow-0.3.0-debug.apk --inno-dir C:\herramientas\InnoSetup
```

Las siguientes compilaciones pueden usar `python scripts/build_windows.py` una
vez que los recursos estén preparados. Actualiza `--apk` si cambia Android.

Resultado onedir: `windows/dist/FileFastFlow/FileFastFlow.exe` junto con `_internal/`.
**Conserva la carpeta completa**; el EXE por sí solo no contiene sus dependencias.
La entrega portátil comprimida está en `releases/FileFastFlow-Windows-x64.zip`.
El instalador está en `releases/FileFastFlow-0.3.0-Setup.exe`. No tiene firma de
código comercial. Instala para el usuario actual, ofrece acceso directo en el
escritorio y permite desinstalar desde Configuración de Windows.

## Generar instaladores desde la aplicación

En Windows abre **Instaladores** en el menú lateral:

- **Generar instalador EXE para Windows**: elige dónde guardar el EXE. Se crea
  un instalador completo de la aplicación que estás ejecutando, con sus recursos.
- **Generar APK para Android**: elige dónde guardar el APK de esta versión,
  incluido en la aplicación y verificado con SHA-256. Es un APK de desarrollo.

Ambos botones funcionan sin Internet, Python, JDK ni Android Studio en la PC del
usuario. La ventana muestra el progreso y permite abrir la carpeta del archivo.
Guarda los paquetes fuera de la carpeta de FileFastFlow. El botón Android exporta
el binario incluido; para compilar cambios de código Android usa Gradle y vuelve
a empaquetar Windows con el nuevo APK.

## Puertos y firewall

TCP **45832** por defecto. Windows permite 45000–45999 en Configuración; hay que
reiniciar para cambiar el puerto, la carpeta compartida y el anuncio mDNS.
Android usa 45832 fijo en V1. mDNS usa UDP 5353 y el servicio
`_devicedrop._tcp.local.`. Las pruebas usan también 45833 y 45981–45986.

Permite FileFastFlow/Python en **redes privadas** desde Firewall de Windows.
No se modifican reglas ni se ejecutan comandos privilegiados automáticamente.
Si no aparecen dispositivos, prueba la vinculación por IP. Redes de invitados,
aislamiento entre clientes Wi-Fi, VPN y algunos routers pueden impedir la LAN
o el multicast. El historial muestra errores comprensibles y los logs técnicos
no guardan tokens.

## Arquitectura y estructura

```text
FileFastFlow/
├── README.md · PROTOCOL.md · SECURITY.md
├── docs/                 arquitectura, pairing, desarrollo, verificación
├── windows/
│   ├── devicedrop/
│   │   ├── main.py · runtime.py
│   │   ├── ui/           PySide6, páginas, bandeja y drag & drop
│   │   ├── network/      FastAPI, mDNS, multipart y WebSocket
│   │   ├── pairing/      ventana temporal y credenciales
│   │   ├── security/     nombres, hashes y publicación segura
│   │   ├── storage/      modelos Pydantic y SQLite
│   │   └── sync/         watchdog y estabilidad
│   ├── tests/ · scripts/
│   └── dist/FileFastFlow/  compilado local, ignorado por Git
├── android/
│   ├── gradlew · gradlew.bat · gradle/wrapper/
│   └── app/src/
│       ├── main/java/devicedrop/
│       │   ├── MainActivity.kt · DropRepository.kt
│       │   └── database/ · discovery/ · network/ · service/
│       └── test/         protocolo, repositorio e interoperabilidad
└── releases/             paquetes de entrega y verificación
```

Windows usa un hilo dedicado para asyncio/Uvicorn. Qt recibe señales; hashing,
transferencias y observación de carpeta no se ejecutan en el hilo visual.
Android usa Compose/Material 3, Coroutines, Room, OkHttp y un servidor Ktor CIO.
Ktor añade el servidor HTTP/WebSocket nativo que necesita Android para recibir.
NSDManager anuncia y descubre; un heartbeat cada 12 segundos actualiza online.
SQLite y Room guardan únicamente metadata, nunca los binarios.

## Pruebas y alcance real

```powershell
cd windows
python -m pytest -q
```

Consulta `docs/verification.md` para los resultados finales y cómo repetir la
integración. Se verificaron transferencias reales sobre TCP entre el código
Windows y el código Android ejecutado con Robolectric, incluido un archivo de
100 MiB en cada sentido. Esto no sustituye una prueba en hardware Android.

Implementado: identidad persistente, pairing, credenciales por relación,
rechazo de dispositivos desconocidos, ofertas con aprobación, streaming y
SHA-256, temporales con limpieza, colisiones, progreso/velocidad, historial,
reintentos, cancelación, mDNS y heartbeat, carpeta compartida, UI nativas,
bandeja, Share Sheet, notificaciones y almacenamiento moderno.

Pendiente de aceptación en hardware: descubrimiento mutuo real por Wi-Fi,
escaneo con cámara, Share Sheet de otras aplicaciones, notificaciones con
permisos reales y continuidad del servicio según fabricante/batería.
Pendiente de futuras versiones: TLS, reanudación, carpetas ZIP, menú contextual,
sincronización de archivos modificados y recuperación de sync offline.
El protocolo admite hasta 16 GiB por archivo; se probaron 100 MiB, no varios GB.

Sin cuentas, nube, acceso remoto, mensajes, VPN, clipboard ni otros extras de V2.
Repositorio oficial: [GerardoRodVal/File-Fast-Flow](https://github.com/GerardoRodVal/File-Fast-Flow). Desarrollo y publicación desde `main`.
