# Vue 3 + Vite

This template should help get you started developing with Vue 3 in Vite. The template uses Vue 3 `<script setup>` SFCs, check out the [script setup docs](https://v3.vuejs.org/api/sfc-script-setup.html#sfc-script-setup) to learn more.

Learn more about IDE Support for Vue in the [Vue Docs Scaling up Guide](https://vuejs.org/guide/scaling-up/tooling.html#ide-support).

## Log Viewer and sign-in

Log Viewer reads remote Client files. Its Browse button and remote path occupy the first toolbar row, with the remaining controls on the second row. Wrap is enabled by default, and the gutter displays line numbers relative to the currently loaded log buffer (search results retain those numbers). Watchdog log links appear immediately after each file path.

Administrator sign-in sends only a lightweight reversible masked password field, not a plaintext password field. It works with existing HTTP deployments and does not require a secure browser context. This is payload obfuscation only, **not** protection against interception on HTTP. The login page distinguishes credential errors, network errors, and server errors.
