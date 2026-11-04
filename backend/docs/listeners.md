# TCP and TLS/TCP listeners

The Server accepts reverse Agent connections through multiple independently managed listeners. Each listener has an ID, name, TCP bind address, port, protocol (`tcp` or `tls_tcp`) and enabled state. All accepted connections share the existing `info` handshake, `ClientSession` pool, command router, heartbeat, PTY and file-transfer control messages. Server endpoint protocols register their own listener construction, certificate provisioning and supported Agent builders. The management UI reads available protocol definitions from the Server rather than maintaining a separate protocol list. The Python Client independently selects its registered connection strategy from `server_transport`. For a new socket-compatible transport, register the Server listener implementation and the corresponding Python Agent connector independently; both keep using the existing RCH message and Session handling after connection.

## Configure

In the Web UI, open **Utilities → Listeners**. Add a listener with a name, protocol, local bind address (usually `0.0.0.0`) and unused port. Listeners start immediately; Stop prevents new connections while existing Sessions remain connected. Start resumes accepting. Delete removes the endpoint, but leaves already connected sessions alive. The default TCP listener remains available as a manageable, nondeletable entry.

Listener configuration is stored at `backend/runtime/listeners.json` (or under `RCH_SERVER_RUNTIME_DIR`). The default entry initially uses `RCH_SOCKET_PORT`, default `9999`. Ports used by the HTTP and browser WebSocket services are reserved. Enabled listeners start when Server starts. If a bind fails, the Listener view shows an error status.

Select **Build Agent → Bundle → Listener** to embed the selected listener's protocol and port. Set Server IP to the address reachable from the Agent (not the listener's `0.0.0.0` bind address). Other builders retain TCP-only support. The device sidebar shows the current or most recently used listener for each device.

## TLS certificate pinning

The first time a TLS/TCP listener starts, the Server uses the `openssl` executable to generate a self-signed certificate and private key under `runtime/listener_tls/<id>.crt` and `<id>.key`. The private key stays on the Server. The Bundle includes only the SHA-256 fingerprint of the public certificate.

On connecting, the Python Bundle establishes TLS 1.2+ and compares the peer's certificate fingerprint with the embedded value **before** sending its `info` handshake. Certificate mismatches fail connection and retry. There is no fallback from TLS to plaintext. Certificates are reused across Server restarts; regenerating a certificate requires rebuilding the corresponding Bundles. Back up the private key and certificate together if moving Server runtime data.

This first version authenticates the **Server endpoint to the Bundle**, but does not authenticate each Agent to the Server. Restrict publicly exposed listening ports with network access controls until Agent enrollment/authentication is added. Browser HTTP, file transfer, and browser WebSocket channels keep their own configurations; the TLS/TCP listener covers only the command/control socket. The Server must have OpenSSL available when creating new TLS listeners.

## API

These endpoints use the existing authenticated Web API session or token:

- `GET /api/listeners` — list listener configurations, status, session counts, errors and protocol build metadata
- `GET /api/listener-protocols` — list registered protocol names, labels and build support
- `POST /api/listeners` — create and immediately start a listener (`name`, `protocol`, `host`, `port`)
- `PATCH /api/listeners/<id>` — set `{ "enabled": true | false }`
- `DELETE /api/listeners/<id>` — remove a nondefault listener and stop accepting

For `POST /api/agent/build`, Bundle requests may add `listener_id` alongside existing Server Host/Port/Web Port fields. Server validates the port against the selected listener and automatically injects the listener protocol and pinned certificate fingerprint. Without `listener_id`, the preexisting TCP Bundle build remains supported.
