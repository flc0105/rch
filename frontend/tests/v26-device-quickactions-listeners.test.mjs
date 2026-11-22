import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import { formatConnectionDirection } from '../src/utils/connectionInfoFormatting.js'

const read = file => readFileSync(new URL(file, import.meta.url), 'utf8')
const connections = read('../src/composables/useConnections.js')
const sidebar = read('../src/components/DeviceSidebar.vue')
const app = read('../src/App.vue')
const actions = read('../src/components/QuickActionsDialog.vue')
const listeners = read('../src/components/ListenerManagerDialog.vue')
const history = read('../src/components/MachineConnectionHistoryDialog.vue')

function connectionComponent() {
  const source = connections.replace(/^import .*$/gm, '').replace('export default', 'const component =')
  return vm.runInNewContext(`(() => { ${source}; return component })()`, {})
}

test('show offline devices defaults on; hiding offline preserves stale/online and hidden filtering', () => {
  const component = connectionComponent()
  assert.equal(component.data().showOfflineDevices, true)
  const source = [
    { client_id: 'online', connection_state: 'online' },
    { client_id: 'old', connection_state: 'offline' },
    { client_id: 'hidden', connection_state: 'online', device_hidden: true },
    { client_id: 'stale', connection_state: 'stale' },
  ]
  const vmInstance = {
    ...component.data(), connections: source,
    decorateConnectionForDeviceView: x => x,
    isConnectionInSelectedDeviceGroup: () => true,
    getConnectionDisplayState: x => x.connection_state,
    compareSidebarConnectionOrder: (a, b) => a.client_id.localeCompare(b.client_id),
    ensureSelectedConnectionVisible() { this.checked = true },
  }
  const visible = () => Array.from(component.computed.deviceSidebarConnections.call(vmInstance), x => x.client_id)
  assert.deepEqual(visible(), ['old', 'online', 'stale'])
  component.methods.toggleShowOfflineDevices.call(vmInstance)
  assert.equal(vmInstance.showOfflineDevices, false)
  assert.equal(vmInstance.checked, true)
  assert.deepEqual(visible(), ['online', 'stale'])
  vmInstance.showHiddenDevices = true
  assert.deepEqual(visible(), ['hidden', 'online', 'stale'])
  component.methods.toggleShowOfflineDevices.call(vmInstance)
  assert.deepEqual(visible(), ['hidden', 'old', 'online', 'stale'])
  assert.match(sidebar, /command="toggle-offline"/)
  assert.match(sidebar, /Hide offline devices/)
  assert.match(app, /:show-offline-devices="showOfflineDevices"/)
  assert.match(app, /@toggle-offline-devices="toggleShowOfflineDevices"/)
})

test('mobile Quick Actions uses the same Element Plus search input as desktop', () => {
  assert.match(actions, /<el-input\s+v-model="searchText"\s+clearable\s+class="quick-actions-search"/)
  assert.doesNotMatch(actions, /<input\s+v-model="searchText"/)
  assert.match(actions, /\.quick-actions-search \{ flex: 0 0 auto; width: 100%; min-width: 0; \}/)
  assert.match(actions, /const keyword = String\(this\.searchText \|\| ''\)/)
  assert.match(actions, /v-for="row in filteredItems"/)
})

test('Direction formatting and history Details use the existing persisted direction', () => {
  assert.equal(formatConnectionDirection('bind'), 'Bind')
  assert.equal(formatConnectionDirection('reverse'), 'Reverse')
  assert.equal(formatConnectionDirection(''), '-')
  assert.match(history, /formatConnectionDirection\(row\.connection_direction\)/)
  assert.match(history, /formatConnectionDirection\(scope\.row\.connection_direction\)/)
})

test('listener manager shows complete TLS fingerprint with copy, also on mobile', () => {
  assert.match(listeners, /TLS Fingerprint/)
  assert.match(listeners, /row\.tls_fingerprint/)
  assert.match(listeners, /navigator\.clipboard\.writeText\(value\)/)
  assert.match(listeners, /listener-fingerprint-mobile/)
})
