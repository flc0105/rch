import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import { test } from 'node:test'
import { sortProcessRows } from '../src/utils/processSorting.js'

const rows = [
  { pid: 15, name: 'zulu', cpu_percent: 3.5, memory_percent: 0.5 },
  { pid: 2, name: 'Alpha', cpu_percent: 61.2, memory_percent: 17.0 },
  { pid: 7, name: 'bravo', cpu_percent: null, memory_percent: null },
  { pid: 3, name: 'alpha', cpu_percent: 61.2, memory_percent: 9.1 },
]
const ids = data => data.map(item => item.pid)

test('CPU / memory / PID / name sorts use numeric values, preserve order choice and put missing data last', () => {
  assert.deepEqual(ids(sortProcessRows(rows, { prop: 'pid', order: 'ascending' })), [2, 3, 7, 15])
  assert.deepEqual(ids(sortProcessRows(rows, { prop: 'name', order: 'ascending' })), [2, 3, 7, 15])
  assert.deepEqual(ids(sortProcessRows(rows, { prop: 'cpu_percent', order: 'descending' })), [2, 3, 15, 7])
  assert.deepEqual(ids(sortProcessRows(rows, { prop: 'memory_percent', order: 'descending' })), [2, 3, 15, 7])
  assert.deepEqual(ids(sortProcessRows(rows, { prop: 'cpu_percent', order: 'ascending' })), [15, 2, 3, 7])
  assert.deepEqual(ids(rows), [15, 2, 7, 3], 'sorting must not mutate SSE snapshots')
  const nextSnapshot = rows.map(item => item.pid === 15 ? { ...item, cpu_percent: 88 } : item)
  assert.deepEqual(ids(sortProcessRows(nextSnapshot, { prop: 'cpu_percent', order: 'descending' })), [15, 2, 3, 7])
})

test('both Process / Apps tables have sortable usage columns, dashboard cards open matching default sort', () => {
  const read = path => readFileSync(new URL(path, import.meta.url), 'utf8')
  const dialog = read('../src/components/ProcessDialogs.vue')
  const info = read('../src/components/ConnectionInfoDialogs.vue')
  const app = read('../src/App.vue')
  assert.equal((dialog.match(/prop="cpu_percent" label="CPU %"/g) || []).length, 2)
  assert.equal((dialog.match(/prop="memory_percent" label="Memory %"/g) || []).length, 2)
  assert.equal((dialog.match(/sortable="custom"/g) || []).length, 8)
  assert.match(dialog, /open\(sortBy = ''\)/)
  assert.match(dialog, /this\.processSort = \{ prop: sortBy, order: 'descending' \}/)
  assert.match(info, /@click="openProcessesFromDashboard\('cpu_percent'\)"/)
  assert.match(info, /@click="openProcessesFromDashboard\('memory_percent'\)"/)
  assert.match(app, /@open-processes="openProcessDialog"/)
  assert.match(app, /openProcessDialog\(sortBy = ''\)/)
})


test('Memory % header has room to stay on one line while Username uses less space', () => {
  const dialog = readFileSync(new URL('../src/components/ProcessDialogs.vue', import.meta.url), 'utf8')
  assert.equal((dialog.match(/label="Memory %" width="135"/g) || []).length, 2)
  assert.match(dialog, /label="Username"\s+min-width="145"/)
  assert.doesNotMatch(dialog, /label="Memory %" width="105"/)
})

test('Dashboard waits for Info dialog to close before emitting Process Manager navigation, with correct sort', () => {
  const source = readFileSync(new URL('../src/components/ConnectionInfoDialogs.vue', import.meta.url), 'utf8')
  assert.match(source, /modal-class="connection-info-overlay"\s+@closed="handleInfoDialogClosed"/)
  const script = source.match(/<script>([\s\S]*?)<\/script>/)?.[1]
  assert.ok(script)
  const code = script.split('\n').filter(line => !/^import /.test(line)).join('\n')
    .replace('export default {', 'const component = {') + '\nglobalThis.component = component'
  const context = { WatchdogInfoPanel: {}, ElMessage: {}, formatBytesHuman() {}, formatDateTimeStandardValue() {} }
  vm.runInNewContext(code, context, { timeout: 1000 })
  const events = []
  const dialog = {
    ...context.component.data(), ...context.component.methods,
    $emit(name, arg) { events.push([name, arg]) },
  }
  for (const prop of ['cpu_percent', 'memory_percent']) {
    dialog.infoVisible = true
    dialog.openProcessesFromDashboard(prop)
    assert.equal(dialog.infoVisible, false, 'Info overlay should start closing before Process opens')
    assert.equal(dialog.pendingProcessSort, prop)
    assert.equal(events.length, prop === 'cpu_percent' ? 0 : 1, 'do not emit before close')
    dialog.handleInfoDialogClosed()
    assert.equal(dialog.pendingProcessSort, '')
    assert.deepEqual(events.at(-1), ['open-processes', prop])
    dialog.handleInfoDialogClosed()
    assert.equal(events.length, prop === 'cpu_percent' ? 1 : 2, 'no duplicate event')
  }
  dialog.openProcessesFromDashboard('pid')
  assert.equal(events.length, 2, 'not all sorts are dashboard navigation targets')
})
