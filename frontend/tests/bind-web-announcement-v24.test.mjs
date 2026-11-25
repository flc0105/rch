import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'

const read = file => readFileSync(new URL(file, import.meta.url), 'utf8')
const dialog = read('../src/components/ConnectToClientDialog.vue')
const api = read('../src/api/connectionsApi.js')
const build = read('../src/components/AgentBuilderDialog.vue')
const card = read('../src/components/ConnectionInfoCards.vue')
const info = read('../src/components/ConnectionInfoDialogs.vue')
const catalogue = read('../src/data/connectionContextFields.js')

function getDialogComponent(context = {}) {
  const source = dialog.match(/<script>([\s\S]*?)<\/script>/)?.[1]
  assert.ok(source)
  return vm.runInNewContext(`(${source.replace(/^import .*$/gm, '').replace('export default', '')})`, context)
}

test('Bind Connect loads Server advertised default and sends per-connection override', async () => {
  assert.match(api, /export function getBindConnectionSettings\(/)
  assert.match(api, /server_web_base_url: serverWebBaseUrl/)
  const sent = []
  const cmp = getDialogComponent({
    getBindConnectionSettings: async () => ({ server_web_base_url: 'http://server:8085' }),
    getBindDiscoveryInterfaces: async () => ({ interfaces: [] }),
    connectToClient: async (...args) => { sent.push(args); return { client_id: 'new-client' } },
    ElMessage: { success() {}, error(e) { throw new Error(e) }, warning(msg) { throw new Error(msg) } },
  })
  const emitted = []
  const obj = { ...cmp.data(), $emit: (...args) => emitted.push(args) }
  await cmp.methods.open.call(obj)
  assert.equal(obj.form.serverWebBaseUrl, 'http://server:8085')
  obj.form.host = 'public-client'
  obj.form.port = 9443
  obj.form.serverWebBaseUrl = 'https://vpn-server.example:443'
  await cmp.methods.connect.call(obj)
  assert.deepEqual(Array.from(sent[0]), ['public-client', 9443, 'https://vpn-server.example:443', '', 'tcp'])
  assert.equal(obj.visible, false)
  assert.deepEqual(Array.from(emitted[0]), ['connected', 'new-client'])
})

test('Bind Agent Builder hides Web inputs, Reverse keeps them', () => {
  assert.match(build, /v-if="agentForm.connection_mode !== 'bind'" label="Server IP"/)
  assert.match(build, /v-if="agentForm.connection_mode !== 'bind'" label="Web Port"/)
  assert.match(build, /delete payload.server_web_host/)
  assert.match(build, /delete payload.web_port/)
  assert.match(build, /v-if="agentForm.connection_mode === 'bind'" label="Listen Port"/)
})

test('Connection Direction is available in Base Info and selectable Connection Context', () => {
  assert.match(card, /Connection Direction/)
  assert.match(card, /formatConnectionDirection\(connection\.connection_direction\)/)
  assert.match(info, /label: 'Connection Direction'/)
  assert.match(catalogue, /id: 'connection_direction', label: 'Connection Direction'/)
  assert.match(catalogue, /connection_direction: formatConnectionDirection\(conn\.connection_direction\)/)
})
