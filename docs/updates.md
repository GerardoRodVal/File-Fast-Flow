# Actualizaciones de FileFastFlow

## Distribuir los cambios locales a todos los dispositivos

La página **Instaladores y actualizaciones** incluye **Actualizar todos los
dispositivos** y un interruptor para preparar y enviar cambios automáticamente.
Esta función se usa desde la PC que contiene el proyecto; los destinos reciben
el instalador adecuado y no necesitan herramientas de desarrollo.

Se calcula una revisión SHA-256 del código, se crea una copia aislada y se
ejecutan las pruebas Android y las compilaciones APK/Windows. Después se generan
los instaladores con tamaño y SHA-256. Si el código cambia durante el proceso,
la compilación se descarta para distribución y se vuelve a intentar con los
cambios estabilizados. Nunca se etiqueta un paquete anterior como si incluyera
código nuevo. Una compilación verificada se reutiliza mientras no haya cambios.

Los envíos usan los vínculos autenticados existentes. La cola y los resultados
persisten al reiniciar; los equipos sin conexión reciben el paquete al regresar.
Cada destino recibe únicamente su APK o EXE en su espacio individual. La
recepción completa y verificada se muestra como **Recibido · falta instalar**.
Solo se muestra **Actualizado** cuando el destino informa que ejecuta esa revisión.

Windows y Android ofrecen una acción para instalar los cambios recibidos. No se
ejecutan instaladores automáticamente. Android conserva el identificador y la
clave de desarrollo; el código de versión local aumenta para admitir la
actualización. Los clientes anteriores siguen recibiendo el instalador como un
archivo normal: necesitan abrirlo para incorporar por primera vez esta función.

La opción automática espera al menos 30 segundos sin cambios, además del
intervalo de revisión, para no compilar mientras se está editando. Requiere que
FileFastFlow continúe abierto, incluso en la bandeja. No crea una tarea de Codex
ni publica archivos en GitHub.

Repositorio: https://github.com/GerardoRodVal/File-Fast-Flow, rama `main`.

La página **Actualizaciones** de Windows permite buscar versiones, descargar el
instalador y abrirlo. En Configuración están **Buscar actualizaciones y avisar
automáticamente**, **Mostrar notificaciones** e **Iniciar con Windows**.
La búsqueda automática está activada inicialmente; consulta GitHub a los ocho
segundos de abrir la aplicación y cada 30 minutos mientras esté ejecutándose,
incluso minimizada en la bandeja. Para recibir avisos con Windows, activa el inicio
automático y permite las notificaciones de Windows.

Android incluye este mecanismo desde **0.4.0**. En **Ajustes → Actualizaciones**
puedes activar la búsqueda automática, buscar manualmente, descargar el APK y abrir
el instalador del sistema. Instala esta primera versión encima del APK anterior y
ábrela una vez para programar las consultas; las versiones anteriores necesitan
esta primera actualización manual.

Android consulta al abrir la aplicación y programa una tarea única de WorkManager
aproximadamente cada 30 minutos, con conexión a Internet como requisito. La tarea
persiste al cerrar la interfaz y reiniciar el teléfono; no depende del servicio LAN.
Android puede retrasarla por ahorro de batería o restricciones de segundo plano.
Después de forzar la detención desde Ajustes de Android, abre la aplicación de nuevo.
Cada teléfono recibe un aviso por versión, si las notificaciones están permitidas.
El aviso abre la sección de Actualizaciones y no instala sin confirmación.

Instala una primera versión FileFastFlow en cada PC. Las versiones anteriores de
DeviceDrop no contienen este mecanismo y no recibirán el primer aviso. El
instalador conserva su AppId para actualizar instalaciones existentes. Windows
reutiliza la base de datos DeviceDrop si existe; conserva identidad, vínculos,
carpetas configuradas e historial. Se mantiene el protocolo LAN y el identificador
Android para conservar la compatibilidad entre dispositivos.

## Publicar cambios

```powershell
git add <archivos-del-cambio>
git commit -m "Describe los cambios"
git push origin main
```

El workflow `.github/workflows/release.yml` prueba y compila Android y Windows,
genera el instalador EXE, el APK de desarrollo y el ZIP portátil. Publica una
GitHub Release solamente después de pasar todas las pruebas y cargar los paquetes.
Cada ejecución recibe una versión creciente, inicialmente `0.3.1`, `0.3.2`, etc.
Las compilaciones fallidas pueden dejar saltos en esa secuencia. La primera versión publicada es **0.3.2**.
No es necesario editar manualmente la versión para cada cambio. El script suma el
número de ejecución al componente patch de la versión base de `pyproject.toml`.
También puedes ejecutar el workflow manualmente desde Actions.

Los pull requests ejecutan las pruebas y preparan paquetes para revisión; solamente
`main` publica versiones. Describe cambios para el usuario en `CHANGELOG.md` y usa
el formato de `.github/pull_request_template.md`. `.gitattributes` fija finales de
línea y trata APK, EXE, iconos y claves como archivos binarios.

Los cambios locales se notifican a las PCs y teléfonos después de subirlos a `main`,
completar la compilación y publicar la Release. La notificación puede tardar hasta
30 minutos en Windows tras la publicación; Android puede tardar más por sus límites
de ejecución. Puedes buscar manualmente para consultar inmediatamente.
Los dispositivos necesitan Internet para consultar GitHub y descargar el instalador;
las transferencias LAN siguen funcionando sin Internet.

## Descarga e instalación

La aplicación compara versiones numéricas, omite borradores, versiones previas
y versiones antiguas, y acepta únicamente el instalador de este repositorio
descargado mediante HTTPS desde GitHub. Comprueba tamaño y SHA-256 contra los
metadatos de la API de GitHub. Una descarga interrumpida o corrupta no reemplaza
un archivo existente. Las descargas se guardan en `updates/` dentro de la carpeta
de datos de la aplicación.

Una notificación por versión se registra por PC. La página mantiene la opción
de descarga aunque el aviso se haya descartado. Pulsa **Descargar actualización**
y después **Instalar actualización descargada**. Se verifica de nuevo el archivo,
se abre el asistente y FileFastFlow se cierra para permitir el reemplazo de sus
binarios. Al terminar, abre FileFastFlow desde el asistente.

En Android se acepta únicamente `FileFastFlow-<versión>-debug.apk` de la Release
oficial, con versión superior a la instalada, tamaño válido y digest SHA-256 de la
API de GitHub. La descarga usa HTTPS y valida cada redirección a los dominios de
GitHub autorizados. Un temporal evita que una descarga incompleta reemplace un APK
previo. Se comprueba nuevamente el hash antes de abrir el instalador.

Pulsa **Descargar actualización** y luego **Instalar actualización**. La primera
vez Android puede pedir **Permitir desde esta fuente** para FileFastFlow: habilítalo,
regresa y vuelve a pulsar Instalar. El APK se comparte mediante FileProvider desde
la carpeta de caché `updates/`; el sistema comprueba la firma y solicita confirmación.
Al actualizar se conserva el identificador `devicedrop.app`, los vínculos y los datos.

## APK de desarrollo

`android/debug.keystore` es una clave **pública y exclusiva de desarrollo**, creada
para este repositorio con los valores estándar `android` / `androiddebugkey`.
Mantiene la firma de los APK debug estable entre las ejecuciones de GitHub Actions.
No debe utilizarse para una publicación de producción ni Play Store. Un APK
anterior firmado con otra clave debug requiere desinstalación antes de instalar
esta primera compilación; desinstalar borra sus datos locales. Las siguientes
compilaciones de este repositorio mantienen la misma clave y pueden actualizarse.
El aviso automático está implementado para Windows y Android. La versión base
local usa un `versionCode` superior a las publicaciones 0.3.x; CI suma su número de
ejecución a ese valor para que Android admita actualizaciones posteriores.

Referencias técnicas:
- [GitHub Releases API y digest de los paquetes](https://docs.github.com/en/rest/releases/releases#get-the-latest-release).
- [Tareas periódicas de WorkManager](https://developer.android.com/develop/background-work/background-tasks/persistent/getting-started/define-work).
- [Permiso de notificaciones en Android](https://developer.android.com/develop/ui/compose/notifications/notification-permission).
- [Inno Setup 6.7.3 y firma de Pyrsys B.V.](https://jrsoftware.org/isdl.php).
