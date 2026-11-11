import assert from 'node:assert/strict'
import test from 'node:test'
import { fixture, notices, task, source } from './foregroundTaskNoticeFixture.mjs'

async function enter(page, id = 'A') {
  page.enter(id)
  await Promise.resolve()
  await Promise.resolve()
}

test('refresh or new tab: first authoritative snapshot admits one existing task', async () => {
  const page = fixture(async () => task)
  page.outputs.A = [{ text: 'existing output', kind: 'info', meta: {} }]
  await enter(page)
  assert.equal(notices(page).length, 1)
  assert.equal(notices(page)[0].text, '[!] Client is running a task.')
  assert.equal(notices(page)[0].meta.foregroundTaskKey, 'task:task-1')
  assert.equal(page.outputs.A[0].text, 'existing output')
})

test('Running command_id updates never recreate a displayed notice', async () => {
  const page = fixture(async () => task)
  await enter(page)
  const previous = notices(page)[0]
  page.applyForegroundTaskUpdate('A', { ...task, command_id: 456 })
  page.applyForegroundTaskUpdate('A', { ...task, command_id: 789 })
  assert.equal(notices(page).length, 1)
  assert.strictEqual(notices(page)[0], previous)
})

test('Cancelling updates the admitted notice, Idle removes permanently', async () => {
  const page = fixture(async () => task)
  await enter(page)
  page.applyForegroundTaskUpdate('A', { ...task, state: 'Cancelling' })
  assert.equal(notices(page).length, 1)
  assert.equal(notices(page)[0].text, '[!] Task cancellation requested.')
  page.applyForegroundTaskUpdate('A', { state: 'Idle' })
  assert.equal(notices(page).length, 0)
  assert.equal(page.getTerminalNotice('A', 'foreground'), null)
  page.applyForegroundTaskUpdate('A', { ...task, task_id: 'another' })
  assert.equal(notices(page).length, 0)
  assert.equal(page.foregroundTasks.A.task_id, 'another', 'real Busy state continues to update')
})

test('remote-file task without Web task_id has stable fallback identity', async () => {
  const remote = { state: 'Running', task_id: '', started_at: '2026-11-11T01:00:00Z',
    source: 'web_remote_file', task_type: 'remote_file', command: 'browse' }
  const page = fixture(async () => remote)
  await enter(page)
  assert.equal(notices(page).length, 1)
  const original = notices(page)[0]
  page.applyForegroundTaskUpdate('A', { ...remote, command_id: 900 })
  assert.strictEqual(notices(page)[0], original)
  page.applyForegroundTaskUpdate('A', { ...remote, started_at: '2026-11-11T01:00:01Z' })
  assert.equal(notices(page).length, 0, 'a different task retires the entry notice')
})

test('local Remote File Browser Running SSE after entry Idle never creates a warning', async () => {
  const page = fixture(async () => ({ state: 'Idle' }))
  await enter(page)
  for (let index = 0; index < 10; index++) {
    page.applyForegroundTaskUpdate('A', { state: 'Running', started_at: `start-${index}`, task_type: 'remote_file', source: 'web_remote_file' })
    page.applyForegroundTaskUpdate('A', { state: 'Idle' })
  }
  assert.equal(notices(page).length, 0)
})


test('Clear removes a notice without a later SSE re-inserting it', async () => {
  const page = fixture(async () => task)
  await enter(page)
  assert.equal(notices(page).length, 1)
  page.outputs.A = []
  page.setTerminalNotice('A', 'foreground', null)
  page.applyForegroundTaskUpdate('A', { ...task, command_id: 'new-binding' })
  page.applyForegroundTaskUpdate('A', { ...task, state: 'Cancelling' })
  assert.equal(notices(page).length, 0)
  assert.equal(page.getTerminalNotice('A', 'foreground'), null)
})

test('SSE reconnect HTTP refresh cannot newly admit a different task', async () => {
  let snapshot = { state: 'Idle' }
  const page = fixture(async () => snapshot)
  await enter(page)
  snapshot = task
  await page.refreshForegroundTask()
  assert.equal(notices(page).length, 0)
  assert.equal(page.foregroundTasks.A.task_id, task.task_id)
})

test('each Client is evaluated once when first selected', async () => {
  const page = fixture(async id => id === 'B' ? task : { state: 'Idle' })
  await enter(page)
  await enter(page, 'B')
  assert.equal(notices(page, 'B').length, 1)
  await enter(page, 'A')
  page.applyForegroundTaskUpdate('A', task)
  assert.equal(notices(page, 'A').length, 0)
  assert.equal(notices(page, 'B').length, 1)
})

test('no status-change timer or delayed reclassification is introduced', () => {
  assert.doesNotMatch(source, /foregroundNoticeTimers|setTimeout\(publishNotice/)
  assert.doesNotMatch(source, /pendingTerminalSubmissions/)
  assert.doesNotMatch(source, /currentActiveTaskId\(\) \{[\s\S]*?syncForegroundTaskNotice/)
})
