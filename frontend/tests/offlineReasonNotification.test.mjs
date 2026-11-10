import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'

const source = readFileSync(new URL('../src/composables/useSseStream.js', import.meta.url), 'utf8')
const start = source.indexOf("es.addEventListener('connection_offline', (event) => {")
const end = source.indexOf("es.addEventListener('connection_heartbeat'", start)
assert.ok(start >= 0 && end > start)
const fragment = source.slice(start, end)

for (const terminationReason of ['connection_lost', 'client_paused', '']) {
  let handler
  const updates = [], cleared = [], foreground = [], popups = []
  const ctx = {
    connections: [],
    upsertConnection(conn) { updates.push(conn) },
    clearActiveTask(clientId) { cleared.push(clientId) },
    applyForegroundTaskUpdate(clientId, task) { foreground.push({clientId, task}) },
    showSseNotification(...args) { popups.push(args) },
  }
  const es = { addEventListener(_, callback) { handler = callback } }
  vm.runInNewContext(`(function(){ ${fragment} }).call(context)`, { es, context: ctx })
  handler({data: JSON.stringify({
    client_id: 'c1', connection: {client_id: 'c1', hostname: 'Mac'},
    termination_reason: terminationReason, time: 't1',
  })})
  assert.equal(updates.length, 1)
  assert.equal(updates[0].connection_state, 'offline')
  assert.equal(updates[0].is_transfer_active, false)
  assert.deepEqual(cleared, ['c1'])
  assert.equal(foreground[0].task.state, 'Idle')
  assert.equal(popups.length, 0, 'raw offline event must not independently format a Toast')
}
console.log('offline connection side effects verified; popup comes from normalized notification')
