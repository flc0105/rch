import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import vm from 'node:vm'

import { getCommandExecutionEntry } from '../src/api/commandHistoryApi.js'
import { activityOutputRecords } from '../src/utils/activityOutput.js'

const readComponent = name => readFileSync(new URL(`../src/components/${name}.vue`, import.meta.url), 'utf8')
const history = readComponent('CommandHistoryDialog')
const detail = readComponent('CommandExecutionDetailDialog')

function detailDialog() {
  const methods = history.match(/^    async openCommandExecutionDetail\(row\) \{[\s\S]+?^    },/m)[0]
  const close = history.match(/^    commandExecutionDetailDialogVisible\(value\) \{[\s\S]+?^    },/m)[0]
  const errors = []
  const timers = new Map()
  const scope = vm.runInNewContext(`({${methods}${close}})`, {
    getCommandExecutionEntry,
    AbortController,
    setTimeout(callback, delay) {
      const id = Symbol()
      timers.set(id, { callback, delay })
      return id
    },
    clearTimeout(id) { timers.delete(id) },
    ElMessage: { error: message => errors.push(message) },
  })
  const state = {
    openCommandExecutionDetail: scope.openCommandExecutionDetail,
    commandExecutionDetailRequest: null,
    getSelectedHistoryMachineId: () => 'm',
  }
  return { state, timers, errors, close: scope.commandExecutionDetailDialogVisible }
}

function waitForAbort(signal) {
  return new Promise((_, reject) => {
    signal.addEventListener('abort', () => reject(signal.reason), { once: true })
  })
}

test('a stalled Activity detail GET exits loading with a timeout', async t => {
  let signal
  t.mock.method(globalThis, 'fetch', (_, options) => {
    signal = options.signal
    return waitForAbort(signal)
  })
  const { state, timers, errors } = detailDialog()
  const loading = state.openCommandExecutionDetail({ activity_id: 'a' })
  assert.equal(state.commandExecutionDetailLoading, true)
  const [deadline] = timers.values()
  assert.equal(deadline.delay, 15000)
  deadline.callback()
  await loading
  assert.equal(signal.aborted, true)
  assert.equal(state.commandExecutionDetailLoading, false)
  assert.equal(state.commandExecutionDetailDialogVisible, false)
  assert.equal(timers.size, 0)
  assert.deepEqual(errors, ['Activity Detail request timed out'])
})

test('opening another detail aborts the old request and keeps the new result', async t => {
  const signals = []
  const entry = { activity_id: 'b', result: [] }
  t.mock.method(globalThis, 'fetch', (url, { signal }) => {
    signals.push(signal)
    return url.endsWith('/a')
      ? waitForAbort(signal)
      : Promise.resolve({ ok: true, json: async () => ({ data: entry }) })
  })
  const { state, timers, errors } = detailDialog()
  const old = state.openCommandExecutionDetail({ activity_id: 'a' })
  const current = state.openCommandExecutionDetail({ activity_id: 'b' })
  await Promise.all([old, current])
  assert.equal(signals[0].aborted, true)
  assert.equal(state.selectedCommandExecutionEntry, entry)
  assert.equal(state.commandExecutionDetailLoading, false)
  assert.equal(state.commandExecutionDetailDialogVisible, true)
  assert.equal(timers.size, 0)
  assert.deepEqual(errors, [])
})

test('closing the detail aborts a pending request without showing an error', async t => {
  let signal
  t.mock.method(globalThis, 'fetch', (_, options) => {
    signal = options.signal
    return waitForAbort(signal)
  })
  const { state, timers, errors, close } = detailDialog()
  const loading = state.openCommandExecutionDetail({ activity_id: 'a' })
  state.commandExecutionDetailDialogVisible = false
  close.call(state, false)
  await loading
  assert.equal(signal.aborted, true)
  assert.equal(state.commandExecutionDetailLoading, false)
  assert.equal(timers.size, 0)
  assert.deepEqual(errors, [])
})

test('a timeout while reading the HTTP body remains a timeout', async t => {
  let notifyBodyRead
  const bodyRead = new Promise(resolve => { notifyBodyRead = resolve })
  t.mock.method(globalThis, 'fetch', async (_, { signal }) => ({
    ok: true,
    json() {
      notifyBodyRead()
      return waitForAbort(signal)
    },
  }))
  const { state, timers, errors } = detailDialog()
  const loading = state.openCommandExecutionDetail({ activity_id: 'a' })
  await bodyRead
  timers.values().next().value.callback()
  await loading
  assert.equal(state.commandExecutionDetailLoading, false)
  assert.deepEqual(errors, ['Activity Detail request timed out'])
})

test('first page projects only 64 visible records and one lookahead, with no full JSON preview', () => {
  const preview = detail.match(/^    resultPreview\(\) \{[\s\S]+?^    },/m)[0]
  const page = detail.match(/^    outputPage\(\) \{[\s\S]+?^    },/m)[0]
  const computed = vm.runInNewContext(`({${preview}${page}})`, { activityOutputRecords })
  const recordedAt = Array.from({ length: 10000 }, (_, i) => `recorded-${i}`)
  const packet = { event_type: 'chunk', message: 'output' }
  const result = Array.from({ length: 10000 }, () => packet)
  result[9999] = { event_type: 'started' }
  let visits = 0
  const guarded = new Proxy(result, {
    get(target, key, receiver) {
      if (/^\d+$/.test(String(key))) visits += 1
      return Reflect.get(target, key, receiver)
    },
  })
  const state = { entry: { result: guarded, recorded_at: recordedAt }, outputSortOrder: 'desc', outputRecordLimit: 64 }
  assert.match(computed.resultPreview.call(state), /^\[\{"event_type":"chunk"/)
  assert.equal(visits, 1)
  const first = computed.outputPage.call(state)
  assert.equal(first.records.length, 64)
  assert.equal(first.hasMore, true)
  assert.equal(first.records[0].created_at, recordedAt[9998])
  assert.equal(visits, 67)
})
