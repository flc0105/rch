import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { shouldShowTaskNotice } from '../src/utils/foregroundTask.js'

const app = readFileSync(new URL('../src/App.vue', import.meta.url), 'utf8')
const match = app.match(/    syncForegroundTaskNotice\(clientId, task\) \{([\s\S]*?)\n    \},\n\n    async refreshForegroundTask\(/)
assert.ok(match, 'App must provide task notice synchronization')
const syncNotice = new Function('shouldShowTaskNotice', `return function syncForegroundTaskNotice(clientId, task) {${match[1]}\n}`)(shouldShowTaskNotice)

function makeApp() {
  return {
    outputs: {},
    currentActiveTaskId: '',
    ensureOutputBucket(clientId) { if (!this.outputs[clientId]) this.outputs[clientId] = [] },
    appendOutput(clientId, text, kind, meta) { this.outputs[clientId].push({ text, kind, meta }) },
    syncForegroundTaskNotice: syncNotice,
  }
}

const running = { state: 'Running', task_id: 'task-1', command_id: '123', started_at: '2026-10-28T10:00:00Z' }
const cancelling = { ...running, state: 'Cancelling' }
const notices = app => app.outputs.clientA.filter(line => line.meta?.foregroundTaskNotice)

test('new tab receives one inline warning and repeat polls do not duplicate or reorder it', () => {
  const state = makeApp()
  state.outputs.clientA = [{ text: 'revision notice', kind: 'warning', meta: { clientRevisionNotice: true } }]
  state.syncForegroundTaskNotice('clientA', running)
  assert.equal(notices(state).length, 1)
  assert.equal(notices(state)[0].kind, 'warning')
  assert.equal(notices(state)[0].text, '[!] Client is running a task.')
  assert.equal(state.outputs.clientA[0].text, 'revision notice')
  state.syncForegroundTaskNotice('clientA', running)
  assert.equal(state.outputs.clientA.length, 2)
})

test('cancelling updates only task notice and idle removes it', () => {
  const state = makeApp()
  state.syncForegroundTaskNotice('clientA', running)
  state.syncForegroundTaskNotice('clientA', cancelling)
  assert.equal(notices(state).length, 1)
  assert.equal(notices(state)[0].text, '[!] Task cancellation requested.')
  state.syncForegroundTaskNotice('clientA', { state: 'Idle' })
  assert.equal(notices(state).length, 0)
})

test('a tab executing its own task never gets cross-tab notice, and clears an old one', () => {
  const state = makeApp()
  state.syncForegroundTaskNotice('clientA', running)
  assert.equal(notices(state).length, 1)
  state.currentActiveTaskId = 'task-1'
  state.syncForegroundTaskNotice('clientA', running)
  assert.equal(notices(state).length, 0)
  state.currentActiveTaskId = ''
  state.syncForegroundTaskNotice('clientA', running)
  assert.equal(notices(state).length, 1)
})

test('another client output and other status notice remain untouched', () => {
  const state = makeApp()
  state.outputs.clientB = [{ text: 'B output', meta: {} }]
  state.syncForegroundTaskNotice('clientA', running)
  state.syncForegroundTaskNotice('clientA', { state: 'Idle' })
  assert.deepEqual(state.outputs.clientB, [{ text: 'B output', meta: {} }])
})
