# Verificación de entrega · actualizada el 4 de octubre de 2026

La V1 está implementada, pero su aceptación completa requiere pruebas sobre un
teléfono Android físico. No había teléfono ni emulador conectado; no se marca
la Definition of Done completa como cerrada.

## FileFastFlow y actualizaciones desde GitHub · 4 de octubre

- Suite completa Windows: **59 pruebas pasadas**. Después de los ajustes finales, 18 pruebas de interfaz y paquetes pasadas y 14 pruebas de actualizaciones y migración pasadas.
- Android: `assembleDebug` y 9 pruebas unitarias pasadas. Se conserva la aceptación pendiente en teléfono físico.
- Ejecutable FileFastFlow reconstruido. Interfaz nativa de Windows y servidor LAN comprobados con `--smoke-test`.
- `--package-smoke-test` ejecutó ambos botones: instalador EXE de 112,031,758 bytes y APK de 21,155,750 bytes; ambos éxitos y salida 0.
- Búsqueda de Releases, comparación numérica, descarga HTTPS con redirección, integridad SHA-256, cancelación, conservación del destino, aviso por versión y reutilización de datos DeviceDrop comprobados.
- La primera ejecución remota del workflow se comprobará después de subir `main`.

## Verificaciones anteriores

## Actualización: botones para instaladores · 4 de octubre

- Suite completa Windows: **38 pruebas pasadas**, incluidas cuatro nuevas sobre
  exportación del APK, verificación SHA-256, protección del archivo anterior ante
  errores, rechazo de destinos dentro de la app, rutas con espacios y botones Qt.
- EXE reconstruido con PySide6 6.8.3. Los dos botones se ejecutaron desde el
  EXE empaquetado: crearon un instalador de 89,709,561 bytes y el APK incluido
  de 21,262,178 bytes. `package_smoke_result.json` declara ambos éxitos; exit 0.
- Instalador Inno Setup 6.7.3 real: instalación silenciosa en una carpeta aislada,
  generación de ambos paquetes desde la copia instalada, desinstalación correcta
  y eliminación de su entrada de registro. Sin crear accesos directos de prueba.
- El nuevo EXE al que apunta el acceso directo pasó la prueba de arranque de UI
  y servicio LAN: `ui_started=true`, `server_started=true`, exit 0.
- Compilador obtenido de su distribución oficial y firma Authenticode verificada
  como válida, con emisor Pyrsys B.V. Su licencia se conserva entre los recursos.
- El APK exportado es el binario debug ya compilado; no se recompila Android al
  pulsar el botón. La aceptación en teléfono físico sigue pendiente.

La captura `installers-preview.png` corresponde a la página de la aplicación
empaquetada. La app anterior estaba abierta; la actualización se dejó en
`windows/dist/FileFastFlow-Installers` y se actualizó el acceso directo del escritorio
para abrir esa carpeta. La sesión anterior no se interrumpió.

## Entorno

- Windows 11 x64; Python 3.12.14; PySide6 6.8.3.
- Android SDK 35; JDK de Android Studio 21.0.10; Gradle 8.14; Kotlin 2.2.20.
- Android API 34 simulado por Robolectric para pruebas de lógica/Room.
- Aplicación Android compilada con minSdk 26, targetSdk/compileSdk 35.

## Resultados comprobados

| Verificación | Resultado y alcance |
|---|---|
| Suite Windows | 38 tests: hashes, pairing, nombres, colisiones, SQLite, metadata, auth, ofertas, espacio, corrupción, cancelación, watcher, sync, UI e instaladores |
| Suite Android habitual | 8 tests pasados; InteropTest omitido si no hay fixture externo |
| Integración Python ↔ Kotlin | InteropTest ejecutado por separado y pasado: 6 transferencias sobre TCP loopback |
| Texto e imagen | small.txt y photo.jpg recibidos y enviados con el mismo SHA-256 |
| Archivo grande | 100MB.bin = 104,857,600 bytes; mismo SHA-256 en ambos sentidos |
| mDNS Windows ↔ Windows | Dos servicios reales se anuncian y descubren en el mismo host |
| Auto Sync Windows | Archivo nuevo detectado por watchdog y enviado por TCP; verificación SHA-256; sin retorno automático |
| Integridad/seguridad HTTP | Rechazo sin token, oferta requerida, hash incorrecto, tamaño incorrecto, espacio insuficiente y pausa de recepción |
| UI Windows | Arranque Qt, drag & drop de archivos locales hacia selección de destino y cierre a bandeja comprobados automáticamente |
| EXE | PyInstaller onedir; arranque de UI/servidor y cierre automático con exit code 0 |
| APK | assembleDebug correcto; paquete APK debug generado |

La comprobación del EXE guarda `ui_started=true` y `server_started=true` en
smoke_result.json y termina el proceso. La captura `windows-preview.png` procede
de la UI real. Los resultados de interoperabilidad están en interop-result.json.

Ejecutar todos los tests Android sin DEVICEDROP_INTEROP_DIR produce una omisión
intencional de InteropTest: ese resultado no se presenta como integración pasada.
La integración se verificó en una ejecución aparte con ambos servidores activos.

Las pruebas mDNS de Windows en un mismo host no certifican NSD ni multicast entre
Windows y un teléfono sobre un router real. Las pruebas de UI automatizadas no
certifican la integración con otras aplicaciones Android.

## Correcciones verificadas durante desarrollo

- Se corrigió un conflicto de import de CancellationException al compilar Ktor.
- Los temporales y la reserva de un upload se liberan solo por su propietario,
  impidiendo que un upload duplicado borre un archivo que otro está recibiendo.
- Las rutas locales se excluyen de los eventos WebSocket remotos.
- Se corrigió el tratamiento de file:// URI en el emisor Android y su error de
  nombre de archivo; la integración bidireccional volvió a ejecutarse con éxito.
- Qt 6.11.2 falló al cargar DLL en el ejecutable congelado. Se fijó Qt/PySide6
  6.8.3, se reconstruyó y se comprobó el EXE.
- Uvicorn no configura un logger que dependa de stdout en un EXE sin consola.
- Se comprueba un escritor abierto en Windows antes de declarar un archivo
  estable para Auto Sync.
- Las pruebas finales usan temporales dentro de work para evitar permisos
  distintos entre ejecuciones del entorno.
- La prueba mDNS se ejecuta con multicast permitido; con el aislamiento de red
  del entorno no llegaban los anuncios, y al retirarlo discovery pasó.

## Aceptación pendiente en hardware

1. Instalar el APK en un teléfono Android 8+ y abrir la app Windows.
2. Confirmar discovery mutuo sin escribir IP y después probar IP manual.
3. Vincular con QR/código, cerrar ambas apps y verificar que el vínculo persista.
4. Enviar small.txt, photo.jpg y 100MB.bin en ambos sentidos; comparar SHA-256.
5. Compartir desde Galería/Archivos → FileFastFlow; verificar selección de destino.
6. Con app Android en segundo plano, verificar servicio, progreso y notificación.
7. Desactivar auto-accept y probar aprobación, rechazo y expiración de oferta.
8. Cancelar un envío y apagar Wi-Fi durante otro; no deben aparecer completos
   ni quedar temporales después del reinicio.
9. Probar nuevos archivos en la carpeta compartida y ausencia de reenvíos.
10. Verificar bandeja, notificaciones y cierre manual; revisar puertos/procesos.

## Límites conocidos

HTTP sin TLS; credenciales locales sin cifrado de base de datos; APK debug y
EXE sin firma comercial. Windows 10 tiene código compatible, pero la ejecución
se probó en Windows 11. No se probaron varios GB ni recepción prolongada en
segundo plano con políticas específicas de fabricantes. Android usa puerto
45832 fijo y tema claro. El auto-sync no recupera archivos que aparecieron con
el destino offline. Los logs SLF4J de Ktor no tienen binding compatible en V1;
los errores de emisor se registran en Logcat y se muestran como códigos breves.
No hay TLS, resume, ZIP de carpetas ni menú contextual.
