# Verificación de entrega · actualizada el 14 de octubre de 2026

## Distribución de cambios locales · 14 de octubre de 2026

- Suite completa Windows: **145 pruebas pasadas, 2 omitidas** del escritorio
  nativo del widget. Verificadas la cola sin conexión, la reconexión, el rechazo
  de paquetes alterados, la recepción real por TCP, el protocolo opcional de
  actualización, la espera por cambios estables y la reutilización de paquetes.
  El cierre durante una distribución detiene los envíos y conserva la cola.
- Compilación real desde copia aislada: Android **14 pruebas pasadas, 1 omitida**
  de interoperabilidad que necesita su fixture externo; APK generado con
  versionCode **100101**. Se conserva la clave debug y el identificador.
- Windows compilado con PyInstaller y ambos instaladores generados por el mismo
  mecanismo que utiliza la nueva opción. Revisión local comprobada al ejecutar
  el EXE: `4530a597359ffabea422449b44332321c42a6e04580aee4a4eb1122af3f29daa`.
- Arranque del EXE con datos aislados: `ui_started=true`, `server_started=true`,
  salida 0. El servidor anuncia la revisión que realmente ejecuta para poder
  distinguir entrega e instalación en el distribuidor.
- Vista de la nueva sección revisada en tamaño compacto. Los paquetes quedan
  preparados para el botón; no se envían ni instalan en dispositivos del usuario
  durante esta verificación. La instalación en un teléfono físico sigue pendiente.
- Acceso directo actualizado y aplicación real reiniciada con autorización previa,
  sin transferencias activas. Ventana visible y una única instancia tras una
  segunda ejecución. Compilación verificada guardada en caché; distribución aún
  sin iniciar hasta pulsar el botón o activar la opción automática.

## Copiar desde notificaciones de Windows · 14 de octubre de 2026

- Suite completa Windows: **137 pruebas pasadas, 2 omitidas** por requerir el
  escritorio nativo del widget. Pruebas dirigidas de copia, interfaz e instancia:
  **62 pasadas**.
- Comprobación nativa adicional: notificación silenciosa publicada en el centro
  de notificaciones, con botones Copiar y Abrir FileFastFlow y URI de protocolo
  para cada transferencia. La notificación de prueba se retiró al terminar.
- Portapapeles nativo: comprobado CF_HDROP para pegar archivos en el Explorador
  y los píxeles de una imagen. Se restauró el portapapeles previo tras la prueba.
- La prueba entre procesos confirmó que Copiar reutiliza la instancia oculta,
  deja la ventana oculta y no vuelve a abrir SQLite ni altera un envío activo.
  Las URI aceptan solo acciones conocidas y UUID; el receptor resuelve solo
  transferencias entrantes completadas de su historial local.
- Accesos adicionales: Copiar en transferencias recientes, Copiar último archivo
  recibido en la bandeja y Ctrl+Shift+C cuando la aplicación tiene el foco.
- Acceso directo actualizado e instancia real reiniciada con autorización previa
  y cero transferencias activas. Ventana visible, servicio LAN activo y una sola
  instancia tras una segunda ejecución.

## Carpeta recepción única · 14 de octubre de 2026

- Suite completa Windows: **129 pruebas pasadas, 2 omitidas**. La revisión
  dirigida de recepción, interfaz y migración pasó sus 85 pruebas. Las dos
  omitidas requieren el escritorio nativo para comprobar el anclaje del widget;
  la suite se ejecutó con Qt en modo offscreen.
- Configuración muestra un solo campo «Carpeta recepción». General utiliza la
  raíz y cada dispositivo tiene una carpeta individual dentro de ella.
- Transferencias TCP con dos destinatarios: ambos reciben los archivos de la
  raíz; únicamente el dueño recibe sus archivos individuales. El catálogo y la
  descarga autenticados tampoco permiten acceder a archivos de otros vínculos.
- Verificados los envíos pendientes al reconectar, la ausencia de duplicados y
  de reenvíos automáticos de archivos recibidos. Migración con colisiones sin
  sobrescribir archivos existentes ni mover archivos ajenos al historial.
- Revisión visual de Configuración en tamaños 1280×900 y 820×650.
- Instancia real reiniciada con autorización previa y cero transferencias
  activas. Recepción verificada en `C:\Users\gerar\filefastflow`; se conservan
  `Asus_TUF` y `Xiaomi 13T Pro`. Acceso directo actualizado; ventana nativa visible
  y un solo proceso tras ejecutar nuevamente el lanzador.

## Actualizaciones en Android · 14 de octubre de 2026

- Windows: **73 pruebas pasadas** en la suite completa, incluidas actualizaciones, migración y numeración de versiones. Después del ajuste de exportación desde una carpeta separada, **22 pruebas de paquetes y actualizaciones pasadas**.
- Android: **13 pruebas pasadas**, incluida la nueva suite del actualizador; InteropTest se omite al no proporcionar un fixture de integración.
- Android compila el APK **0.4.0**, `versionCode=100100`, con WorkManager para comprobaciones periódicas y permiso para abrir el instalador.
- El certificado SHA-256 del APK coincide con el de la entrega anterior 0.3.0: `1322e0281f22b25842ce93f9f568ad54b27775ded78476048feee4352a51ac9d`.
- Se comprueban rechazo de versiones antiguas, borradores, metadatos inválidos y URLs ajenas; descargas corruptas o canceladas; un único trabajo periódico; desactivación; y avisos sin repetición por versión.
- El ejecutable Windows 0.4.0 empaquetado inicia su interfaz y servidor correctamente con datos aislados.
- El acceso directo del escritorio sigue usando el entorno virtual, el lanzador del proyecto, el directorio `windows` y el icono requerido. No se cerró una instancia del usuario.

La entrega 0.4.0 es local hasta subir los cambios a `main`; GitHub Actions publica
las siguientes versiones solamente después de probar y compilar ambas plataformas.
La primera activación de avisos en un teléfono requiere instalar este APK y abrirlo
una vez. La entrega, los permisos de instalación y los tiempos de ejecución en
segundo plano aún requieren comprobación en el teléfono físico.

La V1 está implementada, pero su aceptación completa requiere pruebas sobre un
teléfono Android físico. No había teléfono ni emulador conectado; no se marca
la Definition of Done completa como cerrada.

## FileFastFlow y actualizaciones desde GitHub · 4 de octubre

- Suite completa Windows: **59 pruebas pasadas**. Después de los ajustes finales, 18 pruebas de interfaz y paquetes pasadas y 14 pruebas de actualizaciones y migración pasadas.
- Android: `assembleDebug` y 8 pruebas unitarias pasadas; 1 prueba de interoperabilidad omitida porque no se inició su fixture externo. Se conserva la aceptación pendiente en teléfono físico.
- Ejecutable FileFastFlow reconstruido. Interfaz nativa de Windows y servidor LAN comprobados con `--smoke-test`.
- `--package-smoke-test` ejecutó ambos botones: instalador EXE de 112,031,758 bytes y APK de 21,155,750 bytes; ambos éxitos y salida 0.
- Búsqueda de Releases, comparación numérica, descarga HTTPS con redirección, integridad SHA-256, cancelación, conservación del destino, aviso por versión y reutilización de datos DeviceDrop comprobados.
- GitHub Actions completó la compilación y publicación de **0.3.2**: **60 pruebas Windows pasadas**, APK Android, instalador EXE, ZIP portátil y verificación del ejecutable empaquetado. [Ejecución verificada](https://github.com/GerardoRodVal/File-Fast-Flow/actions/runs/37242674611).
- El actualizador consultó la Release real, detectó 0.3.2 desde 0.3.0, descargó el instalador de 91,464,978 bytes y verificó su SHA-256 contra GitHub.
- [Versión publicada](https://github.com/GerardoRodVal/File-Fast-Flow/releases/tag/v0.3.2). La primera ejecución falló por un paquete Android retirado; el workflow corregido utiliza paquetes de SDK explícitos.

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
45832 fijo y tema claro. Windows recupera los archivos locales pendientes cuando
el destino vuelve a estar online. Los logs SLF4J de Ktor no tienen binding compatible en V1;
los errores de emisor se registran en Logcat y se muestran como códigos breves.
No hay TLS, resume, ZIP de carpetas ni menú contextual.
