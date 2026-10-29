import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import { test } from 'node:test'

const source = file => readFileSync(new URL(file, import.meta.url), 'utf8')
function options(file, globals = {}) {
  const script = source(file).match(/<script>([\s\S]*?)<\/script>/)?.[1]
  assert.ok(script, `${file} must contain script`)
  const withoutImports = script.replace(/^import\s+[\s\S]*?\s+from\s+['"][^'"]+['"]\s*;?\s*$/gm, '')
  const ctx = { ...globals }
  vm.runInNewContext(withoutImports.replace('export default {', 'const options = {') + '\nglobalThis.options = options', ctx)
  return ctx.options
}
const plain = value => JSON.parse(JSON.stringify(value))
const ok = data => ({ ok: true, json: async () => ({ code: 0, data }) })
const deferred = () => {
  let resolve
  const promise = new Promise(done => { resolve = done })
  return { promise, resolve }
}

function pinsDialog({ items = [], promptValue = 'Saved Folder', selectedId = 'client-1', before = [] } = {}) {
  const requests = [], messages = [], emitted = []
  const responses = [...before]
  const opts = options('../src/components/RemotePinsDialog.vue', {
    RemoteFilePicker: {},
    ElMessage: { warning: value => messages.push(['warning', value]), success: value => messages.push(['success', value]), error: value => messages.push(['error', value]) },
    ElMessageBox: { prompt: async (...args) => { messages.push(['prompt', ...args]); return { value: promptValue } }, confirm: async () => {} },
    fetch: async (url, init = {}) => {
      requests.push({ url, init })
      return responses.shift() || ok(init.method === 'POST' ? { items: [{ display_name: promptValue, path: '/var/data' }] } : { items })
    },
  })
  const instance = {
    ...opts.data(), ...opts.methods, modelValue: true, selectedId, items,
    $emit: (...args) => emitted.push(args),
  }
  return { opts, instance, requests, messages, emitted }
}

test('Toolbox adds Manage Pins and Connection History without altering Toolbar + More catalog', () => {
  const sourceToolbar = source('../src/components/TerminalToolbar.vue')
  const sourceApp = source('../src/App.vue')
  const sourcePrefs = source('../src/data/toolbarPreferences.js')
  assert.match(sourceToolbar, /id: 'manage-pins', label: 'Pinned Paths', icon: 'bookmark'/)
  assert.match(sourceToolbar, /id: 'connection-history', label: 'Connection History', icon: 'clock'/)
  assert.match(sourceToolbar, /return \[\.\.\.base, \.\.\.toolboxOnly, \.\.\.shortcuts\]/)
  assert.match(sourceToolbar, /'manage-pins': 'open-manage-pins'/)
  assert.match(sourceToolbar, /'connection-history': 'open-connection-history'/)
  assert.match(sourceToolbar, /'open-manage-pins'/)
  assert.match(sourceToolbar, /'open-connection-history'/)
  assert.match(sourceApp, /@open-manage-pins="openManagePinnedPathsDialog"/)
  assert.match(sourceApp, /@open-connection-history="openSelectedMachineConnectionHistory"/)
  assert.match(sourceApp, /openPinnedQuickJumpManager\(\)/)
  assert.match(sourceApp, /openMachineConnectionHistory\(this\.decorateConnectionForDeviceView\(this\.currentConnection\)\)/)
  assert.doesNotMatch(sourcePrefs, /id: 'manage-pins'|id: 'connection-history'/)
})

test('Toolbox existing action routing opens existing dialogs and honors client availability', () => {
  const p = options('../src/components/TerminalToolbar.vue', {
    ElMessage: { warning() {} }, ElMessageBox: {}, ToolboxDialog: {},
    killConnectionApi() {}, loadToolbarPreferences() {}, saveToolbarPreferences() {}, listQuickActions() {},
    DEFAULT_TOOLBAR_PREFERENCES: {}, TOOLBAR_ACTION_CATALOG: [], TOOLBAR_ACTION_OPTIONS: {},
    cloneToolbarPreferences: () => ({ toolbar: [], more: [], toolbox_shortcuts: [], quick_actions_pinned: [] }),
    normalizeToolbarPreferences: val => val, normalizeToolboxPlatform: () => '',
    isScriptSupportedOnPlatform: () => true, isQuickActionSupportedOnPlatform: () => true,
  })
  const events = []
  const instance = {
    ...p.data(), ...p.methods, selectedId: 'client-1',
    currentConnection: { machine_id: 'machine-1' }, currentConnectionOffline: false,
    toolboxVisible: true, $emit: (...args) => events.push(args),
  }
  Object.defineProperty(instance, 'deviceActionDisabled', { get() { return !this.selectedId || this.currentConnectionOffline } })
  instance.launchToolboxAction('manage-pins')
  instance.launchToolboxAction('connection-history')
  assert.deepEqual(plain(events), [['open-manage-pins'], ['open-connection-history']])
  instance.currentConnectionOffline = true
  instance.launchToolboxAction('manage-pins')
  instance.launchToolboxAction('connection-history')
  assert.deepEqual(plain(events), [['open-manage-pins'], ['open-connection-history'], ['open-connection-history']])
  instance.currentConnection = { machine_id: '' }
  instance.launchToolboxAction('connection-history')
  assert.equal(events.length, 3)
})

test('existing Remote Files pins manager can open directly from Toolbox, including an empty list', async () => {
  const ready = deferred()
  const requests = []
  const p = options('../src/components/RemoteFilesDialog.vue', {
    RemotePinsDialog: {}, RemoteZipPeekDialog: {}, MoreFilled: {}, formatBytesValue() {},
    ElMessage: { warning: value => { throw Error(value) } }, ElMessageBox: {},
    fetch: async url => { requests.push(url); await ready.promise; return ok({ items: [{ display_name: 'Documents', path: '/Documents' }] }) },
  })
  const instance = {
    ...p.data(), ...p.methods,
    selectedId: 'client-1', $emit() {}, $refs: {}, $nextTick: fn => fn(),
  }
  assert.equal(instance.visible, false)
  instance.openPinnedQuickJumpManager()
  assert.equal(instance.visible, false, 'opening Pins must not open the Remote Files Browser')
  assert.equal(instance.pinManagerVisible, true)
  assert.equal(instance.remoteFilesClientId, 'client-1')
  assert.deepEqual(requests, ['/api/connections/client-1/pinned_paths'])
  ready.resolve()
  await new Promise(done => setImmediate(done))
  assert.equal(instance.remotePinnedJumpItems[0]?.display_name, 'Documents')
  // Close manager while a later response is still pending: old context is invalidated.
  instance.pinManagerVisible = false
  p.watch.pinManagerVisible.call(instance, false)
  assert.equal(instance.remoteFilesClientId, '')
  assert.equal(instance.remotePinnedJumpItems.length, 0)
})

test('Manage Pins creates a named Pin using the existing single-folder picker and POST API', async () => {
  const app = pinsDialog({ promptValue: 'Reports' })
  const template = source('../src/components/RemotePinsDialog.vue')
  assert.match(template, /<RemoteFilePicker[\s\S]*?selection-mode="folder"[\s\S]*?:multiple="false"[\s\S]*?@select="createPinnedPathFromSelection"/)
  assert.match(template, /@click="openCreatePicker">Create<\/el-button>/)
  const toolbar = template.indexOf('<div class="remote-pins-toolbar">')
  const table = template.indexOf('<div class="dialog-table-shell remote-pins-table-shell">')
  assert.ok(toolbar > template.indexOf('<div class="fixed-dialog-body remote-pins-body">') && toolbar < table, 'Create belongs in a row above the table')
  assert.doesNotMatch(template, /<template #header>/, 'keep the standard dialog title and close button')
  assert.match(template, /\.remote-pins-toolbar\s*\{[^}]*justify-content:\s*flex-start/s)

  app.instance.openCreatePicker()
  assert.equal(app.instance.createPickerVisible, true)
  await app.instance.createPinnedPathFromSelection('/var/data')
  assert.equal(app.requests.length, 2)
  assert.equal(app.requests[0].init.method, undefined)
  assert.equal(app.requests[1].init.method, 'POST')
  assert.equal(app.requests[1].url, '/api/connections/client-1/pinned_paths')
  assert.deepEqual(JSON.parse(app.requests[1].init.body), { display_name: 'Reports', path: '/var/data' })
  assert.equal(app.messages[0][3].inputValue, 'data')
  assert.equal(app.emitted.length, 1)
  assert.equal(app.emitted[0][0], 'updated')
  assert.equal(app.instance.createSaving, false)
})

test('creating an existing display name keeps the original Pin and does not POST', async () => {
  const app = pinsDialog({ promptValue: 'Docs', items: [{ display_name: 'docs', path: '/old' }] })
  await app.instance.createPinnedPathFromSelection('/new')
  assert.equal(app.requests.length, 1)
  assert.equal(app.messages.find(v => v[0] === 'warning')?.[1], 'A pinned path with this name already exists')
  assert.equal(app.emitted.length, 0)
})

test('changing the selected client during the folder/name flow does not save to the wrong client', async () => {
  const app = pinsDialog()
  const p = app.instance.createPinnedPathFromSelection('/var/data')
  app.instance.selectedId = 'client-2'
  await p
  assert.equal(app.requests.length, 0)
  // Also verify a close event hides the picker on mobile.
  app.instance.createPickerVisible = true
  app.opts.watch.modelValue.call(app.instance, false)
  assert.equal(app.instance.createPickerVisible, false)
})

test('Pinned Paths title and one-shot Refresh update only the active device', async () => {
  const template = source('../src/components/RemotePinsDialog.vue')
  assert.match(template, /title="Pinned Paths"/)
  assert.match(template, /@click="refreshPinnedPaths">Refresh<\/el-button>/)
  const app = pinsDialog({ items: [{ display_name: 'New', path: '/new' }] })
  await app.instance.refreshPinnedPaths()
  assert.equal(app.requests.length, 1)
  assert.equal(app.requests[0].url, '/api/connections/client-1/pinned_paths')
  assert.equal(app.requests[0].init.cache, 'no-store')
  assert.deepEqual(plain(app.emitted[0]), ['updated', [{ display_name: 'New', path: '/new' }]])

  const pending = deferred()
  // Simulate switching devices while the refresh response is pending.
  const calls = []
  const delayedOptions = options('../src/components/RemotePinsDialog.vue', {
    RemoteFilePicker: {},
    ElMessage: { error: value => calls.push(value) },
    ElMessageBox: {},
    fetch: async () => { await pending.promise; return ok({ items: [{ display_name: 'Old', path: '/old' }] }) },
  })
  const instance = { ...delayedOptions.data(), ...delayedOptions.methods, selectedId: 'client-1', modelValue: true, $emit: (...event) => calls.push(event) }
  const task = instance.refreshPinnedPaths()
  instance.selectedId = 'client-2'
  pending.resolve()
  await task
  assert.deepEqual(calls, [], 'stale Client response must not replace current pins')
  assert.equal(instance.refreshing, false)
})
