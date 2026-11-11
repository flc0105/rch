import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import { fixture, notices, task } from './foregroundTaskNoticeFixture.mjs'
import { TERMINAL_HISTORY } from '../src/data/terminalHistoryConfig.js'
import { trimTerminalWindow } from '../src/utils/terminalHistoryStore.js'

// Exercise the production Terminal composable, not a hand-written history model.
const source = readFileSync(new URL('../src/composables/useTerminalOutput.js', import.meta.url), 'utf8')
class MemoryHistoryStore {
  constructor() { this.rows = new Map() }
  async database() {}
  append(id, rows) { this.rows.set(id, [...(this.rows.get(id) || []), ...rows.map(line => ({ ...line }))]) }
  async readBefore(id) { return [...(this.rows.get(id) || [])] }
  async readAll(id) { return [...(this.rows.get(id) || [])] }
  async readAfter(id) { return [...(this.rows.get(id) || [])] }
}
const sandbox = {
  TerminalHistoryStore: MemoryHistoryStore, TERMINAL_HISTORY, trimTerminalWindow,
  ElMessage: { error() {} }, console,
}
vm.runInNewContext(source.replace(/^import\s+[\s\S]*?\s+from\s+['"][^'"]+['"]\s*;?\s*$/gm, '')
  .replace('export default {', 'globalThis.component = {'), sandbox)
const terminal = sandbox.component

function mountHistory(page) {
  page.currentAuthUsername = 'tester'
  page.terminalViewStates = { A: { follow: true, loading: false, hasOlder: false, hasNewer: false } }
  page.$nextTick = async () => {}
  page.$refs = { terminalOutputRef: null }
  for (const [name, method] of Object.entries(terminal.methods)) {
    if (['initializeTerminalHistory', 'restoreTerminalViewport', 'loadTerminalHistory', 'getCompleteTerminalHistory'].includes(name)) {
      page[name] = method.bind(page)
    }
  }
  Object.defineProperty(page, 'currentOutputLines', {
    get() { return terminal.computed.currentOutputLines.call(page) },
  })
  return page
}

async function enterWithNotice() {
  const page = mountHistory(fixture(async () => task))
  page.enter()
  await Promise.resolve()
  await Promise.resolve()
  assert.equal(notices(page).length, 1, 'initial entry adds one transient warning')
  return page
}

function visibleNotices(page) {
  return page.currentOutputLines.filter(line => line.meta?.foregroundTaskNotice)
}

test('initial warning must not enter persistent history or render twice during initialization', async () => {
  const page = await enterWithNotice()
  await page.initializeTerminalHistory()
  assert.equal(page._terminalHistory.rows.get('A')?.filter(line => line.meta?.foregroundTaskNotice).length || 0, 0)
  assert.equal(visibleNotices(page).length, 1, 'same admitted warning renders only once')
})

test('after Idle, legacy persisted notice never reappears on history restore or export', async () => {
  const page = await enterWithNotice()
  await page.initializeTerminalHistory()
  page.applyForegroundTaskUpdate('A', { state: 'Idle' })
  await page.restoreTerminalViewport('A')
  assert.equal(visibleNotices(page).length, 0)
  assert.equal((await page.getCompleteTerminalHistory('A')).filter(line => line.meta?.foregroundTaskNotice).length, 0)
})

test('legacy history notice plus live notice must not create two visible rows', async () => {
  const page = await enterWithNotice()
  await page.initializeTerminalHistory()
  const legacy = { text: '[!] Client is running a task.', kind: 'warning', meta: { foregroundTaskNotice: true } }
  page._terminalHistory.rows.set('A', [legacy, { text: 'real output', kind: 'default', meta: {} }])
  await page.restoreTerminalViewport('A')
  assert.equal(visibleNotices(page).length, 1)
  assert.equal(page.currentOutputLines.some(line => line.text === 'real output'), true)
})

test('active transient warning is excluded from full history export', async () => {
  const page = await enterWithNotice()
  await page.initializeTerminalHistory()
  assert.equal((await page.getCompleteTerminalHistory('A')).filter(line => line.meta?.foregroundTaskNotice).length, 0)
  assert.equal(visibleNotices(page).length, 1, 'notice remains visible in UI')
})

test('loading older history filters persisted task notices without losing ordinary rows', async () => {
  const page = await enterWithNotice()
  await page.initializeTerminalHistory()
  page.outputs.A = [{ text: 'recent output', kind: 'info', __terminalSeq: 30, meta: {} }]
  page._terminalHistory.rows.set('A', [
    { text: 'older output', kind: 'info', __terminalSeq: 10, meta: {} },
    { text: '[!] Client is running a task.', kind: 'warning', __terminalSeq: 11, meta: { foregroundTaskNotice: true } },
  ])
  page.terminalViewStates.A.hasOlder = true
  await page.loadTerminalHistory('older')
  assert.equal(visibleNotices(page).length, 1)
  assert.deepEqual(Array.from(page.currentOutputLines.filter(line => line.__terminalSeq !== undefined), line => line.text),
    ['older output', 'recent output'])
})

test('appendOutput cannot put a foreground notice into ordinary output rows', () => {
  const host = { ...terminal.data(), selectedId: 'A' }
  for (const name of ['ensureOutputBucket', 'appendOutput', 'setTerminalNotice',
    'getTerminalNotice', 'buildTerminalOutputLine']) host[name] = terminal.methods[name].bind(host)
  host.isTerminalJsonText = () => false
  host.isTerminalJsonStartLine = () => false
  host.inferLineKind = () => 'warning'
  host.commitTerminalLines = () => { throw new Error('a transient notice entered durable history') }
  host.appendOutput('A', '[!] Client is running a task.', 'warning', { foregroundTaskNotice: true })
  assert.equal(host.outputs.A.length, 0)
  assert.equal(host.getTerminalNotice('A', 'foreground').text, '[!] Client is running a task.')
  assert.equal(terminal.computed.currentOutputLines.call(host).length, 1)
})

test('cancelled command followed by another sleep does not resurrect old notices', async () => {
  const page = await enterWithNotice()
  await page.initializeTerminalHistory()
  page.applyForegroundTaskUpdate('A', { ...task, state: 'Cancelling' })
  page.applyForegroundTaskUpdate('A', { state: 'Idle' })
  page.startTerminalSubmission('A', 'sleep 20')
  page.applyForegroundTaskUpdate('A', { ...task, task_id: 'another-task', command: 'sleep 20' })
  await page.restoreTerminalViewport('A')
  assert.equal(visibleNotices(page).length, 0)
  assert.equal(page.foregroundTasks.A.state, 'Running', 'Busy state still updates normally')
})
