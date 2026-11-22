# Optional TCP Tunnel

The Tunnel is a manually controlled, in-process TCP port forwarder for Python
Clients. Each saved instance chooses where the forwarded port is exposed with
`expose_on`. The RCH Client's Bind or Reverse connection mode does not select
the mapping direction. The Tunnel is inactive until manually started from the
RCH Web Terminal or **Toolbox → Tunnel**.

| Expose on | Listen address | Target address | TCP channel establishment |
| --- | --- | --- | --- |
| `client` | RCH Client | RCH Server | Uses established RCH listener direction |
| `server` | RCH Server | RCH Client | Uses established RCH listener direction |

For either direction, `listen_host` and `listen_port` belong to the exposed
machine. `target_host` and `target_port` are resolved on the opposite machine.
The same raw TCP forwarding engine carries HTTP, HTTPS, WebSocket, binary
protocols, and streaming file transfers. The tunnel does not inspect the HTTP
API or translate protocol contents. New Tunnel TCP connections follow the
same outbound direction and listener endpoint already proven by the running
RCH session; the exposure choice never changes this direction.

## Instances and commands

Each named Tunnel is a saved instance in the Server's `rch.db` settings store,
scoped to the selected Client. Create only saves the definition; Start, Stop,
and Restart manage its TCP connections. Edit and Remove require the instance
to be stopped. Saved instances persist across Server restarts, but the tunnel
is not auto-started.

Expose the RCH Server Web API on a public Bind Client:

```text
tunnel create --name rch-web --expose-on client --listen-host 127.0.0.1 --listen-port 18085 --target-host 127.0.0.1 --target-port 8085
tunnel start --name rch-web
```

Expose a private Client's web service on the RCH Server (the Client normally
connects using Reverse):

```text
tunnel create --name mac-web --expose-on server --listen-host 127.0.0.1 --listen-port 18086 --target-host 127.0.0.1 --target-port 3000
tunnel start --name mac-web
```

Run `curl http://127.0.0.1:18086/` on the RCH Server to reach the Client's
port `3000`. Setting `listen_host` to `0.0.0.0` makes the exposed port
accessible from other machines that can reach that device.

```text
tunnel list
tunnel status --name mac-web
tunnel restart --name mac-web
tunnel stop --name mac-web
tunnel edit --name mac-web --target-port 3001
tunnel remove --name mac-web
```

`tunnel start` may also accept a complete configuration to save and start
an instance. `tunnel stop --all` stops all running mappings on the selected
Client without deleting their definitions. CLI and Toolbox use the same
instance lifecycle service.

There is no extra Tunnel TCP listening port. Each independent Tunnel control
connection and forwarded TCP data connection uses the **existing RCH TCP/TLS
listener address and port**. An optional, detachable listener adapter is
installed only while a Tunnel mapping is running. The main RCH session socket
never carries Tunnel file or application bytes. Firewall and NAT rules that
allow the original RCH connection generally allow the extra connections too;
proxies that limit new connections can still prevent Tunnel operation.

## Using the RCH Server Web API

Start `rch-web` as shown above and verify the Client can reach
`http://127.0.0.1:18085`. To make the Client's own RCH HTTP API requests use
the Tunnel, set **Connect to Client → Server Web URL** to that URL and
reconnect the Bind Session. The existing Job, Script, Artifact, and Files
HTTP calls continue through their unchanged Web API. A Bind Session disconnect
does not automatically interrupt an already running Tunnel channel, but new
Tunnel activation requires a connected RCH Client.

## Transport and lifetime

The normal RCH Control action starts or stops the optional Tunnel. The Tunnel
establishes its own authenticated control TCP connection and an independent
data TCP connection per accepted user TCP connection. `stream_id` pairs each
connection, after which the same bidirectional byte bridge is used for both
exposure directions. TCP half-close is propagated. No additional daemon or
HTTP business routing is required.

The Tunnel belongs to the Client and Server processes, not a specific RCH
Session. Each process exit closes its tunnel connections. The stored instance
definitions remain available for manual reactivation. The data control
connection is not automatically re-established after a network failure.
The Tunnel channel uses a random token for setup authentication. When the
existing RCH listener is TLS-enabled, independent Tunnel sockets use the same
TLS listener and the Client verifies its configured certificate fingerprint.
Plain TCP transports remain unencrypted. The Tunnel forwards TCP, not UDP, and
does not rewrite HTTP Host, redirects or TLS
certificate names.
