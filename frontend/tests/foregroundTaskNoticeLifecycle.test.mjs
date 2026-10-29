import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { shouldShowTaskNotice } from '../src/utils/foregroundTask.js'

const app = readFileSync(new URL('../src/App.vue', import.meta.url), 'utf8')
const match = app.match(/    syncForegroundTaskNotice\(clientId, task\) \{([\s\S]*?)\n    \},\n\n    applyForegroundTaskUpdate\(/)
assert.ok(match, 'App must provide task notice synchronization')
const syncNotice = new Function('shouldShowTaskNotice',
  `return function syncForegroundTaskNotice(clientId, task) {${match[1]}\n}`
)(shouldShowTaskNotice)

function makeApp() {
  return {
    selectedId: 'clientA',
    activeTaskIds: {},
    outputs: {},
    get currentActiveTaskId() { return this.activeTaskIds[this.selectedId] || '' },
    ensureOutputBucket(clientId) { if (!this.outputs[clientId]) this.outputs[clientId] = [] },
    appendOutput(clientId, text, kind, meta) { this.outputs[clientId].push({ text, kind, meta }) },
    syncForegroundTaskNotice: syncNotice,
  }
}

const running = { state: 'Running', task_id: 'task-1', command_id: '123', started_at: '2026-10-28T10:00:00Z' }
const notices = state => (state.outputs.clientA || []).filter(line => line.meta?.foregroundTaskNotice)

test('a refreshed page immediately renders the existing Running task warning with Details metadata', () => {
  const state = makeApp() // Reload: no local task ID.
  state.outputs.clientA = [{ text: 'existing output', kind: 'info', meta: {} }]
  state.syncForegroundTaskNotice('clientA', running)
  assert.equal(notices(state).length, 1)
  assert.equal(notices(state)[0].text, '[!] Client is running a task.')
  assert.equal(notices(state)[0].kind, 'warning')
  assert.equal(notices(state)[0].meta.foregroundTaskKey, 'task-1:123:2026-10-28T10:00:00Z')
  assert.equal(state.outputs.clientA[0].text, 'existing output')
})

test('repeat Running SSE updates do not duplicate the notice', () => {
  const state = makeApp()
  state.syncForegroundTaskNotice('clientA', running)
  state.syncForegroundTaskNotice('clientA', running)
  assert.equal(notices(state).length, 1)
})

test('a task running in this tab is not shown as another task', () => {
  const state = makeApp()
  state.activeTaskIds.clientA = running.task_id
  state.syncForegroundTaskNotice('clientA', running)
  assert.equal(notices(state).length, 0)
})

test('Cancelling updates the existing notice and Idle removes it', () => {
  const state = makeApp()
  state.syncForegroundTaskNotice('clientA', running)
  state.syncForegroundTaskNotice('clientA', { ...running, state: 'Cancelling' })
  assert.equal(notices(state).length, 1)
  assert.equal(notices(state)[0].text, '[!] Task cancellation requested.')
  state.syncForegroundTaskNotice('clientA', { state: 'Idle' })
  assert.equal(notices(state).length, 0)
})

test('other output and other client buckets are not erased', () => {
  const state = makeApp()
  state.outputs.clientA = [{ text: 'keep', meta: {} }]
  state.outputs.clientB = [{ text: 'B output', meta: {} }]
  state.syncForegroundTaskNotice('clientA', running)
  state.syncForegroundTaskNotice('clientA', { state: 'Idle' })
  assert.equal(state.outputs.clientA[0].text, 'keep')
  assert.deepEqual(state.outputs.clientB, [{ text: 'B output', meta: {} }])
})

test('the removed delay state is not retained anywhere in App', () => {
  assert.doesNotMatch(app, /foregroundNoticeTimers|setTimeout\(publishNotice/)
})
