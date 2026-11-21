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
  const handle = method(sidebar, 'handleToolbarCommand', '    handleGroupFilterCommand(')
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
  dialogObject.form = { host: ' 192.168.1.25 ', port: '9443' }
  await component.methods.connect.call(dialogObject)
  assert.deepEqual(Array.from(sent[0]), ['192.168.1.25', 9443])
  assert.equal(dialogObject.visible, false)
  assert.equal(dialogObject.connecting, false)
  assert.deepEqual(Array.from(events[0]), ['connected', 'new-client'])
})

test('Bind device Disconnect uses session disconnect, Reverse keeps existing behavior', async () => {
  const source = sidebar.match(/<script>([\s\S]*?)<\/script>/)?.[1]
  assert.ok(source)
  const calls = []
  const start = source.indexOf('async disconnectConnection(item) {')
  const end = source.indexOf('async removeConnectionPermanently(', start)
  assert.ok(start >= 0 && end > start)
  const disconnect = vm.runInNewContext(`({${source.slice(start, end)}}).disconnectConnection`, {
    disconnectBindClient: async id => calls.push(['bind', id]),
    killConnectionApi: async id => calls.push(['reverse', id]),
    ElMessage: { success() {}, error(e) { throw e }, warning() {} },
    ElMessageBox: { confirm: async () => {} },
  })
  const instance = { formatDeviceName: () => 'device', getConnectionDisplayState: () => 'online' }
  await disconnect.call(instance, {client_id: 'bind-id', listener_protocol: 'bind_tcp'})
  await disconnect.call(instance, {client_id: 'reverse-id', listener_protocol: 'tcp'})
  assert.deepEqual(calls.map(entry => Array.from(entry)), [['bind', 'bind-id'], ['reverse', 'reverse-id']])
})
