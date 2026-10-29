import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { shouldShowTaskNotice } from '../src/utils/foregroundTask.js'

const appSource = readFileSync(new URL('../src/App.vue', import.meta.url), 'utf8')
const inputSource = readFileSync(new URL('../src/components/CommandInputBar.vue', import.meta.url), 'utf8')

function method(source, name, next, deps = {}) {
  const start = source.indexOf(`    ${name}(`)
  assert.ok(start >= 0, `${name} must exist`)
  const code = source.slice(start, source.indexOf(next, start))
  const body = code.slice(code.indexOf('{') + 1, code.lastIndexOf('}'))
  return new Function(...Object.keys(deps), `return function ${name}(${name === 'syncForegroundTaskNotice' ? 'clientId, task' : name === 'startTerminalSubmission' ? 'clientId, command' : 'clientId'}) {${body}}`)(...Object.values(deps))
}

const start = method(appSource, 'startTerminalSubmission', '\n    finishTerminalSubmission(')
const finish = method(appSource, 'finishTerminalSubmission', '\n    syncForegroundTaskNotice(')
const sync = method(appSource, 'syncForegroundTaskNotice', '\n    applyForegroundTaskUpdate(', { shouldShowTaskNotice })
const running = {
  state: 'Running', task_id: 'job-23', source: 'web', tab_id: 'tab-A',
  command: 'shell sleep 5', command_id: '13', started_at: '2026-10-29T00:00:00Z',
}

function makeApp() {
  return {
    selectedId: 'client-A', tabId: 'tab-A', pendingTerminalSubmissions: {},
    activeTaskIds: {}, foregroundTasks: {}, outputs: {},
    startTerminalSubmission: start, finishTerminalSubmission: finish,
    syncForegroundTaskNotice: sync,
    ensureOutputBucket(id) { this.outputs[id] ??= [] },
    appendOutput(id, text, kind, meta) { this.outputs[id].push({ text, kind, meta }) },
    setActiveTask(id, taskId) { if (taskId) this.activeTaskIds[id] = taskId },
  }
}
const notices = (app, id = 'client-A') => (app.outputs[id] || []).filter(item => item.meta?.foregroundTaskNotice)

function makeSendCommand(api, state) {
  const match = inputSource.match(/    async sendCommand\(\) \{([\s\S]*?)\n\},\n\n    \/\/ async sendCommand\(\)/)
  assert.ok(match, 'real sendCommand method available')
  const send = new Function('sendCommandApi', 'ElMessage', 'formatTerminalCommandFailedLine',
    `return async function sendCommand() {${match[1]}\n}`)(api, { warning() {}, error() {} }, text => text)
  return send.bind({
    commandText: running.command, selectedId: 'client-A', sending: false,
    closeAutocomplete() {}, clearAutocompleteNavigationState() {},
    handleLocalFrontendCommand() { return false },
    getSubmittedCommandCancelPolicy() { return '' },
    getTabScopedHeaders() { return { 'X-Tab-Id': 'tab-A' } },
    clearCommandCompletionCandidateCache() {}, async loadCommandCandidates() {},
    $emit(type, ...args) {
      if (type === 'terminal-submission-start') state.startTerminalSubmission(...args)
      if (type === 'terminal-submission-finish') state.finishTerminalSubmission(...args)
      if (type === 'set-active-task') {
        state.setActiveTask(args[0], args[1]);
        state.syncForegroundTaskNotice(args[0], state.foregroundTasks[args[0]] || { state: 'Idle' })
      }
    },
  })
}

test('deterministic repro: Running SSE before pending POST response never flashes own warning', async () => {
  let resolvePost
  const state = makeApp()
  const send = makeSendCommand(() => new Promise(resolve => { resolvePost = resolve }), state)
  const inFlight = send()
  assert.deepEqual(state.pendingTerminalSubmissions['client-A'], { command: running.command })
  // This is the exact old race: no local task id yet, SSE has already delivered Running.
  assert.equal(shouldShowTaskNotice(running, ''), true, 'old implementation would flash')
  state.foregroundTasks['client-A'] = running
  state.syncForegroundTaskNotice('client-A', running)
  assert.equal(notices(state).length, 0)
  resolvePost({ task_id: running.task_id })
  await inFlight
  assert.equal(notices(state).length, 0)
  assert.equal(state.activeTaskIds['client-A'], running.task_id)
  assert.deepEqual(state.pendingTerminalSubmissions, {})
})

test('refresh with a Running task displays the yellow notice immediately, even with reused tab ID', () => {
  const state = makeApp() // no in-memory pending submission after page reload
  state.foregroundTasks['client-A'] = running
  state.syncForegroundTaskNotice('client-A', running)
  assert.equal(notices(state).length, 1)
  assert.equal(notices(state)[0].text, '[!] Client is running a task.')
  assert.equal(notices(state)[0].meta.foregroundTaskKey, 'job-23:13:2026-10-29T00:00:00Z')
})

test('a different tab with the same command is never hidden during our local submission', () => {
  const state = makeApp()
  state.startTerminalSubmission('client-A', running.command)
  state.syncForegroundTaskNotice('client-A', { ...running, tab_id: 'tab-B' })
  assert.equal(notices(state).length, 1)
})

test('same-tab but different command, source or missing ownership remain visible', () => {
  for (const patch of [
    { command: 'shell sleep 6' }, { source: 'cli' }, { tab_id: '' }, { task_id: '' },
  ]) {
    const state = makeApp()
    state.startTerminalSubmission('client-A', running.command)
    state.syncForegroundTaskNotice('client-A', { ...running, ...patch })
    assert.equal(notices(state).length, 1, JSON.stringify(patch))
  }
})

test('failed POST immediately restores the warning if the task really is running', async () => {
  const state = makeApp()
  const send = makeSendCommand(() => Promise.reject(new Error('HTTP failed')), state)
  state.foregroundTasks['client-A'] = running
  await send()
  assert.equal(notices(state).length, 1)
  assert.deepEqual(state.pendingTerminalSubmissions, {})
})

test('Idle arriving ahead of POST response is not reclassified as Running after completion', async () => {
  let resolvePost
  const state = makeApp()
  const send = makeSendCommand(() => new Promise(resolve => { resolvePost = resolve }), state)
  const inFlight = send()
  state.syncForegroundTaskNotice('client-A', running)
  state.foregroundTasks['client-A'] = { state: 'Idle' }
  state.syncForegroundTaskNotice('client-A', { state: 'Idle' })
  resolvePost({ task_id: running.task_id })
  await inFlight
  assert.equal(notices(state).length, 0)
})

test('pending command of another client does not suppress current client notice', () => {
  const state = makeApp()
  state.startTerminalSubmission('client-B', running.command)
  state.syncForegroundTaskNotice('client-A', running)
  assert.equal(notices(state).length, 1)
})
