# RCH Web Frontend

The Vue 3 / Vite frontend provides the RCH device console, Terminal and management tools. Element Plus supplies shared UI components; Monaco provides text editing and xterm provides PTY interaction.

## Development and deployment

```bash
npm ci
npm run dev
```

Start the Server separately with `python backend/run_web.py` from the project root. The default HTTP port is 8085 and the WebSocket port is HTTP port + 1. Use the same `RCH_WEB_PORT` on the Server and Vite when overriding the port:

```bash
RCH_WEB_PORT=9090 python3 backend/run_web.py
```

In a separate terminal at `frontend/`:

```bash
RCH_WEB_PORT=9090 npm run dev
```

`RCH_VITE_PORT` defaults to 5173. Vite proxies same-origin `/api` and `/ws` to the Server. A reverse proxy in front of Vite must preserve the browser-facing Host and support WebSocket Upgrade. In production, the built page is served by the Server's HTTP service and browser WebSocket connections use the next port.

```bash
npm run build
```

Deploy the entire `dist/` directory contents to `backend/static/`, including compressed assets. Publish new assets before switching `index.html`; retain hashed resources still needed by open tabs. See [Web Frontend Loading](../backend/docs/web_frontend_loading.md).

## UI architecture

`src/api/` owns HTTP request contracts and shared authentication/request helpers. Components and composables own current-device context, UI state, user confirmation and presentation. Shared dialogs, pickers, parameter schemas and formatters support consistent behavior across tools. The Server owns business validation, command catalogs and execution.

Toolbar, More and Toolbox use the shared tool catalog and the selected Client's Feature Manifest. Settings manages global preferences and Server functions. Agent Builder, Agent Outputs and One-liners are available without a selected online Client. See [Toolbox](../backend/docs/toolbar_toolbox.md) and [Listeners](../backend/docs/listeners.md).

WebSocket events provide live connection, task, notification and operation updates. Reconnect refreshes authoritative state; persistently recorded output can be recovered through Activity History. See [Command Execution](../backend/docs/command_execution.md) and [WebSocket Notifications](../backend/docs/websocket_notifications.md).

## Terminal history and performance

The Web Terminal stores output per signed-in user, browser tab and Client in IndexedDB. It renders a bounded recent window and loads earlier/later records while scrolling. Long lines are preserved as segments and rejoined for complete exports. Clear removes the selected Client's stored transcript; Copy and Save to Artifact read the complete transcript where the browser permits. Some non-HTTPS browser clipboard environments require a selection-based fallback for the visible window.

Output events are batched for rendering and persisted in order. A manual scroll away from the end pauses bottom-follow; a new Terminal command resumes it. Browser storage deletion, private-mode restrictions and quota errors can affect persistence; sign-out clears that user/tab's local transcript. Server Activity History follows its independent recording policy.

## Authentication and operations

The sign-in page uses the Server administrator Session. Password payload masking is obfuscation; protect the actual HTTP and WebSocket connections with HTTPS/WSS or a trusted network. See [Administrator Authentication](../backend/docs/admin_auth.md).

Device Dashboard, Processes and Log Viewer use managed monitor sessions; Remote Files, Transfers, PTY, Screen View and other tools retain their own lifecycle and cancellation behavior. See the [RCH documentation index](../README.md#documentation).

## Tests

Run the frontend regression suite from `frontend/`:

```bash
node --test tests/*.test.mjs
```

Use the production build and a real browser for interaction, responsive layout, authentication, asset loading and Server/Client integration checks.
