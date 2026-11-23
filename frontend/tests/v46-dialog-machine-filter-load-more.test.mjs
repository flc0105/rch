import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const read = file => readFileSync(new URL(file, import.meta.url), 'utf8')
const connect = read('../src/components/ConnectToClientDialog.vue')
const quick = read('../src/components/QuickActionsDialog.vue')
const remote = read('../src/components/RemoteFilesDialog.vue')
const transfer = read('../src/components/TransferCenterDrawer.vue')
const notification = read('../src/components/NotificationCenterDrawer.vue')
const loadMore = read('../src/components/HistoryLoadMore.vue')
const app = read('../src/App.vue')

test('Connect to Client form reduces label gap without changing fields', () => {
  assert.match(connect, /\.bind-connect-form \.el-form-item__label \{[^}]*line-height: 20px;[^}]*margin-bottom: 4px;[^}]*padding: 0;/)
  assert.match(connect, /label="Server Web URL"/)
  assert.match(connect, /v-model="form\.serverWebBaseUrl"/)
})

test('Quick Actions uses same small text controls and 32px toolbar dimensions as Remote Files', () => {
  assert.match(remote, /v-model="remoteSearchKeyword"[\s\S]*?size="small"/)
  assert.match(quick, /v-model="filterPlatform" size="small"/)
  assert.match(quick, /v-model="searchText"[\s\S]*?size="small"/)
  assert.match(quick, /type="primary" size="small" class="quick-actions-new-button"/)
  assert.match(quick, /\.quick-actions-search :deep\(\.el-input__wrapper\)[\s\S]*?min-height: 32px;/)
  assert.doesNotMatch(quick, /\.quick-actions-search :deep\(\.el-input__wrapper\)[^}]*font-size: 14px/)
})

test('Transfer filter retains machine_id as SQL key but displays only alias or hostname', () => {
  assert.match(app, /<TransferCenterDrawer[\s\S]*?:machine-alias-map="machineAliasMap"/)
  assert.match(transfer, /:value="machine\.machine_id"\s+:label="machine\.label"/)
  assert.doesNotMatch(transfer, /allow-create|default-first-option/)
  const source = transfer.match(/machineOptions\(\) \{([\s\S]*?)\n    \},\n\n    recentTransfers\(\)/)?.[1]
  assert.ok(source, 'machineOptions computed getter must exist')
  const getter = new Function(source)
  const id = '171db1b51e0684a3471c9f9338b4932e30b2cd5945da9a0ae9a6712a5510b29d'
  const machines = [{ machine_id: id, hostname: 'localhost' }, { machine_id: 'b', hostname: 'Mac.local' }]
  const context = { machines, machineAliasMap: { [id]: 'Build Host' }, machineId: '' }
  const options = getter.call(context)
  assert.deepEqual(options.map(row => row.label), ['Build Host', 'Mac.local'])
  assert.equal(options.find(row => row.machine_id === id).machine_id, id)
  assert.ok(options.every(row => !row.label.includes(id)))
  context.machineAliasMap = {}
  assert.equal(getter.call(context).find(row => row.machine_id === id).label, 'localhost')
  context.machineId = 'unlisted-machine-id'
  assert.equal(getter.call(context).find(row => row.machine_id === context.machineId).label, 'Unknown device')
})

test('both history drawers reuse an understated accessible load-more control', () => {
  for (const source of [transfer, notification]) {
    assert.match(source, /<HistoryLoadMore[\s\S]*?@load-more="\$emit\('load-more'\)"/)
    assert.doesNotMatch(source, /<el-button[^>]*:loading="(?:loading|loadingMore)"[^>]*@click="\$emit\('load-more'\)"/)
  }
  assert.match(loadMore, /:disabled="loading"/)
  assert.match(loadMore, /\{\{ remaining \}\} remaining/)
  assert.match(loadMore, /font-size: 12px/)
  assert.match(loadMore, /border-top: 1px solid/)
  assert.match(loadMore, /@click="\$emit\('load-more'\)"/)
})
