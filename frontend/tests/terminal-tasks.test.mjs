import assert from 'node:assert/strict'
import test from 'node:test'

import { createTerminalTaskCapture } from '../src/composables/terminalTaskCapture.js'
import taskState from '../src/composables/useTaskState.js'
import { createTerminalOperation, getTerminalReplayAction, operationHeaders } from '../src/utils/terminalOperation.js'

test('same-text operations keep separate identities and a script retains typed replay', () => {
  const input = {
    kind: 'script',
    action: 'run',
    clientId: 'client',
    replay: { type: 'script', script_name: 'check', params: { limit: 3 } },
  }
  const first = createTerminalOperation(input)
  const second = createTerminalOperation(input)
  assert.notEqual(first.operation_id, second.operation_id)
  assert.equal(operationHeaders(first)['X-RCH-Operation-ID'], first.operation_id)
  assert.deepEqual(getTerminalReplayAction(first), {
    type: 'script', script_name: 'check', script_path: '', script_display_name: '', params: { limit: 3 },
  })
  assert.equal(getTerminalReplayAction(createTerminalOperation({
    kind: 'transfer', action: 'upload_files', clientId: 'client',
  })), null)
})

test('results before the submit response route by client and operation, never command text', () => {
  const captures = createTerminalTaskCapture()
  const firstOutput = []
  const secondOutput = []
  const first = captures.begin({ clientId: 'client', operationId: 'first', suppress: true,
    onResult: event => firstOutput.push(event.text) })
  const second = captures.begin({ clientId: 'client', operationId: 'second', suppress: true,
    onResult: event => secondOutput.push(event.text) })
  const event = (operationId, taskId, text, clientId = 'client') => ({
    command: 'same command', text, task_id: taskId, client_id: clientId,
    metadata: { operation_id: operationId },
  })
  assert.equal(captures.route('result', event('first', 'task-1', 'foreign', 'other')), false)
  assert.equal(captures.route('result', event('second', 'task-2', 'two')), true)
  assert.equal(captures.route('result', event('first', 'task-1', 'one')), true)
  assert.equal(captures.route('complete', event('first', 'task-1', 'finished')), true)
  assert.equal(first.bind('task-1'), true)
  assert.equal(second.bind('task-2'), true)
  assert.equal(captures.route('result', event('first', 'task-1', 'late')), false)
  assert.deepEqual(firstOutput, ['one'])
  assert.deepEqual(secondOutput, ['two'])
})

test('late submit or completion from a finished task cannot release the current task', () => {
  const page = { ...taskState.data(), ...taskState.methods }
  page.setActiveTask('client', 'old')
  page.markTaskCompleted('client', 'old')
  assert.equal(page.activeTaskIds.client, undefined)
  page.setActiveTask('client', 'new')
  page.setActiveTask('client', 'old')
  page.markTaskCompleted('client', 'old')
  assert.equal(page.activeTaskIds.client, 'new')
  page.markTaskCompleted('client', 'new')
  assert.equal(page.activeTaskIds.client, undefined)
})


test('Activity output matches Server timestamps by the original Result index', async () => {
  const { activityOutputRecords } = await import('../src/utils/activityOutput.js')
  const result = [
    { type: 'result', id: 1, event_type: 'progress', level: 'warning', message: 'Waiting' },
    { type: 'result', id: 1, event_type: 'chunk' },
    { type: 'result', id: 1, event_type: 'chunk', data: { value: 7 } },
    { type: 'result', id: 1, event_type: 'completed', status: 'success', message: 'Done' },
  ]
  const recordedAt = result.map((_, index) => `2026-11-20T12:00:0${index}+00:00`)
  assert.deepEqual(activityOutputRecords(result, { recordedAt }), [
    { seq: 1, status: 1, text: '[!] Waiting', created_at: recordedAt[0] },
    { seq: 3, status: 1, text: '{"value":7}', created_at: recordedAt[2] },
    { seq: 4, status: 1, text: 'Done', created_at: recordedAt[3] },
  ])
  assert.equal(activityOutputRecords(result, { terminal: true })[1].text, '{\n  "value": 7\n}')
})
