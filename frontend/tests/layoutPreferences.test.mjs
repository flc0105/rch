import assert from 'node:assert/strict'
import { test } from 'node:test'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { LAYOUT_PREFERENCES_STORAGE_KEY, loadLayoutPreferences, saveLayoutPreferences } from '../src/utils/layoutPreferences.js'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const toolbar = readFileSync(resolve(root, 'src/components/TerminalToolbar.vue'), 'utf8')
const app = readFileSync(resolve(root, 'src/App.vue'), 'utf8')

function createStorage() {
  const values = new Map()
  return {
    values,
    getItem(key) { return values.has(key) ? values.get(key) : null },
    setItem(key, value) { values.set(key, String(value)) },
  }
}

test('layout preferences persist both collapsed states by default', () => {
  const storage = createStorage()
  assert.deepEqual(loadLayoutPreferences(storage), {
    deviceSidebarCollapsed: false,
    connectionInfoCollapsed: false,
  })

  assert.equal(saveLayoutPreferences({
    deviceSidebarCollapsed: true,
    connectionInfoCollapsed: true,
  }, storage), true)
  assert.deepEqual(loadLayoutPreferences(storage), {
    deviceSidebarCollapsed: true,
    connectionInfoCollapsed: true,
  })
  assert.deepEqual(JSON.parse(storage.getItem(LAYOUT_PREFERENCES_STORAGE_KEY)), {
    deviceSidebarCollapsed: true,
    connectionInfoCollapsed: true,
  })
})

test('legacy remember-layout setting cannot disable automatic persistence', () => {
  const storage = createStorage()
  storage.setItem(LAYOUT_PREFERENCES_STORAGE_KEY, JSON.stringify({ rememberLayoutState: false }))
  assert.deepEqual(loadLayoutPreferences(storage), {
    deviceSidebarCollapsed: false,
    connectionInfoCollapsed: false,
  })
  assert.equal(saveLayoutPreferences({ deviceSidebarCollapsed: true, connectionInfoCollapsed: false }, storage), true)
  assert.deepEqual(loadLayoutPreferences(storage), {
    deviceSidebarCollapsed: true,
    connectionInfoCollapsed: false,
  })
  assert.deepEqual(JSON.parse(storage.getItem(LAYOUT_PREFERENCES_STORAGE_KEY)), {
    deviceSidebarCollapsed: true,
    connectionInfoCollapsed: false,
  })
})

test('layout storage errors fall back safely and the green-dot menu has no persistence toggle', () => {
  const brokenStorage = { getItem() { throw new Error('blocked') }, setItem() { throw new Error('blocked') } }
  assert.deepEqual(loadLayoutPreferences(brokenStorage), {
    deviceSidebarCollapsed: false,
    connectionInfoCollapsed: false,
  })
  assert.equal(saveLayoutPreferences({ deviceSidebarCollapsed: true }, brokenStorage), false)
  assert.doesNotMatch(toolbar, /toggle-layout-persistence|Remember layout/)
  assert.doesNotMatch(app, /rememberLayoutState|remember-layout-state/)
  assert.match(app, /persistLayoutPreferences\(\)/)
})
