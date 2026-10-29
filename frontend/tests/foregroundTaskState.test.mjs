import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { normalizeForegroundTask, shouldShowTaskNotice, formatTaskTime } from '../src/utils/foregroundTask.js'
import { resolveConnectionContextValue, CONNECTION_CONTEXT_FIELD_CATALOG } from '../src/data/connectionContextFields.js'

test('task state normalizes Idle, Running, Cancelling for refresh', () => {
  assert.deepEqual(normalizeForegroundTask(null), { state: 'Idle' })
  assert.deepEqual(normalizeForegroundTask({ state: 'weird' }), { state: 'Idle' })
  assert.equal(normalizeForegroundTask({ state: 'Running', task_id: 'abc' }).task_id, 'abc')
  assert.equal(normalizeForegroundTask({ state: 'Cancelling' }).state, 'Cancelling')
})

test('other tab and refreshed tab show task notice; own active tab does not', () => {
  const running = { state: 'Running', task_id: 'abc' }
  assert.equal(shouldShowTaskNotice(running, ''), true)
  assert.equal(shouldShowTaskNotice(running, 'different'), true)
  assert.equal(shouldShowTaskNotice(running, 'abc'), false)
  assert.equal(shouldShowTaskNotice({ state: 'Idle' }, ''), false)
})

test('Task is a Connection Context option with the same status', () => {
  assert.ok(CONNECTION_CONTEXT_FIELD_CATALOG.some(field => field.id === 'task' && field.label === 'Task'))
  assert.equal(resolveConnectionContextValue('task', { foreground_task: { state: 'Running' } }), 'Running')
  assert.equal(resolveConnectionContextValue('task', {}), 'Idle')
})

test('elapsed time uses UTC timestamp and is refreshable', () => {
  assert.equal(formatTaskTime('2026-10-28T00:00:00Z', Date.parse('2026-10-28T00:01:01Z')), '1m 1s')
  assert.equal(formatTaskTime('invalid'), '-')
})

test('App retains task details and uses SSE rather than task polling', () => {
  const source = readFileSync(new URL('../src/App.vue', import.meta.url), 'utf8')
  const basicInfo = readFileSync(new URL('../src/components/ConnectionInfoDialogs.vue', import.meta.url), 'utf8')
  assert.ok(basicInfo.includes("label: 'Task'"))
  const sse = readFileSync(new URL('../src/composables/useSseStream.js', import.meta.url), 'utf8')
  assert.ok(sse.includes("es.addEventListener('foreground_task_changed'"))
  assert.ok(sse.includes('this.applyForegroundTaskUpdate?.(payload.client_id, payload.task)'))
  assert.ok(sse.includes('this.refreshForegroundTask?.()'))
  assert.ok(!source.includes('foregroundTaskTimer'))
  assert.match(source, /this\.statusTickTimer = setInterval\(\(\) => \{[\s\S]*?this\.statusNowTick = now[\s\S]*?\}, 2000\)/)
  assert.doesNotMatch(source, /setInterval\(\(\) => \{\s*void this\.refreshForegroundTask\(\)/)
  for (const token of ['Client is running a task' , 'Task Details', 'cancelForegroundTask',
                       'this.refreshForegroundTask()', 'applyForegroundTaskUpdate', 'currentForegroundTask']) {
    assert.ok(source.includes(token), token)
  }
})


test('task notice uses existing Terminal warning line and inline Details, never adds a toolbar banner', () => {
  const app = readFileSync(new URL('../src/App.vue', import.meta.url), 'utf8')
  const terminal = readFileSync(new URL('../src/components/TerminalOutput.vue', import.meta.url), 'utf8')
  assert.doesNotMatch(app, /class="task-running-notice"/)
  assert.doesNotMatch(app, /\.task-running-notice\s*\{/)
  assert.match(app, /this\.appendOutput\(clientId,[\s\S]*?foregroundTaskNotice: true/)
  assert.match(app, /this\.outputs\[clientId\] = lines\.filter\(line => line\?\.meta\?\.foregroundTaskNotice !== true\)/)
  assert.match(app, /@open-task-details="openForegroundTaskDetails"/)
  assert.match(terminal, /entry\.line\?\.meta\?\.foregroundTaskNotice/)
  assert.match(terminal, /\$emit\('open-task-details'\)/)
  assert.match(terminal, /\[ Details \]/)
})
