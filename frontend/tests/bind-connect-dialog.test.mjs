import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'

const read = file => readFileSync(new URL(file, import.meta.url), 'utf8')
const sidebar = read('../src/components/DeviceSidebar.vue')
const dialog = read('../src/components/ConnectToClientDialog.vue')
const app = read('../src/App.vue')
const api = read('../src/api/connectionsApi.js')

function method(source, name, stop, context = {}) {
  const begin = source.indexOf(`    ${name}(`)
  const end = source.indexOf(stop, begin)
  assert.ok(begin >= 0 && end > begin, `found ${name}`)
  return vm.runInNewContext(`({${source.slice(begin, end)}}).${name}`, context)
}

test('Device More emits Connect to Client and App opens the dialog', () => {
  assert.match(sidebar, /<el-dropdown-item command="connect-to-client">Connect to Client<\/el-dropdown-item>/)
  assert.match(app, /@connect-to-client="\$refs\.connectToClientDialogRef\?\.open\(\)"/)
  assert.match(app, /<ConnectToClientDialog ref="connectToClientDialogRef" @connected="handleBindClientConnected"/)
  const handle = method(sidebar, 'handleToolbarCommand', '    handleDeviceFilterCommand(')
  const events = []
  handle.call({ $emit: (...args) => events.push([...args]) }, 'connect-to-client')
  assert.equal(events.length, 1)
  assert.deepEqual(Array.from(events[0]), ['connect-to-client'])
})

test('Connect dialog passes a typed address and port to the connection API', async () => {
  assert.match(api, /api\/connections\/bind\/connect/)
  assert.match(api, /api\/connections\/\$\{encodeURIComponent\(clientId\)\}\/disconnect/)
  const source = dialog.match(/<script>([\s\S]*?)<\/script>/)?.[1]
  assert.ok(source)
  const events = []
  const sent = []
  const component = vm.runInNewContext(`(${source.replace(/^import .*$/gm, '').replace('export default', '')})`, {
    connectToClient: async (...args) => { sent.push(args); return { client_id: 'new-client' } },
    ElMessage: { success() {}, error(error) { throw error }, warning() { throw Error('bad input') } },
  })
  const dialogObject = { ...component.data(), $emit: (...args) => events.push(args) }
  dialogObject.visible = true
  dialogObject.form = { host: ' 192.168.1.25 ', port: '9443', serverWebBaseUrl: 'http://lan-server:8085' }
  await component.methods.connect.call(dialogObject)
  assert.deepEqual(Array.from(sent[0]), ['192.168.1.25', 9443, 'http://lan-server:8085', ''])
  assert.equal(dialogObject.visible, false)
  assert.equal(dialogObject.connecting, false)
  assert.deepEqual(Array.from(events[0]), ['connected', 'new-client'])
})

test('Device lifecycle actions use separate APIs, and reconnect selects the returned session', async () => {
  const source = sidebar.match(/<script>([\s\S]*?)<\/script>/)?.[1]
  const calls = [], events = []
  const start = source.indexOf('async runLifecycleAction(item, action) {')
  const end = source.indexOf('async removeConnectionPermanently(', start)
  const run = vm.runInNewContext(`({${source.slice(start, end)}}).runLifecycleAction`, {
    disconnectConnectionApi: async id => { calls.push(['disconnect', id]) },
    killInstanceApi: async id => { calls.push(['kill', id]) },
    reconnectConnectionApi: async id => { calls.push(['reconnect', id]); return {client_id: id} },
    ElMessage: { success() {}, error(e) { throw e } },
    ElMessageBox: { confirm: async () => {} },
  })
  const instance = { lifecyclePending: {}, formatDeviceName: () => 'device',
    getConnectionDisplayState: () => 'online', $emit: (...args) => events.push(args) }
  await run.call(instance, {client_id: 'bind-id'}, 'disconnect')
  await run.call(instance, {client_id: 'reverse-id'}, 'kill-instance')
  await run.call(instance, {client_id: 'bind-id'}, 'reconnect')
  assert.deepEqual(calls, [['disconnect', 'bind-id'], ['kill', 'reverse-id'], ['reconnect', 'bind-id']])
  assert.deepEqual(events.at(-1), ['connection-reconnected', 'bind-id'])
  assert.deepEqual(instance.lifecyclePending, {})
  assert.match(api, /export function disconnectConnection\(clientId\)/)
  assert.match(api, /export function killInstance\(clientId\)/)
  assert.match(api, /export function reconnectConnection\(clientId\)/)
})

test('Remove Connection is disabled online and shares one entry for both directions', async () => {
  const source = sidebar.match(/<script>([\s\S]*?)<\/script>/)?.[1]
  const start = source.indexOf('  canRemoveContextConnection() {')
  const stop = source.indexOf('  contextMachineGroupId()', start)
  const allowed = vm.runInNewContext(`({${source.slice(start, stop)}}).canRemoveContextConnection`)
  const scope = {contextMenuItem: {client_id: 'client'}, isContextBind: false,
    lifecyclePending: {}, getConnectionDisplayState: () => 'online'}
  assert.equal(allowed.call(scope), false)
  scope.getConnectionDisplayState = () => 'offline'
  assert.equal(allowed.call(scope), true)
  scope.contextMenuItem = {bind_target_id: 'never-connected'}
  scope.isContextBind = true
  assert.equal(allowed.call(scope), true)
  assert.equal((sidebar.match(/>\s*Remove Connection\s*<\/button>/g) || []).length, 1)
  assert.doesNotMatch(sidebar, /Remove saved connection/)
  const calls = []
  const begin = source.indexOf('async removeConnectionPermanently(item) {')
  const end = source.indexOf('    isElevated(item)', begin)
  const remove = vm.runInNewContext(`({${source.slice(begin, end)}}).removeConnectionPermanently`, {
    ElMessageBox: {confirm: async () => {}}, ElMessage: {success() {}, error(e) {throw e}},
    removeSavedBindTarget: async id => calls.push(['bind', id]),
    removeConnectionApi: async id => calls.push(['reverse', id]),
  })
  const instance = {lifecyclePending: {}, getConnectionDisplayState: () => 'offline', formatDeviceName: () => 'device', $emit() {}}
  await remove.call(instance, {connection_direction: 'bind', bind_target_id: 'never-connected'})
  await remove.call(instance, {connection_direction: 'reverse', client_id: 'old'})
  instance.getConnectionDisplayState = () => 'online'
  await remove.call(instance, {connection_direction: 'reverse', client_id: 'live'})
  assert.deepEqual(calls, [['bind', 'never-connected'], ['reverse', 'old']])
})

test('Connect dialog distinguishes an existing Bind session from a new connection', async () => {
  const source = dialog.match(/<script>([\s\S]*?)<\/script>/)?.[1]
  assert.ok(source)
  const toasts = []
  const events = []
  let existing = true
  const component = vm.runInNewContext(`(${source.replace(/^import .*$/gm, '').replace('export default', '')})`, {
    connectToClient: async () => ({ client_id: 'same-id', status: existing ? 'already_connected' : 'connected' }),
    ElMessage: {
      info: value => toasts.push(['info', value]),
      success: value => toasts.push(['success', value]),
      error(error) { throw error },
      warning(message) { throw Error(message) },
    },
  })
  const instance = { ...component.data(), $emit: (...args) => events.push(args) }
  instance.visible = true
  instance.form = { host: '127.0.0.1', port: 9443, serverWebBaseUrl: 'http://localhost:8085' }
  await component.methods.connect.call(instance)
  assert.deepEqual(toasts, [['info', 'Client already connected']])
  assert.deepEqual(events, [])
  existing = false
  instance.visible = true
  await component.methods.connect.call(instance)
  assert.deepEqual(toasts.at(-1), ['success', 'Client connected'])
  assert.deepEqual(Array.from(events[0]), ['connected', 'same-id'])
})

test('removed offline Reverse records cannot suppress a subsequent online session', () => {
  const source = read('../src/composables/useConnections.js')
  const begin = source.indexOf('        isConnectionLocallyRemoved(item) {')
  const end = source.indexOf('        filterLocallyRemovedConnections(items)', begin)
  const hidden = vm.runInNewContext(`({${source.slice(begin, end)}}).isConnectionLocallyRemoved`)
  const scope = {
    locallyRemovedConnections: {clientIds: {old: true}, offlineMachineIds: {machine: true}},
    getConnectionClientId: item => item.client_id,
    getConnectionMachineId: item => item.machine_id,
    getConnectionDisplayState: item => item.connection_state,
    clearConnectionLocallyRemoved(item) {
      delete this.locallyRemovedConnections.clientIds[item.client_id]
      delete this.locallyRemovedConnections.offlineMachineIds[item.machine_id]
    },
  }
  const row = {client_id: 'old', machine_id: 'machine', connection_direction: 'reverse', connection_state: 'offline'}
  assert.equal(hidden.call(scope, row), true)
  assert.equal(hidden.call(scope, {...row, connection_direction: 'bind'}), false)
  assert.equal(hidden.call(scope, {...row, connection_state: 'online'}), false)
  assert.equal(hidden.call(scope, row), false)
})
