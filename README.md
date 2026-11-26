# Remote Control Hub (RCH)

RCH is a cross-platform remote device operations and automation platform. It combines a browser-based management console, remote command execution, managed file transfers, scripts, background jobs, artifacts and device monitoring around a shared Server/Client protocol.

Use RCH only on devices you own or are explicitly authorized to administer. Protect the management interface, Client identities, credentials and stored artifacts as administrative resources.

## Capabilities

| Area | Features |
|---|---|
| Devices | Reverse and Bind connections, multiple Server listeners, saved Bind targets, recent devices, groups, aliases, connection history and RTT |
| Terminal | Server Builtins, Client commands, ACMD, Shell and Python execution, autocomplete, streamed output, cancellation and Quick History |
| Remote Files | Directory browsing, search, pagination, pinned paths, copy/move/rename/delete, ZIP operations, previews, editing and managed transfers |
| Automation | Script Library, metadata-driven parameters, Script SDK, structured interactions, Quick Actions, Background Jobs and External Tools |
| Operations | Process and app inspection, Device Dashboard, Log Viewer, PTY, Screen View, Clipboard and optional TCP Tunnel on supported Clients |
| Data | Activity Center, Saved Files, Shared Files, Transfer Center, Keychains, notifications and Server-local Documents |
| Administration | Administrator authentication, mTLS Identities, Agent Builder, One-liners, Agent Outputs, Server Maintenance and cleanup |

The selected Client's Command Manifest and Feature Manifest determine which operations are available. Toolbar, More and Toolbox expose the tools appropriate to the current device; Toolbar Settings and Toolbox shortcuts organize frequently used actions.

## Architecture

| Component | Responsibility |
|---|---|
| `backend/server/` | Application services, connection/session management, execution orchestration, Web API, listeners and persistence |
| `backend/client/` | Python Client runtime, platform adapters, commands, scripts, jobs, file transfers and optional device features |
| `backend/core/` | Shared protocol, identity, platform, parameter and utility contracts |
| `backend/client-go/` | Native Go Client implementing the supported RCH command and Control contracts |
| `backend/go-loader/` | Go Loader that obtains and launches a Python Bundle |
| `frontend/` | Vue 3 / Vite management UI |
| `backend/rchcli/` | Standalone remote operator CLI using the Server Web API and event stream |
| `desktop_notifier/` | Independent desktop notification consumer; see its [current connection requirements](backend/docs/desktop_notifier.md) |
| `tools/` | Supporting deployment tools |

The Server maintains connected Client instances (`client_id`) and associates them with stable device identities (`machine_id`). Command and structured Control requests share execution and result infrastructure. Each session has a single foreground slot; independent Control requests, managed Transfers, PTY and Monitor sessions use their respective lifecycle policies. Activity and History are coordinated at the application boundary. Command, Script and Quick Action entrypoints use common validation and execution contracts rather than duplicating business rules.

## Connection and transport

Python and Go Clients support both directions and both transports:

| Direction | Who establishes the connection? |
|---|---|
| Reverse | Client dials a Server Listener |
| Bind | Server dials a listening Client; saved targets allow manual reconnection |

| Transport | Protection |
|---|---|
| `tcp` | Plain TCP |
| `mtls_tcp` | Mutual TLS (TLS 1.2+) using separately installed Server and Client Identity material |

Configure Reverse endpoints in **Utilities → Listeners**; configure Bind targets in the Device Bar. For mTLS, initialize the Server Identity and provision Client Identity files before connecting. Identity revocation prevents new authenticated connections; existing sessions can be disconnected by the administrator. Build/Update packages do not include Client private keys. See [Listeners](backend/docs/listeners.md), [mTLS Identities](backend/docs/mtls_identities.md) and [Connection Lifecycle](backend/docs/connection_lifecycle.md).

| Default port | Service |
|---|---|
| 9999 | Default Reverse TCP listener (`RCH_SOCKET_PORT`) |
| 8085 | Web UI, API and HTTP transfers (`RCH_WEB_PORT`) |
| 8086 | Browser WebSocket events, notifications, PTY and Screen View (`RCH_WEB_PORT + 1`) |

Managed TCP file transfers use independent authenticated data sockets on the current RCH listener endpoint, following the session's TCP or mTLS transport. Python also supports `http_simple` and `http_streaming`; Go supports `http_streaming` and `tcp_streaming`. Browser-to-Server transfers use HTTP. Browser/API transport security is configured separately from Client Socket mTLS; use protected network access and HTTPS/WSS for remote administration.

## Client types and deployment

| Builder | Output and runtime |
|---|---|
| Python Bundle (`python`) | Python source archive, requiring a supported Python environment; broadest feature set, including platform-specific SDK and Job capabilities |
| Go (`go`) | Standalone native executable, including shell, Remote Files, managed transfer, Configuration and Script execution using a local Python interpreter; consult its Manifest for supported operations |
| Go Loader (`go_loader`) | Native executable that obtains a Python Bundle from the Server and starts it in a suitable Python environment |

Agent Builder and One-liners support Reverse and Bind configuration. Agent Outputs records builder, connection direction, transport, target platform and build metadata. Python Bundle updates use verified downloads and platform-aware release handoff. On iOS/Pythonista, in-process execution and app sandbox/lifecycle determine available features; see the platform guide.

## Getting started

Run the following from the project root on the Server machine (POSIX Shell; on Windows use the corresponding virtual environment activation and copy commands). Python 3.10+ is required for the Python code. Install the Go toolchain only if building Go outputs, and OpenSSL if provisioning mTLS identities.

Build the Web frontend with the Node.js version supported by the project's Vite dependency:

```bash
cd frontend
npm ci
npm run build
cd ..
mkdir -p backend/static
cp -R frontend/dist/. backend/static/
```

Install Python dependencies and start the Server:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python run_web.py
```

Open `http://<server-host>:8085` in the browser. On first initialization the Server prints the generated administrator username and password; subsequent starts use the persisted credentials. Protect the startup output and sign in with those credentials. The administrator account menu manages passwords and API tokens.

Use Agent Builder to prepare a Client for an authorized device, or run the Python source Client with a suitable Profile from its `backend/` directory. For Bind and mTLS configuration see the connection and identity guides above. The standalone Server console can be started with `python rchserver.py`; remote command-line access through the Web service is covered in [RCH CLI](backend/docs/rch_cli.md).

For frontend development, follow [Frontend README](frontend/README.md). For production asset delivery see [Web Frontend Loading](backend/docs/web_frontend_loading.md).

## Runtime and configuration

Server data defaults to `backend/runtime/`, configurable before startup with `RCH_SERVER_RUNTIME_DIR`. `rch.db` stores structured data such as device inventory, activities, artifacts, jobs, transfers, notifications, preferences and Agent Outputs metadata. File contents and selected settings remain filesystem-backed. `auth.json`, `keychains.key` and `identities/` contain sensitive material and require protected backups along with the associated database and files.

Client runtime settings are available through **Info → Configuration** or Server Builtin `config list`, `config set KEY VALUE`, `config reset KEY` and `config reset-all`. Supported settings depend on the Client. Configuration and execution details are documented in the relevant feature guides below.

## Documentation

The following guides define the current behavior, public contracts and operating procedures. Source registries and Client manifests are authoritative for available commands and capabilities.

### Deployment, connections and administration

- [Server Runtime](backend/docs/server_runtime.md) — runtime layout, Server Maintenance and Bind Web URL
- [Administrator Authentication](backend/docs/admin_auth.md) · [Client Session API](backend/docs/client_session_api.md)
- [Listeners](backend/docs/listeners.md) · [mTLS Identities](backend/docs/mtls_identities.md) · [Connection Lifecycle](backend/docs/connection_lifecycle.md)
- [Device Identity](backend/docs/device_identity.md) · [Client Handshake](backend/docs/client_handshake.md)
- [Client Bootstrap](backend/docs/bootstrap.md) · [Client Builds and Updates](backend/docs/client_update.md)
- [Launch Mode](backend/docs/launch_mode.md) · [macOS launchd](backend/docs/launchd.md) · [iOS/Pythonista](backend/docs/ios_pythonista.md)
- [Runtime Configuration](backend/docs/config.md) · [Watchdog](backend/docs/watchdog.md) · [Process Recovery Watchdog](backend/docs/process_recovery_watchdog.md)
- [Logging](backend/docs/logging.md) · [Cleanup](backend/docs/cleanup.md)

### Execution and extension

- [Command Quick Reference](backend/docs/command_quick_reference.md) · [Command Registry](backend/docs/command_registry.md)
- [Command Execution](backend/docs/command_execution.md) · [Socket Protocol](backend/docs/socket_protocol.md)
- [Shell-like Commands](backend/docs/shell_like_commands.md) · [ACMD](backend/docs/acmd.md) · [Variables](backend/docs/variables.md)
- [Autocomplete](backend/docs/autocomplete.md) · [Structured Output](backend/docs/structured_output.md) · [Interaction Broker](backend/docs/interaction_broker.md)
- [Aliases and Quick Actions](backend/docs/alias_quick_actions.md) · [Activity Center and Quick History](backend/docs/command_history.md)
- [Scripts](backend/docs/scripts.md) · [Script SDK](backend/docs/script-sdk.md) · [Parameter Schema](backend/docs/parameter_schema.md)
- [Background Jobs](backend/docs/background_jobs.md) · [External Tools](backend/docs/external_tools.md) · [Device Events](backend/docs/event_emit.md)
- [Remote CLI](backend/docs/rch_cli.md)

### Files, device tools and Web UI

- [Remote Files](backend/docs/remote_files.md) · [File Transfer](backend/docs/file_transfer.md) · [Go File Transfers](backend/docs/go_file_transfers.md)
- [Artifacts](backend/docs/artifacts.md) · [Preview and Monaco](backend/docs/preview_monaco.md) · [Documents](backend/docs/documents.md)
- [Keychains](backend/docs/keychains.md) · [Database](backend/docs/rch_database.md)
- [Device Monitor](backend/docs/device_monitor.md) · [Log Viewer](backend/docs/log_viewer.md)
- [PTY](backend/docs/pty.md) · [Screen View](backend/docs/screenview.md) · [Clipboard](backend/docs/clipboard.md) · [Tunnel](backend/docs/tunnel.md)
- [Toolbox](backend/docs/toolbar_toolbox.md) · [Web Frontend Loading](backend/docs/web_frontend_loading.md)
- [WebSocket Events and Notifications](backend/docs/websocket_notifications.md) · [Desktop Notifier](backend/docs/desktop_notifier.md)

## Development and source snapshots

Business operations belong to their domain services; shared Execution, Transport and persistence infrastructure expose generic contracts. CLI and Web entrypoints reuse the same business validation, and platform support is selected through shared identity/capability definitions. Keep feature documentation synchronized with public behavior and protocol or schema contracts.

The root `zip_project.py` packages the source directories and root documentation, excluding runtime data, caches, dependencies, build output and diagnostic logs. Bundled External Tool resources remain part of the source snapshot. Review local profiles and resource contents for sensitive values before sharing any archive.
