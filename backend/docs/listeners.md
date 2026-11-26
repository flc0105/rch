# TCP and mTLS/TCP listeners

The Server accepts Reverse connections through independently managed listeners. Each listener has a name, local bind address, port, protocol and enabled state. Python Bundle, Go and Go Loader builds support the registered transports:

| Protocol | Connection protection |
|---|---|
| `tcp` (TCP) | Plain TCP; restrict it to trusted network boundaries |
| `mtls_tcp` (mTLS/TCP) | Mutual TLS authentication before RCH application messages |

Both transports carry the same RCH handshake, commands, results and heartbeat. Managed TCP file transfers and supported Tunnel channels use separate connections on the same listener and follow the session's transport. Browser HTTP and WebSocket access have their own deployment security requirements.

## Configure and operate

Open **Utilities → Listeners**. Add a name, protocol, local address (for example `0.0.0.0`) and unused port. For mTLS, initialize Server Identity and securely provision Client Identity before connecting; see [mTLS Identities](mtls_identities.md).

Listeners start when created. Stop prevents new connections; Start resumes acceptance. Delete removes a nondefault listener. Stopping or deleting a listener leaves its existing sessions connected. The default TCP listener can be stopped or started but cannot be deleted. Enabled listeners start with the Server; bind failures appear in the listener status.

The listener configuration is stored in `RCH_SERVER_RUNTIME_DIR/listeners.json`. The default TCP port is `RCH_SOCKET_PORT` (9999 by default); the Web HTTP and WebSocket ports are reserved.

## Agent configuration

In **Build Agent**, select Reverse and the desired Listener. Set the Server host and port to the address reachable by the Client; the listener's local bind address is not the advertised address. Go Loader passes the selected listener to the Bundle request. One-liners can also select a listener. Build and update packages carry transport settings, while mTLS identities are installed separately and retained across releases.

For Bind, the Client listens and the Server dials the saved target. Select TCP or mTLS/TCP consistently on both ends. See [Connection Lifecycle](connection_lifecycle.md) and [Client Bootstrap](bootstrap.md).

## API

These routes require administrator authentication:

| Method | Route | Purpose |
|---|---|---|
| GET | `/api/listeners` | Configurations, status and session counts |
| GET | `/api/listener-protocols` | Registered transports and builder capabilities |
| POST | `/api/listeners` | Create a listener (`name`, `protocol`, `host`, `port`) |
| PATCH | `/api/listeners/<listener_id>` | Set `enabled` |
| DELETE | `/api/listeners/<listener_id>` | Remove a nondefault listener |

Build requests may specify `listener_id` for Reverse connections; the Server resolves the transport and validates the request against the selected listener. Bind builds select the transport directly. Advertised endpoint addresses may be forwarded through NAT or a proxy. See [Client Update](client_update.md) for release handoff.
