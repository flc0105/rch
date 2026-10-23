import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'

const source = path => readFileSync(new URL(path, import.meta.url), 'utf8')
const app = source('../src/App.vue')
const info = source('../src/components/ConnectionInfoDialogs.vue')
const server = source('../../backend/server/application/connection/connection_service.py')

function launch(sourceArg, connection = { client_id: 'c1', client_log_path: '/tmp/client_logs/client.log' }, selectedId = 'c1', offline = false) {
  const result = []
  const ctx = {
    currentConnection: connection, selectedId,
    isCurrentConnectionOffline: offline,
    $refs: { logViewerDialogRef: { open(source) { result.push(source) } } },
  }
  const js = app.match(/    openLogViewerDialog\(source = \{\}\) \{([\s\S]*?)\n    \},/)?.[1]
  assert.ok(js)
  const handler = new Function('source', js)
  handler.call(ctx, sourceArg)
  return result[0]
}

test('Toolbox Log Viewer opens current live Client main log by default', () => {
  assert.equal(launch({}).path, '/tmp/client_logs/client.log')
  assert.equal(launch(undefined).path, '/tmp/client_logs/client.log')
  assert.match(app, /ref="logViewerDialogRef"/)
})

test('Explicit External Tools and Watchdog files always take precedence', () => {
  assert.equal(launch({ clientId: 'c1', path: '/other/watchdog.log', title: 'Watchdog' }).path, '/other/watchdog.log')
  assert.equal(launch({ clientId: 'c2' }).path, undefined)
  assert.equal(launch({}, null).path, undefined)
  assert.equal(launch({}, { client_id: 'c1', client_log_path: '' }).path, undefined)
  assert.equal(launch({}, undefined, 'c1', true).path, undefined)
})

test('Client Log Basic Info card shows the path as monospaced text', () => {
  assert.match(info, /label: 'Client Log', value: conn\.client_log_path \|\| '-', mono: true/)
  assert.match(server, /'client_log_path': info\.get_extra\('client_log_path'\) or ''/)
})
