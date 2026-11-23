import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import { LAYOUT_PREFERENCES_STORAGE_KEY, loadLayoutPreferences, saveLayoutPreferences } from '../src/utils/layoutPreferences.js'

const read = path => readFileSync(new URL(path, import.meta.url), 'utf8')
const app = read('../src/App.vue')
const connections = read('../src/composables/useConnections.js')
const quickActions = read('../src/components/QuickActionsDialog.vue')

function storage(initial = null) {
  const entries = new Map(initial == null ? [] : [[LAYOUT_PREFERENCES_STORAGE_KEY, initial]])
  return {
    getItem: key => entries.get(key) ?? null,
    setItem: (key, value) => entries.set(key, value),
  }
}

test('offline device visibility defaults on and persists beside existing layout preferences', () => {
  const browser = storage()
  assert.deepEqual(loadLayoutPreferences(browser), {
    deviceSidebarCollapsed: false, connectionInfoCollapsed: false, showOfflineDevices: true,
  })
  assert.equal(saveLayoutPreferences({ deviceSidebarCollapsed: true, connectionInfoCollapsed: false,
    showOfflineDevices: false }, browser), true)
  assert.deepEqual(loadLayoutPreferences(browser), {
    deviceSidebarCollapsed: true, connectionInfoCollapsed: false, showOfflineDevices: false,
  })
  assert.equal(saveLayoutPreferences({ deviceSidebarCollapsed: true, connectionInfoCollapsed: true,
    showOfflineDevices: false }, browser), true)
  assert.deepEqual(loadLayoutPreferences(browser), {
    deviceSidebarCollapsed: true, connectionInfoCollapsed: true, showOfflineDevices: false,
  })
})

test('older browser preferences and damaged storage do not hide offline devices', () => {
  const old = storage(JSON.stringify({ deviceSidebarCollapsed: true, connectionInfoCollapsed: true }))
  assert.equal(loadLayoutPreferences(old).showOfflineDevices, true)
  assert.equal(loadLayoutPreferences(storage('not json')).showOfflineDevices, true)
  const blocked = { getItem: () => { throw new Error('blocked') }, setItem: () => { throw new Error('blocked') } }
  assert.equal(loadLayoutPreferences(blocked).showOfflineDevices, true)
  assert.equal(saveLayoutPreferences({ showOfflineDevices: false }, blocked), false)
})

test('App restores browser preference and persists changes via existing layout hook', () => {
  assert.match(app, /showOfflineDevices:\s*layoutPreferences\.showOfflineDevices/)
  assert.match(app, /showOfflineDevices:\s*this\.showOfflineDevices/)
  const source = connections.replace(/^import .*$/gm, '').replace('export default', 'const component =')
  const component = vm.runInNewContext(`(() => { ${source}; return component })()`, {})
  const instance = {
    ...component.data(), ensured: 0, persisted: 0,
    ensureSelectedConnectionVisible() { this.ensured++ },
    persistLayoutPreferences() { this.persisted++ },
  }
  component.methods.toggleShowOfflineDevices.call(instance)
  assert.equal(instance.showOfflineDevices, false)
  assert.equal(instance.ensured, 1)
  assert.equal(instance.persisted, 1)
})

test('Quick Actions uses one responsive Element Plus search input with unchanged filtering', () => {
  assert.equal((quickActions.match(/v-model="searchText"/g) || []).length, 1)
  assert.match(quickActions, /<el-input\s+v-model="searchText"\s+clearable\s+class="quick-actions-search"/)
  assert.doesNotMatch(quickActions, /<input\s+v-model="searchText"/)
  assert.match(quickActions, /class="quick-actions-search"\s+size="small"/)
  assert.match(quickActions, /<el-select v-model="filterPlatform" size="small"/)
  assert.doesNotMatch(quickActions, /quick-actions-search :deep\(\.el-input__inner\) \{ font-size: 16px;/)
  assert.match(quickActions, /\.quick-actions-search \{ flex: 0 0 auto; width: 100%; min-width: 0; \}/)
  assert.match(quickActions, /\$\{item\.alias \|\| ''\} \$\{item\.command \|\| ''\}/)
})
