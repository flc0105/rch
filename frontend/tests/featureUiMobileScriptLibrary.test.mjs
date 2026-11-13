import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import vm from 'node:vm'

const read = file => readFileSync(new URL(file, import.meta.url), 'utf8')
const sidebar = read('../src/components/DeviceSidebar.vue')
const app = read('../src/App.vue')
const info = read('../src/components/ConnectionInfoDialogs.vue')
const scriptLibrary = read('../src/components/ScriptLibraryDialog.vue')

function connectionInfoOptions() {
  const script = info.match(/<script>([\s\S]*?)<\/script>/)?.[1]
  assert.ok(script)
  const sandbox = { WatchdogInfoPanel: {}, IosDashboardPanel: {} }
  const code = script.replace(/^import\s+[\s\S]*?\s+from\s+['"][^'"]+['"]\s*;?\s*$/gm, '')
    .replace('export default {', 'globalThis.options = {')
  vm.runInNewContext(code, sandbox, { timeout: 1000 })
  return sandbox.options
}

const options = connectionInfoOptions()

test('device sidebar status icons use actual Element Plus hover tooltips', () => {
  assert.match(sidebar, /<el-tooltip\s+v-if="[^"]*client_revision_state === 'outdated'"\s+content="Outdated"/)
  assert.match(sidebar, /<el-tooltip\s+v-if="[^"]*isElevated\(item\)"\s+content="Elevated"/)
  assert.match(sidebar, /<span class="device-indicator-tooltip" aria-label="Outdated">/)
  assert.match(sidebar, /<span class="device-indicator-tooltip" aria-label="Elevated">/)
})

test('Configuration renders backend set JSON item order without key-specific frontend sorting', () => {
  const base = ['COMMAND_DEFAULT_SHELL_TIMEOUT', 'COMMAND_DEFAULT_STREAM_TIMEOUT', 'SCRIPT_DEFAULT_TIMEOUT', 'OTHER']
  const ctx = { currentConnection: { feature_manifest: {} }, ...options.methods }
  ctx.applyRuntimeConfigPayload({ store_path: 'file.json', items: base.map(key => ({ key })) })
  assert.equal(ctx.runtimeConfigStorePath, 'file.json')
  assert.deepEqual(Array.from(ctx.runtimeConfigItems, row => row.key), base)
  assert.doesNotMatch(info, /scriptIndex|shellIndex|items\.splice\(/)
  ctx.applyRuntimeConfigPayload({ items: [{ key: 'OTHER' }, { key: 'SCRIPT_DEFAULT_TIMEOUT' }] })
  assert.deepEqual(Array.from(ctx.runtimeConfigItems, row => row.key), ['OTHER', 'SCRIPT_DEFAULT_TIMEOUT'])
})

test('Dashboard surfaces backend error verbatim and hides stale metric cards', async () => {
  const ctx = { currentConnection: { feature_manifest: { device_monitor: false } }, monitorError: '', ...options.methods }
  assert.match(options.computed.monitorDisplayError.call(ctx), /not supported on this Client/)
  ctx.monitorError = 'backend: device monitor unavailable'
  assert.equal(options.computed.monitorDisplayError.call(ctx), ctx.monitorError)
  assert.match(info, /v-if="monitorDisplayError"[\s\S]*?\{\{ monitorDisplayError \}\}/)
  assert.match(info, /<template v-else>\s*<div class="monitor-overview-grid">/)
  ctx.infoVisible = true
  ctx.activeTab = 'dashboard'
  ctx.selectedId = 'go-client'
  let fetches = 0
  const previousFetch = globalThis.fetch
  globalThis.fetch = () => { fetches += 1; throw Error('unexpected request') }
  try {
    await ctx.startDeviceMonitor()
    assert.equal(fetches, 0)
  } finally {
    globalThis.fetch = previousFetch
  }
})

test('Log Viewer is gated by feature manifest in Toolbar and direct App open', () => {
  const toolbar = read('../src/components/TerminalToolbar.vue')
  assert.match(toolbar, /'log-viewer': 'log_viewer'/)
  const js = app.match(/    openLogViewerDialog\(source = \{\}\) \{([\s\S]*?)\n    \},/)?.[1]
  assert.ok(js)
  const open = new Function('source', js)
  const seen = []
  const ctx = { selectedId: 'go-client', currentConnection: { client_id: 'go-client', feature_manifest: { log_viewer: false } }, $refs: { logViewerDialogRef: { open: source => seen.push(source) } } }
  open.call(ctx, {})
  assert.equal(seen.length, 0)
  ctx.currentConnection.feature_manifest.log_viewer = true
  open.call(ctx, {})
  assert.equal(seen.length, 1)
})

test('Script Library returns to existing mobile styles and card sizing', () => {
  const css = scriptLibrary.match(/<style scoped>([\s\S]*?)<\/style>/)?.[1] || ''
  assert.match(css, /@media \(max-width: 760px\)/)
  assert.match(css, /grid-template-rows: minmax\(120px, 28%\) minmax\(0, 1fr\)/)
  assert.doesNotMatch(css, /grid-template-rows: minmax\(112px, 31%\)/)
  assert.doesNotMatch(css, /height: 28px;[\s\S]*?padding: 0 7px;/)
  assert.match(scriptLibrary, /@click="openScriptRunDialog\(item\)"/)
  assert.match(scriptLibrary, /@click="openRemoteScriptEditor\(item.script_name\)"/)
})


test('Script mode radios remain visible but are disabled outside effective allowed values', () => {
  const run = read('../src/components/ScriptRunDialog.vue')
  for (const [key, values] of Object.entries({execution_mode: ['inproc', 'subprocess_pipe'], output_mode: ['collect', 'stream']})) {
    for (const value of values) {
      assert.ok(run.includes(`value="${value}" :disabled="!modeOptions.${key}?.allowed?.includes('${value}')"`))
    }
  }
  assert.match(run, /\.script-run-modes :deep\(\.el-form-item__content\)\s*\{\s*display: block;/)
  assert.match(run, /\.script-run-mode-help\s*\{\s*display: block;\s*width: 100%;\s*margin-top: 6px;/)
  assert.match(run, /:disabled="submitting \|\| !modesReady"/)
  assert.match(run, /\.script-run-mode-toggle\s*\{[^}]*background: var\(--el-fill-color-extra-light\)/)
  assert.match(run, /modesExpanded: false/)
  assert.match(run, /v-show="modesExpanded"/)
  assert.match(run, /:aria-expanded="modesExpanded" @click="modesExpanded = !modesExpanded"/)
  assert.match(run, /visible\(value\) \{\s*if \(value\) this.modesExpanded = false/)

})

test('Script list title includes the existing Lucide script icon and platform/parameter tags, with width-dependent mobile actions', () => {
  const heading = scriptLibrary.match(/class="script-library-card-heading"[\s\S]*?class="script-library-card-path mono"/)?.[0] || ''
  assert.match(heading, /<FileCode2[\s\S]*?item\.display_name \|\| item\.script_name[\s\S]*?formatScriptPlatformLabel\(item\)[\s\S]*?Params/)
  assert.match(scriptLibrary, /import \{ FileCode2 \} from '@lucide\/vue'/)
  assert.match(scriptLibrary, /@container \(width < 520px\)[\s\S]*?grid-template-columns: repeat\(3, minmax\(0, 1fr\)\)/)
  assert.match(scriptLibrary, /@container \(width < 420px\)[\s\S]*?grid-template-columns: repeat\(2, minmax\(0, 1fr\)\)/)
  assert.match(scriptLibrary, /\.script-library-card-actions :deep\(\.el-dropdown\)\s*\{\s*grid-column: 1 \/ -1;/)
  assert.match(scriptLibrary, /\.script-library-card-actions :deep\(\.el-button\)\s*\{\s*border-radius: 6px;/)
  assert.doesNotMatch(scriptLibrary, /min-width: 64px;\s*height: 32px;/)
  assert.doesNotMatch(scriptLibrary, /@container \(width < 208px\)/)
  assert.match(scriptLibrary, /@command="handleScriptMoreCommand\(item, \$event\)"/)
})
