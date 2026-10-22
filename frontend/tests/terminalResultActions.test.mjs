import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import vm from 'node:vm'
import { JSON_ROW_ACTIONS, getJsonRenderModel, buildJsonTableModel, buildJsonGroupedModel, buildJsonFlatModel, normalizeJsonRowActions, formatJsonFlatValue, isJsonContainerText, isJsonStartLine, parseJsonLines, jsonBracketDelta } from '../src/utils/terminalJson.js'

const base = resolve(dirname(fileURLToPath(import.meta.url)), '../src')
const viewerSource = readFileSync(resolve(base, 'components/TerminalJsonDialog.vue'), 'utf8')
const template = viewerSource.match(/<template>([\s\S]*?)<\/template>\s*<script>/)?.[1] || ''
assert.match(template, /v-if="tableHasActions"/)
assert.match(template, /getTerminalJsonRowActions\(row\)\.slice\(0, 2\)/)
assert.match(template, /v-if="getTerminalJsonRowActions\(row\)\.length > 2"/)
assert.match(template, /getTerminalJsonRowActions\(row\)\.slice\(2\)/)
assert.match(template, /:command="index \+ 2"/)
// Ordinary buttons and the dropdown trigger must share one flex gap.
const actionCell = template.match(/<div class="terminal-json-row-actions">([\s\S]*?)<\/el-dropdown>\s*<\/div>/)?.[1] || ''
assert.match(actionCell, /getTerminalJsonRowActions\(row\)\.slice\(0, 2\)/)
assert.match(actionCell, /getTerminalJsonRowActions\(row\)\.length > 2/)
assert.match(actionCell, /getTerminalJsonRowActions\(row\)\.slice\(2\)/)
const viewerStyle = viewerSource.match(/<style scoped>([\s\S]*?)<\/style>/)?.[1] || ''
assert.match(viewerStyle, /\.terminal-json-row-actions\s*\{[^}]*display:\s*inline-flex;[^}]*align-items:\s*center;[^}]*gap:\s*8px;/)
assert.match(viewerStyle, /\.terminal-json-row-actions\s+:deep\(\.el-button\)\s*\{[^}]*margin-left:\s*0;/)
assert.match(template, /resultVisible/)
assert.match(template, /terminal-json-action-result-output/)
assert.match(template, /@click\.stop="confirmTableAction\(action\)"/)
assert.match(template, /@command="index => confirmTableAction\(getTerminalJsonRowActions\(row\)\[index\]\)"/)
const viewerScript = viewerSource.match(/<script>([\s\S]*?)<\/script>/)?.[1] || ''
const previewCalls = []
let shouldConfirm = true
const emitted = []
const sandbox = { JSON_ROW_ACTIONS, getJsonRenderModel, buildJsonTableModel, buildJsonGroupedModel, buildJsonFlatModel, normalizeJsonRowActions, formatJsonFlatValue,
  ref: value => ({value}),
  ElRadioGroup: 'radio-group', ElRadioButton:'radio-button',
  h: (tag, props, children) => ({ tag, props, children }),
  ElMessage: { success() {}, error() {}, warning() {} },
  ElMessageBox: { confirm: async (...args) => {
    previewCalls.push(args)
    if (!shouldConfirm) throw new Error('cancel')
  } },
}
vm.runInNewContext(viewerScript.replace(/^import\s+[^\n]*\n/gm, '').replace('export default {', 'globalThis.component = {'), sandbox)
const component = sandbox.component
const viewer = {
  ...component.data(), selectedId: 'client-A',
  currentConnection: {client_id:'client-A', machine_id:'machine-A', hostname:'macmini.local'},
  machineAliasMap: {'machine-A':'Ops Mac'},
  $emit: (...args) => emitted.push(args),
}
for (const [name, fn] of Object.entries(component.methods)) viewer[name] = fn.bind(viewer)
for (const [name, fn] of Object.entries(component.computed)) Object.defineProperty(viewer, name, {get: () => fn.call(viewer)})
const input = [
  { pid: 3, name: 'third' },
  { pid: 1, name: 'first', _actions: [{ label: 'Inspect', command: 'ps -p 1' }] },
  { pid: 2, name: 'second', _actions: [
    { label: 'One', command: 'echo 1' }, { label: 'Two', command: 'echo 2' },
    { label: 'Three', command: 'echo 3' },
  ] },
]
viewer.open({isJsonMessage: true, jsonText: JSON.stringify(input)})
assert.equal(viewer.displayMode, 'table', 'optional _actions must not break table structure')
assert.equal(viewer.actionTargetName, 'Ops Mac', 'machine alias takes priority over hostname')
assert.deepEqual(Array.from(viewer.tableColumns, col => col.prop), ['pid','name'])
assert.equal(viewer.tableHasActions, true)
assert.equal(viewer.getTerminalJsonRowActions(viewer.tableRows[0]).length, 0)
assert.equal(viewer.getTerminalJsonRowActions(viewer.tableRows[1]).length, 1)
assert.equal(viewer.getTerminalJsonRowActions(viewer.tableRows[2]).length, 3)
assert.deepEqual(Object.keys(viewer.tableRows[2]), ['pid', 'name'], 'actions should not become data fields')
viewer.tableSearchText = 'second'
assert.equal(viewer.filteredTableRows.length, 1)
assert.equal(viewer.getTerminalJsonRowActions(viewer.visibleTableRows[0])[2].command, 'echo 3')
viewer.tableSearchText = 'echo 3'
assert.equal(viewer.filteredTableRows.length, 0, 'search should only match visible columns')
viewer.tableSearchText = ''
viewer.handleTableSortChange({prop:'pid', order:'ascending'})
assert.deepEqual(Array.from(viewer.visibleTableRows, row => row.pid), ['1','2','3'])
assert.equal(viewer.getTerminalJsonRowActions(viewer.visibleTableRows[0])[0].command, 'ps -p 1')

shouldConfirm = false
await viewer.confirmTableAction(viewer.getTerminalJsonRowActions(viewer.tableRows[1])[0])
assert.equal(emitted.length, 0, 'cancel must never execute')
assert.equal(viewer.visible, true)
shouldConfirm = true
const action = viewer.getTerminalJsonRowActions(viewer.tableRows[2])[2]
await viewer.confirmTableAction(action)
assert.equal(emitted.length, 1)
assert.equal(emitted[0][0], 'run-result-action')
assert.equal(emitted[0][1].command, 'echo 3')
assert.equal(emitted[0][1].clientId, 'client-A')
assert.equal(emitted[0][1].presentation, 'terminal')
assert.equal(viewer.visible, false)
const confirmation = previewCalls[1][0]
assert.equal(confirmation.children[0].children[0], 'Run the following command on ')
assert.equal(confirmation.children[0].children[1].tag, 'strong')
assert.equal(confirmation.children[0].children[1].children, 'Ops Mac')
assert.equal(confirmation.children[0].children[2], '?')
assert.equal(confirmation.children[1].tag, 'pre')
assert.equal(confirmation.children[1].children[0].tag, 'code')
assert.equal(confirmation.children[1].children[0].children, 'echo 3', 'full original command must be shown')
assert.equal(confirmation.children[1].props.style.whiteSpace, 'pre-wrap')
assert.equal(confirmation.children[1].props.style.fontFamily.includes('monospace'), true)
// Keep single-line commands compact without affecting multiline wrapping and scrolling.
const commandCodeStyle = confirmation.children[1].props.style
assert.equal(commandCodeStyle.margin, '8px 0 0')
assert.equal(commandCodeStyle.padding, '6px 12px')
assert.equal(commandCodeStyle.fontSize, '13px')
assert.equal(commandCodeStyle.lineHeight, '1.35')
assert.equal(commandCodeStyle.maxHeight, '45vh')
assert.equal(commandCodeStyle.overflowY, 'auto')
assert.equal(previewCalls[1][1], 'Execute Command')
assert.equal(previewCalls[1][2].confirmButtonText, 'Run')
// The choice in the confirmation message is reactive and changes where output goes.
viewer.open({isJsonMessage:true, jsonText:JSON.stringify(input)})
const originalConfirm = sandbox.ElMessageBox.confirm
sandbox.ElMessageBox.confirm = async (...args) => {
  previewCalls.push(args)
  const picker = args[0].children[3]
  const radioView = picker.tag()   // reactive functional component
  radioView.props['onUpdate:modelValue']('dialog')
}
await viewer.confirmTableAction(action)
assert.equal(viewer.visible, true, 'Dialog output must leave the source JSON viewer open')
assert.equal(viewer.resultVisible, true)
assert.equal(emitted[1][1].presentation, 'dialog')
assert.ok(emitted[1][1].runId)
assert.equal(viewer.activeResult.command, 'echo 3')
const runId = emitted[1][1].runId
assert.equal(viewer.handleResultActionCommandResult({client_id:'client-A', text:'one'}, runId), true)
assert.equal(viewer.handleResultActionCommandResult({client_id:'client-A', text:'two'}, runId), true)
assert.equal(viewer.activeResult.output, 'one\ntwo')
assert.equal(viewer.handleResultActionCommandComplete({client_id:'client-A',success:true,status:'success'}, runId), true)
assert.equal(viewer.activeResult.status,'Success')
assert.equal(viewer.resultStatusType,'success')
assert.equal(viewer.visible,true)
assert.equal(viewer.handleResultActionCommandResult({client_id:'client-A', text:'bad'}, 'other-run'),true)
assert.equal(viewer.activeResult.output,'one\ntwo')
sandbox.ElMessageBox.confirm = originalConfirm

// Target name is captured when opening the viewer; live selection changes must not relabel it.
viewer.open({isJsonMessage:true, jsonText:JSON.stringify(input)})
assert.equal(viewer.actionTargetName, 'Ops Mac')
viewer.machineAliasMap = {'machine-A':'Renamed Mac'}
viewer.currentConnection = {client_id:'client-B', machine_id:'machine-B', hostname:'other-host'}
assert.equal(viewer.actionTargetName, 'Ops Mac')
viewer.currentConnection = {client_id:'client-A', machine_id:'machine-A', hostname:'macmini.local'}
viewer.open({isJsonMessage:true, jsonText:JSON.stringify(input)})
assert.equal(viewer.actionTargetName, 'Renamed Mac')
viewer.machineAliasMap = {}
viewer.open({isJsonMessage:true, jsonText:JSON.stringify(input)})
assert.equal(viewer.actionTargetName, 'macmini.local', 'hostname is used when alias is unavailable')
viewer.currentConnection = {client_id:'client-A', machine_id:'machine-A', hostname:''}
viewer.open({isJsonMessage:true, jsonText:JSON.stringify(input)})
assert.equal(viewer.actionTargetName, 'client-A', 'client ID is fallback when no host name exists')
viewer.currentConnection = {client_id:'client-B', machine_id:'machine-B', hostname:'other-host'}
viewer.open({isJsonMessage:true, jsonText:JSON.stringify(input)})
assert.equal(viewer.actionTargetName, 'client-A', 'never display another target device')

for (const data of [
  [{x:1}, {x:2}],
  [{x:1, _actions:[]}, {x:2}],
  [{x:1, _actions: 'bad'}, {x:2, _actions:[{label:'Bad', command:''}]}],
  [{x:1, _actions:[null, {label:2, command:'echo not valid'}]}, {x:2}],
]) {
  viewer.open({ isJsonMessage: true, jsonText: JSON.stringify(data) })
  assert.equal(viewer.displayMode, 'table')
  assert.equal(viewer.tableHasActions, false)
}
viewer.open({isJsonMessage:true, jsonText: JSON.stringify([{x:1,_actions:[{label:'Go',command:'echo ok'}]},{y:2}])})
assert.equal(viewer.displayMode, 'raw', 'different actual columns must not become a table')
viewer.open({isJsonMessage:true, jsonText: JSON.stringify([{x:1,_actions:[{label:'Go',command:'echo ok'}]},{x:2}])})
assert.match(viewer.text, /"_actions"/, 'copy/save/raw must keep original JSON')
viewer.toggleTerminalJsonViewMode()
assert.match(viewer.formattedRawText, /"_actions"/)

// Echo and Script output feed the same JSON recognizer, without relying on command names.
const terminalOutputSource = readFileSync(resolve(base, 'composables/useTerminalOutput.js'), 'utf8')
const outputSandbox = {isJsonContainerText, isJsonStartLine, parseJsonLines, jsonBracketDelta, isTerminalCommandFinishedText:()=>false, isTerminalCommandFailedText:()=>false}
vm.runInNewContext(terminalOutputSource.replace(/^import\s*\{[\s\S]*?\}\s*from\s*[^;]+;/m, '').replace('export default {', 'globalThis.mixin = {'), outputSandbox)
const output = {...outputSandbox.mixin.data(), outputs:{}, scrollToBottom() {}}
for (const [key, fn] of Object.entries(outputSandbox.mixin.methods)) output[key] = fn.bind(output)
output.inferLineKind = () => 'default'
output.scrollToBottom = () => {}
assert.equal(output.isTerminalJsonText(JSON.stringify(input)), true)
output.appendOutput('client-A', JSON.stringify(input))
assert.equal(output.outputs['client-A'][0].isJsonMessage, true)
assert.equal(JSON.parse(output.outputs['client-A'][0].jsonText)[1]._actions[0].command, 'ps -p 1')
// Script 常见的 pretty-printed JSON 可分多次到达，但走同一终端检测。
const prettyJson = JSON.stringify(input, null, 2)
for (const line of prettyJson.split('\n')) output.appendOutput('client-script', line)
const scriptJsonLine = output.outputs['client-script'].find(line => line.isJsonMessage)
assert.ok(scriptJsonLine, 'multi-line Script JSON must still produce a View JSON message')
assert.equal(JSON.parse(scriptJsonLine.jsonText)[2]._actions[2].command, 'echo 3')

// Terminal command submission reuses the existing API/task output channel and preserves drafts.
const barSource = readFileSync(resolve(base, 'components/CommandInputBar.vue'), 'utf8')
const barScript = barSource.match(/<script>([\s\S]*?)<\/script>/)?.[1] || ''
const apiCalls = [], terminalEvents = [], feedback = []
const barSandbox = {
  ElMessage:{warning: msg => feedback.push(msg), error: msg => feedback.push(msg)},
  sendCommandApi: async (...args) => {apiCalls.push(args); return {task_id:'task-33'}},
  formatTerminalCommandFailedLine: x => `FAILED:${x}`,
}
vm.runInNewContext(barScript.replace(/^import[\s\S]*?from\s*['"][^'"\n]+['"]\s*;?\s*$/gm, '').replace('export default {','globalThis.component = {'), barSandbox)
const bar = { ...barSandbox.component.data(), selectedId:'client-A', commandText:'my unfinished draft',
  currentActiveTaskId:'', tabId:'tab-A',
  $emit:(...args) => terminalEvents.push(args), }
for (const [name, method] of Object.entries(barSandbox.component.methods)) bar[name] = method.bind(bar)
assert.equal(await bar.runResultActionCommand('echo hello', 'client-A'), 'task-33')
assert.equal(await bar.runResultActionCommand('echo dialog', 'client-A', 'dialog'), 'task-33')
assert.equal(apiCalls[1].length, 3, 'dialog must never send UI metadata to command API')
assert.equal(terminalEvents.filter(item=>item[0]==='append-output').length,1,
  'Dialog command must not be echoed into Terminal')

assert.equal(apiCalls.length, 2)
assert.deepEqual(Array.from(apiCalls[0]).slice(0,2), ['client-A','echo hello'])
assert.equal(apiCalls[0][2]['X-Tab-Id'], 'tab-A')
assert.equal(bar.commandText, 'my unfinished draft')
assert.equal(terminalEvents[0][0], 'append-output')
assert.equal(terminalEvents[1][0], 'set-active-task')
bar.selectedId = 'client-B'
assert.equal(await bar.runResultActionCommand('echo wrong', 'client-A'), '')
assert.equal(apiCalls.length, 2, 'changed target device must not receive the command')
bar.selectedId = 'client-A'
bar.sending = true
assert.equal(await bar.runResultActionCommand('echo busy', 'client-A'), '')
assert.equal(apiCalls.length, 2)

const appSource = readFileSync(resolve(base, 'App.vue'), 'utf8')
assert.match(appSource, /@run-result-action="runTerminalJsonResultAction"/)
const jsonViewerTag = appSource.match(/<TerminalJsonDialog\s+ref="terminalJsonDialogRef"[\s\S]*?\/>/)?.[0] || ''
assert.match(jsonViewerTag, /:current-connection="currentConnection"/)
assert.match(jsonViewerTag, /:machine-alias-map="machineAliasMap"/)
assert.match(appSource, /:selected-id="selectedId"[\s\S]*?@run-result-action="runTerminalJsonResultAction"/)
assert.match(appSource, /async runTerminalJsonResultAction\(payload = \{\}\)/)
assert.match(appSource, /payload.command, payload.clientId, payload.presentation/)
assert.match(appSource, /terminalTaskCapture.begin/)
assert.match(appSource, /handleResultActionCommandResult/)
assert.match(appSource, /handleResultActionCommandComplete/)
const sseSource = readFileSync(resolve(base, 'composables/useSseStream.js'), 'utf8')
assert.match(sseSource, /routeTerminalTaskCapture/)
assert.doesNotMatch(sseSource, /result_action_presentation/)
const apiSource = readFileSync(resolve(base, 'api/connectionsApi.js'), 'utf8')
assert.match(apiSource, /jsonRequestOptions\('POST', \{ command \}, headers\)/)
console.log('Result Actions: optional metadata, row association, confirmation, Script/echo JSON, Terminal execution passed')
