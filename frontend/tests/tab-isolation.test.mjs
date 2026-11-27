import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { claimTabIdentity } from '../src/utils/tabIdentity.js'
import { TERMINAL_HISTORY } from '../src/data/terminalHistoryConfig.js'
import { trimTerminalWindow } from '../src/utils/terminalHistoryStore.js'

function globalValue(t, key, value) {
  const previous = Object.getOwnPropertyDescriptor(globalThis, key)
  Object.defineProperty(globalThis, key, { configurable: true, writable: true, value })
  t.after(() => previous ? Object.defineProperty(globalThis, key, previous) : delete globalThis[key])
}

test('copied storage never shares a live tab claim, reload reclaims its own scope', async t => {
  const active = new Set()
  const storage = new Map([['rat_web_tab_id', 'original']])
  let navigation = 'reload'
  globalValue(t, 'performance', { getEntriesByType: () => [{ type: navigation }] })
  globalValue(t, 'sessionStorage', { getItem: k => storage.get(k), setItem: (k, v) => storage.set(k, v) })
  globalValue(t, 'navigator', { locks: { async request(name, _options, cb) {
    if (active.has(name)) return cb(null)
    active.add(name)
    try { await cb({ name }) } finally { active.delete(name) }
  } } })
  const a = await claimTabIdentity()
  assert.equal(a.id, 'original')
  const b = await claimTabIdentity()
  assert.notEqual(b.id, a.id)
  storage.set('rat_web_tab_id', 'original')
  navigation = 'navigate'
  const c = await claimTabIdentity()
  assert.notEqual(c.id, a.id)
  a.release(); b.release(); c.release()
  await Promise.resolve()
  navigation = 'reload'
  storage.set('rat_web_tab_id', 'original')
  const again = await claimTabIdentity()
  assert.equal(again.id, 'original')
  again.release()
})

const source = readFileSync(new URL('../src/composables/useTerminalOutput.js', import.meta.url), 'utf8')
// Load the original methods without the UI package imports.
const module = new Function('TERMINAL_HISTORY', 'trimTerminalWindow', source.replace(/^import[\s\S]*?from ['"][^'"]+['"];?\s*$/gm, '').replace('export default', 'return'))(TERMINAL_HISTORY, trimTerminalWindow)
function page() {
  const p = { ...module.data(), ...module.methods, selectedId: 'client', $refs: {}, scrollToBottom() {} }
  p.ensureOutputBucket('client')
  let seq = 0
  p._terminalHistory = { append: (_, lines) => lines.forEach(line => { line.__terminalSeq = seq++ }) }
  return p
}

test('background stream renders without animation frames and return-to-visible flushes once', async t => {
  const document = { hidden: false }
  globalValue(t, 'document', document)
  globalValue(t, 'requestAnimationFrame', () => { throw new Error('frame not available') })
  const p = page()
  p.commitTerminalLines('client', [{ text: 'probe 1' }], true)
  assert.equal(p.outputs.client.length, 0)
  document.hidden = true
  p.commitTerminalLines('client', [{ text: 'probe 2' }], true)
  assert.deepEqual(p.outputs.client.map(x => x.text), ['probe 1', 'probe 2'])
  document.hidden = false
  p.commitTerminalLines('client', [{ text: 'probe 3' }], true)
  p.flushTerminalRenderQueues()
  await new Promise(resolve => setTimeout(resolve, 35))
  assert.deepEqual(p.outputs.client.map(x => x.text), ['probe 1', 'probe 2', 'probe 3'])
})

test('restoring the tail while a live event arrives neither drops nor repeats it', async t => {
  globalValue(t, 'document', { hidden: false })
  const p = page()
  let finishRead
  p._terminalHistory.readBefore = () => new Promise(resolve => { finishRead = resolve })
  p.commitTerminalLines('client', [{ text: 'probe 1' }], true)
  const loading = p.restoreTerminalViewport('client')
  p.commitTerminalLines('client', [{ text: 'probe 2' }], true)
  finishRead([{ text: 'probe 1', __terminalSeq: 0 }])
  await loading
  assert.deepEqual(p.outputs.client.map(x => x.text), ['probe 1', 'probe 2'])
  assert.equal(p._terminalRenderQueues.client, undefined)
})

test('Idle of another task does not retire a running independent task; live completion wins recovery race', async t => {
  const { default: state } = await import('../src/composables/useTaskState.js')
  await import('../src/api/commandHistoryApi.js')
  let finishRead, requestStarted
  globalValue(t, 'fetch', () => new Promise(resolve => { finishRead = resolve; requestStarted() }))
  const p = { ...state.data(), ...state.methods, connections: [{ client_id: 'client', machine_id: 'machine' }],
    appended: [], appendOutput(...args) { this.appended.push(args) } }
  p.setActiveTask('client', 'config', '', 'activity')
  let started = new Promise(resolve => { requestStarted = resolve })
  let recovering = p.recoverFinishedTask('client', 'config', '', false)
  await started
  finishRead({ ok: true, json: async () => ({ code: 0, data: { activity_id: 'activity', client_id: 'client', result: [], finished_at: '' } }) })
  await recovering
  assert.equal(p.activeTaskIds.client, 'config')
  started = new Promise(resolve => { requestStarted = resolve })
  recovering = p.recoverFinishedTask('client', 'config', '', false)
  await started
  p.markTaskCompleted('client', 'config')
  finishRead({ ok: true, json: async () => ({ code: 0, data: { activity_id: 'activity', client_id: 'client', result: [], finished_at: 'now', status: 'success' } }) })
  await recovering
  assert.deepEqual(p.appended, [])
})

test('cancel request marker is emitted before a fast completion and retains the originating client', async () => {
  const input = readFileSync(new URL('../src/components/CommandInputBar.vue', import.meta.url), 'utf8')
  const body = input.slice(input.indexOf('    async cancelCurrentTask() {'), input.indexOf('    async queryCommandCandidates(')).trim().replace(/,$/, '')
  let finish
  const calls = []
  const methods = new Function('cancelTask', 'ElMessage', 'formatTerminalCancelRequestedLine', `return { ${body} }`)(
    id => { calls.push(['post', id]); return new Promise(resolve => { finish = resolve }) },
    { success() {}, error() {}, warning() {} }, id => `[Cancel requested] task=${id}`)
  const vm = { selectedId: 'a', currentActiveTaskId: 'task', $emit: (...args) => calls.push(args) }
  const pending = methods.cancelCurrentTask.call(vm)
  assert.deepEqual(calls.map(x => x[0]), ['append-output', 'post'])
  assert.equal(calls[0][1], 'a')
  vm.selectedId = 'b'
  finish(); await pending
  assert.equal(calls.length, 2)
})
