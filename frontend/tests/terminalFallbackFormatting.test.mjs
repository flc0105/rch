import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import { createTerminalOperation } from '../src/utils/terminalOperation.js'
import { formatTerminalCommandFinishedLine } from '../src/composables/terminalMarkers.js'
import { isJsonContainerText, isJsonStartLine, parseJsonLines, jsonBracketDelta } from '../src/utils/terminalJson.js'

function loadComposable(name, imports) {
  const source = readFileSync(new URL(`../src/composables/${name}`, import.meta.url), 'utf8')
  const body = source.replace(/^import\s+[\s\S]*?\s+from\s+['"][^'"]+['"]\s*;?\s*$/gm, '')
    .replace('export default {', 'globalThis.component = {')
  const sandbox = { ...imports, console }
  vm.runInNewContext(body, sandbox, { filename: name })
  return sandbox.component
}

function fixture() {
  const handlers = new Map()
  const es = { addEventListener(type, cb) { handlers.set(type, cb) }, close() {} }
  const output = loadComposable('useTerminalOutput.js', {
    createTerminalOperation, isJsonContainerText, isJsonStartLine, parseJsonLines, jsonBracketDelta,
    TERMINAL_BACKGROUND_PREFIX: '[Background]',
    isTerminalCancelRequestedText: () => false,
    isTerminalCommandFailedText: () => false,
    isTerminalCommandFinishedText: text => String(text || '').startsWith('[Command finished]'),
  })
  const sse = loadComposable('useSseStream.js', {
    openWebEventStream: () => es, h: () => {}, ElNotification: () => {},
    formatTerminalCommandFinishedLine,
    TERMINAL_BACKGROUND_PREFIX: '[Background]', TERMINAL_FILE_READY_PREFIX: '[File Ready]',
    DEFAULT_SSE_NOTIFICATION_PREFERENCES: {}, cloneSseNotificationPreferences: () => ({}),
  })
  const ctx = {
    ...output.data(), ...sse.data(), connections: [], selectedId: 'client-1',
    ensureTabId: () => 'tab-1', loadConnections: async () => {},
    noteTaskOutput() {}, markTaskCompleted() {}, scrollToBottom() {}, $nextTick(cb) { cb() }, $refs: {},
    routeTerminalTaskCapture: () => false,
  }
  for (const [name, method] of Object.entries(output.methods)) ctx[name] = method.bind(ctx)
  for (const [name, method] of Object.entries(sse.methods)) ctx[name] = method.bind(ctx)
  ctx.ensureTabId = () => 'tab-1'
  ctx.initSSE()
  return { ctx, emit: async (type, payload) => await handlers.get(type)({ data: JSON.stringify(payload) }) }
}

const event = (taskId, metadata = {}, more = {}) => ({
  client_id: 'client-1', task_id: taskId, command: 'printf test', metadata, ...more,
})

test('unassociated SSE stdout and completion create one typed start line', async () => {
  const { ctx, emit } = fixture()
  await emit('command_result', event('task-a', { operation_id: 'op-a' }, { text: 'test' }))
  await emit('command_result', event('task-a', { operation_id: 'op-a' }, { text: 'more' }))
  await emit('command_complete', event('task-a', { operation_id: 'op-a' }, { status: 'success', success: true }))
  const rows = ctx.outputs['client-1']
  assert.deepEqual(Array.from(rows, row => row.text), [
    '> printf test', 'test', 'more', '[Command finished] printf test (Success)',
  ])
  assert.ok(rows.every(row => row.meta.operation_id === 'op-a'))
  assert.equal(rows[3].meta.event_type, 'completed')
})

test('missing operation id is bound by task id; no duplicated header', async () => {
  const { ctx, emit } = fixture()
  await emit('command_result', event('task-b', {}, { text: 'one' }))
  await emit('command_complete', event('task-b', {}, { status: 'failed', success: false }))
  const rows = ctx.outputs['client-1']
  assert.equal(rows.filter(r => r.kind === 'command').length, 1)
  assert.ok(rows.every(r => r.meta.operation_id === rows[0].meta.operation_id))
  assert.match(rows[0].meta.operation_id, /^[0-9a-f-]{36}$/)
})

test('Clear Terminal mid-task produces a fresh start for later SSE results', async () => {
  const { ctx, emit } = fixture()
  const op = createTerminalOperation({ kind: 'command', action: 'invoke', clientId: 'client-1', replay: null })
  ctx.appendOutput('client-1', '> printf test', 'command', { operation: op })
  await emit('command_result', event('task-c', { operation_id: op.operation_id }, { text: 'early' }))
  assert.equal(ctx.outputs['client-1'].filter(r => r.kind === 'command').length, 1)
  ctx.clearOutput()
  await emit('command_result', event('task-c', { operation_id: op.operation_id }, { text: 'late' }))
  await emit('command_complete', event('task-c', { operation_id: op.operation_id }, { success: true }))
  assert.deepEqual(Array.from(ctx.outputs['client-1'], row => row.text), [
    '> printf test', 'late', '[Command finished] printf test (Success)',
  ])
})

test('completion without prior results creates a visible start', async () => {
  const { ctx, emit } = fixture()
  await emit('command_complete', event('task-silent', {}, { success: true }))
  assert.deepEqual(Array.from(ctx.outputs['client-1'], row => row.text), [
    '> printf test', '[Command finished] printf test (Success)',
  ])
})

test('Quick Action fallback uses alias identity, not executable shell reconstruction', async () => {
  const { ctx, emit } = fixture()
  const metadata = { quick_action: true, quick_action_presentation: 'terminal', quick_action_display_command: 'cwd' }
  await emit('command_complete', event('task-alias', metadata, { success: true }))
  const rows = ctx.outputs['client-1']
  assert.equal(rows[0].text, '> cwd')
  assert.equal(rows[0].meta.operation.kind, 'alias')
  assert.equal(rows[0].meta.operation.replay, null)
})

test('typed stdout beginning > stays output, not a second command header', async () => {
  const { ctx, emit } = fixture()
  await emit('command_result', event('task-stdout', {}, { text: '> literal data' }))
  assert.deepEqual(Array.from(ctx.outputs['client-1'], row => row.kind), ['command', 'default'])
})
