# Desarrollo

Python 3.12+, PySide6 6.8.3, FastAPI, Uvicorn, WebSockets, python-multipart,
httpx, watchdog, zeroconf, qrcode/Pillow, cryptography, SQLite y PyInstaller.
Android: Kotlin 2.2.20, AGP 8.11.1, Gradle 8.14, JDK 17+, API 35, Compose/
Material 3, Coroutines, Room 2.7.2, OkHttp 4.12.0, Ktor CIO 3.2.1, ZXing y Coil.
Robolectric/JUnit verifican Android sin un dispositivo físico.

El wrapper y su distribución se verifican con SHA-256 oficial. Los repositorios
de dependencias son Google Maven, Maven Central y Gradle Plugin Portal.
No se incluyen SDK, JDK, entornos virtuales ni caches en el repositorio.

Para ejecutar Windows: `python scripts/run_dev.py`. Para empaquetar:
`python scripts/build_windows.py`. Para Android: `gradlew.bat assembleDebug`.
Consulta README.md para los comandos completos y rutas de datos.

## Integración Python/Kotlin reproducible

En una terminal, desde windows, define una carpeta temporal **vacía** y ejecuta:

```powershell
python -m scripts.interop_fixture C:\ruta\temporal\interop
```

Sin demora, en otra terminal desde android:

```powershell
$env:DEVICEDROP_INTEROP_DIR='C:\ruta\temporal\interop'
.\gradlew.bat testDebugUnitTest --tests devicedrop.InteropTest
Remove-Item Env:DEVICEDROP_INTEROP_DIR
```

Requiere 45832 y 45833 libres. Si es la primera compilación, compila/testea antes
de iniciar el fixture: el código de pairing caduca en 120 segundos. El fixture
escribe un código temporal en esa carpeta, lo elimina al salir y genera
finished.json con la verificación de seis transferencias. No compartas esa
carpeta mientras la prueba está activa. InteropTest se omite en la suite habitual
si no se proporciona la variable; no se cuenta esa omisión como integración pasada.

Las pruebas Android no sustituyen comprobar NSD, permisos, cámara y límites de
servicio foreground sobre un teléfono. No hay un dispositivo conectado en el
entorno de entrega. La prueba de aceptación manual está en verification.md.

## Extensiones futuras

El protocolo versionado admite endpoints adicionales para resume/Range, nuevos
transportes cifrados y discovery alternativo. Mantener el UUID como identidad,
la metadata separada del archivo y los temporales antes de publicación. No añadir
servicios cloud ni V2 sin revisar expresamente el alcance.

Referencias técnicas: [compatibilidad de AGP 8.11](https://developer.android.com/build/releases/agp-8-11-0-release-notes),
[streaming de solicitudes Ktor](https://ktor.io/docs/requests.html),
[despliegue PyInstaller con Qt](https://doc.qt.io/qtforpython-6/deployment/deployment-pyinstaller.html).
