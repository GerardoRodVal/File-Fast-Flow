# Contrato de red

La fuente canónica es [PROTOCOL.md](../PROTOCOL.md). Ambas implementaciones
utilizan los mismos campos snake_case y protocol_version 1. Los modelos de
Android se convierten explícitamente a JSON; los nombres camelCase de Room
no se usan como contrato HTTP.

Decisión de V1: oferta JSON separada para poder autorizar, aprobar y comprobar
almacenamiento antes de leer el binario. El multipart tiene exactamente dos
partes, metadata y file, en ese orden. Los emisores generan boundary aleatorio.
Los receptores rechazan formas diferentes del contrato; no son un servidor
genérico de formularios HTML.
