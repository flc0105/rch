import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import { test } from 'node:test'

function loadVueOptions(path, globals = {}) {
  const source = readFileSync(new URL(path, import.meta.url), 'utf8')
  const script = source.match(/<script>([\s\S]*?)<\/script>/)?.[1]
  assert.ok(script, `${path} must contain a script block`)
  const code = script.split('\n').filter(line => !/^import /.test(line)).join('\n')
    .replace('export default {', 'const component = {') + '\nglobalThis.component = component'
  const context = { ...globals }
  vm.runInNewContext(code, context, { timeout: 1000 })
  return { options: context.component, source }
}

async function settle() {
  await new Promise(resolve => setImmediate(resolve))
}

test('Process Manager: close releases current monitor, direct reopen and Dashboard navigation both work', async () => {
  const requests = []
  const sorts = []
  let opened = 0
  const fetch = async (url, options) => {
    requests.push({ url, options })
    if (url.endsWith('/device-monitor/open')) {
      return { ok: true, json: async () => ({ code: 0, data: { monitor_session_id: `session-${++opened}` } }) }
    }
    if (url.endsWith('/close')) return { ok: true, json: async () => ({ code: 0 }) }
    throw new Error(`Unexpected API call: ${url}`)
  }
  const processComponent = loadVueOptions('../src/components/ProcessDialogs.vue', {
    fetch,
    ElMessage: { warning(message) { throw new Error(message) }, error(message) { throw new Error(message) } },
    ElMessageBox: {}, Document: {}, sortProcessRows() { return [] },
  })
  assert.match(processComponent.source, /@closed="handleProcessDialogClosed"/)
  const dialog = {
    ...processComponent.options.data(), ...processComponent.options.methods,
    selectedId: 'client-1', tabId: 'tab-1',
    $refs: { processTable: { sort(prop, order) { sorts.push([prop, order]) } } },
    $nextTick(callback) { return Promise.resolve().then(callback) },
  }

  // Open Process Manager normally, then close it via Element Plus' @closed event.
  dialog.open()
  await settle()
  assert.equal(dialog.processDialogVisible, true)
  assert.equal(dialog.processMonitorSessionId, 'session-1')
  dialog.processDialogVisible = false
  assert.doesNotThrow(() => dialog.handleProcessDialogClosed())
  await settle()
  assert.equal(dialog.processMonitorSessionId, '')
  assert.equal(requests.filter(req => req.url.endsWith('/close')).length, 1)

  // The ordinary Process Manager entry must still work after the first close.
  dialog.open()
  await settle()
  assert.equal(dialog.processMonitorSessionId, 'session-2')
  dialog.processDialogVisible = false
  dialog.handleProcessDialogClosed()
  await settle()
  assert.equal(requests.filter(req => req.url.endsWith('/close')).length, 2)

  // The Dashboard sends navigation only after its own dialog has closed.
  const infoComponent = loadVueOptions('../src/components/ConnectionInfoDialogs.vue', {
    ElMessage: {}, WatchdogInfoPanel: {}, formatBytesHuman() {}, formatDateTimeStandardValue() {},
  })
  assert.match(infoComponent.source, /@closed="handleInfoDialogClosed"/)
  const info = {
    ...infoComponent.options.data(), ...infoComponent.options.methods,
    infoVisible: true,
    $emit(event, sort) {
      assert.equal(event, 'open-processes')
      dialog.open(sort)
    },
  }
  info.openProcessesFromDashboard('memory_percent')
  assert.equal(info.infoVisible, false)
  assert.equal(dialog.processDialogVisible, false)
  info.handleInfoDialogClosed()
  await settle()
  assert.equal(dialog.processDialogVisible, true)
  assert.equal(dialog.processMonitorSessionId, 'session-3')
  assert.equal(dialog.processSort.prop, 'memory_percent')
  assert.equal(dialog.processSort.order, 'descending')
  assert.deepEqual(sorts.at(-1), ['memory_percent', 'descending'])
  const closes = requests.filter(req => req.url.endsWith('/close'))
  assert.equal(closes[0].options.headers['X-Tab-Id'], 'tab-1')

  // Repeated Dashboard navigation, this time CPU, still opens a fresh session.
  dialog.processDialogVisible = false
  dialog.handleProcessDialogClosed()
  await settle()
  info.infoVisible = true
  info.openProcessesFromDashboard('cpu_percent')
  info.handleInfoDialogClosed()
  await settle()
  assert.equal(dialog.processMonitorSessionId, 'session-4')
  assert.equal(dialog.processSort.prop, 'cpu_percent')
  assert.deepEqual(sorts.at(-1), ['cpu_percent', 'descending'])
})

test('stale @closed event must not terminate an already reopened Process Manager', async () => {
  const closed = []
  const { options } = loadVueOptions('../src/components/ProcessDialogs.vue', {
    fetch: async url => { closed.push(url); return { ok: true } },
    ElMessage: {}, ElMessageBox: {}, Document: {}, sortProcessRows() { return [] },
  })
  const dialog = { ...options.data(), ...options.methods, processDialogVisible: true }
  dialog.processMonitorSessionId = 'new-session'
  dialog.handleProcessDialogClosed()
  await settle()
  assert.equal(dialog.processMonitorSessionId, 'new-session')
  assert.equal(closed.length, 0)
})
