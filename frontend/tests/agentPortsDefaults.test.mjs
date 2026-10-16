import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import {resolve, dirname} from 'node:path'
import {fileURLToPath} from 'node:url'
import vm from 'node:vm'
import {terminalOneLiners} from '../src/data/terminalOneLiners.js'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const platform = {code: 0, data: {socket_port: 12000, web_port: 9000, target_os: 'mac', builders: ['bundle', 'pyinstaller', 'go', 'go_loader']}}
const sandbox = {
  window: {location: {hostname: 'example.test', protocol: 'http:'}},
  fetch: async () => ({ok: true, json: async () => platform}),
  ElMessage: {warning() {}, error() {}, success() {}},
  navigator: {},
  terminalOneLiners,
}
function component(path) {
  const source = readFileSync(resolve(root, path), 'utf8')
  assert.doesNotMatch(source, /fileTransferPort|file_transfer_port/)
  const script = source.split('<script>')[1].split('</script>')[0]
  vm.runInNewContext(script.replace(/^import\s+.*?\n/gm, '').replace('export default {', 'globalThis.component = {'), sandbox)
  const definition = sandbox.component
  const obj = {...definition.data.call({getDefaultServerForm: definition.methods?.getDefaultServerForm}), ...definition.methods}
  Object.keys(definition.methods).forEach(name => {obj[name] = definition.methods[name].bind(obj)})
  return {source, state: obj}
}

const builder = component('src/components/AgentBuilderDialog.vue')
assert.doesNotMatch(builder.source, /label="File Port"/)
await builder.state.loadAgentServerPlatform()
assert.equal(builder.state.agentForm.server_port, 12000)
assert.equal(builder.state.agentForm.web_port, 9000)
const payload = builder.state.buildAgentPayload()
assert.equal(payload.server_port, 12000)
assert.equal(payload.web_port, 9000)
assert.equal(Object.hasOwn(payload, 'file_transfer_port'), false)

const oneliners = component('src/components/OneLinersDialog.vue')
await oneliners.state.loadServerPlatform()
assert.equal(oneliners.state.serverForm.serverPort, '12000')
assert.equal(oneliners.state.serverForm.webPort, '9000')
for (const entry of terminalOneLiners) {
  assert.doesNotMatch(entry.code, /file_transfer_port|fileTransferPort|file_transfer_port/)
  const rendered = oneliners.state.renderOneLinerCode(entry.code)
  assert.match(rendered, /12000/)
  assert.match(rendered, /9000/)
  assert.doesNotMatch(rendered, /{{/)
}
console.log('Agent/one-liner port defaults and two-port payloads passed')
