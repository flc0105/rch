import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'
import vm from 'node:vm'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const source = readFileSync(resolve(root, 'src/composables/useSseStream.js'), 'utf8')
const start = source.indexOf("es.addEventListener('connection_offline', (event) => {")
const end = source.indexOf("es.addEventListener('connection_heartbeat'", start)
assert.ok(start >= 0 && end > start)
const fragment = source.slice(start, end)

function run(payload) {
  let handler
  const ctx = {
    notifications: [],
    connections: [],
    upsertConnection(conn) { this.connections.push(conn) },
    clearActiveTask() {},
    showSseNotification(key, data, meta) { this.notifications.push({ key, data, meta }) },
  }
  const es = { addEventListener(_, callback) { handler = callback } }
  vm.runInNewContext(`(function(){ ${fragment} }).call(context)`, { es, context: ctx })
  handler({ data: JSON.stringify(payload), lastEventId: 'event-offline-1' })
  return ctx.notifications[0]
}

const withReason = run({
  client_id: 'c1',
  connection: { client_id: 'c1', hostname: 'Mac' },
  termination_reason: 'connection_lost',
})
assert.equal(withReason.data.message, 'Mac went offline · Reason: Connection lost')
assert.equal(withReason.meta.context.termination_reason, 'connection_lost')

const withoutReason = run({
  client_id: 'c2',
  connection: { client_id: 'c2', hostname: 'iPhone' },
})
assert.equal(withoutReason.data.message, 'iPhone went offline')
assert.equal(withoutReason.meta.context.termination_reason || '', '')

console.log('offline reason notification SSE tests passed')
