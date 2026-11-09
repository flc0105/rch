import assert from 'node:assert/strict'
import { test } from 'node:test'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import { createTerminalOperation, getTerminalReplayAction, operationHeaders } from '../src/utils/terminalOperation.js'

const quickSource = readFileSync(new URL('../src/components/QuickActionsDialog.vue', import.meta.url), 'utf8')
const appSource = readFileSync(new URL('../src/App.vue', import.meta.url), 'utf8')
const script = quickSource.match(/<script>([\s\S]*?)<\/script>/)?.[1] || ''
const calls = []
const emitted = []
const warnings = []
const messages = []
const sandbox = {
  createTerminalOperation, operationHeaders,
  ElMessage: { warning: text => warnings.push(text), error: text => messages.push(text) },
  normalizeToolbarPreferences: () => ({}),
  executeQuickAction: async (clientId, payload, headers) => {
    calls.push({clientId, payload, headers})
    return { task_id: `task-${calls.length}`, display_command: 'from-server', resolved_command: 'echo done' }
  },
}
vm.runInNewContext(script
  .replace(/^import\s+[\s\S]*?\s+from\s+['"][^'"]+['"]\s*;?\s*$/gm, '')
  .replace('export default {', 'globalThis.component = {'), sandbox)
const quick = sandbox.component
const runMethod = (name) => {
  const match = appSource.match(new RegExp(`    (?:async )?${name}\\(payload = \\{\\}\\) \\{[\\s\\S]*?\\n    \\},`))
  assert.ok(match, `${name} must remain a dedicated App method`)
  return vm.runInNewContext(`({${match[0]}})`, {createTerminalOperation})[name]
}

function makeQuickContext(selectedId = 'client-A') {
  const ctx = {
    selectedId, runSubmitting: false,
    getTabScopedHeaders: () => ({ 'X-Tab-Id': 'tab-A' }),
    $emit: (...args) => emitted.push(args),
    activeRun: {},
  }
  for (const [key, value] of Object.entries(quick.methods)) ctx[key] = value.bind(ctx)
  return ctx
}

const canon = value => JSON.parse(JSON.stringify(value))

test('Quick Action terminal execution and replay call the same typed API with saved platform and arguments', async () => {
  calls.length = 0
  emitted.length = 0
  const ctx = makeQuickContext()
  assert.equal(await ctx.executeItem({alias:'getinfo', platform:'mac'}, ['with spaces', '--long'], 'terminal'), 'task-1')
  assert.equal(calls[0].clientId, 'client-A')
  assert.deepEqual(canon(calls[0].payload).arguments, ['with spaces', '--long'])
  assert.equal(calls[0].payload.platform, 'mac')
  assert.equal(calls[0].payload.presentation, 'terminal')
  const first = emitted.find(item => item[0] === 'append-output')
  assert.equal(first[2], '> getinfo "with spaces" --long')
  const operation = first[4].operation
  const replay = getTerminalReplayAction(operation)
  assert.deepEqual(replay, {type:'alias',alias:'getinfo',platform:'mac',arguments:['with spaces','--long']})
  assert.equal(calls[0].headers['X-RCH-Operation-ID'], operation.operation_id)
  assert.equal(calls[0].headers['X-Tab-Id'], 'tab-A')
  assert.equal(await ctx.runQuickActionFromTerminalBlock({...replay, clientId:'client-A'}), 'task-2')
  const second = emitted.filter(item => item[0] === 'append-output').at(-1)
  assert.equal(second[2], first[2])
  assert.notEqual(second[4].operation.operation_id, operation.operation_id)
  assert.deepEqual(canon(calls[1].payload).arguments, ['with spaces','--long'])
  assert.equal(calls[1].payload.platform, 'mac')
  assert.equal(emitted.filter(item => item[0] === 'set-active-task').length, 2)
})

test('replay refuses cross-device, incomplete and untyped aliases; uploads stay disabled', async () => {
  const ctx = makeQuickContext('client-A')
  const count = calls.length
  assert.equal(await ctx.runQuickActionFromTerminalBlock({clientId:'client-B',alias:'cwd',platform:'mac',arguments:[]}), '')
  assert.equal(await ctx.runQuickActionFromTerminalBlock({clientId:'client-A',alias:'cwd',platform:'mac',arguments:'raw'}), '')
  assert.equal(calls.length, count)
  assert.match(warnings.at(-1), /target device/)
  assert.equal(getTerminalReplayAction({kind:'alias',replay:{type:'alias',alias:'cwd',platform:'mac',arguments:[]}}).type, 'alias')
  assert.equal(getTerminalReplayAction({kind:'transfer',replay:{type:'alias',alias:'cwd',platform:'mac',arguments:[]}}), null)
  assert.equal(getTerminalReplayAction({kind:'alias',replay:{type:'alias',alias:'cwd',platform:'mac',arguments:[null]}}), null)
  assert.equal(getTerminalReplayAction({kind:'transfer',replay:null}), null)
})

test('App routes alias replay to Quick Action, never to command input or script execution', async () => {
  const rerun = runMethod('rerunTerminalBlock')
  const dispatch = []
  const ctx = {$refs:{
    quickActionsDialogRef: {runQuickActionFromTerminalBlock: payload => {dispatch.push(['alias',payload]);return 'task-alias'}},
    scriptLibraryDialogRef: {runScriptFromTerminalBlock: payload => {dispatch.push(['script',payload]);return 'task-script'}},
    commandInputBarRef: {runCommandText: text => {dispatch.push(['command',text]);return 'task-command'}},
  }}
  assert.equal(rerun.call(ctx,{type:'alias',clientId:'client-A',alias:'getinfo',platform:'mac',arguments:[]}), 'task-alias')
  assert.equal(rerun.call(ctx,{type:'script',script_name:'hello'}), 'task-script')
  assert.equal(rerun.call(ctx,{type:'command',command:'echo hello'}), 'task-command')
  assert.equal(rerun.call(ctx,{type:'transfer',command:'[Artifact Send] name'}), null)
  assert.deepEqual(dispatch.map(item=>item[0]), ['alias','script','command'])
})

test('JSON Viewer alias Run Again binds the resulting task and stays typed', async () => {
  const runAgain = runMethod('runTerminalJsonAgain')
  const bound = []
  const emitted = []
  const ctx = {
    $refs: {
      terminalJsonDialogRef: {handleJsonRefreshResult(){},handleJsonRefreshComplete(){}},
      quickActionsDialogRef: {runQuickActionFromTerminalBlock: async payload => {
        emitted.push(payload)
        assert.equal(payload.operation.kind,'alias')
        assert.equal(payload.operation.replay.type,'alias')
        return 'task-JSON'
      }},
      scriptLibraryDialogRef: {runScriptFromTerminalBlock(){throw Error('wrong path')}},
      commandInputBarRef: {runJsonViewerRefreshCommand(){throw Error('shell fallback')}},
    },
    terminalTaskCapture: {begin: details => ({bind: id => bound.push(id),cancel(){throw Error('unexpected cancel')}})},
  }
  let done = null
  assert.equal(await runAgain.call(ctx, {type:'alias',clientId:'client-A',alias:'getinfo',platform:'mac',arguments:[],runId:'run-1',onDone: ok => done=ok}), true)
  assert.equal(bound[0], 'task-JSON')
  assert.equal(done, true)
  assert.equal(emitted.length, 1)
})

test('Quick Action Result Dialog carries replay identity into JSON Viewer', () => {
  const ctx = makeQuickContext()
  ctx.resultJsonText = '{"ok":true}'
  ctx.activeRun = { alias:'cwd',platform:'mac',arguments:['a'],clientId:'client-A' }
  emitted.length = 0
  ctx.viewResultJson()
  const event = emitted[0]
  assert.equal(event[0],'open-json')
  assert.equal(event[1].jsonText,'{"ok":true}')
  assert.deepEqual(getTerminalReplayAction(event[1].jsonCommandInfo.operation), {
    type:'alias',alias:'cwd',platform:'mac',arguments:['a']
  })
  assert.match(appSource, /jsonCommandInfo: payload\.jsonCommandInfo \|\| \{\}/)
})
