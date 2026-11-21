import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import vm from 'node:vm'
import { getJsonRenderModel } from '../src/utils/terminalJson.js'
import { JSON_ROW_ACTIONS, normalizeJsonRowActions } from '../src/utils/terminalJson.js'
import { createTerminalOperation, getTerminalReplayAction } from '../src/utils/terminalOperation.js'
import { canRerunTerminalSource } from '../src/utils/terminalRerun.js'
import { createTerminalTaskCapture } from '../src/composables/terminalTaskCapture.js'

const source = readFileSync(new URL('../src/components/TerminalJsonDialog.vue', import.meta.url), 'utf8')
const appSource = readFileSync(new URL('../src/App.vue', import.meta.url), 'utf8')
const notifications = []
let askConfirmation = async () => {}
let chooseDialog = false
const radioGroup = {}
const ElMessage = { warning: message => notifications.push(['warning', message]),
  error: message => notifications.push(['error', message]) }
const script = source.match(/<script>([\s\S]*?)<\/script>/)?.[1]
assert.ok(script)
const context = { ref: value => ({ value }), h: (tag, props, children) => {
  if (typeof tag === 'function') return tag()
  if (tag === radioGroup && chooseDialog) props['onUpdate:modelValue']('dialog')
  return children
},
  ElMessage, ElMessageBox: { confirm: (...args) => askConfirmation(...args) },
  ElRadioGroup: radioGroup, ElRadioButton: {}, JSON_ROW_ACTIONS, getJsonRenderModel,
  getTerminalReplayAction, canRerunTerminalSource }
const component = vm.runInNewContext(`(${script.replace(/^import .*$/gm, '').replace('export default', '')})`, context)

function dialog(replay = { type: 'command', command: 'acmd ps --json' }) {
  const events = []
  const nextTicks = []
  const instance = { ...component.data(), ...component.methods, selectedId: 'client-A',
    currentConnection: { client_id: 'client-A', hostname: 'Host' }, machineAliasMap: {},
    $emit: (event, data) => { events.push({ event, data }) },
    $nextTick: callback => nextTicks.push(callback),
  }
  Object.defineProperty(instance, 'canRunAgain', { get: () => component.computed.canRunAgain.call(instance) })
  instance.open({ isJsonMessage: true, jsonText: '[{"counter":0}]',
    jsonCommandInfo: { operation: { kind: replay.type, replay } } })
  return { instance, events, nextTicks }
}

function complete(instance, status = 'success') {
  return instance.handleResultActionCommandComplete({ client_id: 'client-A', status }, instance.actionRun.runId)
}

test('row actions honor literal booleans and keep raw JSON unmodified', () => {
  assert.deepEqual(normalizeJsonRowActions([
    { label: 'A', command: 'echo a', confirm: false, refresh: true },
    { label: 'B', command: 'echo b', confirm: 'false', refresh: 'true' },
    { label: 'C', command: 'echo c' },
  ]), [
    { label: 'A', command: 'echo a', confirm: false, refresh: true },
    { label: 'B', command: 'echo b', confirm: true, refresh: false },
    { label: 'C', command: 'echo c', confirm: true, refresh: false },
  ])
  const raw = '[{"counter":0,"_actions":[{"label":"A","command":"getpid","confirm":false,"refresh":true}]}]'
  const model = getJsonRenderModel(raw)
  assert.equal(model.mode, 'table')
  assert.deepEqual(model.columns.map(c => c.prop), ['counter'])
  assert.equal(model.rows[0][JSON_ROW_ACTIONS][0].refresh, true)
  assert.deepEqual(JSON.parse(raw)[0]._actions[0], { label: 'A', command: 'getpid', confirm: false, refresh: true })
})

test('confirm=false submits to Terminal without closing Viewer; refresh waits until completion', async () => {
  askConfirmation = () => { throw new Error('unexpected confirm') }
  const { instance, events, nextTicks } = dialog()
  await instance.confirmTableAction({ label: 'Increment', command: 'getpid', confirm: false, refresh: true })
  assert.equal(instance.visible, true)
  assert.equal(events[0].event, 'run-result-action')
  assert.equal(events[0].data.presentation, 'terminal')
  assert.equal(nextTicks.length, 0)
  complete(instance)
  assert.equal(nextTicks.length, 1)
  assert.equal(instance.refreshRunning, false)
  nextTicks.shift()()
  const event = events.find(e => e.event === 'rerun-json')
  assert.ok(event)
  assert.equal(event.data.command, 'acmd ps --json')
  instance.tableSearchText = '1'
  instance.tableSort = { prop: 'counter', order: 'ascending' }
  instance.handleJsonRefreshResult({ client_id: 'client-A', text: '[{"counter":1}]' }, event.data.runId)
  instance.handleJsonRefreshComplete({ client_id: 'client-A', status: 'success' }, event.data.runId)
  assert.equal(instance.tableRows[0].counter, '1')
  assert.equal(instance.tableSearchText, '1')
  assert.equal(instance.tableSort.prop, 'counter')
  assert.equal(instance.visible, true)
})

test('failed or cancelled action never queues refresh', async () => {
  askConfirmation = () => { throw new Error('unexpected confirm') }
  for (const status of ['failed', 'cancelled', 'partial', 'interrupted', 'timed_out']) {
    const { instance, nextTicks } = dialog()
    await instance.confirmTableAction({ label: 'Try', command: 'getpid', confirm: false, refresh: true })
    complete(instance, status)
    assert.equal(nextTicks.length, 0, status)
    assert.equal(instance.actionRun, null)
  }
})

test('confirmation defaults to on; cancelling prevents command submission', async () => {
  let prompts = 0
  askConfirmation = async () => { prompts++; throw new Error('cancel') }
  const { instance, events } = dialog()
  await instance.confirmTableAction({ label: 'Inspect', command: 'getpid' })
  assert.equal(prompts, 1)
  assert.equal(events.length, 0)
  assert.equal(instance.actionRun, null)
})

test('confirmed action can use New Dialog, showing output and refreshing after success', async () => {
  askConfirmation = async () => {}
  chooseDialog = true
  try {
    const { instance, events, nextTicks } = dialog()
    await instance.confirmTableAction({ label: 'Inspect', command: 'getpid', refresh: true })
    assert.equal(events[0].data.presentation, 'dialog')
    assert.equal(instance.resultVisible, true)
    const runId = instance.actionRun.runId
    instance.handleResultActionCommandResult({ client_id: 'client-A', text: 'ok' }, runId)
    complete(instance)
    assert.equal(instance.activeResult.output, 'ok')
    assert.equal(instance.activeResult.status, 'Success')
    assert.equal(nextTicks.length, 1)
    assert.equal(instance.visible, true)
  } finally {
    chooseDialog = false
  }
})

test('a source without replay is allowed to execute, but cannot refresh', async () => {
  askConfirmation = () => { throw new Error('unexpected confirm') }
  notifications.length = 0
  const { instance, nextTicks } = dialog()
  instance.commandInfo = {}
  await instance.confirmTableAction({ label: 'Inspect', command: 'getpid', confirm: false, refresh: true })
  complete(instance)
  assert.equal(nextTicks.length, 0)
  assert.equal(notifications.at(-1)[0], 'warning')
})

test('target change, dialog closing and submit failure do not start refresh', async () => {
  askConfirmation = () => { throw new Error('unexpected confirm') }
  const { instance, events, nextTicks } = dialog()
  await instance.confirmTableAction({ label: 'Do', command: 'getpid', confirm: false, refresh: true })
  events[0].data.onDone(false)
  assert.equal(instance.actionRun, null)
  await instance.confirmTableAction({ label: 'Do', command: 'getpid', confirm: false, refresh: true })
  instance.selectedId = 'client-B'
  assert.equal(instance.handleResultActionCommandComplete({ client_id: 'client-A', status: 'success' }, instance.actionRun.runId), true)
  assert.equal(nextTicks.length, 0)
})

test('auto-refresh preserves Script replay arguments and modes', async () => {
  askConfirmation = () => { throw new Error('unexpected confirm') }
  const replay = { type: 'script', script_name: 'test/misc/json_result_actions_probe', params: { flag: 4 },
    execution_mode: 'inproc', output_mode: 'collect' }
  const { instance, events, nextTicks } = dialog(replay)
  await instance.confirmTableAction({ label: 'Update', command: 'getpid', confirm: false, refresh: true })
  complete(instance)
  nextTicks[0]()
  assert.equal(events.at(-1).event, 'rerun-json')
  assert.equal(events.at(-1).data.type, 'script')
  assert.equal(events.at(-1).data.script_name, replay.script_name)
  assert.equal(events.at(-1).data.params.flag, 4)
  assert.equal(events.at(-1).data.output_mode, 'collect')
})

test('Terminal action is tracked without suppressing SSE, Dialog mode suppresses it', async () => {
  const fragment = appSource.slice(appSource.indexOf('    async runTerminalJsonResultAction('), appSource.indexOf('    async runTerminalJsonAgain('))
  assert.ok(fragment.includes('suppress: inDialog'))
  const action = vm.runInNewContext(`({${fragment}}).runTerminalJsonResultAction`, { createTerminalOperation })
  for (const presentation of ['terminal', 'dialog']) {
    const captures = createTerminalTaskCapture()
    const received = []
    const app = { terminalTaskCapture: captures, $refs: {
      terminalJsonDialogRef: { handleResultActionCommandResult: e => received.push('result'),
        handleResultActionCommandComplete: e => received.push('complete') },
      commandInputBarRef: { runResultActionCommand: async function (_command, _clientId, _presentation, operation) {
        this.lastOperation = operation; return 'task-A'
      } },
    } }
    let done = null
    await action.call(app, { command: 'getpid', clientId: 'client-A', presentation,
      runId: 'run', onDone: ok => { done = ok } })
    assert.equal(done, true)
    const submitted = app.$refs.commandInputBarRef.lastOperation
    const event = { client_id: 'client-A', task_id: 'task-A', metadata: {
      operation_id: submitted.operation_id }, status: 'success', text: 'ok' }
    assert.equal(captures.route('result', event), presentation === 'dialog')
    assert.deepEqual(received, presentation === 'dialog' ? ['result'] : [])
    assert.equal(captures.route('complete', event), presentation === 'dialog')
    assert.deepEqual(received, presentation === 'dialog' ? ['result', 'complete'] : ['complete'])
    assert.equal(captures.route('complete', event), false)
  }
})

test('failed Run Again preserves current JSON even if its output contains valid JSON', async () => {
  askConfirmation = () => { throw new Error('unexpected confirm') }
  const { instance, events } = dialog()
  await instance.runAgain()
  const run = events.find(e => e.event === 'rerun-json')
  assert.ok(run)
  instance.handleJsonRefreshResult({ client_id: 'client-A', text: '[{"counter":999}]' }, run.data.runId)
  instance.handleJsonRefreshComplete({ client_id: 'client-A', status: 'failed' }, run.data.runId)
  assert.equal(instance.tableRows[0].counter, '0')
  assert.equal(instance.refreshRunning, false)
})
