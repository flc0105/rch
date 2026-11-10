import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import { test } from 'node:test'

const source = readFileSync(new URL('../src/composables/useSseStream.js', import.meta.url), 'utf8')
const normalize = value => value && typeof value === 'object' ? value : {}

function fixture(selectedId = 'c1') {
  const handlers = new Map(), popups = [], actions = [], refreshed = []
  const stream = {
    addEventListener(name, callback) { handlers.set(name, callback) },
    close() {},
  }
  const imports = {
    console,
    h: (tag, props, children) => ({tag, props, children}),
    ElNotification: options => popups.push(options),
    formatTerminalCommandFinishedLine: () => '', TERMINAL_BACKGROUND_PREFIX: '',
    openWebEventStream: () => stream,
    DEFAULT_SSE_NOTIFICATION_PREFERENCES: {enabled: true, events: {}},
    cloneSseNotificationPreferences: value => ({enabled: value?.enabled !== false, events: {...(value?.events || {})}}),
    normalizeSseNotificationPreferences: normalize,
  }
  vm.runInNewContext(source.replace(/^import\s+[\s\S]*?\s+from\s+['"][^'"]+['"]\s*;?\s*$/gm, '')
    .replace('export default {', 'globalThis.component = {'), imports)
  const component = imports.component
  const ctx = {
    ...component.data(), selectedId, connections: [], $refs: {},
    ensureTabId: () => 'tab-1',
    upsertConnection(conn) { this.connections.push(conn) },
    refreshForegroundTask() { refreshed.push('foreground') },
    clearActiveTask(id) { refreshed.push(`clear:${id}`) },
    applyForegroundTaskUpdate(id, task) { refreshed.push(`${id}:${task.state}`) },
    scheduleBackgroundJobsRefresh(id) { refreshed.push(`job:${id}`) },
    refreshExternalToolsIfOpen() { refreshed.push('external') },
    refreshAgentOutputsIfOpen() { refreshed.push('agent') },
    refreshArtifactsIfOpen() { refreshed.push('artifacts') },
    recordTerminalArtifact(artifact) { refreshed.push(`artifact:${artifact.artifact_id}`) },
    handleSseNotificationAction(action, context) { actions.push({action, context}) },
  }
  for (const [name, method] of Object.entries(component.methods)) ctx[name] = method.bind(ctx)
  ctx.ensureTabId = () => 'tab-1'
  ctx.initSSE()
  return {
    ctx, handlers, popups, actions, refreshed,
    emit(name, data, id = 'event-1') {
      assert.ok(handlers.has(name), `${name} handler must exist`)
      return handlers.get(name)({data: JSON.stringify(data), lastEventId: id})
    },
    added(key, overrides = {}) {
      return this.emit('notification_center_updated', {
        action: 'added', notification: {
          id: `note-${key}`, event_id: `source-${key}`, notification_key: key,
          title: 'Server title', message: 'Server message', type: 'success',
          context: {client_id: 'c1'}, actions: [], ...overrides,
        },
      })
    },
  }
}

test('canonical server notification supplies Toast text, kind, event ID, context and actions once', () => {
  const h = fixture()
  h.emit('connection_online', {connection: {client_id: 'c1', hostname: 'Mac'}})
  assert.equal(h.popups.length, 0)
  h.added('connection_online', {
    title: 'Device Online', message: 'Mac is now available',
    actions: [{id:'preview', label:'Preview', type:'artifact_preview'}],
    context: {client_id: 'c1', artifact_id: 'A'},
  })
  assert.equal(h.popups.length, 1)
  assert.equal(h.popups[0].title, 'Device Online')
  assert.equal(h.popups[0].type, 'success')
  assert.equal(h.popups[0].duration, undefined) // retains Element Plus default
  assert.equal(h.popups[0].message.children[0].children, 'Mac is now available')
  const button = h.popups[0].message.children[1].children[0]
  assert.equal(button.children, 'Preview')
  button.props.onClick({preventDefault() {}, stopPropagation() {}})
  assert.equal(h.actions[0].action.type, 'artifact_preview')
  assert.equal(h.actions[0].context.artifact_id, 'A')
  assert.equal(h.ctx.sseNotificationHistory.length, 1)
  assert.equal(h.ctx.sseNotificationHistory[0].event_id, 'source-connection_online')
})

test('raw lifecycle events refresh their original UI without synthesizing Toasts', async () => {
  const h = fixture()
  await h.emit('external_tool_lifecycle', {action:'daemon', state:'error', client_id:'c1'})
  await h.emit('agent_build_lifecycle', {state:'completed'})
  await h.emit('agent_build_lifecycle', {state:'error'})
  await h.emit('background_job_lifecycle', {client_id:'c1', state:'error'})
  await h.emit('artifact_created', {artifact_id:'A', client_id:'c1'})
  await h.emit('transfer_updated', {transfer_id:'T', state:'started'})
  h.emit('connection_offline', {client_id:'c1', time:'now'})
  assert.deepEqual(h.refreshed, ['external', 'agent', 'job:c1', 'artifact:A', 'artifacts', 'clear:c1', 'c1:Idle'])
  assert.equal(h.ctx.transferItems.length, 1)
  assert.equal(h.ctx.connections[0].connection_state, 'offline')
  assert.equal(h.popups.length, 0)
})

test('server-created artifact Toast is selected-client scoped while its history stays global', () => {
  const h = fixture('c1')
  h.added('artifact_created', {context:{client_id:'c2', artifact_id:'A'}})
  assert.equal(h.ctx.sseNotificationHistory.length, 1)
  assert.equal(h.popups.length, 0)
  h.added('artifact_created', {id:'n2', context:{client_id:'c1', artifact_id:'B'}})
  assert.equal(h.popups.length, 1)
  assert.equal(h.popups[0].duration, 6000)
  h.ctx.selectedId = ''
  h.added('artifact_created', {id:'n3', context:{client_id:'c2', artifact_id:'C'}})
  assert.equal(h.popups.length, 2)
})

test('normalized Toast obeys global/category preferences; delete and clear never Toast', () => {
  const h = fixture()
  h.ctx.sseNotificationPreferences.events.pty_opened = false
  h.added('pty_opened')
  assert.equal(h.ctx.sseNotificationHistory.length, 1)
  assert.equal(h.popups.length, 0)
  h.ctx.sseNotificationPreferences.events.pty_opened = true
  h.added('pty_opened', {id:'n2'})
  assert.equal(h.popups.length, 1)
  h.emit('notification_center_updated', {action:'deleted', id:'n2'})
  assert.equal(h.popups.length, 1)
  h.ctx.sseNotificationPreferences.enabled = false
  h.added('server_cleanup_completed')
  assert.equal(h.popups.length, 1)
  h.emit('notification_center_updated', {action:'cleared'})
  assert.equal(h.ctx.sseNotificationHistory.length, 0)
})

test('category-specific display durations stay unchanged', () => {
  const h = fixture()
  const cases = [
    ['file_transfer_started', 'info', 3500],
    ['file_transfer_stopped', 'warning', 4500],
    ['file_transfer_error', 'error', 7000],
    ['device_event', 'info', 6000],
    ['pty_closed', 'warning', 4000],
    ['pty_error', 'error', 5000],
    ['screen_view_closed', 'warning', 4000],
    ['agent_build_error', 'error', 7000],
    ['server_cleanup_completed', 'warning', 8000],
  ]
  for (const [key, type, duration] of cases) {
    h.added(key, {id:`${key}-${type}`, type})
    assert.equal(h.popups.at(-1).duration, duration, key)
  }
})
