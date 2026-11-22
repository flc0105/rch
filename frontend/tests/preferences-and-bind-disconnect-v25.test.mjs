import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createPreferenceState } from '../src/api/preferenceState.js'
import { normalizeConnectionContextPreferences } from '../src/data/connectionContextFields.js'
import { normalizeToolbarPreferences } from '../src/data/toolbarPreferences.js'

const read = file => readFileSync(new URL(file, import.meta.url), 'utf8')

test('direction and toolbar catalogs have a single frontend owner', () => {
  assert.deepEqual(normalizeConnectionContextPreferences({ field_ids: ['connection_direction', 'status'] }).field_ids,
    ['connection_direction', 'status'])
  const normalized = normalizeToolbarPreferences({ toolbar: ['documents', 'log-viewer'] })
  assert.deepEqual(normalized.toolbar.slice(0, 2), ['documents', 'log-viewer'])
  assert.equal(normalized.more.filter(id => id === 'documents').length, 0)
})

test('preference save immediately updates every subscribed consumer', async () => {
  const originalFetch = globalThis.fetch
  let stored = { field_ids: [] }
  let resolveStaleRead
  let readCount = 0
  globalThis.fetch = async (_url, options = {}) => {
    if (options.method === 'PUT') {
      stored = JSON.parse(options.body)
      return { ok: true, json: async () => ({ code: 0, data: stored }) }
    }
    readCount++
    if (readCount === 1) {
      // Emulate a slow GET started before the user's Save.
      return new Promise(resolve => { resolveStaleRead = () => resolve({ ok: true, json: async () => ({ code: 0, data: { field_ids: [] } }) }) })
    }
    return { ok: true, json: async () => ({ code: 0, data: stored }) }
  }
  try {
    const state = createPreferenceState('/api/test/preferences', { field_ids: [] })
    const panel = []
    const toolbar = []
    state.subscribe(value => panel.push(value.field_ids))
    state.subscribe(value => toolbar.push(value.field_ids))
    const loading = state.load()
    const saved = await state.save({ field_ids: ['connection_direction'] })
    resolveStaleRead()
    assert.deepEqual((await loading).field_ids, ['connection_direction'])
    assert.deepEqual(saved.field_ids, ['connection_direction'])
    assert.deepEqual(panel, [['connection_direction']])
    assert.deepEqual(toolbar, [['connection_direction']])
    assert.deepEqual((await state.load()).field_ids, ['connection_direction'])
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('Toolbar Disconnect and sidebar Disconnect use the same API method', () => {
  const toolbar = read('../src/components/TerminalToolbar.vue')
  const sidebar = read('../src/components/DeviceSidebar.vue')
  const api = read('../src/api/connectionsApi.js')
  assert.match(toolbar, /disconnectConnection as disconnectConnectionApi/)
  assert.match(sidebar, /disconnectConnection as disconnectConnectionApi/)
  assert.match(toolbar, /disconnectConnectionApi\(this\.selectedId\)/)
  assert.doesNotMatch(toolbar, /killConnectionApi|killConnection\(/)
  assert.match(api, /\/disconnect/)
  assert.doesNotMatch(api, /\/kill`/)
})


test('temporary GET failure does not erase a successfully saved toolbar layout', async () => {
  const originalFetch = globalThis.fetch
  let failReads = false
  globalThis.fetch = async (_url, options = {}) => {
    if (options.method === 'PUT') {
      return { ok: true, json: async () => ({ code: 0, data: { toolbar: ['documents'], more: [] } }) }
    }
    if (failReads) throw new Error('temporarily offline')
    return { ok: true, json: async () => ({ code: 0, data: { toolbar: [], more: [] } }) }
  }
  try {
    const store = createPreferenceState('/api/test/toolbar', { toolbar: [], more: [] })
    const seen = []
    store.subscribe(value => seen.push([...value.toolbar]))
    await store.load()
    await store.save({ toolbar: ['documents'], more: [] })
    failReads = true
    assert.deepEqual((await store.load()).toolbar, ['documents'])
    assert.deepEqual(seen, [[], ['documents']])
  } finally {
    globalThis.fetch = originalFetch
  }
})
