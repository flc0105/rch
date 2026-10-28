import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import { test } from 'node:test'
import {
  CONNECTION_CONTEXT_FIELD_CATALOG,
  DEFAULT_CONNECTION_CONTEXT_PREFERENCES,
  cloneConnectionContextPreferences,
  normalizeConnectionContextPreferences,
  resolveConnectionContextValue,
} from '../src/data/connectionContextFields.js'

const read = path => readFileSync(new URL(path, import.meta.url), 'utf8')

function optionsFrom(path, globals = {}) {
  const vue = read(path)
  const script = vue.match(/<script>([\s\S]*?)<\/script>/)?.[1]
  assert.ok(script, `${path} should contain a component script`)
  const js = script.replace(/^import\s+[\s\S]*?\s+from\s+['"][^'"]+['"]\s*;?\s*$/gm, '')
    .replace('export default {', 'const options = {') + '\nglobalThis.options = options'
  const context = { ...globals }
  vm.runInNewContext(js, context, { timeout: 1000 })
  return { vue, options: context.options }
}

const FIELD_IDS = CONNECTION_CONTEXT_FIELD_CATALOG.map(field => field.id)

test('Connection Context catalog includes Basic Info fields and live Task state', () => {
  assert.equal(FIELD_IDS.length, 30)
  assert.equal(new Set(FIELD_IDS).size, FIELD_IDS.length)
  assert.ok(FIELD_IDS.includes('status'))
  assert.ok(FIELD_IDS.includes('task'))
  assert.ok(FIELD_IDS.includes('pid'))
  assert.ok(FIELD_IDS.includes('launch_mode'))
  assert.ok(!FIELD_IDS.includes('reported_jobs'))
  assert.ok(!FIELD_IDS.includes('command_count'))
  const iconSource = read('../src/data/connectionContextIcons.js')
  const iconMapBody = iconSource.match(/CONNECTION_CONTEXT_ICONS = Object\.freeze\(\{([\s\S]*?)\}\)/)?.[1] || ''
  const iconNames = new Set([...iconMapBody.matchAll(/^  (\w+),$/gm)].map(match => match[1]))
  for (const field of CONNECTION_CONTEXT_FIELD_CATALOG) {
    assert.ok(iconNames.has(field.icon), `${field.id} should have a fixed Lucide icon`)
  }
  assert.deepEqual(cloneConnectionContextPreferences(), { field_ids: [] })
  assert.deepEqual(normalizeConnectionContextPreferences({ field_ids: ['pid', 'status', 'pid', 'command_count', 'bogus'] }), {
    field_ids: ['pid', 'status'],
  })
  assert.deepEqual(normalizeConnectionContextPreferences(null), DEFAULT_CONNECTION_CONTEXT_PREFERENCES)
})

test('Connection Context resolves shared status, timestamp, RTT and launch formatting', () => {
  const seenAt = Date.parse('2026-10-27T12:00:00')
  const connection = {
    connection_state: 'online',
    hostname: 'build-mac',
    last_seen_at: '2026-10-27T12:00:00',
    connected_at: '2026-10-27T11:58:00.000',
    last_rtt_ms: 12,
    process_id: 24511,
    launch_mode: 'detached',
    launch_source: 'new_session',
    stale_after_seconds: 45,
  }

  assert.equal(resolveConnectionContextValue('status', connection, seenAt + 1000), 'online')
  assert.equal(resolveConnectionContextValue('status', connection, seenAt + 46000), 'stale')
  assert.equal(resolveConnectionContextValue('hostname', connection, seenAt), 'build-mac')
  assert.equal(resolveConnectionContextValue('connected_at', connection, seenAt), '2026-10-27 11:58:00')
  assert.equal(resolveConnectionContextValue('last_seen', connection, seenAt + 46000), '2026-10-27 12:00:00')
  assert.equal(resolveConnectionContextValue('rtt', connection, seenAt), '12 ms')
  assert.equal(resolveConnectionContextValue('pid', connection, seenAt), '24511')
  assert.equal(resolveConnectionContextValue('launch_mode', connection, seenAt), 'Detached (new session)')
  assert.equal(resolveConnectionContextValue('username', {}, seenAt), '-')
})

test('Connection Context Last Seen uses disconnected time when offline', () => {
  assert.equal(resolveConnectionContextValue('last_seen', {
    connection_state: 'offline',
    last_seen_at: '2026-10-27T10:00:00',
    disconnected_at: '2026-10-27T10:05:00',
  }, Date.parse('2026-10-27T10:06:00')), '2026-10-27 10:05:00')
})

test('Settings Connection Context supports selecting, ordering, removing and saving fields', async () => {
  const events = []
  let savedPayload = null
  const fakePreferences = { field_ids: [] }
  const globals = {
    ElMessage: { success() {}, error(message) { throw new Error(message) } },
    loadToolbarPreferences: async () => ({}),
    saveToolbarPreferences: async value => value,
    loadNotificationPreferences: async () => ({}),
    saveNotificationPreferences: async value => value,
    loadTerminalContextPreferences: async () => fakePreferences,
    saveTerminalContextPreferences: async value => { savedPayload = value; return value },
    DEFAULT_TOOLBAR_PREFERENCES: { toolbar: [], more: [], quick_actions_pinned: [], toolbox_shortcuts: [] },
    TOOLBAR_ACTION_CATALOG: [],
    cloneToolbarPreferences: value => value,
    normalizeToolbarPreferences: value => value,
    DEFAULT_SSE_NOTIFICATION_PREFERENCES: { enabled: true, events: {} },
    SSE_NOTIFICATION_GROUPS: [],
    cloneSseNotificationPreferences: value => value,
    normalizeSseNotificationPreferences: value => value,
    CONNECTION_CONTEXT_FIELD_CATALOG,
    DEFAULT_CONNECTION_CONTEXT_PREFERENCES,
    cloneConnectionContextPreferences,
    normalizeConnectionContextPreferences,
    CONNECTION_CONTEXT_ICONS: {},
  }
  const { vue, options } = optionsFrom('../src/components/SettingsDialog.vue', globals)
  assert.match(vue, /label="Connection Context" name="connection-context"/)
  const instance = {
    ...options.data(),
    ...options.methods,
    $emit: (name, value) => events.push([name, value]),
  }
  instance.toggleConnectionContextField('pid', true)
  instance.toggleConnectionContextField('status', true)
  instance.moveConnectionContextField(1, -1)
  assert.deepEqual(JSON.parse(JSON.stringify(instance.connectionContextDraft.field_ids)), ['status', 'pid'])
  instance.toggleConnectionContextField('status', false)
  assert.deepEqual(JSON.parse(JSON.stringify(instance.connectionContextDraft.field_ids)), ['pid'])
  await instance.saveConnectionContextSettings()
  assert.deepEqual(JSON.parse(JSON.stringify(savedPayload)), { field_ids: ['pid'] })
  assert.deepEqual(JSON.parse(JSON.stringify(events)), [['connection-context-saved', { field_ids: ['pid'] }]])
  instance.resetConnectionContextDefaults()
  assert.deepEqual(JSON.parse(JSON.stringify(instance.connectionContextDraft.field_ids)), [])
})

test('Terminal Connection Context hides itself when no fields are selected and preserves chosen order', () => {
  const { vue, options } = optionsFrom('../src/components/TerminalConnectionContext.vue', {
    loadTerminalContextPreferences: async () => ({ field_ids: [] }),
    CONNECTION_CONTEXT_FIELD_CATALOG,
    cloneConnectionContextPreferences,
    resolveConnectionContextValue,
    CONNECTION_CONTEXT_ICONS: {},
  })
  assert.match(vue, /v-if="currentConnection && displayFields.length"/)
  const selected = {
    preferences: { field_ids: ['pid', 'status'] },
    currentConnection: { process_id: 9, connection_state: 'online' },
    statusNowTick: Date.now(),
  }
  const displayFields = options.computed.displayFields.call(selected)
  assert.deepEqual(JSON.parse(JSON.stringify(displayFields.map(field => [field.id, field.value]))), [
    ['pid', '9'], ['status', 'online'],
  ])
})

test('mobile layout keeps the dashboard within the viewport and confines context overflow to its tag row', () => {
  const appCss = read('../public/app.css')
  const contextVue = read('../src/components/TerminalConnectionContext.vue')
  const infoCardsVue = read('../src/components/ConnectionInfoCards.vue')

  assert.match(appCss, /@media \(max-width: 960px\) \{[\s\S]*?\.content\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)/)
  assert.match(appCss, /\.main\.panel,[\s\S]*?\.command-row\s*\{[^}]*width:\s*100%;[^}]*max-width:\s*100%;[^}]*min-width:\s*0;/)
  assert.match(infoCardsVue, /@media \(max-width: 960px\) \{\s*\.info-grid\s*\{[^}]*grid-template-columns:\s*repeat\(2,\s*minmax\(0,\s*1fr\)\)/)

  const mobileContextStyles = contextVue.match(/@media \(max-width: 960px\) \{([\s\S]*?)\n\}/)?.[1] || ''
  assert.match(mobileContextStyles, /\.terminal-connection-context\s*\{[^}]*width:\s*100%;[^}]*max-width:\s*100%;[^}]*min-width:\s*0;[^}]*overflow-x:\s*auto;/)
  assert.match(mobileContextStyles, /overscroll-behavior-x:\s*contain;/)
})

