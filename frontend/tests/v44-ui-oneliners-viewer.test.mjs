import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'

const read = file => readFileSync(new URL(file, import.meta.url), 'utf8')
const json = read('../src/components/TerminalJsonDialog.vue')
const oneliner = read('../src/components/OneLinersDialog.vue')
const listener = read('../src/components/ListenerManagerDialog.vue')
const connect = read('../src/components/ConnectToClientDialog.vue')
const quick = read('../src/components/QuickActionsDialog.vue')

function component(src, context = {}) {
  const script = src.match(/<script>([\s\S]*?)<\/script>/)?.[1]
  assert.ok(script)
  return vm.runInNewContext(`(${script.replace(/^import .*$/gm, '').replace('export default', '')})`, context)
}

test('connect form keeps Server Web URL label on a single line', () => {
  assert.match(connect, /label-position="top"/)
  assert.match(connect, /\.bind-connect-dialog \.el-form-item__label \{ white-space: nowrap; \}/)
})

test('reverse One-liner omits mode but Bind includes it, keeping mTLS listener selection', () => {
  const cmp = component(oneliner)
  const ctx = { selectedListenerId: 'tcp-default', listeners: [{ id: 'tcp-default' }, { id: 'tls1' }],
    serverForm: { serverHost: '192.0.2.2', serverPort: '9999', webPort: '8085' },
    connectionMode: 'reverse', bindHost: '0.0.0.0', bindPort: '9443' }
  const code = `json={{bootstrap_payload_python}}`
  const reverse = cmp.methods.renderOneLinerCode.call(ctx, code)
  assert.doesNotMatch(reverse, /connection_mode/)
  assert.match(reverse, /server_port/)
  ctx.selectedListenerId = 'tls1'
  assert.match(cmp.methods.renderOneLinerCode.call(ctx, code), /listener_id.*tls1/)
  ctx.connectionMode = 'bind'
  const bind = cmp.methods.renderOneLinerCode.call(ctx, code)
  assert.match(bind, /connection_mode.*bind/)
  assert.doesNotMatch(bind, /server_port/)
})

test('mTLS listener manager has no legacy certificate pinning action', () => {
  assert.doesNotMatch(listener, /<el-table-column label="TLS Fingerprint"/)
  assert.doesNotMatch(listener, /showCertificate|certificateVisible|tls_fingerprint|row.protocol === 'tls_tcp'/)
  const cmp = component(listener, { AddListenerDialog: {} })
  assert.deepEqual(Array.from(cmp.data().listeners), [])
  assert.match(listener, /row.protocol_label/)
})

test('Quick Actions toolbar matches Remote Files small control typography and 32px height', () => {
  const toolbar = quick.split('quick-actions-table-shell')[0]
  assert.match(toolbar, /v-model="filterPlatform" size="small"/)
  assert.match(toolbar, /v-model="searchText"[\s\S]*?size="small"/)
  assert.match(toolbar, /type="primary" size="small" class="quick-actions-new-button"/)
  assert.doesNotMatch(quick, /border-radius: 10px;\s*font-size: 14px;/)
  assert.match(quick, /\.platform-filter :deep\(\.el-select__wrapper\)/)
  assert.match(quick, /\.quick-actions-search :deep\(\.el-input__wrapper\)/)
  assert.match(quick, /min-height: 32px/)
})

test('JSON toolbar keeps copy and rerun; More dispatches all actions with original semantics', () => {
  assert.match(json, /@click="copyTerminalJsonRaw">Copy<\/el-button>/)
  assert.match(json, /@click="runAgain">Run Again<\/el-button>/)
  for (const command of ['save-artifact', 'toggle-raw', 'toggle-card']) assert.match(json, new RegExp(`command="${command}"`))
  const cmp = component(json)
  const calls = []
  const ctx = { hasTerminalJsonRenderView: true, displayMode: 'table', isTerminalJsonRawView: false,
    tableViewMode: 'card', saveTerminalJsonToArtifact: () => calls.push('save'),
    toggleTerminalJsonViewMode: () => calls.push('raw') }
  cmp.methods.handleToolbarCommand.call(ctx, 'save-artifact')
  cmp.methods.handleToolbarCommand.call(ctx, 'toggle-raw')
  cmp.methods.handleToolbarCommand.call(ctx, 'toggle-card')
  assert.deepEqual(calls, ['save', 'raw'])
  assert.equal(ctx.tableViewMode, 'table')
})

test('JSON card view is single-column and default titles use zero-based #index', () => {
  assert.match(json, /\.terminal-json-cards \{ display: grid; grid-template-columns: minmax\(0, 1fr\)/)
  const cmp = component(json)
  const instance = { resultView: { titleField: null } }
  assert.equal(cmp.methods.cardTitle.call(instance, { name: 'row' }, 0), '#0')
  assert.equal(cmp.methods.cardTitle.call(instance, { name: 'row' }, 1), '#1')
  instance.resultView.titleField = 'name'
  assert.equal(cmp.methods.cardTitle.call(instance, { name: 'data' }, 1), 'data')
  assert.equal(cmp.methods.cardTitle.call(instance, { name: 0 }, 1), 0)
})
