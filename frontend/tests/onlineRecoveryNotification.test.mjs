import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'
import vm from 'node:vm'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const source = readFileSync(resolve(root, 'src/composables/useSseStream.js'), 'utf8')
const start = source.indexOf("es.addEventListener('connection_online', (event) => {")
const end = source.indexOf("es.addEventListener('connection_offline'", start)
assert.ok(start >= 0 && end > start)
const fragment = source.slice(start, end)
for (const [value, suffix] of [
  ['', ''], ['local_watchdog', ' (recovered by Local Watchdog)'],
  ['process_watchdog', ' (recovered by Process Watchdog)'], ['unknown', ''],
]) {
  let handler
  const ctx = { notifications: [], connections: [],
    upsertConnection(conn) { this.connections.push(conn) },
    showSseNotification(key, data, meta) { this.notifications.push({ key, data, meta }) },
  }
  const es = { addEventListener(_, callback) { handler = callback } }
  vm.runInNewContext(`(function(){ ${fragment} }).call(context)`, { es, context: ctx })
  const payload = { connection: { client_id: 'c1', hostname: 'Mac' } }
  if (value) payload.recovery_source = value
  handler({ data: JSON.stringify(payload), lastEventId: 'event-1' })
  assert.equal(ctx.connections.length, 1)
  assert.equal(ctx.notifications.length, 1)
  const notification = ctx.notifications[0]
  assert.equal(notification.key, 'connection_online')
  assert.equal(notification.data.title, 'Device Online')
  assert.equal(notification.data.message, 'Mac is now available' + suffix)
  assert.equal(notification.meta.context.recovery_source || '', suffix ? value : '')
}
console.log('online recovery notification SSE tests passed')
