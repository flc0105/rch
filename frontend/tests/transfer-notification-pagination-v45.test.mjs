import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = filename => readFileSync(new URL(filename, import.meta.url), 'utf8')
const transferApi = source('../src/api/transferApi.js')
const notificationApi = source('../src/api/notificationHistoryApi.js')
const transferDrawer = source('../src/components/TransferCenterDrawer.vue')
const notificationDrawer = source('../src/components/NotificationCenterDrawer.vue')
const stream = source('../src/composables/useSseStream.js')
const app = source('../src/App.vue')
const tunnel = source('../src/components/TunnelManagerDialog.vue')
const quick = source('../src/components/QuickActionsDialog.vue')
const connect = source('../src/components/ConnectToClientDialog.vue')

test('transfer history uses SQL LIMIT/OFFSET and machine-id filters with only 20 initial rows', () => {
  assert.match(transferApi, /limit = 20, offset = 0, machineId = ''/)
  assert.match(transferApi, /query\.set\('machine_id', machineId\)/)
  assert.match(stream, /limit: 20, offset: previous\.length, machineId: this\.transferMachineId/)
  assert.match(transferDrawer, /<HistoryLoadMore[\s\S]*?@load-more="\$emit\('load-more'\)"/)
  assert.match(transferDrawer, /aria-label="Filter transfers by Machine ID"/)
  assert.match(app, /@filter-machine="setTransferMachineFilter"/)
  assert.doesNotMatch(transferDrawer, /RECENT_RENDER_BATCH_SIZE|recentRenderLimit/)
})

test('notification history uses server-filtered SQL pages, retains total count and manual clear', () => {
  assert.match(notificationApi, /limit = 20, offset = 0, type = 'all'/)
  assert.match(stream, /loadNotificationHistory\(\{ limit: 20, offset, type \}\)/)
  assert.match(notificationDrawer, /\{\{ totalCount \}\}/)
  assert.match(notificationDrawer, /:remaining="filteredCount - filteredNotifications\.length"/)
  assert.match(notificationDrawer, /<HistoryLoadMore[\s\S]*?@load-more="\$emit\('load-more'\)"/)
  assert.match(app, /@filter-changed="setSseNotificationFilter"/)
  assert.match(notificationDrawer, /clearNotificationHistory/)
})

test('fixed dialogs and control sizes align with Remote Files without losing content', () => {
  assert.match(tunnel, /height: min\(660px, 88dvh\)/)
  assert.match(tunnel, /\.tunnel-instance-list \{ flex: 1 1 auto; min-height: 0; overflow-y: auto;/)
  assert.doesNotMatch(tunnel, /\{\{ snapshot\.connected \? 'Connected' : 'Disconnected' \}\}/)
  assert.match(connect, /label-position="top"/)
  assert.match(quick, /min-height: 32px/)
  assert.match(quick, /height: 32px/)
})
