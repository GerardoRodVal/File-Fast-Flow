# Generadores EXE y APK

FileFastFlow para Windows incluye una página **Instaladores**, con dos acciones
que funcionan sin conexión y sin herramientas de desarrollo en la PC destino.

El EXE se construye con Inno Setup 6.7.3 a partir de `FileFastFlow.exe` y `_internal/`
de la aplicación actual. Se incluyen el generador y el APK, por lo que una copia
instalada también puede crear nuevos paquetes. El instalador configura la
aplicación para el usuario actual en `%LOCALAPPDATA%\Programs\FileFastFlow`, crea
una entrada en Inicio y ofrece un acceso directo opcional en el escritorio.
La desinstalación elimina los binarios, conservando recibidos, carpeta compartida
y datos del usuario. Windows 10/11 x64, sin elevación de administrador.

El botón APK publica el APK debug incluido, verificando SHA-256 y tamaño antes
de reemplazar el archivo elegido. No recompila Kotlin ni usa un servidor externo.
Una versión release con firma de publicación requiere configurar una clave
propia y adaptar el pipeline antes de distribuirla como tal.

La generación se ejecuta en un hilo independiente. Los botones se desactivan
mientras se genera un paquete; se puede seguir usando el resto de FileFastFlow.
El resultado se escribe en una carpeta temporal junto al destino y se publica
con reemplazo atómico. Si falla, se conserva el archivo anterior. Se impide
guardar dentro de la propia aplicación para evitar incluir paquetes generados
en futuros instaladores. Para salir, espera a que termine la generación.

## Preparar recursos y compilar

1. Compila Android con `android/gradlew.bat assembleDebug`.
2. Descarga Inno Setup 6.7.3 desde su sitio oficial y verifica su firma Authenticode
   (Pyrsys B.V.). Su instalador admite modo portátil para extraer el compilador en
   una carpeta de herramientas, sin registrar una instalación del compilador:

   ```powershell
   .\innosetup-6.7.3.exe /PORTABLE=1 /CURRENTUSER /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /NOICONS /DIR="C:\herramientas\InnoSetup"
   ```

3. Desde `windows/`, ejecuta:

   ```powershell
   .venv\Scripts\python.exe scripts/build_windows.py --apk ../android/app/build/outputs/apk/debug/app-debug.apk --inno-dir C:\herramientas\InnoSetup
   ```

`prepare_package_assets.py` copia el APK y crea su manifest SHA-256; copia el
compilador, sus archivos de firma, la traducción española y su licencia. Esos
binarios se ignoran en Git, y se incluyen como recursos al ejecutar PyInstaller.
El script y la receta `devicedrop/assets/FileFastFlow.iss` sí están versionados.
Si faltan los recursos, la compilación falla con una explicación.

`build_windows.py --dist-dir <carpeta>` permite construir en una carpeta separada
cuando el paquete anterior está abierto o tiene archivos protegidos.

Para generar el instalador desde el código después de compilar Windows:

```powershell
.venv\Scripts\python.exe -c "from devicedrop.packages import create_package; create_package('windows', '../releases/FileFastFlow-0.3.0-Setup.exe')"
```

Si compilaste en otra carpeta, indica `bundle=Path('dist/FileFastFlow-Installers')`
en `create_package`, importando `Path` de `pathlib`. En la aplicación empaquetada
el generador siempre usa la carpeta del EXE que se está ejecutando.

`python scripts/package_release.py` actualiza los ZIP portátil y de código y el
manifest SHA-256 después de generar el instalador.
Usa `--bundle-dir dist/FileFastFlow-Installers` para empaquetar la actualización
local creada en la carpeta separada.

Para verificar los dos botones desde el EXE, usando una carpeta de datos aislada:

```powershell
dist\FileFastFlow\FileFastFlow.exe --package-smoke-test --data-dir C:\pruebas\FileFastFlow --port 45990
```

Genera ambos archivos con el flujo de la UI, guarda `package_smoke_result.json`
y `installers-smoke.png`, y cierra automáticamente. Usa una carpeta de prueba
fuera de la aplicación. `--smoke-test` continúa comprobando el servidor LAN.

## Dependencia de terceros

Se redistribuye el compilador original de **Inno Setup 6.7.3**, sin modificar.
Su licencia se incluye en `_internal/devicedrop/assets/inno/license.txt`.

- [Inno Setup y descarga oficial](https://jrsoftware.org/isdl.php)
- [Licencia de la versión usada](https://github.com/jrsoftware/issrc/blob/is-6_7_3/license.txt)
- [Modo portátil](https://jrsoftware.org/ishelp/topic_technotes.htm)
- [Parámetros del compilador](https://jrsoftware.org/ishelp/topic_compilercmdline.htm)
