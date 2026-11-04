import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import { terminalOneLiners } from '../src/data/terminalOneLiners.js'

function component(path) {
  const source = readFileSync(new URL(`../src/components/${path}`, import.meta.url), 'utf8')
  const script = source.split('<script>')[1].split('</script>')[0]
    .replace(/\bimport\s+[\s\S]*?\sfrom\s*['"][^'"]+['"]\s*;?/g, '')
    .replace('export default', 'module.exports =')
  const context = {module: {exports: {}}, window: {location: {hostname: 'lan.host'}}, terminalOneLiners, AddListenerDialog: {}}
  vm.runInNewContext(script, context)
  return {source, component: context.module.exports}
}

function stateOf(c) {
  const state = {...c.data.call({getDefaultServerForm: c.methods.getDefaultServerForm})}
  for (const [key, method] of Object.entries(c.methods)) state[key] = method.bind(state)
  return state
}

test('one-liner default TCP remains unchanged and TLS passes a single listener ID', () => {
  const {component: c, source} = component('OneLinersDialog.vue')
  const state = stateOf(c)
  state.serverForm = {serverHost: '192.168.1.20', serverPort: '9999', webPort: '8085'}
  state.listeners = [
    {id: 'tcp-default', name: 'TCP', port: 9999, protocol: 'tcp'},
    {id: 'tls-123', name: 'TLS', port: 9443, protocol: 'tls_tcp'},
  ]
  state.selectedListenerId = 'tcp-default'
  for (const item of terminalOneLiners) {
    const command = state.renderOneLinerCode(item.code)
    assert.doesNotMatch(command, /listener_id|{{/)
    assert.match(command, /9999/)
  }
  state.selectedListenerId = 'tls-123'
  state.onListenerChange('tls-123')
  const python = state.renderOneLinerCode(terminalOneLiners[0].code)
  const ps1 = state.renderOneLinerCode(terminalOneLiners[1].code)
  assert.match(python, /'listener_id':'tls-123'/)
  assert.match(ps1, /`"listener_id`":`"tls-123`"/)
  assert.match(python, /9443/)
  assert.match(ps1, /9443/)
  assert.doesNotMatch(python, /{{/)
  assert.doesNotMatch(ps1, /{{/)
  assert.match(source, /@change="onListenerChange"/)
  const labels = [...source.matchAll(/<span>(Listener|Server IP|Web port)<\/span>/g)].map(match => match[1])
  assert.deepEqual(labels, ['Listener', 'Server IP', 'Web port'])
})

test('Listener dialog has visible action buttons and mobile presentation', () => {
  const {source} = component('ListenerManagerDialog.vue')
  assert.match(source, /width="1080px"/)
  assert.match(source, /:close-on-click-modal="true"/)
  assert.match(source, /class="listener-actions"/)
  assert.match(source, /@media \(max-width: 960px\)/)
  assert.match(source, /height: 100dvh !important/)
  assert.ok(source.indexOf('>Refresh</el-button>') > 0)
  assert.ok(source.indexOf('>Add</el-button>') > 0)
  assert.match(source, /:disabled="row.id === 'tcp-default'"/)
  assert.doesNotMatch(source, /<template #footer>/)
  assert.match(source, /<AddListenerDialog /)
})

test('Listener toolbar is below the dialog title and above the scrollable table', () => {
  const {source} = component('ListenerManagerDialog.vue')
  const template = source.split('</template>\n\n<script>')[0]
  assert.match(template, /<el-dialog[^>]*title="Listeners"/)
  assert.doesNotMatch(template, /<template #header>/)
  const toolbar = template.indexOf('<div class="listener-manager-toolbar">')
  const table = template.indexOf('<div class="listener-manager-table">')
  assert.ok(toolbar > template.indexOf('<div class="listener-manager-content"'), 'toolbar must be inside dialog body')
  assert.ok(table > toolbar, 'table must follow toolbar')
  assert.match(template.slice(toolbar, table), /@click="load">Refresh<\/el-button>/)
  assert.match(template.slice(toolbar, table), /@click="openAdd">Add<\/el-button>/)
  assert.match(source, /listener-manager-toolbar \{ flex: 0 0 auto;/)
  assert.match(source, /listener-manager-table \{ flex: 1;/)
})

test('Listener tag follows device name before status icons; history details show Listener', () => {
  const device = readFileSync(new URL('../src/components/DeviceSidebar.vue', import.meta.url), 'utf8')
  const segment = device.slice(device.indexOf('class="device-name-row"'), device.indexOf('class="device-os"'))
  assert.ok(segment.indexOf('class="device-listener-tag"') < segment.indexOf('<ClockAlert'))
  const history = readFileSync(new URL('../src/components/MachineConnectionHistoryDialog.vue', import.meta.url), 'utf8')
  assert.equal((history.match(/<span class="label">Listener<\/span>/g) || []).length, 2)
  assert.match(history, /formatListener\(row\)/)
  assert.match(history, /port \${port}/)
})

test('banner Utilities opens the existing Settings dialog', () => {
  const app = readFileSync(new URL('../src/App.vue', import.meta.url), 'utf8')
  assert.match(app, /<el-dropdown-item command="settings">Settings<\/el-dropdown-item>/)
  const match = app.match(/handleBannerUtilityCommand\(command\) \{([\s\S]*?)\n    \},/)
  assert.ok(match)
  const handler = vm.runInNewContext(`(function(command){ ${match[1]} })`)
  let called = 0
  handler.call({openSettingsDialog() {called++}}, 'settings')
  assert.equal(called, 1)
})
