import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import {dirname, resolve} from 'node:path'
import {fileURLToPath} from 'node:url'
import vm from 'node:vm'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const source = readFileSync(resolve(root, 'src/components/AgentBuilderDialog.vue'), 'utf8')
assert.match(source, /v-for="builder in availableBuilders"/)
assert.doesNotMatch(source, /<el-radio label="(?:pyinstaller|go|go_loader)"/)
const script = source.split('<script>')[1].split('</script>')[0]
const sandbox = {
  window: {location: {hostname: 'example.test', protocol: 'http:'}},
  ElMessage: {warning() {}, error() {}, success() {}},
  fetch: null,
}
vm.runInNewContext(script.replace(/^import\s+.*?\n/gm, '').replace('export default {', 'globalThis.component = {'), sandbox)
const definition = sandbox.component
function makeInstance() {
  const obj = {...definition.data(), ...definition.methods}
  for (const name of Object.keys(definition.methods)) {
    obj[name] = definition.methods[name].bind(obj)
  }
  Object.defineProperty(obj, 'availableBuilders', {get() {return definition.computed.availableBuilders.call(obj)}})
  return obj
}

let response = ['bundle', 'go_loader']
sandbox.fetch = async url => {
  assert.equal(url, '/api/agent/platform')
  return {ok: true, json: async () => ({code: 0, data: {
    socket_port: 12000, web_port: 9000, target_os: 'linux', builders: response,
  }})}
}
const builder = makeInstance()
// A previously selected plugin disappears after its registration is disabled.
builder.agentForm.builder = 'pyinstaller'
await builder.loadAgentServerPlatform()
assert.equal(builder.agentForm.builder, 'bundle')
assert.deepEqual(Array.from(builder.availableBuilders, item => item.label), ['Bundle', 'Go (Loader)'])
assert.equal(builder.agentForm.server_port, 12000)
assert.equal(builder.agentForm.web_port, 9000)

// After re-enabling it on Server, the existing original labels and order reappear.
response = ['bundle', 'pyinstaller', 'go', 'go_loader']
await builder.loadAgentServerPlatform()
assert.deepEqual(Array.from(builder.availableBuilders, item => item.label),
  ['Bundle', 'PyInstaller', 'Go (Simple)', 'Go (Loader)'])

// Bundle is not special: registry without Bundle must select an available builder.
response = ['go_loader']
builder.agentForm.builder = 'bundle'
await builder.loadAgentServerPlatform()
assert.equal(builder.agentForm.builder, 'go_loader')
assert.deepEqual(Array.from(builder.availableBuilders, item => item.value), ['go_loader'])

// The backend may have no registered builders at all.
response = []
await builder.loadAgentServerPlatform()
assert.equal(builder.agentForm.builder, '')
assert.equal(builder.availableBuilders.length, 0)

// API failure must not fabricate a default Bundle or leave any modes visible.
builder.agentForm.builder = 'go'
sandbox.fetch = async () => {throw Error('offline')}
await builder.loadAgentServerPlatform()
assert.equal(builder.agentForm.builder, '')
assert.deepEqual(Array.from(builder.availableBuilders, item => item.label), [])
console.log('Dynamic agent builder visibility and selection recovery passed')
