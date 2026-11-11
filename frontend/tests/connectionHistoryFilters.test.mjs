import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import vm from 'node:vm'

const source = readFileSync(new URL('../src/components/MachineConnectionHistoryDialog.vue', import.meta.url), 'utf8')
const script = source.match(/<script>([\s\S]*?)<\/script>/)?.[1]

function makeDialog(fetchHistory, timers = {}) {
  const sandbox = {
    formatLaunchMode: mode => ({ ide: 'IDE', terminal: 'Terminal', unknown: 'Unknown' }[mode] || mode),
    diffDateTimeMs: () => 0, formatDateTimeStandard: () => '',
    ElMessage: { error(message) { throw Error(message) } },
    getMachineConnectionCommands: async () => ({}), getMachineConnectionHistory: fetchHistory,
    setTimeout: timers.setTimeout || setTimeout, clearTimeout: timers.clearTimeout || clearTimeout,
  }
  vm.runInNewContext(script.replace(/^import\s+.*$/gm, '').replace('export default {', 'globalThis.component = {'), sandbox)
  const def = sandbox.component
  const dialog = Object.assign({}, def.data(), def.methods, { machineId: 'M' })
  for (const [name, fn] of Object.entries(def.computed)) {
    Object.defineProperty(dialog, name, { get: () => fn.call(dialog) })
  }
  return dialog
}
function deferred() {
  let resolve
  const promise = new Promise(done => { resolve = done })
  return { promise, resolve }
}

test('filter is server-side; two matching rows do not show the unfiltered Load More', async () => {
  const calls = []
  const dialog = makeDialog(async (machine, query) => {
    calls.push({ machine, ...query })
    if (query.integrity) return {
      sessions: [{ client_id: 'A' }, { client_id: 'B' }], has_more: false,
      connection_count: 103,
      filter_options: {
        integrity: ['high', 'medium', 'unknown'], launch_mode: ['ide', 'terminal'],
        termination_reason: ['client_exit', 'timeout', 'unknown'],
      },
    }
    return {
      sessions: Array.from({ length: 20 }, (_, i) => ({ client_id: String(i) })),
      has_more: true, connection_count: 103,
      filter_options: { integrity: ['high', 'medium', 'unknown'], launch_mode: ['ide', 'terminal'], termination_reason: ['client_exit'] },
    }
  })
  await dialog.loadHistory()
  assert.equal(dialog.canLoadMoreHistory, true)
  assert.deepEqual(Array.from(dialog.integrityOptions, item => item.value), ['high', 'medium', 'unknown'])
  assert.deepEqual(Array.from(dialog.launchModeOptions, item => item.label), ['IDE', 'Terminal'])
  dialog.filters.integrity = 'high'
  dialog.filters.launchMode = 'ide'
  dialog.filters.termination = 'client_exit'
  await dialog.onFilterChange()
  assert.equal(dialog.activeFilterCount, 3)
  assert.deepEqual(Array.from(dialog.sessions, item => item.client_id), ['A', 'B'])
  assert.equal(dialog.canLoadMoreHistory, false)
  assert.equal(dialog.history.connection_count, 103)
  await dialog.loadMoreHistory()
  assert.equal(calls.length, 2)
  assert.equal(calls[1].offset, 0)
  assert.equal(calls[1].integrity, 'high')
  assert.equal(calls[1].launchMode, 'ide')
  assert.equal(calls[1].termination, 'client_exit')
  assert.match(source, /:data="sessions"/)
  assert.match(source, /v-for="\(row, index\) in sessions"/)
  assert.match(source, /v-if="canLoadMoreHistory" class="machine-history-table-load-more"/)
  await dialog.clearFilters()
  assert.equal(dialog.activeFilterCount, 0)
  assert.equal(dialog.sessions.length, 20)
  assert.equal(dialog.canLoadMoreHistory, true)
})

test('old requests cannot overwrite a newer filter result', async () => {
  const oldResponse = deferred()
  const dialog = makeDialog(async (_, query) => query.integrity ? {
    sessions: [{ client_id: 'filtered' }], has_more: false, filter_options: {},
  } : oldResponse.promise)
  const pending = dialog.loadHistory()
  dialog.filters.integrity = 'high'
  await dialog.onFilterChange()
  oldResponse.resolve({ sessions: [{ client_id: 'stale' }], has_more: true, filter_options: {} })
  await pending
  assert.equal(dialog.sessions.length, 1)
  assert.equal(dialog.sessions[0].client_id, 'filtered')
  assert.equal(dialog.canLoadMoreHistory, false)
})

test('changing Client ID search disables stale Load More before debounce completes', async () => {
  let trigger
  const calls = []
  const dialog = makeDialog(async (_, query) => {
    calls.push(query)
    return { sessions: [{ client_id: query.clientIdSearch || 'original' }], has_more: !query.clientIdSearch, filter_options: {} }
  }, { setTimeout(fn) { trigger = fn; return 1 }, clearTimeout() {} })
  await dialog.loadHistory()
  assert.equal(dialog.canLoadMoreHistory, true)
  dialog.clientSearch = 'node_03'
  dialog.onClientSearchInput()
  assert.equal(dialog.canLoadMoreHistory, false)
  await dialog.loadMoreHistory()
  assert.equal(calls.length, 1)
  await trigger()
  assert.equal(calls.length, 2)
  assert.equal(calls[1].clientIdSearch, 'node_03')
  assert.equal(dialog.sessions[0].client_id, 'node_03')
  assert.equal(dialog.canLoadMoreHistory, false)
})

test('HTTP API sends search and filter arguments together', async () => {
  const apiSource = readFileSync(new URL('../src/api/connectionsApi.js', import.meta.url), 'utf8')
  const pathMatch = apiSource.match(/export function getMachineConnectionHistory\([\s\S]*?\n}\n/)
  assert.ok(pathMatch)
  const invoked = []
  const context = { URLSearchParams, Promise, apiData(url) { invoked.push(url); return Promise.resolve({}) } }
  vm.runInNewContext(pathMatch[0].replace('export function ', 'function ') + '\nglobalThis.invoke = getMachineConnectionHistory', context)
  await context.invoke('m/x', { clientIdSearch: 'node_03', integrity: 'high', launchMode: 'ide', termination: 'timeout' })
  const url = new URL(invoked[0], 'https://example.org')
  assert.equal(url.pathname, '/api/machines/m%2Fx/connection-history')
  assert.equal(url.searchParams.get('client_id_search'), 'node_03')
  assert.equal(url.searchParams.get('integrity'), 'high')
  assert.equal(url.searchParams.get('launch_mode'), 'ide')
  assert.equal(url.searchParams.get('termination_reason'), 'timeout')
})
