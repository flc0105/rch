import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import { createTerminalOperation } from '../src/utils/terminalOperation.js'
import { formatTerminalCommandFinishedLine } from '../src/composables/terminalMarkers.js'
import { isJsonContainerText, isJsonStartLine, parseJsonLines, jsonBracketDelta } from '../src/utils/terminalJson.js'
import { trimTerminalWindow, splitLongTerminalLine, terminalLineBytes } from '../src/utils/terminalHistoryStore.js'
import { TERMINAL_HISTORY } from '../src/data/terminalHistoryConfig.js'

function loadOptions(name, overrides = {}) {
  const source = readFileSync(new URL(`../src/composables/${name}`, import.meta.url), 'utf8')
  const body = source.replace(/^import\s+[\s\S]*?\s+from\s+['"][^'"]+['"]\s*;?\s*$/gm, '')
    .replace('export default {', 'globalThis.component = {')
  const sandbox = { ...overrides, console }
  vm.runInNewContext(body, sandbox, { filename: name })
  return sandbox.component
}

function fixture() {
  const frames = []
  const saved = []
  let nextSeq = 0
  let visibleCommits = 0
  const options = loadOptions('useTerminalOutput.js', {
    TERMINAL_HISTORY, trimTerminalWindow, splitLongTerminalLine,
    createTerminalOperation, isJsonContainerText, isJsonStartLine, parseJsonLines, jsonBracketDelta,
    ElMessage: { error() {} },
    TERMINAL_BACKGROUND_PREFIX: '[Background]',
    isTerminalCancelRequestedText: () => false,
    isTerminalCommandFailedText: () => false,
    isTerminalCommandFinishedText: text => String(text).startsWith('[Command finished]'),
    requestAnimationFrame(callback) { frames.push(callback); return frames.length },
    cancelAnimationFrame() {},
  })
  const host = { ...options.data(), selectedId: 'dev', $refs: {}, $nextTick(callback) { callback?.() },
    _terminalHistory: { append(client, rows) {
      for (const row of rows) { row.__terminalSeq = nextSeq++; saved.push(structuredClone(row)) }
    }, clear: async () => { saved.length = 0 } },
    scrollToBottom() {},
  }
  for (const [name, fn] of Object.entries(options.methods)) host[name] = fn.bind(host)
  let lastRendered = host.outputs.dev
  Object.defineProperty(host.outputs, 'dev', {
    configurable: true, get() { return lastRendered }, set(rows) { visibleCommits++; lastRendered = rows },
  })
  return { host, saved, frames, commits: () => visibleCommits }
}

test('10000 streamed rows persist exactly once and update visible window by frame, not by line', () => {
  const { host, frames, saved, commits } = fixture()
  host.ensureOutputBucket('dev')
  const initialCommits = commits()
  for (let start = 0; start < 10000; start += 128) {
    const entries = Array.from({ length: Math.min(128, 10000 - start) }, (_, i) => ({
      text: `RCH-${String(start + i + 1).padStart(5, '0')}`,
      meta: { event_type: 'output', operation_id: 'operation-1', task_id: 'task-1' },
    }))
    host.appendOutputBatch('dev', entries)
  }
  assert.equal(saved.length, 10000)
  assert.equal(saved[0].text, 'RCH-00001')
  assert.equal(saved.at(-1).text, 'RCH-10000')
  assert.equal(commits(), initialCommits, 'no per-event DOM refresh during incoming burst')
  assert.equal(frames.length, 1, 'a single rAF commit is scheduled')
  frames.shift()()
  assert.equal(commits(), initialCommits + 1)
  assert.equal(host.outputs.dev.length, TERMINAL_HISTORY.visibleLines)
  assert.equal(host.outputs.dev.at(-1).text, 'RCH-10000')
})

test('completion flushes pending output in order; Clear discards a pending render frame', () => {
  const { host, frames, saved } = fixture()
  host.ensureOutputBucket('dev')
  host.appendOutputBatch('dev', [{ text: 'one', meta: { event_type: 'output' } }])
  host.appendOutput('dev', '[Command finished] test (Success)', 'success', { event_type: 'completed' })
  assert.deepEqual(Array.from(host.outputs.dev, line => line.text), ['one', '[Command finished] test (Success)'])
  assert.equal(saved.length, 2)
  // A stale scheduled callback must not resurrect already-cleared UI history.
  host.clearOutput()
  for (const callback of frames) callback()
  assert.equal(host.outputs.dev.length, 0)
})

test('programmatic scrolling does not disable follow; real upward scrolling does', () => {
  const { host } = fixture()
  host.ensureOutputBucket('dev')
  host.handleTerminalScroll({ atTop: false, atBottom: false, userInitiated: false })
  assert.equal(host.terminalViewStates.dev.follow, true)
  host.handleTerminalScroll({ atTop: false, atBottom: false, userInitiated: true })
  assert.equal(host.terminalViewStates.dev.follow, false)
})


test('batched websocket result enters the same Terminal and task-completion path', async () => {
  const { host, saved, frames } = fixture()
  const handlers = new Map()
  const es = { addEventListener(type, callback) { handlers.set(type, callback) }, close() {} }
  const sse = loadOptions('useSseStream.js', {
    openWebEventStream: () => es,
    formatTerminalCommandFinishedLine,
    TERMINAL_BACKGROUND_PREFIX: '[Background]',
    TERMINAL_FILE_READY_PREFIX: '[File Ready]',
    DEFAULT_SSE_NOTIFICATION_PREFERENCES: {},
    cloneSseNotificationPreferences: () => ({}),
    ElNotification: () => {}, h: () => {},
  })
  let outputCount = 0
  let finished = 0
  Object.assign(host, sse.data(), {
    connections: [], selectedId: 'dev', ensureTabId() { return 'tab-1' },
    loadConnections: async () => {}, noteTaskOutput(_id, count) { outputCount += count },
    markTaskCompleted() { finished++ }, routeTerminalTaskCapture: () => false,
  })
  for (const [name, fn] of Object.entries(sse.methods)) host[name] = fn.bind(host)
  host.ensureTabId = () => 'tab-1'
  host.initSSE()
  const shared = { client_id: 'dev', task_id: 'task-1', command: 'test', metadata: { operation_id: 'operation-1' } }
  const emit = async (name, payload) => handlers.get(name)({ data: JSON.stringify(payload) })
  await emit('command_result_batch', { ...shared, results: [
    { status: 1, text: 'hello' }, { status: 1, text: 'world' }, { status: 0, text: 'warning' },
  ] })
  assert.equal(outputCount, 3)
  assert.deepEqual(saved.map(row => row.text), ['> test', 'hello', 'world', 'warning'])
  await emit('command_complete', { ...shared, status: 'success', success: true })
  assert.equal(finished, 1)
  assert.equal(saved.at(-1).text, '[Command finished] test (Success)')
  for (const callback of frames) callback()
  assert.equal(host.outputs.dev.at(-1).text, '[Command finished] test (Success)')
})

test('batch preserves dialog routing per chunk without adding its output to Terminal', () => {
  const { host, saved } = fixture()
  const handlers = new Map()
  const es = { addEventListener(type, callback) { handlers.set(type, callback) }, close() {} }
  const sse = loadOptions('useSseStream.js', {
    openWebEventStream: () => es, formatTerminalCommandFinishedLine,
    TERMINAL_BACKGROUND_PREFIX: '[Background]', TERMINAL_FILE_READY_PREFIX: '[File Ready]',
    DEFAULT_SSE_NOTIFICATION_PREFERENCES: {}, cloneSseNotificationPreferences: () => ({}),
    ElNotification: () => {}, h: () => {},
  })
  let dialogCalls = 0
  Object.assign(host, sse.data(), {
    connections: [], selectedId: 'dev', ensureTabId() { return 'tab-1' },
    noteTaskOutput() {}, loadConnections: async () => {},
    routeTerminalTaskCapture: () => false,
    handleScriptCommandResult() { dialogCalls++; return true },
  })
  for (const [name, fn] of Object.entries(sse.methods)) host[name] = fn.bind(host)
  host.ensureTabId = () => 'tab-1'
  host.initSSE()
  handlers.get('command_result_batch')({ data: JSON.stringify({
    client_id: 'dev', task_id: 'dialog', command: 'script run',
    metadata: { script_run: true, script_run_presentation: 'dialog' },
    results: [{ status: 1, text: 'line1' }, { status: 1, text: 'line2' }],
  }) })
  assert.equal(dialogCalls, 2)
  assert.equal(saved.length, 0)
})
