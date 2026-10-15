# Preferencias del proyecto

## Carpetas e interfaz

Configuración debe tener un único campo «Carpeta recepción». Su valor
predeterminado es `%USERPROFILE%\filefastflow` (en esta PC,
`C:\Users\gerar\filefastflow`). Los espacios individuales deben quedar dentro,
en carpetas con el nombre de cada dispositivo. Sanear nombres inválidos y
distinguir nombres repetidos sin sobrescribir archivos. Las carpetas individuales
solo se comparten con su dispositivo. Los archivos generales recibidos van a la
raíz, al mismo nivel que las carpetas individuales. Cada vínculo puede listar y
descargar únicamente los archivos de la raíz y los de su propia carpeta, sin
exponer carpetas ajenas. Evitar reenvíos automáticos de archivos recibidos y
duplicados entre el observador, las revisiones periódicas y la interfaz.

El menú contiene Inicio, Dispositivos, Configuración, Instaladores y
actualizaciones, y Widget. No añadir Compartidos ni Historial al menú. El tema
del widget se elige en una cuadrícula de vistas previas, sin desplegable.

«Actualizar todos los dispositivos» distribuye la versión LOCAL de esta PC.
Compilar fuentes actuales en una copia aislada, comprobar su revisión al terminar
y enviar a cada vínculo su EXE/APK. Mantener la opción automática, la cola
persistente para equipos sin conexión y la distinción recibido/instalado. No
marcar actualizado hasta comprobar la revisión ejecutada por el destino. La
instalación se inicia desde una acción del usuario en el dispositivo receptor.

Las notificaciones de archivos recibidos en Windows incluyen «Copiar». Ofrecer
el archivo al portapapeles y, para imágenes, también sus píxeles. Mantener el
acceso de bandeja «Copiar último archivo recibido» y Ctrl+Shift+C dentro de la
app. El protocolo `filefastflow://copy/<transfer_id>` debe resolver únicamente
transferencias entrantes completadas de la base local, nunca rutas de la URI,
y reutilizar la instancia abierta sin mostrar la ventana al copiar.

## Acceso directo del escritorio

El usuario pidió mantener actualizado el acceso directo `FileFastFlow.lnk` del
escritorio con cualquier cambio. Debe abrir la versión actual de este proyecto
mediante el `pythonw.exe` base indicado por `windows/.venv/pyvenv.cfg`, con
los argumentos `-S windows/scripts/launch_desktop.pyw`, `windows` como directorio de trabajo
y `assets/FileFastFlow.ico` como icono.

El usuario pidió que exista una sola instancia y que cerrar la ventana la deje
en segundo plano. Usar el intérprete base evita el proceso adicional del
redirector `.venv/Scripts/pythonw.exe`; el lanzador carga las dependencias de
`.venv/Lib/site-packages`. La protección de instancia debe adquirirse antes de
abrir la base de datos. Una segunda ejecución restaura la ventana existente y
termina. Solo la acción Salir de la bandeja cierra la aplicación.
El acceso directo debe restaurar la ventana principal oculta o minimizada, o
iniciar y mostrarla si no hay proceso. Un clic o doble clic en el icono de la
bandeja también debe restaurarla; un clic derecho mantiene el menú contextual.

Este lanzador carga el código del proyecto al abrir la aplicación, por lo que
los cambios de código no requieren recompilar un EXE para el acceso directo.
Para ver cambios en una aplicación ya abierta, hay que salir desde la bandeja
y volver a abrirla. No cerrar una instancia del usuario sin su autorización.

Si cambian las rutas, el entorno virtual o el lanzador, restaurar y verificar el
acceso directo usando `windows/scripts/update_desktop_shortcut.ps1`. Mantener
este mecanismo al realizar futuros cambios en el proyecto.
