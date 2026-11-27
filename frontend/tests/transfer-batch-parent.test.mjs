import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'

const read = file => readFileSync(new URL(file, import.meta.url), 'utf8')
const drawer = read('../src/components/TransferCenterDrawer.vue')
const sse = read('../src/composables/useSseStream.js')
const remote = read('../src/composables/useRemoteBatchUpload.js')
const api = read('../src/api/transferApi.js')

test('Transfer Center groups parent rows and exposes file-level details without changing Cancel for singles', () => {
  assert.match(drawer, /v-if="transfer\.is_batch"[^>]*@click="openBatchDetails\(transfer\)"/)
  assert.match(drawer, /:disabled="transfer\.cancel_supported === false/ )
  assert.match(drawer, /loadBatchTransfers\(transfer\.batch_id, this\.tabId\)/)
  assert.match(drawer, /file\.batch_id/)
  assert.match(api, /\/api\/transfers\/batches\/\$\{encodeURIComponent\(batchId\)\}\/items/)
})

test('batch has one terminal operation and per-file Transfer SSE stays distinct', () => {
  assert.match(remote, /`> \$\{TERMINAL_REMOTE_UPLOAD_PREFIX\} \$\{queue\.length\} file\(s\) -> \$\{root\}`/)
  assert.match(sse, /if \(transfer\.batch_id && !transfer\.is_batch\) return/)
  assert.match(sse, /addEventListener\('transfer_batch_updated'/)
  assert.doesNotMatch(sse, /addEventListener\('file_transfer_batch_finished'/)
  assert.match(sse, /handleTransferChildUpdate\?\.\(payload\)/)
})


test('batch details renders one titled scrollable list with per-file progress and separated parent actions', () => {
  assert.match(drawer, /<h3>File Transfers<\/h3>/)
  assert.match(drawer, /v-for="file in orderedBatchMembers"/)
  assert.match(drawer, /:percentage="normalizedPercent\(file.percent\)"/)
  assert.match(drawer, /formatInfoBytes\(file.transferred_bytes\)/)
  assert.match(drawer, /class="transfer-batch-member-error">\{\{ file.error \}\}/)
  assert.match(drawer, /\.transfer-card-actions\s*\{[^}]*gap:\s*12px/)
  assert.match(drawer, /\.transfer-batch-members\s*\{[^}]*overflow-y:\s*auto/)
})

function drawerInstance(loadBatchTransfers) {
  const script = drawer.match(/<script>([\s\S]*?)<\/script>/)[1]
  const component = vm.runInNewContext(`(${script.replace(/import[\s\S]*?from '[^']+'\s*/g, '').replace('export default', '')})`, {
    HistoryLoadMore: {}, CircleCheckFilled: {}, CircleCloseFilled: {}, Close: {}, MoreFilled: {},
    loadBatchTransfers, ElMessage: { error: () => {} },
  })
  const ui = { ...component.data(), tabId: 'tab' }
  for (const [key, method] of Object.entries(component.methods)) ui[key] = method.bind(ui)
  for (const [key, method] of Object.entries(component.computed)) Object.defineProperty(ui, key, { get: () => method.call(ui) })
  return ui
}

test('batch detail live progress wins over the in-flight snapshot and unrelated child events are ignored', async () => {
  let resolve
  const ui = drawerInstance(() => new Promise(done => { resolve = done }))
  const parent = { batch_id: 'batch', is_batch: true }
  const load = ui.openBatchDetails(parent)
  ui.handleTransferChildUpdate({ batch_id: 'batch', transfer_id: 'a', total_bytes: 100, percent: 70, state: 'running' })
  ui.handleTransferChildUpdate({ batch_id: 'other', transfer_id: 'x', percent: 90 })
  resolve({ items: [{ batch_id: 'batch', transfer_id: 'a', total_bytes: 100, percent: 10 }, { transfer_id: 'b', percent: 100 }] })
  await load
  assert.equal(ui.batchMembers.length, 2)
  assert.equal(ui.batchMembers[0].percent, 70)
  assert.equal(ui.hasProgress(ui.batchMembers[0]), true)
  assert.equal(ui.hasProgress({ percent: null, total_bytes: 100 }), false)
  assert.equal(ui.hasProgress({ percent: 0, total_bytes: 100 }), true)
  assert.equal(ui.hasProgress({ percent: 42, total_bytes: 100, progress_supported: false }), false)
  ui.handleTransferChildUpdate({ batch_id: 'batch', transfer_id: 'a', percent: 100, state: 'completed' })
  assert.equal(ui.batchMembers[0].state, 'completed')
  assert.equal(ui.batchMembersLoading, false)
  ui.handleTransferChildUpdate({ batch_id: 'batch', transfer_id: 'c', percent: 10, state: 'running' })
  assert.equal(ui.orderedBatchMembers[0].transfer_id, 'c')
  assert.equal(ui.orderedBatchMembers[1].transfer_id, 'a')
})

test('an older request for the same batch cannot overwrite a newer detail snapshot', async () => {
  const requests = []
  const ui = drawerInstance(() => new Promise(resolve => requests.push(resolve)))
  const parent = { batch_id: 'batch', is_batch: true }
  const first = ui.openBatchDetails(parent)
  const second = ui.openBatchDetails(parent)
  requests[1]({ items: [{ transfer_id: 'a', percent: 80 }] })
  await second
  requests[0]({ items: [{ transfer_id: 'a', percent: 20 }, { transfer_id: 'stale' }] })
  await first
  assert.equal(ui.batchMembers.length, 1)
  assert.equal(ui.batchMembers[0].percent, 80)
})

test('Info and Batch Progress are separate dialogs; switching invalidates old child loads and reopening reloads', async () => {
  const pending = []
  const ui = drawerInstance(() => new Promise(resolve => pending.push(resolve)))
  const parent = { batch_id: 'batch', transfer_id: 'parent', is_batch: true, destination_path: '/root' }
  const first = ui.openBatchDetails(parent)
  assert.equal(ui.batchVisible, true)
  assert.equal(ui.infoVisible, false)
  ui.openTransferInfo(parent)
  assert.equal(ui.batchVisible, false)
  assert.equal(ui.infoVisible, true)
  ui.handleTransferChildUpdate({ batch_id: 'batch', transfer_id:'stale' })
  pending[0]({ items: [{ transfer_id:'old' }] })
  await first
  assert.equal(ui.batchMembers.length,0)
  assert.equal(ui.refreshBatchDetails(),undefined)
  const second = ui.openBatchDetails(parent)
  pending[1]({ items: [{ transfer_id:'new', filename:'a.txt', destination_path:'/root/sub', percent:50 }] })
  await second
  assert.equal(ui.batchMembers.length,1)
  assert.equal(ui.batchMemberPath(ui.batchMembers[0]), 'sub/a.txt')
  assert.equal(ui.infoVisible,false)
  assert.equal(ui.batchVisible,true)
  const infoTemplate = drawer.split('title="Transfer Info"')[1].split('</el-dialog>')[0]
  assert.doesNotMatch(infoTemplate, /orderedBatchMembers/)
  assert.match(drawer, /v-model="batchVisible" title="Batch Progress"/)
  assert.match(drawer, /command="batch-progress"/)
})
