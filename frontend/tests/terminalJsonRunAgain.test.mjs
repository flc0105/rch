import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import vm from 'node:vm'
import { JSON_ROW_ACTIONS, getJsonRenderModel, buildJsonTableModel, buildJsonGroupedModel, buildJsonFlatModel, normalizeJsonRowActions, formatJsonFlatValue } from '../src/utils/terminalJson.js'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const source = readFileSync(resolve(root, 'src/components/TerminalJsonDialog.vue'), 'utf8')
const template = source.match(/<template>([\s\S]*?)<\/template>\s*<script>/)?.[1] || ''
assert.match(template, /v-if="canRunAgain"/)
assert.match(template, /:loading="refreshRunning"/)
assert.match(template, /@click="runAgain"/)
const script = source.match(/<script>([\s\S]*?)<\/script>/)?.[1] || ''
const errors = []
const warnings = []
const sandbox = { JSON_ROW_ACTIONS, getJsonRenderModel, buildJsonTableModel, buildJsonGroupedModel, buildJsonFlatModel, normalizeJsonRowActions, formatJsonFlatValue,
  h: (tag, props, children) => ({ tag, props, children }), ref: value => ({value}),
  ElRadioGroup: '', ElRadioButton: '', ElMessageBox: { confirm: async () => {} },
  ElMessage: { error: message => errors.push(message), warning: message => warnings.push(message), success: () => {} },
}
vm.runInNewContext(script.replace(/^import\s+[^\n]*\n/gm, '').replace('export default {', 'globalThis.component = {'), sandbox)
const component = sandbox.component
function viewerFor(commandInfo, clientId = 'client-A') {
  const emitted = []
  const viewer = {
    ...component.data(), selectedId: clientId,
    currentConnection: {client_id: clientId, hostname: 'test-host'}, machineAliasMap: {},
    $emit: (...args) => emitted.push(args),
  }
  for (const [name, fn] of Object.entries(component.methods)) viewer[name] = fn.bind(viewer)
  for (const [name, fn] of Object.entries(component.computed)) Object.defineProperty(viewer, name, { get: () => fn.call(viewer) })
  viewer.open({ isJsonMessage: true, jsonText: '[{"pid":1}]', jsonCommandInfo: commandInfo })
  return { viewer, emitted }
}
const sourceCommand = { blockType: 'command', commandText: 'echo "[{\\"pid\\":1}]"' }
const {viewer, emitted} = viewerFor(sourceCommand)
assert.equal(viewer.canRunAgain, true)
await viewer.runAgain()
assert.equal(viewer.visible, true)
assert.equal(viewer.refreshRunning, true)
assert.equal(emitted.length, 1)
assert.equal(emitted[0][0], 'rerun-json')
assert.equal(emitted[0][1].type, 'command')
assert.equal(emitted[0][1].clientId, 'client-A')
assert.equal(emitted[0][1].command, sourceCommand.commandText)
assert.ok(emitted[0][1].runId)
await viewer.runAgain()
assert.equal(emitted.length, 1, 'must not duplicate while pending')
const runId = emitted[0][1].runId
viewer.handleJsonRefreshResult({client_id:'client-A', text:'[{"pid":'}, 'wrong-run')
viewer.handleJsonRefreshResult({client_id:'client-A', text:'[{"pid":'}, runId)
viewer.handleJsonRefreshResult({client_id:'client-A', text:'2}]'}, runId)
viewer.handleJsonRefreshComplete({client_id:'client-A', success:true}, runId)
assert.equal(viewer.refreshRunning, false)
assert.equal(viewer.visible, true)
assert.equal(viewer.tableRows[0].pid, '2')
assert.equal(viewer.commandInfo.commandText, sourceCommand.commandText)
assert.equal(errors.length, 0)

await viewer.runAgain()
const invalidId = emitted[1][1].runId
viewer.handleJsonRefreshResult({client_id:'client-A', text:'not JSON'}, invalidId)
viewer.handleJsonRefreshComplete({client_id:'client-A', success:false}, invalidId)
assert.equal(viewer.tableRows[0].pid, '2')
assert.match(errors.at(-1), /valid JSON/)

await viewer.runAgain()
const newlineId = emitted[2][1].runId
viewer.handleJsonRefreshResult({client_id:'client-A', text:'['}, newlineId)
viewer.handleJsonRefreshResult({client_id:'client-A', text:'{"pid": 5}'}, newlineId)
viewer.handleJsonRefreshResult({client_id:'client-A', text:']'}, newlineId)
viewer.handleJsonRefreshComplete({client_id:'client-A'}, newlineId)
assert.equal(viewer.tableRows[0].pid, '5')

await viewer.runAgain()
const failure = emitted[3][1]
failure.onDone(false)
assert.equal(viewer.refreshRunning, false)
assert.match(errors.at(-1), /failed to start/)

viewer.selectedId = 'client-B'
await viewer.runAgain()
assert.equal(emitted.length, 4)
assert.match(warnings.at(-1), /target device/)

const scriptInfo = {blockType:'script',script_name:'diagnostics/mac_python',script_path:'diagnostics/mac_python.py',params:{limit:4},script_display_name:'Python List'}
const scriptTest = viewerFor(scriptInfo)
await scriptTest.viewer.runAgain()
const scriptEvent = scriptTest.emitted[0][1]
assert.equal(scriptEvent.type, 'script')
assert.equal(scriptEvent.script_name, scriptInfo.script_name)
assert.equal(scriptEvent.params.limit, 4)
scriptTest.viewer.handleJsonRefreshResult({client_id:'client-A', text:'{"updated":true}'}, scriptEvent.runId)
scriptTest.viewer.handleJsonRefreshComplete({client_id:'client-A'}, scriptEvent.runId)
assert.equal(scriptTest.viewer.displayMode, 'flat')
assert.equal(scriptTest.viewer.flatRows[0].value, 'true')

const noSource = viewerFor({})
assert.equal(noSource.viewer.canRunAgain, false)
await noSource.viewer.runAgain()
assert.equal(noSource.emitted.length, 0)

const closeTest = viewerFor(sourceCommand)
await closeTest.viewer.runAgain()
const staleId = closeTest.emitted[0][1].runId
closeTest.viewer.visible = false
closeTest.viewer.reset()
closeTest.viewer.handleJsonRefreshResult({client_id:'client-A', text:'{"changed":1}'}, staleId)
closeTest.viewer.handleJsonRefreshComplete({client_id:'client-A'}, staleId)
assert.equal(closeTest.viewer.text, '')

// A local task capture is used; no view-specific request metadata is sent.
const app = readFileSync(resolve(root, 'src/App.vue'), 'utf8')
const input = readFileSync(resolve(root, 'src/components/CommandInputBar.vue'), 'utf8')
const library = readFileSync(resolve(root, 'src/components/ScriptLibraryDialog.vue'), 'utf8')
const sse = readFileSync(resolve(root, 'src/composables/useSseStream.js'), 'utf8')
const route = readFileSync(resolve(root, '../backend/server/web/routes/command_execution.py'), 'utf8')
assert.match(app, /@rerun-json="runTerminalJsonAgain"/)
assert.match(app, /terminalTaskCapture.begin/)
assert.match(input, /runJsonViewerRefreshCommand/)
assert.match(library, /runScriptFromTerminalBlock/)
assert.match(sse, /routeTerminalTaskCapture/)
assert.doesNotMatch(route, /json_viewer_refresh_run_id|result_action_presentation/)
console.log('Terminal JSON Run Again tests passed')
