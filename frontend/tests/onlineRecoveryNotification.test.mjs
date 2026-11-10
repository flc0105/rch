import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'

const source = readFileSync(new URL('../src/composables/useSseStream.js', import.meta.url), 'utf8')
const start = source.indexOf("es.addEventListener('connection_online', (event) => {")
const end = source.indexOf("es.addEventListener('connection_offline'", start)
assert.ok(start >= 0 && end > start)
const fragment = source.slice(start, end)

for (const recoverySource of ['', 'local_heartbeat_watchdog', 'process_recovery_watchdog']) {
  let handler
  const ctx = {
    selectedId: 'c1', connections: [], refreshCount: 0, popups: [],
    upsertConnection(conn) { this.connections.push(conn) },
    refreshForegroundTask() { this.refreshCount++ },
    showSseNotification(...args) { this.popups.push(args) },
  }
  const es = { addEventListener(_, callback) { handler = callback } }
  vm.runInNewContext(`(function(){ ${fragment} }).call(context)`, { es, context: ctx })
  const payload = { connection: { client_id: 'c1', hostname: 'Mac' } }
  if (recoverySource) payload.recovery_source = recoverySource
  handler({ data: JSON.stringify(payload), lastEventId: 'event-1' })
  assert.equal(ctx.connections.length, 1)
  assert.equal(ctx.connections[0].hostname, 'Mac')
  assert.equal(ctx.refreshCount, 1)
  assert.equal(ctx.popups.length, 0, 'raw connection event must not independently format a Toast')
}
console.log('online connection side effects verified; popup comes from normalized notification')
