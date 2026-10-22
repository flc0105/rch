import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import { test } from 'node:test'

const file = path => readFileSync(new URL(path, import.meta.url), 'utf8')
const prefs = {}
vm.runInNewContext(file('../src/data/toolbarPreferences.js')
  .replaceAll('export const ', 'const ').replaceAll('export function ', 'function ')
  + '\nglobalThis.fns = {normalizeToolbarPreferences,cloneToolbarPreferences,normalizeToolboxShortcuts,toolboxShortcutKey,TOOLBOX_SHORTCUT_ICONS,normalizeToolboxPlatform,isScriptSupportedOnPlatform,isQuickActionSupportedOnPlatform};', prefs)
const { normalizeToolbarPreferences, cloneToolbarPreferences, TOOLBOX_SHORTCUT_ICONS, normalizeToolboxPlatform, isScriptSupportedOnPlatform, isQuickActionSupportedOnPlatform } = prefs.fns
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
  const source = file('../src/components/ToolboxDialog.vue').match(/import \{([\s\S]*?)\} from '@lucide\/vue'/)[1]
  const icons = Object.fromEntries(source.split(',').map(k => [k.trim(), {}]))
  Object.assign(icons, { Close: {}, IconPickerDialog: {}, TOOLBOX_SHORTCUT_ICONS, isScriptSupportedOnPlatform, isQuickActionSupportedOnPlatform })
  const options = vueOptions('../src/components/ToolboxDialog.vue', icons)
  const events = []
  const instance = Object.assign({}, options.data(), options.methods, {
    actions: [], shortcuts: [], scripts: [], quickActions: [], currentPlatform: 'linux', pinLoading: false,
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
  assert.match(quick, /runPinnedAction\(row, presentation = 'dialog'\)/)
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
    normalizeToolboxPlatform, isScriptSupportedOnPlatform, isQuickActionSupportedOnPlatform,
    listQuickActions: async () => ({ items: [{ platform: 'common', alias: 'start', in_current_scope: true, parameters: [{ name: 'host' }] }] }),
  })
  const events = []
  const item = Object.assign({}, options.data(), options.methods, {
    selectedId: 'client-1', currentConnectionOffline: false, toolboxVisible: true, toolboxCurrentPlatform: 'linux', toolboxScripts: [{script_name: 'ops/deploy'}],
    $emit(...args) { events.push(args) },
  })
  Object.defineProperty(item, 'deviceActionDisabled', { get() { return options.computed.deviceActionDisabled.call(item) } })
  await item.launchToolboxPin({ kind: 'script', script_name: 'ops/deploy', icon: 'rocket' })
  assert.deepEqual(plain(events), [['run-toolbox-script', 'ops/deploy']])
  assert.equal(item.toolboxVisible, true)
  await item.launchToolboxPin({ kind: 'quick_action', platform: 'common', alias: 'start', icon: 'zap' })
  assert.equal(item.toolboxVisible, true)
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
    normalizeToolboxPlatform, isScriptSupportedOnPlatform, isQuickActionSupportedOnPlatform,
    listQuickActions: () => new Promise(resolve => { resolveList = resolve }),
  })
  const events = []
  const item = Object.assign({}, options.data(), options.methods, {
    selectedId: 'first-client', currentConnectionOffline: false, toolboxVisible: true, toolboxCurrentPlatform: 'linux',
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


test('new labels survive normalization, remain separate from script identity, and expanded icon set is shared', () => {
  const result = normalizeToolbarPreferences({ toolbox_shortcuts: [
    { kind: 'quick_action', platform: 'mac', alias: 'long_alias_name', icon: 'heart', label: '  My Deploy  ' },
    { kind: 'script', script_name: 'ops/cleanup', icon: 'git-branch', label: ' Cleanup ' },
  ] })
  assert.deepEqual(plain(result.toolbox_shortcuts), [
    { kind: 'quick_action', platform: 'mac', alias: 'long_alias_name', icon: 'heart', label: 'My Deploy' },
    { kind: 'script', script_name: 'ops/cleanup', icon: 'git-branch', label: 'Cleanup' },
  ])
  assert.ok(TOOLBOX_SHORTCUT_ICONS.length >= 65)
  assert.equal(new Set(TOOLBOX_SHORTCUT_ICONS).size, TOOLBOX_SHORTCUT_ICONS.length)
})

test('Script compatibility uses metadata platforms; Quick Actions honor their platform identity', () => {
  assert.equal(normalizeToolboxPlatform('Darwin'), 'mac')
  assert.equal(normalizeToolboxPlatform('Windows'), 'win')
  assert.equal(isScriptSupportedOnPlatform({ metadata: { platforms: ['linux'] } }, 'win'), false)
  assert.equal(isScriptSupportedOnPlatform({ metadata: { platforms: ['mac'] } }, 'mac'), true)
  assert.equal(isScriptSupportedOnPlatform({ metadata: {} }, 'mac'), true)
  assert.equal(isScriptSupportedOnPlatform({ metadata: { platforms: ['win'] } }, ''), false)
  assert.equal(isQuickActionSupportedOnPlatform('common', 'mac'), true)
  assert.equal(isQuickActionSupportedOnPlatform('linux', 'mac'), false)
})

test('Add picker shows only compatible resources and custom label is emitted', () => {
  const app = mountPicker({
    scripts: [
      {script_name: 'mac/test', metadata: {platforms: ['mac']}},
      {script_name: 'linux/test', metadata: {platforms: ['linux']}},
      {script_name: 'all/test', metadata: {platforms: []}},
    ],
    quickActions: [
      {platform:'mac', alias:'mac-only', in_current_scope:false},
      {platform:'linux', alias:'linux-only', in_current_scope:true},
      {platform:'common', alias:'all', in_current_scope:true},
    ],
  })
  app.instance.currentPlatform = 'mac'
  assert.deepEqual(plain(app.instance.pickerResources.map(it => it.key)), ['all/test', 'mac/test'])
  app.instance.shortcutKind = 'quick_action'
  assert.deepEqual(plain(app.instance.pickerResources.map(it => it.key)), [JSON.stringify(['common','all'])])
  app.instance.shortcutKind = 'script'
  app.instance.shortcutResource = 'mac/test'
  app.instance.shortcutLabel = ' My Check '
  app.instance.shortcutIcon = 'heart'
  app.instance.addShortcut()
  assert.deepEqual(plain(app.events[0]), ['add-pin', {kind:'script', script_name:'mac/test', icon:'heart', label:'My Check'}])
})

test('Toolbar excludes platform-mismatched pins but preserves missing same-platform pins for Unpin', () => {
  const options = vueOptions('../src/components/TerminalToolbar.vue', {
    ElMessage: {warning(){},error(){}}, ElMessageBox:{}, ToolboxDialog:{},
    DEFAULT_TOOLBAR_PREFERENCES: plain(normalizeToolbarPreferences({})),
    TOOLBAR_ACTION_CATALOG:[], TOOLBAR_ACTION_OPTIONS:{},
    cloneToolbarPreferences: x => x, normalizeToolbarPreferences: x => x,
    normalizeToolboxPlatform, isScriptSupportedOnPlatform, isQuickActionSupportedOnPlatform,
  })
  const inst = Object.assign({}, options.data(), options.methods, {
    currentConnectionOffline: false, selectedId:'c1', toolboxCurrentPlatform:'mac', toolboxPinsLoaded:true,
    toolbarPreferences: { toolbar:[], more:[], toolbox_shortcuts:[
      {kind:'script',script_name:'win/tool',icon:'rocket'},
      {kind:'script',script_name:'deleted',icon:'heart',label:'Missing Tool'},
      {kind:'quick_action',platform:'win',alias:'no',icon:'rocket'},
      {kind:'quick_action',platform:'common',alias:'gone',icon:'star',label:'Deleted Alias'},
    ]},
    toolboxScripts:[{script_name:'win/tool',metadata:{platforms:['win']}}],
    toolboxQuickActions:[],
  })
  Object.defineProperty(inst, 'deviceActionDisabled', { get() { return options.computed.deviceActionDisabled.call(inst) } })
  assert.deepEqual(plain(options.computed.toolboxActions.call(inst).map(x=>x.label)), ['Missing Tool','Deleted Alias'])
  assert.ok(options.computed.toolboxActions.call(inst).every(x=>x.disabled && x.unavailable && x.shortcut))
  inst.toolboxPinsLoaded = false
  assert.ok(options.computed.toolboxActions.call(inst).every(x=>x.disabled && !x.unavailable), 'loading or offline must not be mislabeled as a deleted resource')
})

test('both Toolbox dialogs use fixed height with internal scroll', () => {
  const vue = file('../src/components/ToolboxDialog.vue')
  assert.match(vue,/\.toolbox-dialog\.el-dialog \{[^}]*height: min\(70vh/)
  assert.match(vue,/\.toolbox-list \{[^}]*overflow-y: auto/)
  assert.match(vue,/\.toolbox-add-dialog\.el-dialog \{[^}]*height: min\(58vh/)
  assert.match(vue,/\.toolbox-add-dialog \.el-dialog__body \{[^}]*overflow-y: auto/)
})


test('reusable IconPickerDialog supports fuzzy name search and selecting an icon', () => {
  const picker = file('../src/components/IconPickerDialog.vue')
  assert.match(picker, /name: 'IconPickerDialog'/)
  assert.match(picker, /aria-label="Search icon names"/)
  assert.match(picker, /overflow-y: auto/)
  const options = vueOptions('../src/components/IconPickerDialog.vue')
  const events = []
  const inst = Object.assign({}, options.data(), options.methods, {
    icons: ['file-code', 'git-branch', 'cloud-upload', 'cloud-download'],
    iconComponents: { 'file-code': {}, 'git-branch': {}, 'cloud-upload': {}, 'cloud-download': {} },
    modelValue: 'file-code',
    $emit(...args) { events.push(args) },
  })
  inst.search = 'CLOUD uP'
  assert.deepEqual(plain(options.computed.filteredIcons.call(inst)), ['cloud-upload'])
  inst.search = 'git_br'
  assert.deepEqual(plain(options.computed.filteredIcons.call(inst)), ['git-branch'])
  inst.choose('cloud-upload')
  assert.deepEqual(plain(events), [['select', 'cloud-upload'], ['update:visible', false]])
  inst.choose('invalid')
  assert.equal(events.length, 2)
  inst.search = 'stale'
  options.watch.visible.call(inst, true)
  assert.equal(inst.search, '')
  const toolbox = file('../src/components/ToolboxDialog.vue')
  assert.match(toolbox, /<IconPickerDialog/)
  assert.doesNotMatch(toolbox, /class="toolbox-icon-picker"/)
  assert.match(toolbox, /toolbox-shortcut-type :deep\(\.el-radio-button:first-child/)
})

test('Add picker orders Script and Quick Action resources by visible name A-Z', () => {
  const app = mountPicker({
    scripts: [{ script_name: 'z', display_name: 'Zulu' }, { script_name: 'b', display_name: 'alpha' }, { script_name: 'c', display_name: 'Beta' }],
    quickActions: [
      { platform: 'common', alias: 'zoo', in_current_scope: true },
      { platform: 'common', alias: 'Alpha', in_current_scope: true },
      { platform: 'common', alias: 'beta', in_current_scope: true },
    ],
  })
  assert.deepEqual(plain(app.instance.pickerResources.map(x => x.label)), ['alpha', 'Beta', 'Zulu'])
  app.instance.shortcutKind = 'quick_action'
  assert.deepEqual(plain(app.instance.pickerResources.map(x => x.label)), ['Alpha · common', 'beta · common', 'zoo · common'])
})

test('right-click Quick Action can execute in Terminal using original Quick Action runner', async () => {
  const app = mountPicker()
  app.instance.handleContextCommand({ shortcut: { kind: 'quick_action', platform: 'common', alias: 'build' }, disabled: false }, 'terminal')
  assert.deepEqual(plain(app.events), [['launch-pin', { kind: 'quick_action', platform: 'common', alias: 'build' }, 'terminal']])
  const toolbar = file('../src/components/TerminalToolbar.vue')
  const quick = file('../src/components/QuickActionsDialog.vue')
  const root = file('../src/App.vue')
  assert.match(toolbar, /run-quick-action-terminal/)
  assert.match(root, /@run-quick-action-terminal="runPinnedQuickActionInTerminal"/)
  assert.match(root, /runPinnedAction\(item, 'terminal'\)/)
  assert.match(quick, /runPinnedAction\(row, presentation = 'dialog'\)/)
  assert.match(quick, /this\.requestRun\(row, presentation/)
})
