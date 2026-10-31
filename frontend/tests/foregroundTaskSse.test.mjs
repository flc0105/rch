import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { normalizeForegroundTask } from '../src/utils/foregroundTask.js'

const app = readFileSync(new URL('../src/App.vue', import.meta.url), 'utf8')
const sse = readFileSync(new URL('../src/composables/useSseStream.js', import.meta.url), 'utf8')

function method(name, end, deps = {}) {
  const start = app.indexOf(`    ${name}(`)
  assert.notEqual(start, -1, name)
  const content = app.slice(start, app.indexOf(end, start))
  const body = content.slice(content.indexOf('{') + 1, content.lastIndexOf('}'))
  return new Function(...Object.keys(deps), `return function ${name}(clientId, payload) {${body}}`)(...Object.values(deps))
}

const applyUpdate = method('applyForegroundTaskUpdate', '\n    async refreshForegroundTask()', { normalizeForegroundTask })
const refreshSource = app.match(/    async refreshForegroundTask\(\) \{([\s\S]*?)\n    \},\n\n    async cancelForegroundTask\(/)
assert.ok(refreshSource)
const makeRefresh = getConnectionTask => new Function('getConnectionTask', 'normalizeForegroundTask',
  `return async function refreshForegroundTask() {${refreshSource[1]}
}`)(getConnectionTask, normalizeForegroundTask)

function fixture(getConnectionTask) {
  return {
    selectedId: 'A', foregroundQuerySequence: 0, foregroundTasks: {},
    isCurrentConnectionOffline: false, notices: [],
    syncForegroundTaskNotice(id, task) { this.notices.push([id, task.state]) },
    applyForegroundTaskUpdate: applyUpdate,
    refreshForegroundTask: makeRefresh(getConnectionTask),
  }
}

test('SSE update invalidates an older HTTP snapshot response', async () => {
  let resolve
  const app = fixture(() => new Promise(done => { resolve = done }))
  const pending = app.refreshForegroundTask()
  app.applyForegroundTaskUpdate('A', { state: 'Running', task_id: 'new' })
  resolve({ state: 'Idle' })
  await pending
  assert.equal(app.foregroundTasks.A.task_id, 'new')
  assert.deepEqual(app.notices, [['A', 'Running']])
})

test('switching clients and delayed responses do not overwrite newer state', async () => {
  const pendingResolvers = []
  const app = fixture(() => new Promise(resolve => pendingResolvers.push(resolve)))
  const old = app.refreshForegroundTask()
  app.selectedId = 'B'
  const current = app.refreshForegroundTask()
  pendingResolvers[1]({ state: 'Running', task_id: 'b-task' })
  await current
  pendingResolvers[0]({ state: 'Running', task_id: 'a-stale' })
  await old
  assert.equal(app.foregroundTasks.B.task_id, 'b-task')
  assert.equal(app.foregroundTasks.A, undefined)
})

test('the SSE listener applies payload snapshots without HTTP query', () => {
  assert.match(sse, /es\.addEventListener\('foreground_task_changed',[\s\S]*?this\.applyForegroundTaskUpdate\?\.\(payload\.client_id, payload\.task\)/)
  const handler = sse.match(/es\.addEventListener\('foreground_task_changed', \(event\) => \{([\s\S]*?)\n            \}\);/)
  assert.ok(handler)
  const callback = new Function('event', handler[1])
  const received = []
  callback.call({ applyForegroundTaskUpdate(id, task) { received.push([id, task]) }, selectedId: 'B' },
    { data: JSON.stringify({ client_id: 'A', task: { state: 'Running' } }) })
  assert.deepEqual(received, [['A', { state: 'Running' }]])
  assert.doesNotMatch(handler[1], /refreshForegroundTask|GET|fetch/)
})


test('both initial WebSocket open and reconnect reconcile authoritative task snapshots', () => {
  const handler = sse.match(/es\.addEventListener\('open', \(\) => \{([\s\S]*?)\n            \}\);/)
  assert.ok(handler)
  const open = new Function('tabId', `return function open() {${handler[1]}\n}`)('tab-a')
  let fetches = 0
  const state = { sseReady: false, $refs: {}, refreshForegroundTask() { fetches++ } }
  open.call(state)
  assert.equal(fetches, 1)
  open.call(state)
  assert.equal(fetches, 2)
})

test('local task-id arrival clears a premature own-task notice', () => {
  const watcher = app.match(/    currentActiveTaskId\(\) \{([\s\S]*?)\n    \},/)
  assert.ok(watcher)
  const onOwnTaskChanged = new Function(`return function(){${watcher[1]}\n}`)()
  const state = { selectedId: 'A', currentForegroundTask: { state: 'Running', task_id: 'mine' }, calls: [],
    syncForegroundTaskNotice(id, task) { this.calls.push([id, task.task_id]) } }
  onOwnTaskChanged.call(state)
  assert.deepEqual(state.calls, [['A', 'mine']])
})


test('another client SSE does not invalidate this client snapshot request', async () => {
  let resolve
  const app = fixture(() => new Promise(done => { resolve = done }))
  const pending = app.refreshForegroundTask()
  app.applyForegroundTaskUpdate('B', { state: 'Running', task_id: 'b' })
  resolve({ state: 'Running', task_id: 'a' })
  await pending
  assert.equal(app.foregroundTasks.A.task_id, 'a')
  assert.equal(app.foregroundTasks.B.task_id, 'b')
})
