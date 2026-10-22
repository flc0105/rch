import assert from 'node:assert/strict'
import { test } from 'node:test'
import { readFileSync } from 'node:fs'
import { findJsonOutput, isJsonContainerText, isJsonStartLine, parseJsonLines, jsonBracketDelta, getJsonRenderModel, JSON_ROW_ACTIONS } from '../src/utils/terminalJson.js'

const source = path => readFileSync(new URL(path, import.meta.url), 'utf8')

test('one JSON recognizer handles full results, separate lines, pretty JSON, and rejects plaintext', () => {
  assert.equal(findJsonOutput('  {"ready": true}  '), '{"ready": true}')
  assert.equal(findJsonOutput('log before\n[1, 2]\nlog after'), '[1, 2]')
  assert.equal(findJsonOutput('start\n{\n  "value": [1, 2]\n}\nfinish'), '{\n  "value": [1, 2]\n}')
  assert.equal(findJsonOutput('hello\ninvalid {json}\nbye'), null)
  assert.equal(findJsonOutput('true'), null)
  assert.equal(findJsonOutput('[1,'), null)
  assert.equal(isJsonContainerText(' {"x":1} '), true)
  assert.equal(isJsonStartLine(' { '), true)
  assert.equal(jsonBracketDelta('{"literal": "[ }", "obj": {}}'), 0)
  assert.equal(parseJsonLines(['[', '1, 2', ']']), '[\n1, 2\n]')
})

test('shared render modes match Terminal Table, Grouped, Flat and Raw rules', () => {
  const table = getJsonRenderModel('[{"a":1,"_actions":[{"label":"Inspect","command":"echo hi"}]},{"a":2}]')
  assert.equal(table.mode, 'table')
  assert.deepEqual(table.columns, [{prop:'a', label:'a'}])
  assert.equal(table.rows[0][JSON_ROW_ACTIONS][0].command, 'echo hi')
  assert.deepEqual(Object.keys(table.rows[0]), ['a'])
  assert.equal(getJsonRenderModel('{"cpu":{"pid":1},"memory":{"used":3}}').mode, 'grouped')
  assert.equal(getJsonRenderModel('{"cpu":1,"memory":3}').mode, 'flat')
  assert.equal(getJsonRenderModel('[{"a":1},{"b":2}]').mode, 'raw')
  assert.equal(getJsonRenderModel('[]').mode, 'raw')
})

test('both Result Dialogs only offer View JSON for detected JSON and route to existing App viewer', () => {
  const app = source('../src/App.vue')
  const terminal = source('../src/composables/useTerminalOutput.js')
  const viewer = source('../src/components/TerminalJsonDialog.vue')
  const toolbox = source('../src/components/ToolboxDialog.vue')
  assert.match(toolbox, /class="toolbox-icon toolbox-icon-add"/)
  assert.match(toolbox, /\.toolbox-icon-add\s*\{\s*border-style:\s*dashed;/)
  assert.match(terminal, /isTerminalJsonText\(text\) \{ return isJsonContainerText\(text\) \}/)
  assert.match(terminal, /calculateTerminalJsonDelta\(text\) \{ return jsonBracketDelta\(text\) \}/)
  assert.match(viewer, /getJsonRenderModel\(jsonText\)/)
  assert.match(app, /@open-json="openResultJson"/)
  assert.match(app, /terminalJsonDialogRef\?\.open\(/)
  for (const path of ['../src/components/ScriptLibraryDialog.vue','../src/components/QuickActionsDialog.vue']) {
    const contents = source(path)
    assert.match(contents, /v-if="resultJsonText"[^>]+@click="viewResultJson"[^>]*>View JSON/)
    assert.doesNotMatch(contents, /<el-button[^>]+\blink\b[^>]*>View JSON<\/el-button>/)
    assert.doesNotMatch(contents, /<template #header>[\s\S]*?View JSON/)
    const metaClass = path.includes('QuickActions') ? 'quick-action-result-meta' : 'script-result-meta'
    const section = contents.match(new RegExp(String.raw`<div class="${metaClass}">([\s\S]*?)<pre class="(?:quick-action|script)-result-output"`))?.[1] || ''
    assert.match(section, /<el-button[^>]+size="small"[^>]+@click="viewResultJson"[^>]*>View JSON<\/el-button>/)
    assert.match(contents, /findJsonOutput\(this\.activeRun\.output\)/)
    assert.match(contents, /this\.\$emit\('open-json', \{ jsonText: this\.resultJsonText, clientId: this\.activeRun\.clientId \}\)/)
  }
})

test('Script and Quick Action Result Dialog actions pass recognized JSON and current run client', async () => {
  const { default: vm } = await import('node:vm')
  for (const path of ['../src/components/ScriptLibraryDialog.vue','../src/components/QuickActionsDialog.vue']) {
    const script = source(path).match(/<script>([\s\S]*?)<\/script>/)?.[1] || ''
    const sandbox = { findJsonOutput, ScriptRunDialog: {} }
    // Imports are removed only for this isolated component method test.
    const code = script.replace(/^import\s+[\s\S]*?\s+from\s+['"][^'"]+['"]\s*;?\s*$/gm, '')
      .replace('export default {', 'globalThis.component = {')
    vm.runInNewContext(code, sandbox, { timeout: 1000 })
    const events = []
    const instance = {
      activeRun: { clientId:'client-1', output:'{ "state": "ok" }' },
      $emit: (...args) => events.push(args),
    }
    Object.defineProperty(instance, 'resultJsonText', {get() { return sandbox.component.computed.resultJsonText.call(instance) }})
    assert.equal(instance.resultJsonText, '{ "state": "ok" }')
    sandbox.component.methods.viewResultJson.call(instance)
    assert.deepEqual(JSON.parse(JSON.stringify(events[0])), ['open-json', {jsonText:'{ "state": "ok" }', clientId:'client-1'}])
    instance.activeRun.output = 'plain output'
    assert.equal(instance.resultJsonText, null)
    sandbox.component.methods.viewResultJson.call(instance)
    assert.equal(events.length, 1, 'plain output must not show or open JSON Viewer')
  }
})


test('Quick Action actual dialog execution routes JSON to the shared viewer for the executing client', async () => {
  const { default: vm } = await import('node:vm')
  const quickSource = source('../src/components/QuickActionsDialog.vue')
  const script = quickSource.match(/<script>([\s\S]*?)<\/script>/)?.[1] || ''
  const sandbox = {
    findJsonOutput,
    executeQuickAction: async () => ({task_id:'task-a', resolved_command:'getinfo --json'}),
    ElMessage: { error() {}, success() {}, warning() {} },
  }
  const code = script.replace(/^import\s+[\s\S]*?\s+from\s+['"][^'"]+['"]\s*;?\s*$/gm, '')
    .replace('export default {', 'globalThis.component = {')
  vm.runInNewContext(code, sandbox, {timeout: 1000})
  const events = []
  const methods = sandbox.component.methods
  const instance = {
    selectedId: 'client-123',
    runSubmitting: false,
    activeRun: {},
    resultVisible: false,
    createRunId: () => 'json-run',
    buildDisplayCommand: () => 'info --json',
    getTabScopedHeaders: () => ({}),
    $emit: (...args) => events.push(args),
  }
  for (const name of ['appendResultChunk', 'viewResultJson']) {
    instance[name] = (...args) => methods[name].apply(instance, args)
  }
  Object.defineProperty(instance, 'resultJsonText', {get() {
    return sandbox.component.computed.resultJsonText.call(instance)
  }})
  await methods.executeItem.call(instance, {alias:'info', platform:'macos'}, [], 'dialog')
  assert.equal(instance.activeRun.clientId, 'client-123', 'actual run must carry the executing client, not an absent ID')
  assert.equal(instance.resultVisible, true)
  assert.equal(instance.activeRun.runId, 'json-run')
  assert.equal(instance.activeRun.taskId, 'task-a')

  assert.equal(methods.handleCommandResult.call(instance, {
    text: '{"ready":true}',
    metadata: {quick_action:true, quick_action_presentation:'dialog', quick_action_run_id:'json-run'},
  }), true)
  methods.handleCommandComplete.call(instance, {
    success: true,
    metadata: {quick_action:true, quick_action_presentation:'dialog', quick_action_run_id:'json-run'},
  })
  instance.viewResultJson()
  const event = events.find(row => row[0] === 'open-json')
  assert.ok(event, 'JSON button must emit an open request')
  assert.equal(event[1].clientId, 'client-123')
  assert.equal(event[1].jsonText, '{"ready":true}')

  const app = source('../src/App.vue')
  const handlerBody = app.match(/    openResultJson\(payload = \{\}\) \{([\s\S]*?)\n    \},/)?.[1]
  assert.ok(handlerBody, 'actual App JSON event handler must be present')
  const openResultJson = new Function('payload', handlerBody)
  const viewerOpens = []
  const appInstance = {
    selectedId: 'client-123',
    $refs: {terminalJsonDialogRef: {open: item => viewerOpens.push(item)}},
  }
  openResultJson.call(appInstance, event[1])
  assert.equal(viewerOpens.length, 1, 'correct client opens existing shared JSON Viewer')
  assert.equal(viewerOpens[0].jsonText, '{"ready":true}')
  appInstance.selectedId = 'another-client'
  openResultJson.call(appInstance, event[1])
  assert.equal(viewerOpens.length, 1, 'switching clients must not open a stale run on another device')
})
