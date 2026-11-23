import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { clearRecentTransfers } from '../src/api/transferApi.js'

const transfer = readFileSync(new URL('../src/components/TransferCenterDrawer.vue', import.meta.url), 'utf8')

test('Recent toolbar contains compact Machine filter adjacent to Clear Recent', () => {
  const title = transfer.split('<div class="transfer-center-header">')[1].split('<section')[0]
  assert.doesNotMatch(title, /class="transfer-machine-filter"/)
  const toolbar = transfer.split('class="transfer-center-section-heading"')[1].split('<article')[0]
  assert.match(toolbar, /class="transfer-center-recent-tools"/)
  assert.match(toolbar, /class="transfer-machine-filter"/)
  assert.match(toolbar, /:model-value="machineId"/)
  assert.match(toolbar, /@change="\$emit\('filter-machine', \$event \|\| ''\)"/)
  assert.match(toolbar, /@click="clearRecent"/)
  assert.match(transfer, /v-if="recentTransfers\.length \|\| machineId"/)
  assert.match(transfer, /selectedMachineId\s*\? `Clear recent transfer records for \$\{label\}\?`/)
  assert.match(transfer, /await clearRecentTransfers\(this\.tabId, selectedMachineId\)/)
})

test('clearRecentTransfers passes selected Machine ID only when filtering', async () => {
  const original = globalThis.fetch
  const seen = []
  globalThis.fetch = async (url, options) => {
    seen.push({ url: String(url), ...options })
    return { ok: true, json: async () => ({ code: 0, data: { removed: 1 } }) }
  }
  try {
    await clearRecentTransfers('tab-a', 'mac with / slash')
    await clearRecentTransfers('tab-a')
    assert.equal(new URL(seen[0].url, 'http://local').searchParams.get('machine_id'), 'mac with / slash')
    assert.equal(seen[0].method, 'DELETE')
    assert.equal(seen[0].headers['X-Tab-Id'], 'tab-a')
    assert.equal(seen[1].url, '/api/transfers/recent')
  } finally {
    globalThis.fetch = original
  }
})
