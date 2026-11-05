import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import { test } from 'node:test'

const read = path => readFileSync(new URL(path, import.meta.url), 'utf8')
function component(path, injected = {}) {
  const template = read(path)
  const script = template.match(/<script>([\s\S]*?)<\/script>/)?.[1]
  assert.ok(script)
  const body = script.replace(/^import\s+[\s\S]*?\s+from\s+['"][^'"]+['"]\s*;?\s*$/gm, '')
    .replace('export default {', 'const options = {') + '\nglobalThis.options = options'
  const context = { ...injected }
  vm.runInNewContext(body, context)
  return { template, options: context.options }
}
function makeDialog(options) {
  const instance = Object.assign({}, options.data(), options.methods, { machineId: 'M' })
  Object.defineProperty(instance, 'sessions', { get() { return options.computed.sessions.call(instance) } })
  return instance
}
function deferred() {
  let resolve
  const promise = new Promise(done => { resolve = done })
  return { promise, resolve }
}

// Refresh must not empty an expanded activity list while the new GET is in flight.
test('top Refresh retains Activity details and expanded state, then updates the current row', async () => {
  const next = deferred()
  let detailCalls = 0
  const { template, options } = component('../src/components/MachineConnectionHistoryDialog.vue', {
    getMachineConnectionHistory: async () => ({ sessions: [{ client_id: 'X', command_count: 1 }] }),
    getMachineConnectionCommands: async () => { detailCalls++; return next.promise },
    ElMessage: { error(message) { throw Error(message) } },
  })
  assert.match(template, /:expand-row-keys="expandedSessionIds"/)
  const instance = makeDialog(options)
  instance.history = { sessions: [{
    client_id: 'X', command_count: 1, commands: [{ activity_id: 'prior' }], command_loaded: true,
    command_loading: false, command_next_cursor: 'next', command_has_more: true,
  }] }
  instance.expandedSessionIds = ['X']
  instance.mobileExpandedSessionIds = ['X']
  await instance.loadHistory()
  assert.deepEqual(Array.from(instance.expandedSessionIds), ['X'])
  assert.deepEqual(Array.from(instance.mobileExpandedSessionIds), ['X'])
  assert.equal(instance.sessions[0].commands[0].activity_id, 'prior')
  assert.equal(instance.sessions[0].command_loading, true)
  next.resolve({ items: [{ activity_id: 'fresh' }], has_more: false, next_cursor: '' })
  await new Promise(setImmediate)
  assert.equal(detailCalls, 1)
  assert.equal(instance.sessions[0].commands[0].activity_id, 'fresh')
  assert.equal(instance.sessions[0].command_loading, false)
})

test('an in-flight Activity response follows the new session row across Refresh', async () => {
  const pending = deferred()
  const { options } = component('../src/components/MachineConnectionHistoryDialog.vue', {
    getMachineConnectionHistory: async () => ({ sessions: [{ client_id: 'X', command_count: 1 }] }),
    getMachineConnectionCommands: async () => pending.promise,
    ElMessage: { error(message) { throw Error(message) } },
  })
  const dialog = makeDialog(options)
  dialog.history = { sessions: [{ client_id: 'X', command_count: 1, commands: [], command_loaded: false, command_loading: false }] }
  const inflight = dialog.loadSessionCommands(dialog.sessions[0])
  await dialog.loadHistory()
  pending.resolve({ items: [{ activity_id: 'still-present' }], next_cursor: '', has_more: false })
  await inflight
  assert.equal(dialog.sessions[0].commands[0].activity_id, 'still-present')
  assert.equal(dialog.sessions[0].command_loading, false)
})

test('termination uses original reason text and includes details only when present', () => {
  const { options, template } = component('../src/components/MachineConnectionHistoryDialog.vue')
  const instance = makeDialog(options)
  assert.equal(instance.formatEndReason('server_requested_disconnect'), 'Server requested disconnect')
  assert.equal(instance.terminationDetailText({ termination_detail: {} }), '')
  assert.equal(instance.terminationDetailText({ termination_detail: { command: 'httpctl kill' } }), 'Command: httpctl kill')
  assert.match(template, /<span v-if="terminationDetailText\(scope.row\)"> \(/)
  assert.doesNotMatch(template, /Server interrupted/)
})

test('Connection History fetches only 20 sessions at a time and 10 activities per detail page', async () => {
  const calls = []
  const { template, options } = component('../src/components/MachineConnectionHistoryDialog.vue', {
    getMachineConnectionHistory: async (machine, params) => {
      calls.push(['history', machine, params.limit, params.offset])
      const start = params.offset
      const length = start === 40 ? 5 : 20
      return { sessions: Array.from({ length }, (_, i) => ({client_id: `client-${start + i}`, command_count: 30})), has_more: start < 40 }
    },
    getMachineConnectionCommands: async (machine, client, params) => {
      calls.push(['activities', machine, client, params.limit, params.cursor])
      return { items: [{activity_id: params.cursor || 'initial'}], has_more: !params.cursor, next_cursor: params.cursor ? '' : 'second' }
    },
    ElMessage: { error(message) { throw Error(message) } },
  })
  assert.match(template, /@click="loadMoreHistory"/)
  assert.match(template, /@click="loadHistory\(\)"/)
  const dialog = makeDialog(options)
  await dialog.loadHistory()
  assert.equal(dialog.sessions.length, 20)
  assert.equal(dialog.history.has_more, true)
  await dialog.loadMoreHistory()
  assert.equal(dialog.sessions.length, 40)
  await dialog.loadMoreHistory()
  assert.equal(dialog.sessions.length, 45)
  assert.equal(dialog.history.has_more, false)
  assert.deepEqual(calls.slice(0, 3), [
    ['history', 'M', 20, 0],
    ['history', 'M', 20, 20],
    ['history', 'M', 20, 40],
  ])
  await dialog.loadSessionCommands(dialog.sessions[0])
  await dialog.loadSessionCommands(dialog.sessions[0], true)
  assert.deepEqual(calls.slice(3), [
    ['activities', 'M', 'client-0', 10, ''],
    ['activities', 'M', 'client-0', 10, 'second'],
  ])
  assert.equal(dialog.sessions[0].commands.length, 2)
})
