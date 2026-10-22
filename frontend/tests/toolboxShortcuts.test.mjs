import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import { test } from 'node:test'

const file = path => readFileSync(new URL(path, import.meta.url), 'utf8')
const prefs = {}
vm.runInNewContext(file('../src/data/toolbarPreferences.js')
  .replaceAll('export const ', 'const ').replaceAll('export function ', 'function ')
  + '\nglobalThis.fns = {normalizeToolbarPreferences,cloneToolbarPreferences,normalizeToolboxShortcuts,toolboxShortcutKey};', prefs)
const { normalizeToolbarPreferences, cloneToolbarPreferences } = prefs.fns
const plain = value => JSON.parse(JSON.stringify(value))
function vueOptions(path, mocks = {}) {
  const code = file(path).match(/<script>([\s\S]+?)<\/script>/)[1]
    .replace(/^import\s+[\s\S]*?\s+from\s+['"][^'"]+['"]\s*$/gm, '')
    .replace('export default {', 'const options = {') + '\nglobalThis.options = options'
  const context = { ...mocks }
  vm.runInNewContext(code, context, { timeout: 1000 })
  return context.options
}
function mountPicker(props = {}) {
  const icons = Object.fromEntries('Activity Archive BookOpen Bot CalendarClock Clipboard Code2 FileCode FolderOpen History KeyRound Monitor MonitorPlay Search Settings2 Terminal Wrench Zap ScrollText Plus Rocket Play ShieldCheck Close'.split(' ').map(k => [k, {}]))
  const options = vueOptions('../src/components/ToolboxDialog.vue', icons)
  const events = []
  const instance = Object.assign({}, options.data(), options.methods, {
    actions: [], shortcuts: [], scripts: [], quickActions: [], pinLoading: false,
    $emit(...args) { events.push(args) }, $nextTick(fn) { fn() }, $refs: {}, ...props,
  })
  Object.defineProperty(instance, 'pickerResources', { get() { return options.computed.pickerResources.call(instance) } })
  return { instance, options, events }
}

test('preferences persist Script and Quick Action identities plus validated icons without duplicates', () => {
  const normalized = normalizeToolbarPreferences({
    toolbar: ['scripts'], more: ['quick-actions'],
    quick_actions_pinned: [{ platform: 'common', alias: 'ping' }],
    toolbox_shortcuts: [
      { kind: 'script', script_name: 'ops/a', icon: 'rocket', command: 'should-not-save' },
      { kind: 'script', script_name: 'ops/a', icon: 'terminal' },
      { kind: 'quick_action', platform: 'Linux', alias: 'serve', icon: 'zap', params: ['hidden'] },
      { kind: 'background_job', job_name: 'monitor', icon: 'zap' },
      { kind: 'script', script_name: 'oops', icon: '<svg onload=alert(1)>' },
    ],
  })
  assert.deepEqual(plain(normalized.toolbox_shortcuts), [
    { kind: 'script', script_name: 'ops/a', icon: 'rocket' },
    { kind: 'quick_action', platform: 'linux', alias: 'serve', icon: 'zap' },
  ])
  assert.deepEqual(plain(cloneToolbarPreferences(normalized).toolbox_shortcuts), plain(normalized.toolbox_shortcuts))
  assert.deepEqual(plain(normalized.quick_actions_pinned), [{ platform: 'common', alias: 'ping' }])
})

test('picker offers Scripts and current scope Quick Actions without allowing duplicate pins', () => {
  const app = mountPicker({
    scripts: [{ script_name: 'ops/health', display_name: 'Health Check' }],
    quickActions: [
      { platform: 'common', alias: 'restart', in_current_scope: true },
      { platform: 'win', alias: 'secret', in_current_scope: false },
    ],
    shortcuts: [{ kind: 'script', script_name: 'ops/health', icon: 'rocket' }],
  })
  app.instance.openShortcutPicker()
  assert.equal(app.events[0][0], 'load-pin-options')
  assert.equal(app.instance.pickerResources.length, 1)
  assert.equal(app.instance.pickerResources[0].pinned, true)
  app.instance.shortcutResource = 'ops/health'
  app.instance.addShortcut()
  assert.equal(app.events.length, 1, 'duplicate must not emit add')
  app.instance.shortcutKind = 'quick_action'
  app.instance.shortcutResource = JSON.stringify(['common', 'restart'])
  app.instance.shortcutIcon = 'zap'
  app.instance.addShortcut()
  assert.deepEqual(plain(app.events[1]), ['add-pin', { kind: 'quick_action', platform: 'common', alias: 'restart', icon: 'zap' }])
  assert.equal(app.instance.shortcutPickerVisible, false)
})

test('unavailable shortcut remains removable using the one Toolbox context menu', () => {
  const pin = { kind: 'script', script_name: 'gone', icon: 'file-code' }
  const app = mountPicker()
  const action = { id: 'shortcut:0', label: 'gone', shortcut: pin, disabled: true }
  app.instance.openContextMenu({ clientX: 12, clientY: 34 }, action)
  assert.equal(app.instance.contextMenuAction, action)
  app.instance.handleContextCommand(action, 'unpin')
  assert.equal(app.events[0][0], 'remove-pin')
  assert.equal(app.instance.contextMenuAction, null)
})

test('Script and Quick Action invoke original Run interfaces with no direct command execution', () => {
  const app = file('../src/App.vue')
  const library = file('../src/components/ScriptLibraryDialog.vue')
  const quick = file('../src/components/QuickActionsDialog.vue')
  const toolbar = file('../src/components/TerminalToolbar.vue')
  assert.match(app, /@run-toolbox-script="runToolboxScript"/)
  assert.match(app, /openRunForScript\(scriptName\)/)
  assert.match(library, /async openRunForScript\(scriptName\)/)
  assert.match(library, /this\.openScriptRunDialog\(item\)/)
  assert.match(quick, /runPinnedAction\(row\)[\s\S]*?this\.requestRun\(row, 'dialog', \{ allowTerminal: false \}\)/)
  assert.match(toolbar, /this\.\$emit\('run-quick-action', item\)/)
  assert.match(toolbar, /this\.\$emit\('run-toolbox-script', pin\.script_name\)/)
  assert.match(file('../src/components/ToolboxDialog.vue'), /aria-label="Add shortcut"/)
  assert.doesNotMatch(file('../src/data/toolbarPreferences.js'), /background_job.*toolbox_shortcuts/)
})

test('Settings preserves Toolbox pins when Toolbar layout is saved', () => {
  assert.match(file('../src/components/SettingsDialog.vue'), /toolbox_shortcuts: latest\.toolbox_shortcuts/)
})


test('Toolbar launch for pinned Script or Quick Action invokes the existing App event only once', async () => {
  const catalogs = JSON.parse(JSON.stringify(normalizeToolbarPreferences({})))
  const options = vueOptions('../src/components/TerminalToolbar.vue', {
    ElMessage: { warning(message) { throw Error(`Unexpected warning: ${message}`) }, error(message) { throw Error(message) } },
    ElMessageBox: {}, ToolboxDialog: {},
    DEFAULT_TOOLBAR_PREFERENCES: catalogs,
    TOOLBAR_ACTION_CATALOG: [], TOOLBAR_ACTION_OPTIONS: {},
    cloneToolbarPreferences: x => x,
    normalizeToolbarPreferences: x => x,
    listQuickActions: async () => ({ items: [{ platform: 'common', alias: 'start', in_current_scope: true, parameters: [{ name: 'host' }] }] }),
  })
  const events = []
  const item = Object.assign({}, options.data(), options.methods, {
    selectedId: 'client-1', currentConnectionOffline: false, toolboxVisible: true,
    $emit(...args) { events.push(args) },
  })
  Object.defineProperty(item, 'deviceActionDisabled', { get() { return options.computed.deviceActionDisabled.call(item) } })
  await item.launchToolboxPin({ kind: 'script', script_name: 'ops/deploy', icon: 'rocket' })
  assert.deepEqual(plain(events), [['run-toolbox-script', 'ops/deploy']])
  assert.equal(item.toolboxVisible, false)
  item.toolboxVisible = true
  await item.launchToolboxPin({ kind: 'quick_action', platform: 'common', alias: 'start', icon: 'zap' })
  assert.equal(item.toolboxVisible, false)
  assert.equal(events.length, 2)
  assert.equal(events[1][0], 'run-quick-action')
  assert.deepEqual(plain(events[1][1].parameters), [{ name: 'host' }])
})


test('Toolbox shortcuts are a flat tail, with a single add icon and no Job type', () => {
  const vue = file('../src/components/ToolboxDialog.vue')
  const grid = vue.slice(vue.indexOf('class="toolbox-grid"'), vue.indexOf('<el-empty'))
  assert.ok(grid.indexOf('v-for="action in filteredActions"') < grid.indexOf('aria-label="Add shortcut"'))
  assert.match(vue, /shortcutKind = 'script'/)
  assert.match(vue, /value="quick_action"/)
  assert.doesNotMatch(vue, /value="background_job"/)
  assert.match(vue, /@click="handleContextCommand\(contextMenuAction, 'unpin'\)"/)
})


test('switching devices while a Quick Action lookup is pending does not dispatch to a different client', async () => {
  let resolveList
  const options = vueOptions('../src/components/TerminalToolbar.vue', {
    ElMessage: { warning() {}, error() {} }, ElMessageBox: {}, ToolboxDialog: {},
    DEFAULT_TOOLBAR_PREFERENCES: plain(normalizeToolbarPreferences({})),
    TOOLBAR_ACTION_CATALOG: [], TOOLBAR_ACTION_OPTIONS: {},
    cloneToolbarPreferences: x => x, normalizeToolbarPreferences: x => x,
    listQuickActions: () => new Promise(resolve => { resolveList = resolve }),
  })
  const events = []
  const item = Object.assign({}, options.data(), options.methods, {
    selectedId: 'first-client', currentConnectionOffline: false, toolboxVisible: true,
    $emit(...args) { events.push(args) },
  })
  Object.defineProperty(item, 'deviceActionDisabled', { get() { return options.computed.deviceActionDisabled.call(item) } })
  const pending = item.launchToolboxPin({ kind: 'quick_action', platform: 'common', alias: 'restart', icon: 'zap' })
  item.selectedId = 'second-client'
  resolveList({ items: [{ platform: 'common', alias: 'restart', in_current_scope: true }] })
  await pending
  assert.deepEqual(events, [])
  assert.equal(item.toolboxVisible, true)
})
