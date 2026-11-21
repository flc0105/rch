import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import vm from 'node:vm'

import { getTerminalReplayAction } from '../src/utils/terminalOperation.js'
import { canRerunTerminalSource } from '../src/utils/terminalRerun.js'
import { JSON_ROW_SOURCE, findJsonOutput, getJsonRenderModel, normalizeJsonView,
  resolveJsonViewRowActions } from '../src/utils/terminalJson.js'

const read = relative => readFileSync(new URL(relative, import.meta.url), 'utf8')
const appSource = read('../src/App.vue')
const scriptSource = read('../src/components/ScriptLibraryDialog.vue')
const quickSource = read('../src/components/QuickActionsDialog.vue')
const viewerSource = read('../src/components/TerminalJsonDialog.vue')

function method(source, start, end, name, context = {}) {
  const from = source.indexOf(start)
  const to = source.indexOf(end, from + start.length)
  assert.ok(from >= 0 && to > from, `${name} source exists`)
  return vm.runInNewContext(`({ ${source.slice(from, to)} }).${name}`, context)
}

const openResultJson = method(appSource, '    openResultJson(payload = {}) {',
  '    openScriptLibraryDialog() {', 'openResultJson')
const emitScriptJson = method(scriptSource, '    viewResultJson() {',
  '    forwardAppendOutput(', 'viewResultJson')
const emitQuickJson = method(quickSource, '    viewResultJson() {',
  '    platformLabel(', 'viewResultJson')
const handleQuickResult = method(quickSource, '    handleCommandResult(payload = {}) {',
  '    appendResultChunk(', 'handleCommandResult')
const resultJsonText = method(quickSource, '    resultJsonText() {',
  '    resultTitle() {', 'resultJsonText', { findJsonOutput })

const viewerScript = viewerSource.match(/<script>([\s\S]*?)<\/script>/)?.[1]
assert.ok(viewerScript, 'Viewer component script exists')
const viewerComponent = vm.runInNewContext(`(${viewerScript.replace(/^import .*$/gm, '').replace('export default', '')})`, {
  JSON_ROW_SOURCE, findJsonOutput, getJsonRenderModel, normalizeJsonView,
  resolveJsonViewRowActions, getTerminalReplayAction, canRerunTerminalSource,
})

const DATA = [{ name: 'demo', pid: 42, checked_at: '2026-11-21T23:30:00' }]
const VIEW = { titleField: 'name', columns: [{ field: 'name', width: 125 }, { field: 'pid' }],
  details: ['checked_at'], actions: [
    { label: 'Run Child', command: 'script exec test/misc/json_result_actions_update', confirm: false, refresh: true },
    { label: 'Inspect', command: 'getpid', confirm: true, refresh: false },
  ] }

function makeViewer() {
  const dialog = { ...viewerComponent.data(), ...viewerComponent.methods,
    selectedId: 'client-A', currentConnection: { client_id: 'client-A', hostname: 'Test Host' },
    machineAliasMap: {}, $emit() {}, $nextTick: fn => fn(),
  }
  Object.defineProperty(dialog, 'canRunAgain', { get: () => viewerComponent.computed.canRunAgain.call(dialog) })
  return dialog
}

function appBridge(dialog, selectedId = 'client-A') {
  return { selectedId, $refs: { terminalJsonDialogRef: dialog }, openResultJson }
}

function assertSameView(dialog) {
  assert.equal(dialog.visible, true)
  assert.equal(dialog.displayMode, 'table')
  assert.deepEqual(dialog.resultView.columns.map(column => column.prop), ['name', 'pid'])
  assert.equal(dialog.resultView.columns[0].width, 125)
  assert.deepEqual([...dialog.resultView.details], ['checked_at'])
  const actions = dialog.getTerminalJsonRowActions(dialog.tableRows[0])
  assert.deepEqual(actions.map(action => action.label), ['Run Child', 'Inspect'])
  assert.equal(actions[0].confirm, false)
  assert.equal(actions[0].refresh, true)
  assert.equal(actions[0].command, 'script exec test/misc/json_result_actions_update')
}

function refreshView(dialog) {
  const original = dialog.getTerminalJsonRowActions(dialog.tableRows[0])
  const newData = [{ ...DATA[0], checked_at: '2026-11-21T23:31:00' }]
  dialog.refreshRun = { runId: 'refresh-1', clientId: 'client-A', chunks: [], view: null, jsonText: '' }
  dialog.refreshRunning = true
  dialog.handleJsonRefreshResult({ client_id: 'client-A', text: 'Script output\n', result: {
    data: newData, view: VIEW,
  } }, 'refresh-1')
  dialog.handleJsonRefreshComplete({ client_id: 'client-A', status: 'success' }, 'refresh-1')
  assert.equal(dialog.tableRows[0].checked_at, '2026-11-21T23:31:00')
  assertSameView(dialog)
  assert.deepEqual(dialog.getTerminalJsonRowActions(dialog.tableRows[0]), original)
}

test('Script Run Dialog first View JSON preserves data/view/actions/replay identically to Run Again', () => {
  const dialog = makeViewer()
  const app = appBridge(dialog)
  const script = { resultJsonText: JSON.stringify(DATA), activeRun: {
    clientId: 'client-A', view: VIEW, scriptPath: 'test/misc/json_result_actions_probe.py',
    operation: { kind: 'script', replay: { type: 'script', script_name: 'test/misc/json_result_actions_probe',
      params: {}, execution_mode: 'inproc', output_mode: 'collect' } },
  }, $emit: (event, payload) => { assert.equal(event, 'open-json'); app.openResultJson(payload) } }
  emitScriptJson.call(script)
  assertSameView(dialog)
  assert.equal(dialog.commandInfo.operation.replay.script_name, 'test/misc/json_result_actions_probe')
  assert.equal(dialog.canRunAgain, true)
  refreshView(dialog)
})

test('Quick Action Result Dialog keeps structured data/view and passes them through App on first open', () => {
  const dialog = makeViewer()
  const app = appBridge(dialog)
  const activeRun = { runId: 'q1', clientId: 'client-A', alias: 'inspect', platform: 'common',
    arguments: ['arg'], output: 'diagnostics: non-JSON', jsonText: '', view: null, resolvedCommand: '' }
  const quick = { activeRun, resultVisible: true, appendResultChunk: text => { activeRun.output += text || '' },
    $emit: (event, payload) => { assert.equal(event, 'open-json'); app.openResultJson(payload) } }
  const handled = handleQuickResult.call(quick, { client_id: 'client-A', text: ' human-readable projection',
    metadata: { quick_action: true, quick_action_presentation: 'dialog', quick_action_run_id: 'q1' },
    result: { data: DATA, view: VIEW },
  })
  assert.equal(handled, true)
  assert.equal(activeRun.jsonText, JSON.stringify(DATA))
  assert.deepEqual(activeRun.view, VIEW)
  quick.resultJsonText = resultJsonText.call(quick)
  emitQuickJson.call(quick)
  assertSameView(dialog)
  assert.equal(dialog.commandInfo.operation.replay.type, 'alias')
  assert.equal(dialog.canRunAgain, true)
  refreshView(dialog)
})

test('Terminal output metadata opens the same viewer with the same actions', () => {
  const dialog = makeViewer()
  dialog.open({ isJsonMessage: true, jsonText: JSON.stringify(DATA), meta: { resultView: VIEW },
    jsonCommandInfo: { operation: { kind: 'command', replay: { type: 'command', command: 'acmd ps --json' } } },
  })
  assertSameView(dialog)
  refreshView(dialog)
})

test('App rejects missing or other-client results without changing the current Viewer', () => {
  const dialog = makeViewer()
  const app = appBridge(dialog)
  app.openResultJson({ clientId: 'other-client', jsonText: JSON.stringify(DATA), jsonView: VIEW })
  app.openResultJson({ clientId: 'client-A', jsonText: '', jsonView: VIEW })
  assert.equal(dialog.visible, false)
  app.openResultJson({ clientId: 'client-A', jsonText: JSON.stringify(DATA), jsonView: VIEW })
  assertSameView(dialog)
})

test('Quick Action no-structure output continues to use plain JSON text and no actions', () => {
  const dialog = makeViewer()
  const app = appBridge(dialog)
  const quick = { activeRun: { clientId: 'client-A', alias: 'plain', platform: 'common', arguments: [],
    jsonText: '', view: null, output: `log\n${JSON.stringify(DATA)}` },
    $emit: (_event, payload) => app.openResultJson(payload) }
  quick.resultJsonText = resultJsonText.call(quick)
  emitQuickJson.call(quick)
  assert.equal(dialog.displayMode, 'table')
  assert.equal(dialog.getTerminalJsonRowActions(dialog.tableRows[0]).length, 0)
})
