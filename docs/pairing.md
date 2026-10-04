# Vinculación

1. El receptor abre una ventana desde la interfaz local.
2. La ventana genera código y token QR con expiración de 120 segundos.
3. El iniciador manda identidad y código/token a pair/request.
4. El receptor consume la ventana, conserva una confirmación temporal en
   memoria y entrega un token aleatorio de relación.
5. El iniciador confirma mediante pair/confirm. El receptor persiste el vínculo.
6. Tras la respuesta, el iniciador persiste el mismo token con la identidad
   del receptor. El resto de endpoints exige Bearer.

Una confirmación fallida o caducada no establece confianza. Si una respuesta
se pierde en este handshake de V1, puede ser necesario repetir el pairing con
un nuevo código; no se reanudan handshakes. Ningún token temporal se guarda
en settings, logs ni el historial.

QR: JSON con protocol=devicedrop, version=1, protocol_version=1, device_id,
device_name, platform, public_key, ip, port y pairing_token. El servidor usa
la IP de la conexión entrante para el peer; no confía en la IP enviada en el body.
Las credenciales viajan por HTTP en V1; consulta SECURITY.md.
