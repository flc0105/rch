# Optional Bind TCP Tunnel

The Tunnel is a manually controlled, in-process TCP forwarder for **Python Bind
Clients**. It maps a TCP listener on the public/listening Client to a TCP service
reachable from the RCH Server machine. It works for the RCH Web API and also for
other local or LAN TCP services. The Tunnel is inactive until started from the
RCH Web Terminal.

## Commands

Select an online Python Bind Client and run the Server builtin commands:

```text
tunnel start --name rch-web --listen-host 127.0.0.1 --listen-port 18085 --target-host 127.0.0.1 --target-port 8085 --channel-port 9444
tunnel list
tunnel status --name rch-web
tunnel stop --name rch-web
```

`--listen-host` defaults to `127.0.0.1`, `--target-host` defaults to
`127.0.0.1`, and `--channel-port` defaults to `9444`. `--name`,
`--listen-port`, and `--target-port` are required for `start`. Separate service
mappings may reuse the same channel port, but each must have a different
Client-facing listen port. To stop every active mapping for the selected Client,
use `tunnel stop --all`.

**Address perspectives:** `--listen-host` is an interface on the Client,
`--target-host` is resolved by the Server. Setting `--listen-host 0.0.0.0`
exposes the forwarded service to other hosts that can reach the Client. The
Server must be able to connect to the Client's Tunnel channel port as well as
to its existing Bind session port. The Client's Tunnel channel listener accepts
connections on all interfaces; a per-Tunnel token authenticates its setup
connections.

## Using the RCH Server Web API

Create the mapping above, then use the existing **Connect to Client** dialog to
set **Server Web URL** to `http://127.0.0.1:18085` for that Client. Disconnect
and reconnect the normal Bind session to apply it. The Client's existing HTTP
API caller uses the newly announced URL for the next session. The Tunnel stays
running during the Bind session reconnect, and all existing API routes, HTTP
uploads/downloads and SDK operations continue through the unchanged Server Web
application.

The Server does not rewrite response links, Host headers, cookies or TLS
certificates. A target web service that emits absolute addresses must be
configured for the desired public origin if needed.

## Other services

For a separate HTTP service bound on the Server at `127.0.0.1:3000`, start:

```text
tunnel start --name mini-web --listen-host 0.0.0.0 --listen-port 18086 --target-host 127.0.0.1 --target-port 3000 --channel-port 9444
```

A browser able to reach the Client can open `http://CLIENT_IP:18086`. Replace
`CLIENT_IP` with the actual Client address. Raw TCP connections, including
HTTP upgrades and binary streams, use one independent data connection per
accepted incoming TCP connection. Multiple named mappings share a Tunnel control
connection and channel port. Large transfers use streaming reads/writes rather
than full-file buffers.

## Runtime and lifetime

The Tunnel modules are imported when first used. `tunnel start` creates Client
TCP listeners and a Server-initiated control connection. Each incoming Client
connection signals its mapping over the Tunnel control connection; the Server
then opens an authenticated data connection back to the Client, connects to the
configured target, and copies bytes in both directions. After all mappings are
stopped, the Tunnel listeners and control/data sockets close. Restarting a
Client or Server process also closes that process's Tunnel connections.

The Tunnel belongs to the processes, not a particular RCH Session. Disconnecting
and reconnecting the existing Bind session does not change or stop an active
Tunnel. Mapping state is not persisted across process restarts. Reverse mode
retains its existing direct HTTP configuration and does not use this module.
