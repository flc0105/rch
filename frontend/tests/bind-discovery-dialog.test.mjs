import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'

const read = file => readFileSync(new URL(file, import.meta.url), 'utf8')
const dialog = read('../src/components/ConnectToClientDialog.vue')
const api = read('../src/api/connectionsApi.js')
const connectCalls = []
const script = dialog.match(/<script>([\s\S]*?)<\/script>/)?.[1]
const component = vm.runInNewContext(`(${script.replace(/^import .*$/gm, '').replace('export default', '')})`, {
  getBindConnectionSettings: async () => ({ server_web_base_url: 'http://192.168.1.10:8085' }),
  getBindDiscoveryInterfaces: async () => ({ interfaces: [{ name: 'en0', address: '192.168.1.10' }] }),
  discoverBindClients: async () => ({ devices: [{host: '192.168.1.23', port: 9443, hostname: 'lab-machine', os: 'Linux', transport: 'mtls_tcp', available: true}] }),
  connectToClient: async (...args) => { connectCalls.push(args); return { client_id: 'connected-id' } },
  saveBindTarget: async () => ({}),
  ElMessage: { success() {}, info() {}, error(e) {throw Error(e)}, warning(m) {throw Error(m)} },
})

test('Discovery UI keeps manual entry, stable dialog and existing Save/Connect footer', () => {
  assert.match(dialog, /class="fixed-dialog bind-connect-dialog"/)
  assert.doesNotMatch(dialog, /height:\s*78vh/)
  assert.match(dialog, /\.bind-connect-dialog\.el-dialog \{[^}]*max-height: calc\(100dvh - 32px\)/)
  assert.match(dialog, /el-tabs__content \{ min-height: 0; max-height: calc\(100dvh - 192px\); overflow-y: auto/)
  assert.match(dialog, /bind-discovery-results \{[^}]*max-height: 240px; overflow-y: auto/)
  assert.doesNotMatch(dialog, /bind-discovery-panel \{[^}]*min-height: 100%/)
  assert.match(dialog, /\.bind-connect-dialog \.el-dialog__body \{ flex: 1; \}/)
  assert.match(dialog, /label="Manual" name="manual"/)
  assert.match(dialog, /label="Discovery" name="discovery"/)
  assert.match(dialog, /role="radiogroup"/)
  assert.match(dialog, /@click="save"/)
  assert.match(dialog, /@click="connect"/)
  assert.match(api, /export function getBindDiscoveryInterfaces/)
  assert.match(api, /export function discoverBindClients/)
})

test('Discovery selects an existing Bind Client and fills the same Manual form', async () => {
  const instance = {...component.data(), $emit() {}}
  instance.deviceKey = device => component.methods.deviceKey.call(instance, device)
  await component.methods.open.call(instance)
  assert.equal(instance.activeTab, 'discovery')
  assert.equal(instance.interfaceAddress, '192.168.1.10')
  await component.methods.scan.call(instance)
  assert.equal(instance.devices.length, 1)
  component.methods.selectDevice.call(instance, instance.devices[0])
  assert.equal(instance.form.host, '192.168.1.23')
  assert.equal(instance.form.port, 9443)
  assert.equal(instance.form.transport, 'mtls_tcp')
  assert.equal(instance.form.name, 'lab-machine')
  assert.equal(instance.form.serverWebBaseUrl, 'http://192.168.1.10:8085')
  await component.methods.connect.call(instance)
  assert.deepEqual(Array.from(connectCalls.at(-1)),
    ['192.168.1.23', 9443, 'http://192.168.1.10:8085', 'lab-machine', 'mtls_tcp'])
  component.methods.onInterfaceChange.call(instance)
  assert.equal(instance.selectedDeviceKey, '')
  assert.equal(instance.devices.length, 0)
})

test('Editing a saved Bind target still opens Manual tab', async () => {
  const instance = {...component.data()}
  await component.methods.open.call(instance, {target_id:'saved', host:'10.0.0.2', port:9000, transport:'tcp'})
  assert.equal(instance.activeTab, 'manual')
  assert.equal(instance.targetId, 'saved')
  assert.equal(instance.form.host, '10.0.0.2')
})
