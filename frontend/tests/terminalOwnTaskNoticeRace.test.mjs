import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { fixture, notices, task, source } from './foregroundTaskNoticeFixture.mjs'
import { createTerminalOperation, operationHeaders } from '../src/utils/terminalOperation.js'

const inputSource = readFileSync(new URL('../src/components/CommandInputBar.vue', import.meta.url), 'utf8')
function sendCommand(api, page) {
  const match = inputSource.match(/    async sendCommand\(\) \{([\s\S]*?)\n\},\n\n    \/\/ async sendCommand\(\)/)
  assert.ok(match)
  const send = new Function('sendCommandApi', 'ElMessage', 'formatTerminalCommandFailedLine', 'createTerminalOperation', 'operationHeaders',
    `return async function sendCommand() {${match[1]}\n}`)(api, { warning() {}, error() {} }, text => text, createTerminalOperation, operationHeaders)
  return send.bind({
    commandText: task.command, selectedId: 'A', sending: false,
    closeAutocomplete() {}, clearAutocompleteNavigationState() {}, handleLocalFrontendCommand() { return false },
    getSubmittedCommandCancelPolicy() { return '' }, getTabScopedHeaders() { return { 'X-Tab-Id': 'reused-tab' } },
    clearCommandCompletionCandidateCache() {}, async loadCommandCandidates() {},
    $emit(type, ...args) {
      if (type === 'terminal-submission-start') page.startTerminalSubmission(...args)
      if (type === 'set-active-task' && args[1]) page.activeTaskIds[args[0]] = args[1]
    },
  })
}

test('Running SSE before Terminal POST returns cannot insert an entry notice', async () => {
  let resolve
  const page = fixture(() => new Promise(done => { resolve = done }))
  page.enter()
  const send = sendCommand(() => Promise.resolve({ task_id: task.task_id }), page)
  const request = send()
  page.applyForegroundTaskUpdate('A', task)
  await request
  assert.equal(page.activeTaskIds.A, task.task_id)
  assert.equal(page.foregroundTasks.A.state, 'Running')
  assert.equal(notices(page).length, 0)
  resolve(task)
  await Promise.resolve()
  assert.equal(notices(page).length, 0)
})

test('command_complete before Server Idle never flashes yellow on local task-id removal', async () => {
  const page = fixture(async () => ({ state: 'Idle' }))
  page.enter()
  await Promise.resolve()
  page.applyForegroundTaskUpdate('A', task)
  page.activeTaskIds.A = task.task_id
  delete page.activeTaskIds.A // command_complete clears it before Idle arrives
  page.syncForegroundTaskNotice('A', task)
  assert.equal(notices(page).length, 0)
  page.applyForegroundTaskUpdate('A', { state: 'Idle' })
  assert.equal(notices(page).length, 0)
})

test('pointer/keyboard interaction closes an outstanding initial snapshot gate', async () => {
  let resolve
  const page = fixture(() => new Promise(done => { resolve = done }))
  page.enter()
  page.closePendingTaskNoticeEntry()
  resolve(task)
  await Promise.resolve()
  await Promise.resolve()
  assert.equal(page.foregroundNoticeEntries.A.status, 'closed')
  assert.equal(notices(page).length, 0)
  assert.match(source, /@pointerdown\.capture="closePendingTaskNoticeEntry\(\)"/)
  assert.match(source, /@keydown\.capture="closePendingTaskNoticeEntry\(\)"/)
})

test('Terminal submission retains follow-tail behavior without pending-command string matching', () => {
  const page = fixture()
  page.startTerminalSubmission('A', 'shell sleep 10')
  page.startTerminalSubmission('A', 'view json', false)
  page.startTerminalSubmission('B', 'other client')
  assert.deepEqual(page.scrollCalls, [true])
  assert.doesNotMatch(source, /pendingTerminalSubmissions|finishTerminalSubmission/)
  assert.doesNotMatch(inputSource, /terminal-submission-finish/)
})
