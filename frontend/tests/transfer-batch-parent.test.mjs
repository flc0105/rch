import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const read = file => readFileSync(new URL(file, import.meta.url), 'utf8')
const drawer = read('../src/components/TransferCenterDrawer.vue')
const sse = read('../src/composables/useSseStream.js')
const remote = read('../src/components/RemoteFilesDialog.vue')
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
