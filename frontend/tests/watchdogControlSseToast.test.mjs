import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import { test } from 'node:test'

const source = readFileSync(new URL('../src/composables/useSseStream.js', import.meta.url), 'utf8')
const start = source.indexOf("es.addEventListener('notification_center_updated', (event) => {")
const end = source.indexOf("es.addEventListener('server_cleanup_completed'", start)
assert.ok(start >= 0 && end > start, 'SSE notification center handler must exist')
const handlerSource = source.slice(start, end)

function createHarness(preferences = {}) {
  const handlers = new Map(), history = [], popups = []
  const context = {
    sseNotificationPreferences: {
      enabled: true,
      events: {
        watchdog_control_timeout: true,
        watchdog_control_failed: true,
        watchdog_control_received: false,
        ...preferences,
      },
    },
    applySseNotificationCenterUpdate(payload) { history.push(payload) },
    showSseNotification(key, options, context) {
      if (this.sseNotificationPreferences.enabled === false) return
      if (this.sseNotificationPreferences.events[key] === false) return
      popups.push({ key, options, context })
    },
  }
  vm.runInNewContext(`(function(){ ${handlerSource} }).call(context)`, {
    es: { addEventListener(name, callback) { handlers.set(name, callback) } }, context,
  })
  function emit(key, type = 'info', action = 'added') {
    handlers.get('notification_center_updated')({
      lastEventId: 'sse-1',
      data: JSON.stringify({ action, notification: {
        id: 'note-1', event_id: 'event-1', notification_key: key,
        title: 'Watchdog event', message: 'machine · clone', type,
        context: { client_id: 'c1', command_id: 'cmd1' },
      } }),
    })
  }
  return { emit, history, popups, context }
}

test('Watchdog timeout and failure show SSE popups while Notification Center retains history', () => {
  const { emit, history, popups } = createHarness()
  emit('watchdog_control_timeout', 'error')
  emit('watchdog_control_failed', 'error')
  assert.equal(history.length, 2)
  assert.equal(popups.length, 2)
  assert.deepEqual(popups.map(item => item.key), ['watchdog_control_timeout', 'watchdog_control_failed'])
  assert.equal(popups[0].options.type, 'error')
  assert.equal(popups[0].options.duration, 7000)
  assert.equal(popups[0].context.context.command_id, 'cmd1')
})

test('Receipt popup is suppressed by default but appears when Watchdog preference is enabled', () => {
  const harness = createHarness()
  harness.emit('watchdog_control_received')
  assert.equal(harness.history.length, 1)
  assert.equal(harness.popups.length, 0)
  harness.context.sseNotificationPreferences.events.watchdog_control_received = true
  harness.emit('watchdog_control_received')
  assert.equal(harness.popups.length, 1)
  assert.equal(harness.popups[0].context.eventId, 'event-1')
})

test('Unrelated notifications and history replay/delete do not show duplicate popups', () => {
  const { emit, history, popups } = createHarness()
  emit('artifact_created')
  emit('watchdog_control_timeout', 'error', 'deleted')
  assert.equal(history.length, 2)
  assert.equal(popups.length, 0)
})

test('Watchdog delivery obeys the global and individual switches', () => {
  const harness = createHarness({ watchdog_control_timeout: false })
  harness.emit('watchdog_control_timeout', 'error')
  assert.equal(harness.popups.length, 0)
  harness.context.sseNotificationPreferences.events.watchdog_control_timeout = true
  harness.context.sseNotificationPreferences.enabled = false
  harness.emit('watchdog_control_timeout', 'error')
  assert.equal(harness.popups.length, 0)
})
