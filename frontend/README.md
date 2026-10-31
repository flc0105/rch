# Vue 3 + Vite

This template should help get you started developing with Vue 3 in Vite. The template uses Vue 3 `<script setup>` SFCs, check out the [script setup docs](https://v3.vuejs.org/api/sfc-script-setup.html#sfc-script-setup) to learn more.

Learn more about IDE Support for Vue in the [Vue Docs Scaling up Guide](https://vuejs.org/guide/scaling-up/tooling.html#ide-support).

## Log Viewer and sign-in

Log Viewer reads remote Client files. Its Browse button and remote path occupy the first toolbar row, with the remaining controls on the second row. Wrap is enabled by default, and the gutter displays line numbers relative to the currently loaded log buffer (search results retain those numbers). Watchdog log links appear immediately after each file path.

Administrator sign-in sends only a lightweight reversible masked password field, not a plaintext password field. It works with existing HTTP deployments and does not require a secure browser context. This is payload obfuscation only, **not** protection against interception on HTTP. The login page distinguishes credential errors, network errors, and server errors.

## Banner utilities

The right side of the banner shows Online Nodes, followed by Transfers, Notifications, and a Utilities dropdown. The Utilities menu opens One-liners or Build Agent without requiring a selected online Client. Sign out stays separate from the icon group.

## Production asset delivery

Build with `npm run build`, then copy **the entire** `frontend/dist/` directory
(including `assets/*.gz`) to `backend/static/`. Flask automatically serves the
precompressed JavaScript and CSS when the browser supports gzip. Vite-generated
hashed assets use a long-lived browser cache; deploy all new assets before
updating `index.html` and retain old hashed assets while older tabs may still be
open.

Optional dialogs download in priority order after the page's first paint during
browser idle time: External Tools, Command History, PTY, Background Jobs,
Processes, Keychains, then Preview and Documents (including Monaco). Moving the
pointer over a supported toolbar, More-menu, or Toolbox action can preload its
dialog earlier.

Element Plus is installed globally with its complete stylesheet so all component
styles, child-component styles, directives, and layout rules match the original UI.
Programmatic message/confirmation/notification APIs remain imported directly where
used. The Vite auto-registration plugin is not required.

## Local development ports

The Server HTTP listener is configured by `RCH_WEB_PORT` (default `8085`);
its WebSocket listener always uses the next port. Start the Vite developer
server with **the same** `RCH_WEB_PORT` environment value as the Server:

```sh
RCH_WEB_PORT=9090 python3 backend/run_web.py
# From frontend/ in a second terminal:
RCH_WEB_PORT=9090 npm run dev
```

Vite forwards `/api` to the configured HTTP port and `/ws` to HTTP port + 1.
Browser uploads use `/api/...` URLs on the current page origin, so the dev
server proxy is applied without browser CORS changes. The PTY, Screen and
notification WebSocket paths all use the same browser URL helper.
The Vite listening port can be overridden with `RCH_VITE_PORT` (default `5173`);
provide the same value to the Server when using a nondefault development port
so its WebSocket Origin check accepts the development page.

In production, RCH serves the built frontend on its HTTP port; the browser
connects WebSocket directly to that HTTP port + 1.
