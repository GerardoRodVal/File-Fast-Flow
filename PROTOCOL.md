# FileFastFlow LAN protocol v1

Service: `_devicedrop._tcp.local.`; default TCP port 45832 (45000–45999 configurable).
Identity is a persistent UUID v4, never an IP address. All JSON contracts include
`protocol_version: 1`. mDNS TXT carries device_id, device_name, platform, port and protocol_version.

## Pairing
Only `/api/v1/ping`, `/api/v1/device` and the two pairing routes are public.
The receiving user explicitly opens a 120-second pairing window in the local UI.
A six-digit code or QR random token authorizes `POST /api/v1/pair/request`:
`{device: Device, code: string}`. Reply: `{request_id, confirmation_token,
shared_token, device, protocol_version}`. The initiator calls
`POST /api/v1/pair/confirm` with `{request_id, confirmation_token}`, then persists
the returned device and 256-bit token. Receiver persists only after confirmation.
The code/QR token is consumed once and not written to disk. Failed requests are rate limited.

All other endpoints and `/ws` require `Authorization: Bearer <relationship-token>`.
Device = `{device_id, device_name, device_type, platform, ip, port, public_key,
protocol_version}`. public_key is an Ed25519 identity key reserved for future TLS;
it does **not** imply authenticated key exchange or encrypted transport in v1.

## Transfers
1. `POST /api/v1/offers` with Metadata. Returns `{status: accepted|pending|completed}`.
2. With pending approval, poll `GET /api/v1/offers/{transfer_id}`. Timeout is 120s.
3. `POST /api/v1/files`: multipart with `metadata` JSON followed by binary `file`.
   Metadata must match the authorized offer exactly. Receivers authenticate before
   consuming a body, enforce the size while streaming, write a temporary file,
   verify SHA-256 and publish with a collision-safe name only after verification.
4. Reply `{status: completed, transfer_id, sha256, filename, protocol_version}`.
   Retries reuse transfer_id, allowing an already committed result to be returned.

Metadata = `{transfer_id, batch_id?, filename, size, sha256, mime_type,
sender_device_id, origin_device_id, share_scope?, protocol_version: 1}`. IDs are UUIDs;
SHA-256 is 64 lowercase hex characters; size is 0–16 GiB. Reject path separators,
control characters and Windows reserved names. Each file has its own transfer_id.

Local application updates optionally include `update_revision` (64 lowercase
SHA-256 hex characters) and `app_version` (numeric three-part version). Both must
be present together, with device scope. They use the same authenticated offer,
approval and hash-verified upload flow as other files. Recipients stage the
verified installer and offer installation locally; they do not execute it on
receipt. Older clients can ignore these optional fields and receive the file.
The authenticated connection response may include `local_revision` and Android
`version_code`. A distributor reports installation only after the recipient
advertises the expected revision; transfer completion alone is delivery.

Windows supports optional `share_scope: "general" | "device"`. Omission defaults
to `device` for legacy senders. General files are stored at the reception root;
individual files are stored in the authenticated sender's named subfolder. The
sender cannot supply a destination path or select another device's folder.

Windows provides authenticated `GET /api/v1/shared` returning
`{files: [{filename, size, share_scope}], protocol_version: 1}` and
`GET /api/v1/shared/{scope}/{filename}` for downloading one file. These expose
only flat root files and the caller's individual files. Device directories,
partial files, symbolic links and files belonging to other peers are excluded.
Legacy clients can continue using the offer/upload flow without these routes.

`GET /api/v1/devices`, `GET /api/v1/transfers`, `GET /api/v1/files/{transfer_id}`
return metadata, scoped to the authenticated relationship; never arbitrary paths.
`DELETE /api/v1/transfers/{transfer_id}` cancels a transfer owned by that peer.
WebSocket events: transfer_started, transfer_progress (bytes_done, size, progress,
speed), transfer_verifying, transfer_completed, transfer_failed, transfer_cancelled,
device_online, device_offline. All events contain protocol_version and transfer_id
when applicable. WebSocket listeners receive only their own transfer events.

Errors use `{error: CODE, protocol_version: 1}` with 400 invalid metadata,
401 unauthorized, 403 rejected, 409 conflicting offer, 410 expired,
429 pairing rate limit, 503 reception paused, 507 insufficient storage.
States: queued, connecting, transferring, verifying, completed, failed, cancelled.
Resume is reserved for a later protocol revision (offset/Range/chunk hashes).
