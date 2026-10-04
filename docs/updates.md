# Actualizaciones de FileFastFlow

Repositorio: https://github.com/GerardoRodVal/File-Fast-Flow, rama `main`.

La página **Actualizaciones** de Windows permite buscar versiones, descargar el
instalador y abrirlo. En Configuración están **Buscar actualizaciones y avisar
automáticamente**, **Mostrar notificaciones** e **Iniciar con Windows**.
La búsqueda automática está activada inicialmente; consulta GitHub a los ocho
segundos de abrir la aplicación y cada 30 minutos mientras esté ejecutándose,
incluso minimizada en la bandeja. Para recibir avisos con Windows, activa el inicio
automático y permite las notificaciones de Windows.

Instala una primera versión FileFastFlow en cada PC. Las versiones anteriores de
DeviceDrop no contienen este mecanismo y no recibirán el primer aviso. El
instalador conserva su AppId para actualizar instalaciones existentes. Windows
reutiliza la base de datos DeviceDrop si existe; conserva identidad, vínculos,
carpetas configuradas e historial. Se mantiene el protocolo LAN y el identificador
Android para conservar la compatibilidad entre dispositivos.

## Publicar cambios

```powershell
git add .
git commit -m "Describe los cambios"
git push origin main
```

El workflow `.github/workflows/release.yml` prueba y compila Android y Windows,
genera el instalador EXE, el APK de desarrollo y el ZIP portátil. Publica una
GitHub Release solamente después de pasar todas las pruebas y cargar los paquetes.
Cada ejecución recibe una versión creciente, inicialmente `0.3.1`, `0.3.2`, etc.
No es necesario editar manualmente la versión para cada cambio. El script suma el
número de ejecución al componente patch de la versión base de `pyproject.toml`.
También puedes ejecutar el workflow manualmente desde Actions.

Los cambios locales se notifican a las otras PCs después de subirlos a `main`,
completar la compilación y publicar la Release. La notificación puede tardar hasta
30 minutos tras la publicación, o aparecer inmediatamente al buscar manualmente.
Ambas PCs necesitan Internet para consultar GitHub y descargar el instalador;
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

## APK de desarrollo

`android/debug.keystore` es una clave **pública y exclusiva de desarrollo**, creada
para este repositorio con los valores estándar `android` / `androiddebugkey`.
Mantiene la firma de los APK debug estable entre las ejecuciones de GitHub Actions.
No debe utilizarse para una publicación de producción ni Play Store. Un APK
anterior firmado con otra clave debug requiere desinstalación antes de instalar
esta primera compilación; desinstalar borra sus datos locales. Las siguientes
compilaciones de este repositorio mantienen la misma clave y pueden actualizarse.
El aviso automático solicitado está implementado para las PCs Windows.

Referencias técnicas:
- [GitHub Releases API y digest de los paquetes](https://docs.github.com/en/rest/releases/releases#get-the-latest-release).
- [Inno Setup 6.7.3 y firma de Pyrsys B.V.](https://jrsoftware.org/isdl.php).
