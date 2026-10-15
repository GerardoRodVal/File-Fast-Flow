# FileFastFlow · LAN v0.4.0

Aplicaciones nativas para compartir archivos entre Windows y Android en la misma
red. Sin cuentas, nube ni servidor externo. Ambas aplicaciones pueden enviar y
recibir; cada una ejecuta su propio servidor HTTP.

**Estado:** implementación funcional de V1 con pruebas automatizadas y compilación
Android. La aceptación final en un teléfono físico sigue pendiente; no se declara
cerrada la Definition of Done completa sin esa prueba. El tráfico usa **HTTP sin
cifrado TLS**, protegido por una credencial distinta para cada vínculo.

## Actualizaciones en Windows y Android

Instala FileFastFlow en ambas PCs. En **Instaladores y actualizaciones** puedes buscar, descargar e instalar nuevas versiones. **Configuración → Buscar actualizaciones y avisar automáticamente** está activado por defecto: la aplicación consulta GitHub al iniciar y cada 30 minutos mientras esté abierta o en la bandeja.

En Android, **Ajustes → Actualizaciones** permite buscar, descargar el APK verificado
y abrir el instalador. La búsqueda automática está activada inicialmente: comprueba
al abrir la aplicación y aproximadamente cada 30 minutos en segundo plano mediante
WorkManager, aunque la conexión LAN esté detenida. Permite las notificaciones del
teléfono. Android puede retrasar la tarea por ahorro de batería.

Cada `git push origin main` ejecuta las pruebas, compila los paquetes y publica una nueva [versión descargable](https://github.com/GerardoRodVal/File-Fast-Flow/releases/latest). Los cambios locales llegan a las PCs y teléfonos después de publicarse. Necesitas Internet para recibir el aviso y descargar. Consulta [el flujo de actualización y compatibilidad](docs/updates.md) y [el historial de cambios](CHANGELOG.md).

Instala una vez el APK **0.4.0 o posterior** para activar los avisos en Android.
Los APK anteriores no contienen el actualizador y necesitan esta primera instalación
manual. Las siguientes actualizaciones se instalan encima, con confirmación de Android.

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

El acceso directo de desarrollo del escritorio abre el código actual con
`windows/scripts/launch_desktop.pyw` y las dependencias del entorno `.venv`, sin
consola. Usa directamente el intérprete base del entorno para mantener un solo
proceso, evitando el redirector de Windows.
Para crearlo o restaurarlo desde la raíz del proyecto:

```powershell
powershell -ExecutionPolicy Bypass -File windows/scripts/update_desktop_shortcut.ps1
```

Después de modificar el código, sal de FileFastFlow desde la bandeja y vuelve a
abrir el acceso directo para cargar los cambios.

Si una entrega empaquetada está abierta, puedes preparar otra sin sobrescribirla:
`python scripts/build_windows.py --dist-dir dist/updates-0.4.0` desde `windows/`.
El generador de EXE desde el código utiliza esa carpeta cuando contiene la versión
actual completa; las instalaciones empaquetadas utilizan su propia carpeta.

FileFastFlow mantiene una sola instancia por carpeta de datos. Volver a abrir
el acceso directo restaura la ventana existente. Cerrar la ventana la deja
funcionando en segundo plano; para terminarla, usa **Salir** desde la bandeja.
Un clic o doble clic en el icono de la bandeja vuelve a abrir la ventana
principal. Si no hay una instancia en ejecución, el acceso directo inicia una
nueva y muestra su ventana.

El **widget de escritorio** muestra los dispositivos vinculados, una bolita de
estado y accesos rápidos para validar la conexión o seleccionar archivos para
enviar a cada equipo. El icono de carpeta abre el espacio local de archivos
compartidos de ese dispositivo, incluso si está desconectado.
Verde significa conectado; rojo, sin conexión; ámbar,
validando, conexión parcial o recepción remota pausada; gris, sin comprobar.
Se activa por defecto y está anclado al escritorio de Windows, debajo de las
demás aplicaciones; permanece allí al mostrar el escritorio o al ocultar la
ventana principal en la bandeja. No aparece como ventana independiente en Alt+Tab.
En el menú **Widget → Activar widget de escritorio** puedes activarlo o
desactivarlo al instante; también desde el menú de la bandeja. Arrastra su
encabezado para moverlo: la posición y la preferencia se conservan al reiniciar.
En **Widget → Tema del widget** elige una tarjeta de la cuadrícula con una vista previa real.
Puedes seleccionar **Clásico**, que sigue los colores de la app,
o **Minimalista · estilo Disks**, un panel oscuro translúcido con una fila compacta
por dispositivo. El cambio se aplica al instante y se guarda. En Minimalista,
pasa el cursor sobre la bolita para ver el estado y haz doble clic en el
encabezado para abrir la ventana principal.

La primera ejecución pide nombre y una única **Carpeta recepción**. Por defecto:

| Uso | Ubicación |
|---|---|
| Carpeta recepción / General | `%USERPROFILE%\filefastflow` |
| Por dispositivo | `%USERPROFILE%\filefastflow\<Nombre del dispositivo>` |
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
Una copia de entrega se guarda en `releases/FileFastFlow-0.4.0-debug.apk`.
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
   Esta pestaña muestra el equipo principal en el centro y los demás como
   burbujas con nombre, plataforma, IP y estado. Verde indica conexión, rojo
   desconexión, ámbar atención o validación y gris un estado sin comprobar o
   sin vincular. Usa **Validar** en cada burbuja y **Opciones** para corregir la
   dirección, cambiar la aceptación de archivos o desvincular. Los equipos cercanos sin vínculo
   permiten iniciar la vinculación desde su burbuja.
3. En Android escanea el QR, o elige la PC descubierta e introduce el código.
   También puedes indicar manualmente la IP y el puerto mostrados por Windows.
4. El código/QR caduca en 120 segundos y sirve una sola vez. El vínculo persiste.
5. En Windows, Inicio muestra **General** y un espacio por dispositivo vinculado.
   Arrastra o selecciona archivos en General para enviarlos a todos, o en un
   espacio individual para enviarlos solo a ese dispositivo. Se guarda una copia
   local en cada espacio; puedes abrirla con doble clic o usar **Abrir carpeta**.
   **Enviar guardados** permite reenviarlos cuando un dispositivo vuelve a estar
   conectado o después de vincular uno nuevo. El progreso y los errores de envío
   aparecen en Transferencias recientes de Inicio. General guarda los archivos
   directamente en `%USERPROFILE%\filefastflow` (en esta PC, `C:\Users\gerar\filefastflow`).
   Cada dispositivo tiene una subcarpeta con su nombre. Las copias de los espacios
   anteriores se migran conservando los archivos y resolviendo nombres repetidos
   sin sobrescribir. La recepción usa esa misma raíz: archivos generales al nivel
   de las subcarpetas, archivos individuales dentro de la carpeta del remitente.
   Cada vínculo accede a los archivos generales y a sus archivos individuales;
   nunca al interior de las carpetas de otros dispositivos.
   En Android usa Enviar archivo o Compartir → FileFastFlow desde otra aplicación.
6. Transferencias recientes en Inicio muestra estado, tamaño y progreso. Los archivos de imagen tienen
   miniatura, resolución y vista ampliada.
   En Windows, la notificación de un archivo recibido incluye **Copiar** para
   pegarlo directamente con Ctrl+V. Las imágenes se ofrecen también como imagen
   en el portapapeles. Puedes usar **Copiar** en Transferencias recientes,
   **Copiar último archivo recibido** en la bandeja o **Ctrl+Shift+C** cuando
   FileFastFlow está en primer plano. La acción de la notificación reutiliza la
   instancia abierta sin mostrar la ventana; si saliste de la app, la inicia en
   segundo plano para copiar el archivo correspondiente.

Android puede mostrar su propio código/QR para que Windows inicie la vinculación.
Windows permite introducir el código por IP o pegar el JSON del QR.
Al desactivar Aceptar automáticamente en un vínculo, el receptor solicita
aprobación antes de recibir el contenido.

En Android los archivos quedan inicialmente en almacenamiento privado. Guardar
en Descargas usa MediaStore en Android 10+; Android 8/9 usa el selector de
documentos del sistema, sin permisos de almacenamiento obsoletos.

## Sincronizar una carpeta

Coloca archivos directamente en Carpeta recepción para compartirlos con todos
los dispositivos vinculados, o dentro de una subcarpeta de dispositivo para
compartirlos solo con ese equipo. El envío comienza cuando el destino está online
y el archivo está estable. En Windows se comprueba también que no haya un
escritor manteniendo el archivo abierto.

Una revisión periódica recupera archivos pendientes cuando un equipo vuelve a
conectarse. El registro de entregas evita duplicar los envíos del observador y
la interfaz. Los archivos recibidos no se reexportan automáticamente, evitando
ciclos. Las modificaciones de archivos locales se envían como una nueva copia;
no se replican eliminaciones ni se sobrescriben archivos del receptor.

## Compilar el EXE

En **Instaladores y actualizaciones → Actualizar todos los dispositivos**, la PC
que tiene este proyecto puede compilar y distribuir sus cambios locales por LAN.
Prepara Android y Windows desde una copia del código, verifica los paquetes y
envía a cada dispositivo vinculado el formato correspondiente. No requiere
publicar los cambios en GitHub. La primera preparación necesita las herramientas
de desarrollo de Windows y Android; puede necesitar Internet para sus dependencias.

Activa **Preparar y enviar automáticamente cuando cambie el código** para revisar
los cambios cada 30 segundos y compilar cuando se hayan estabilizado. Los equipos
sin conexión quedan pendientes y se reintenta al reconectar. El panel distingue
«Recibido · falta instalar» de «Actualizado», que requiere que el equipo confirme
la revisión ejecutada. En cada destino pulsa **Instalar cambios recibidos de mi
PC**; Android pide la confirmación del instalador del sistema. En versiones
antiguas, abre el EXE/APK recibido para instalar por primera vez esta función.

Desde `windows/`, con el entorno instalado, prepara el APK de esta versión y una
copia portátil de Inno Setup 6.7.3 (consulta `docs/installers.md`):

```powershell
python scripts/build_windows.py --apk ../releases/FileFastFlow-0.4.0-debug.apk --inno-dir C:\herramientas\InnoSetup
```

Las siguientes compilaciones pueden usar `python scripts/build_windows.py` una
vez que los recursos estén preparados. Actualiza `--apk` si cambia Android.

Resultado onedir: `windows/dist/FileFastFlow/FileFastFlow.exe` junto con `_internal/`.
**Conserva la carpeta completa**; el EXE por sí solo no contiene sus dependencias.
La entrega portátil comprimida está en `releases/FileFastFlow-Windows-x64.zip`.
El instalador está en `releases/FileFastFlow-0.4.0-Setup.exe`. No tiene firma de
código comercial. Instala para el usuario actual, ofrece acceso directo en el
escritorio y permite desinstalar desde Configuración de Windows.

## Generar instaladores desde la aplicación

En Windows abre **Instaladores y actualizaciones** en el menú lateral:

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
sincronización bidireccional de modificaciones y eliminaciones entre plataformas.
El protocolo admite hasta 16 GiB por archivo; se probaron 100 MiB, no varios GB.

Sin cuentas, nube, acceso remoto, mensajes, VPN, clipboard ni otros extras de V2.
Repositorio oficial: [GerardoRodVal/File-Fast-Flow](https://github.com/GerardoRodVal/File-Fast-Flow). Desarrollo y publicación desde `main`.
