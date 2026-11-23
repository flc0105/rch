import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'

const read = path => readFileSync(new URL(path, import.meta.url), 'utf8')
const connections = read('../src/composables/useConnections.js')
const sidebar = read('../src/components/DeviceSidebar.vue')
const dialog = read('../src/components/ConnectToClientDialog.vue')
const api = read('../src/api/connectionsApi.js')
const component = vm.runInNewContext(`(() => {
 ${connections.replace(/^import .*$/gm, '').replace('export default', 'const component =')}; return component })()`, {})

function sidebarEntries(sessions, targets) {
  const instance = {
    ...component.data(), connections: sessions, savedBindTargets: targets,
    decorateConnectionForDeviceView: x => x,
    getConnectionDisplayState: x => x.connection_state,
    isConnectionInSelectedDeviceGroup: () => true,
    getMachineAlias: () => '',
    compareSidebarConnectionOrder: (a, b) =>
      (a.sidebar_key || a.client_id).localeCompare(b.sidebar_key || b.client_id),
  }
  return Array.from(component.computed.deviceSidebarConnections.call(instance))
}

test('two offline Bind endpoints on the same machine remain independent of Reverse history', () => {
  const targets = [
    { target_id: 'a', host: '127.0.0.1', port: 9443, machine_id: 'machine-1', name: 'First' },
    { target_id: 'b', host: '127.0.0.1', port: 9555, machine_id: 'machine-1', name: 'Second' },
  ]
  const entries = sidebarEntries([
    { client_id: 'reverse-recent', connection_direction: 'reverse',
      machine_id: 'machine-1', connection_state: 'offline', listener_protocol: 'tls_tcp' },
  ], targets)
  assert.deepEqual(entries.map(x => x.sidebar_key || x.client_id),
    ['bind:a', 'bind:b', 'reverse-recent'])
  assert.deepEqual(entries.filter(x => x.saved_bind_target).map(x => x.saved_bind_target.port), [9443, 9555])
})

test('online Bind target is shown as its live session, not an extra offline copy', () => {
  const target = { target_id: 'a', host: '127.0.0.1', port: 9443, machine_id: 'machine-1' }
  const entries = sidebarEntries([
    { client_id: 'live-bind', bind_target_id: 'a', connection_direction: 'bind',
      machine_id: 'machine-1', listener_protocol: 'bind_tcp', connection_state: 'online' },
  ], [target])
  assert.equal(entries.length, 1)
  assert.equal(entries[0].client_id, 'live-bind')
  assert.equal(entries[0].saved_bind_target.target_id, 'a')
})

test('Device Bar retains Connect shortcut and original Listener tag with Bind border accent', () => {
  assert.match(sidebar, /class="device-toolbar-connect-btn"/)
  assert.match(sidebar, /<CirclePlus :size="17"/)
  assert.match(sidebar, /connect-saved-target/)
  assert.match(sidebar, /edit-saved-target/)
  assert.match(sidebar, /removeSavedBindTarget/)
  assert.match(sidebar, /class="device-listener-tag"/)
  assert.match(sidebar, /size="small" type="info" effect="plain"/)
  assert.match(sidebar, /item\.connection_direction === 'bind' \? 'Bind' : item\.listener_name/)
  assert.match(sidebar, /device-listener-tag-bind/)
  assert.match(sidebar, /border-color: var\(--el-color-primary-light-5\)/)
  assert.match(sidebar, /\.device-listener-tag-bind\s*\{[^}]*color:\s*var\(--el-color-primary\)/)
  assert.match(sidebar, /<LockKeyhole class="device-locked-indicator"/)
  assert.doesNotMatch(sidebar, /device-transport-meta|device-ip-separator|getDirectionProtocolLabel/)
  assert.match(dialog, /@click="save">Save/)
  assert.match(api, /export function listSavedBindTargets/)
})

test('missing or unknown operating system displays a dash without changing known names', () => {
  assert.match(sidebar, /\{\{ formatOsLabel\(item\.os_type\) \}\}/)
  const method = sidebar.match(/formatOsLabel\(osType\) \{[\s\S]*?\n    \}/)?.[0]
  assert.ok(method)
  const formatOsLabel = vm.runInNewContext(`({ ${method} }).formatOsLabel`, {})
  assert.equal(formatOsLabel(null), '-')
  assert.equal(formatOsLabel(''), '-')
  assert.equal(formatOsLabel('Unknown'), '-')
  assert.equal(formatOsLabel(' unknown '), '-')
  assert.equal(formatOsLabel('macOS'), 'macOS')
  assert.equal(formatOsLabel('Windows'), 'Windows')
  assert.equal(formatOsLabel('iOS'), 'iOS')
})

test('Device Bar scrollbar is thin with a transparent track and a low-contrast rounded thumb', () => {
  assert.match(sidebar, /\.sidebar-body\s*\{[^}]*scrollbar-width:\s*thin/)
  assert.match(sidebar, /\.sidebar-body\s*\{[^}]*scrollbar-color:\s*rgba\(148, 163, 184, 0\.35\) transparent/)
  assert.match(sidebar, /\.sidebar-body::-webkit-scrollbar\s*\{[^}]*width:\s*8px/)
  assert.match(sidebar, /\.sidebar-body::-webkit-scrollbar-track\s*\{[^}]*background:\s*transparent/)
  assert.match(sidebar, /\.sidebar-body::-webkit-scrollbar-thumb\s*\{[^}]*border-radius:\s*999px/)
  assert.match(sidebar, /\.sidebar-body::-webkit-scrollbar-thumb\s*\{[^}]*background-clip:\s*padding-box/)
  assert.match(sidebar, /\.sidebar-body::-webkit-scrollbar-thumb:hover\s*\{/)
})

test('offline Bind keeps its last Client ID to select the same history as an offline Reverse', () => {
  const target = {
    target_id: 'a', host: '127.0.0.1', port: 9433,
    machine_id: 'machine-1', last_client_id: 'previous-bind-client', name: 'Office',
  }
  const entries = sidebarEntries([], [target])
  assert.equal(entries.length, 1)
  assert.equal(entries[0].client_id, 'previous-bind-client')
  assert.equal(entries[0].sidebar_key, 'bind:a')
  assert.equal(entries[0].connection_state, 'offline')

  let selected = null
  const instance = {
    connections: [], deviceSidebarConnections: entries, selectedId: '',
    rememberSelectedConnection: item => { selected = item },
    ensureOutputBucket: () => {}, refreshClientRevisionStatus: () => {},
    reloadCommandCandidatesFromRuntime: () => {}, scrollToBottom: () => {},
    refreshBackgroundJobsIfOpen: () => {},
  }
  component.methods.selectConnection.call(instance, 'previous-bind-client')
  assert.equal(instance.selectedId, 'previous-bind-client')
  assert.equal(selected.saved_bind_target.name, 'Office')
  assert.equal(component.computed.currentConnection.call(instance), entries[0])
})

test('online and offline Bind prefer Connection Name over machine alias and hostname', () => {
  const decorate = component.methods.decorateConnectionForDeviceView
  const decorated = item => decorate.call({
    getMachineAlias: () => 'Machine Alias',
    isClientIdHidden: () => false,
    isMachineIdHidden: () => false,
  }, item)
  const target = { target_id: 'one', host: 'localhost', port: 9443, machine_id: 'm',
    hostname: 'host', name: 'Custom Connection Name' }
  const instance = {
    ...component.data(), connections: [{
      client_id: 'live', machine_id: 'm', bind_target_id: 'one',
      hostname: 'host', connection_direction: 'bind', connection_state: 'online',
    }], savedBindTargets: [target],
    decorateConnectionForDeviceView: decorated,
    getConnectionDisplayState: x => x.connection_state,
    isConnectionInSelectedDeviceGroup: () => true,
    getMachineAlias: () => 'Machine Alias',
    compareSidebarConnectionOrder: (a, b) => String(a.sidebar_key || a.client_id).localeCompare(String(b.sidebar_key || b.client_id)),
  }
  const online = component.computed.deviceSidebarConnections.call(instance)[0]
  assert.equal(online.device_display_name, 'Custom Connection Name')
  instance.connections = []
  const offline = component.computed.deviceSidebarConnections.call(instance)[0]
  assert.equal(offline.device_display_name, 'Custom Connection Name')
  target.name = ''
  assert.equal(component.computed.deviceSidebarConnections.call(instance)[0].device_display_name, 'Machine Alias')
  instance.getMachineAlias = () => ''
  instance.decorateConnectionForDeviceView = item => decorate.call({
    getMachineAlias: () => '', isClientIdHidden: () => false, isMachineIdHidden: () => false,
  }, item)
  assert.equal(component.computed.deviceSidebarConnections.call(instance)[0].device_display_name, 'host')
})

test('Device Bar restores original address line and listener tag dimensions', () => {
  assert.match(sidebar, /<div class="device-ip">\s*\{\{ formatAddress\(item\.addr, item\) \}\}\s*<\/div>/)
  assert.match(sidebar, /\.device-ip \{\s*margin-top: 9px;\s*font-size: 12px;\s*color: var\(--muted-2\);\s*overflow: hidden;\s*text-overflow: ellipsis;\s*white-space: nowrap;\s*\}/)
  assert.match(sidebar, /\.device-listener-tag \{\s*flex: 0 1 auto;\s*min-width: 0;\s*max-width: 76px;\s*height: 17px;\s*padding: 0 5px;\s*line-height: 15px;\s*font-size: 10px;\s*font-weight: 500;\s*border-radius: 4px;\s*\}/)
  assert.doesNotMatch(sidebar, /device-ip-address|device-ip-separator|device-transport-meta/)
})

test('Bind without a historical Client ID prompts Connect instead of opening machine history', () => {
  const notifications = []
  const componentScript = sidebar.match(/<script>([\s\S]*?)<\/script>/)?.[1] || ''
  const javascript = componentScript.replace(/^import[\s\S]*?from ['"][^'"]+['"]\s*$/gm, '')
    .replace('export default', 'const component =') + '\ncomponent'
  const context = {
    ElMessage: { info: message => notifications.push(message) },
    CirclePlus: {}, ClockAlert: {}, LockKeyhole: {}, ShieldPlus: {},
  }
  const sidebarComponent = vm.runInNewContext(javascript, context)
  const events = []
  const instance = {
    suppressNextDeviceClick: false,
    closeDeviceContextMenu: () => {},
    $emit: (event, ...args) => events.push([event, ...args]),
  }
  const click = sidebarComponent.methods.handleDeviceClick
  click.call(instance, { saved_bind_target: { host: '127.0.0.1', port: 9443 }, machine_id: 'machine-1', client_id: '' })
  assert.deepEqual(events, [])
  assert.deepEqual(notifications, ['Connect first'])

  click.call(instance, { saved_bind_target: { host: '127.0.0.1', port: 9443 }, machine_id: 'machine-1', client_id: 'previous-bind-client' })
  assert.deepEqual(events, [['select', 'previous-bind-client']])
  assert.deepEqual(notifications, ['Connect first'])
  assert.match(sidebar, /'connection-history'/)
})
