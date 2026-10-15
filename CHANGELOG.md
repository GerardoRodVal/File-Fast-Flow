# Historial de cambios

## 0.4.0

- Inicio con archivos generales en la raíz de una única carpeta recepción y espacios privados por dispositivo.
- Vista de dispositivos en burbujas alrededor del equipo principal, con colores de conexión.
- Una sola instancia: el acceso directo y la bandeja restauran la ventana; cerrarla mantiene el servicio activo.
- Notificaciones Windows con Copiar, copia de imágenes y archivos, y atajo Ctrl+Shift+C.
- Menú simplificado y temas del widget mediante vistas previas; el widget permanece en el escritorio.
- Actualizar todos los dispositivos desde los cambios locales, con compilación verificada para Windows y Android.
- Distribución automática opcional, cola para equipos desconectados y estados separados de entrega e instalación.
- Android busca nuevas versiones al abrir la aplicación y en segundo plano.
- Aviso de actualización una vez por versión, con acceso a Ajustes → Actualizaciones.
- Descarga del APK y comprobación de tamaño y SHA-256 antes de instalar.
- Instalación con confirmación de Android, conservando la identidad de la aplicación.
- Opción para activar o desactivar la búsqueda automática en Android.
- Publicación conjunta de Windows y Android desde `main`, con versiones y firmas compatibles.

Las publicaciones de GitHub Actions añaden el número de ejecución al último
componente de la versión base. Los detalles de cada publicación están en GitHub Releases.
