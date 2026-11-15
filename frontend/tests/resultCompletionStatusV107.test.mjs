import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import { createTerminalOperation } from '../src/utils/terminalOperation.js'
import { formatTerminalCommandFinishedLine } from '../src/composables/terminalMarkers.js'
import { isJsonContainerText, isJsonStartLine, parseJsonLines, jsonBracketDelta } from '../src/utils/terminalJson.js'

const load = relative => readFileSync(new URL(relative, import.meta.url), 'utf8')
function loadComposable(relative, imports) {
  const body = load(relative)
    .replace(/^import\s+[\s\S]*?\s+from\s+['"][^'"]+['"]\s*;?\s*$/gm, '')
    .replace('export default {', 'globalThis.component = {')
  const sandbox = {...imports, console}
  vm.runInNewContext(body, sandbox, { filename: relative })
  return sandbox.component
}
function session() {
  const handlers = new Map()
  const es = { addEventListener(type, cb) { handlers.set(type, cb) }, close() {} }
  const output = loadComposable('../src/composables/useTerminalOutput.js', {
    createTerminalOperation, isJsonContainerText, isJsonStartLine, parseJsonLines, jsonBracketDelta,
    TERMINAL_BACKGROUND_PREFIX: '[Background]',
    isTerminalCancelRequestedText: () => false,
    isTerminalCommandFailedText: () => false,
    isTerminalCommandFinishedText: text => String(text || '').startsWith('[Command finished]'),
  })
  const sse = loadComposable('../src/composables/useSseStream.js', {
    openWebEventStream: () => es, h: () => {}, ElNotification: () => {},
    formatTerminalCommandFinishedLine,
    TERMINAL_BACKGROUND_PREFIX: '[Background]', TERMINAL_FILE_READY_PREFIX: '[File Ready]',
    DEFAULT_SSE_NOTIFICATION_PREFERENCES: {}, cloneSseNotificationPreferences: () => ({}),
  })
  const ctx = {...output.data(), ...sse.data(), connections: [], selectedId: 'client-1',
    ensureTabId: () => 'tab-1', loadConnections: async () => {},
    noteTaskOutput() {}, markTaskCompleted() {}, scrollToBottom() {}, $nextTick(cb) { cb() }, $refs: {},
    routeTerminalTaskCapture: () => false,
  }
  for (const [name, method] of Object.entries(output.methods)) ctx[name] = method.bind(ctx)
  for (const [name, method] of Object.entries(sse.methods)) ctx[name] = method.bind(ctx)
  ctx.ensureTabId = () => 'tab-1'
  ctx.initSSE()
  return {ctx, complete: async more => await handlers.get('command_complete')({data: JSON.stringify({client_id:'client-1',task_id:'t',command:'pwd',metadata:{},...more})})}
}

test('Web terminal honors partial and detailed terminal failure even if boolean disagrees', async () => {
  for (const [status, success, label, kind] of [
    ['partial', false, 'Partial', 'warning'],
    ['timed_out', false, 'Timed out', 'error'],
    ['interrupted', false, 'Interrupted', 'error'],
    ['cancelled', false, 'Cancelled', 'info'],
    ['error', true, 'Failed', 'error'],
    ['success', false, 'Success', 'success'],
  ]) {
    const {ctx, complete} = session()
    await complete({status, success})
    const line = ctx.outputs['client-1'].at(-1)
    assert.equal(line.text, `[Command finished] pwd (${label})`)
    assert.equal(line.kind, kind)
    assert.equal(line.meta.execution_status, status)
    assert.equal(ctx.terminalOperationRegistry[line.meta.operation_id].status, status)
  }
})

function method(relative, label, next) {
  const source = load(relative)
  const begin = source.indexOf(label)
  const end = source.indexOf(next, begin)
  assert.ok(begin >= 0 && end > begin, `${relative}: method not found`)
  const body = source.slice(begin, end).trim().replace(/,\s*$/, '')
  return Function(`return ({${body}})[${JSON.stringify(label.split('(')[0].trim())}]`)()
}

for (const [file, action, next, resultField] of [
  ['../src/components/QuickActionsDialog.vue','handleCommandComplete(payload = {}) {', '    async copyResult()', 'activeRun'],
  ['../src/components/ScriptLibraryDialog.vue','handleCommandComplete(payload = {}) {', '    async copyResult()', 'activeRun'],
  ['../src/components/TerminalJsonDialog.vue',"handleResultActionCommandComplete(payload = {}, runId = '') {", '    async copyResultActionOutput()', 'activeResult'],
]) {
  test(`${file} displays partial independently of success boolean`, () => {
    const fn = method(file, '    '+action, next)
    const state = {runId:'test', clientId:'client-1', complete:false, status:''}
    const ctx = {[resultField]:state}
    const metadata = {quick_action:true, quick_action_presentation:'dialog', quick_action_run_id:'test',
      script_run:true, script_run_presentation:'dialog', script_run_id:'test'}
    const payload = {client_id:'client-1', status:'partial', success:false, metadata}
    const handled = resultField === 'activeResult' ? fn.call(ctx, payload, 'test') : fn.call(ctx, payload)
    assert.equal(handled, true)
    assert.equal(state.status, 'Partial')
    assert.equal(state.complete, true)
  })
}

// A refreshed page takes a different path from the live SSE event. Ensure the
// persisted Activity status does not regress to the old success/failed binary.
test('recovered terminal task uses original completed status', async () => {
  const source = load('../src/composables/useTaskState.js')
  const begin = source.indexOf('        async recoverFinishedTask(')
  const end = source.indexOf('        clearActiveTask(', begin)
  assert.ok(begin >= 0 && end > begin)
  const declaration = source.slice(begin, end).trim().replace(/,\s*$/, '')
    .replace("await import('../api/commandHistoryApi.js')", 'await Promise.resolve({ getCommandExecutionEntry: injectedReader })')
    .replace("await import('./terminalMarkers.js')", 'await Promise.resolve({ formatTerminalCommandFinishedLine: injectedMarker })')
  const factory = Function('injectedReader', 'injectedMarker',
    `return ({${declaration}}).recoverFinishedTask`)
  for (const [status, label, kind] of [
    ['success', 'Success', 'success'],
    ['partial', 'Partial', 'warning'],
    ['error', 'Failed', 'error'],
    ['cancelled', 'Cancelled', 'info'],
    ['timed_out', 'Timed out', 'error'],
    ['interrupted', 'Interrupted', 'error'],
  ]) {
    const printed = []
    const ctx = {
      connections: [{client_id: 'client-1', machine_id: 'machine-1'}],
      activeTaskHistoryIds: {}, taskOutputCounts: {}, completedTaskIds: {},
      markTaskCompleted(_clientId, taskId) { this.completedTaskIds[taskId] = true },
      appendOutput(_clientId, text, color, meta) { printed.push({text, color, meta}) },
    }
    const readEntry = async () => ({client_id:'client-1', finished_at:'2026-11-15T00:00:00Z',
      presentation: 'terminal', invocation:{command:'pwd'}, status, result:{output_records:[]}})
    await factory(readEntry, formatTerminalCommandFinishedLine).call(ctx, 'client-1', 'task-'+status, 'entry-1')
    assert.equal(printed.length, 1)
    assert.equal(printed[0].text, `[Command finished] pwd (${label})`)
    assert.equal(printed[0].color, kind)
    assert.equal(printed[0].meta.execution_status, status)
  }
})
