# Seguridad de FileFastFlow v0.1.0

## Modelo de confianza

V1 está destinada a una LAN privada y confiable. Utiliza **HTTP sin TLS**:
archivo, código de pairing, credencial y metadata pueden ser observados o
alterados por un atacante con acceso al tráfico. SHA-256 detecta discrepancias
del contenido recibido, pero no autentica el intercambio inicial ante un MITM.
No se debe afirmar cifrado de transporte ni cifrado de extremo a extremo.

Se mantienen claves de identidad para una revisión futura del protocolo
(Ed25519 en Windows, EC P-256 en Android). En V1 `public_key` es metadata
reservada: no hay firma de mensajes, pinning ni intercambio autenticado de claves.

## Protecciones implementadas

- Pairing habilitado por el usuario local durante 120 segundos.
- Código de seis dígitos o token QR aleatorio; un solo uso, solo en memoria.
- Cinco solicitudes por IP en 120 segundos y confirmación temporal adicional.
- Credencial aleatoria de 32 bytes distinta por cada relación de confianza.
- Comparación de credenciales con compare_digest/MessageDigest.isEqual.
- Autenticación antes de consumir uploads; ninguna transferencia desde un
  dispositivo desconocido. Identidad del emisor ligada al token autenticado.
- Metadata normalizada ligada a una oferta; recepción manual o automática
  configurada por vínculo, y control global para pausar recepción.
- Rutas remotas nunca usadas como destinos locales; rechazo de separadores,
  rutas relativas, controles, streams NTFS y nombres reservados de Windows.
- Metadata con límite de 16 KiB y controles JSON pequeños de 32 KiB.
- Binarios recibidos incrementalmente y límite de tamaño en cada bloque.
- Reserva lógica de espacio entre ofertas; respuesta 507 antes de recibir.
- Temporales exclusivos en la carpeta de destino; no se publica un archivo
  incompleto. Verificación de tamaño y SHA-256 antes de publicar.
- Publicación sin reemplazar archivos existentes; nombres foto (1).png, etc.
- Limpieza de temporales por fallo/cancelación y recuperación al iniciar.
- Historial remoto y WebSocket restringidos al vínculo, sin rutas locales.
- Hosts remotos de transferencia restringidos a direcciones LAN numéricas;
  no ejecución de rutas, eval, comandos remotos ni proxy HTTP del entorno.
- Android: servidor no exportado por IPC; FileProvider solo expone recibidos
  con permisos temporales. Backup del estado y credenciales desactivado.
- Logs de aplicación sin valores de tokens; logs HTTP de acceso desactivados.

Solo identidad, ping y handshake de pairing son públicos. No hay una ruta HTTP
que abra la ventana de pairing: requiere acción en la UI local.

## Almacenamiento y límites

Tokens y claves se guardan en la base local dentro del perfil del usuario en
Windows y almacenamiento privado de Android. V1 no implementa DPAPI, cifrado
de SQLite ni protección de tokens con Android Keystore. Un proceso con acceso
al perfil o un teléfono comprometido puede leerlos. Desvincular elimina la
credencial del receptor local; desvincula también el otro extremo para retirarla
de ambos. El sistema de permisos local constituye la protección en reposo.

No hay garantías contra denegación de servicio avanzada. Las ofertas tienen
límite y timeout; todavía no se han realizado auditoría externa, fuzzing ni
pruebas prolongadas bajo carga. No se aceptan certificados arbitrarios: V1 no
usa HTTPS ni cambia validaciones globales de TLS.

## Firewall y distribución

No se abren puertos privilegiados ni se modifican reglas de firewall
automáticamente. Permite el puerto configurado únicamente en redes privadas.
El EXE no está firmado comercialmente; el APK de entrega usa firma debug.
Antes de uso con redes no confiables, implementar TLS con pinning y confirmar
la identidad del peer durante pairing, protección de secretos en reposo y
una revisión de seguridad independiente.
