import assert from 'node:assert/strict'
import { readFileSync, readdirSync } from 'node:fs'
import { test } from 'node:test'
import vm from 'node:vm'

const read = path => readFileSync(new URL(path, import.meta.url), 'utf8')
const component = read('../src/components/FloatingWindowTaskbar.vue')
const app = read('../src/App.vue')
const connections = read('../src/composables/useConnections.js')

function loadTaskbar() {
  const script = component.match(/<script>([\s\S]*?)<\/script>/)?.[1]
  assert.ok(script)
  const module = { exports: {} }
  vm.runInNewContext(script.replace('export default {', 'module.exports = {'), { module })
  return module.exports
}

function fakeDialog(id) {
  const host = { style: { zIndex: '2000', display: '' }, isConnected: true }
  const dialog = {
    classList: { contains: value => ['rch-managed-window', `rch-window-${id}`].includes(value) },
    closest: () => host,
    querySelector: () => null,
  }
  return { dialog, host }
}

test('Window manager advertises managed top-level dialogs and keeps nested dialogs modal', () => {
  const managed = [
    'LogViewerDialog', 'ScreenViewDialog', 'PtyDialog', 'RemoteFilesDialog',
    'ProcessDialogs', 'ConnectionInfoDialogs', 'ExternalToolManagerDialog',
    'ScriptLibraryDialog', 'BackgroundJobsDialog',
  ]
  for (const name of managed) {
    const file = read(`../src/components/${name}.vue`)
    const head = file.slice(file.indexOf('<el-dialog'), file.indexOf('>', file.indexOf('<el-dialog')))
    assert.match(head, /rch-managed-window/)
    assert.match(head, /:modal="false"/)
    assert.match(head, /draggable|:draggable="!fullscreen"/)
    assert.match(head, /append-to-body/)
  }
  assert.doesNotMatch(read('../src/components/RemoteFilePicker.vue').slice(0, 450), /rch-managed-window/)
  assert.match(read('../src/components/SettingsDialog.vue').slice(0, 450), /rch-managed-window/)
})

test('Every managed top-level Dialog ignores backdrop clicks, while transient dialogs remain modal', () => {
  const folder = new URL('../src/components/', import.meta.url)
  const managedFiles = readdirSync(folder).filter(name => name.endsWith('.vue')).filter(name => {
    const source = read(`../src/components/${name}`)
    const tag = source.match(/<el-dialog\b[^>]*>/s)?.[0] || ''
    return tag.includes('rch-managed-window')
  })
  assert.equal(managedFiles.length, 20)
  for (const name of managedFiles) {
    const tag = read(`../src/components/${name}`).match(/<el-dialog\b[^>]*>/s)?.[0] || ''
    assert.match(tag, /:modal="false"/, name)
    assert.match(tag, /:modal-penetrable="true"/, `${name} must allow background interaction`)
    assert.match(tag, /:close-on-click-modal="false"/, `${name} must not dismiss on backdrop click`)
  }
  assert.match(read('../src/components/ConnectionInfoDialogs.vue'), /:close-on-click-modal="true"/, 'nested detail dialog keeps its original behavior')
  assert.doesNotMatch(read('../src/components/RemoteFilePicker.vue').slice(0, 450), /rch-managed-window/)
})

test('Window manager minimizes without closing, restores and tracks one window per tool', () => {
  const entry = fakeDialog('log')
  const sandbox = {
    module: { exports: {} },
    document: { querySelectorAll: selector => selector.includes(':not(') ? [] : [entry.dialog] },
    window: { dispatchEvent: () => {}, innerWidth: 1100, innerHeight: 800 },
    Event: class {},
  }
  const script = component.match(/<script>([\s\S]*?)<\/script>/)?.[1]
  vm.runInNewContext(script.replace('export default {', 'module.exports = {'), sandbox)
  const options = sandbox.module.exports
  const emitted = []
  const manager = Object.assign({}, options.data(), options.methods, {
    _entries: new Map(),
    $emit: (...args) => emitted.push(args),
  })
  manager.scanWindows()
  assert.equal(manager.windows.length, 1)
  assert.deepEqual([...manager.getDeviceWindowIds()], ['log'])
  assert.equal(manager.minimize('log'), true)
  assert.equal(entry.host.style.display, 'none')
  assert.equal(manager.windows[0].minimized, true)
  assert.deepEqual(emitted, [])
  assert.equal(manager.activate('log'), true)
  assert.equal(entry.host.style.display, '')
  assert.equal(manager.windows[0].minimized, false)
  assert.equal(entry.host.style.zIndex, '2000')
  manager.requestClose('log')
  assert.equal(emitted[0][0], 'close-window')
  assert.equal(emitted[0][1], 'log')
  manager.scanWindows()
  assert.equal(manager.windows.length, 1, 'Repeated scanning does not duplicate the same tool')
  manager.minimize('log')
  manager.prepareClose('log')
  assert.equal(entry.host.style.display, '', 'Closing a minimized dialog unhides its host for cleanup')
  entry.host.style.display = 'none' // Element Plus v-show after close transition
  manager.scanWindows()
  assert.equal(manager.windows.length, 0, 'A closed but still-mounted dialog is not a task')
  sandbox.document.querySelectorAll = () => []
  manager.scanWindows()
  assert.equal(manager.windows.length, 0)
})

test('Closed dialog hidden inside a still-visible overlay is removed from the taskbar', () => {
  const screen = fakeDialog('screen')
  const log = fakeDialog('log')
  screen.dialog.getClientRects = () => [{ width: 700 }]
  log.dialog.getClientRects = () => [{ width: 600 }]
  const dialogs = [screen.dialog, log.dialog]
  const sandbox = {
    module: { exports: {} },
    document: { querySelectorAll: selector => selector.includes(':not(') ? [] : dialogs },
    window: { dispatchEvent: () => {}, innerWidth: 1100, innerHeight: 800 },
    Event: class {},
  }
  const script = component.match(/<script>([\s\S]*?)<\/script>/)?.[1]
  vm.runInNewContext(script.replace('export default {', 'module.exports = {'), sandbox)
  const manager = Object.assign({}, sandbox.module.exports.data(), sandbox.module.exports.methods, {
    _entries: new Map(),
  })
  manager.scanWindows()
  assert.equal(manager.windows.length, 2)
  // Vue v-show hides an inner dialog while the outer overlay still has display: ''
  log.dialog.getClientRects = () => []
  manager.scanWindows()
  assert.equal(manager.windows.length, 1)
  assert.equal(manager.windows[0].id, 'screen')
  assert.equal(manager.activate('log'), false, 'closed window cannot be revived from a stale task')
  assert.deepEqual([...manager.getDeviceWindowIds()], ['screen'])
  // Reopening the real dialog with the same tool identity creates one live task.
  log.dialog.getClientRects = () => [{ width: 600 }]
  manager.scanWindows()
  assert.equal(manager.windows.length, 2)
  manager.minimize('log')
  log.dialog.getClientRects = () => []
  manager.scanWindows()
  assert.equal(manager.windows.length, 2, 'minimized window must remain registered')
  manager.prepareClose('log')
  manager.scanWindows()
  assert.equal(manager.windows.length, 1, 'closing a minimized window must also remove its task')
})

test('Device switching must prompt before selecting and exclude global-only windows', () => {
  assert.match(app, /async selectConnection\(clientId\) \{[\s\S]*?confirmDeviceWindowSwitch\(\)[\s\S]*?AppConnectionModule\.methods\.selectConnection\.call/)
  assert.match(app, /async clearSelectedConnection\(\) \{[\s\S]*?confirmDeviceWindowSwitch\(\)/)
  assert.match(app, /getDeviceWindowIds\(\)/)
  assert.match(connections, /if \(previousSelectedId && previousSelectedId !==/)
  assert.match(connections, /this\.closeDeviceWindowsForImplicitChange\?\.\(\)/)
  assert.match(component, /const GLOBAL_TOOLS = new Set\(\['agents', 'one-liners', 'settings'/)
  assert.match(app, /if \(this\.activateManagedWindow\('screen'\)\) return/)
  assert.match(app, /if \(this\.activateManagedWindow\('pty'\)\) return/)
  assert.match(app, /if \(!source\?\.path && this\.activateManagedWindow\('log'\)\) return/)
})

function loadAppMethods(confirm) {
  const script = app.match(/<script>([\s\S]*?)<\/script>/)?.[1]
  assert.ok(script)
  const module = { exports: {} }
  const env = { module, ElMessageBox: { confirm }, ElMessage: { warning: () => {} } }
  for (const match of script.matchAll(/^import\s+([A-Za-z_$][\w$]*)\s+from\s+['"][^'"]+['"]/gm)) {
    if (!env[match[1]]) env[match[1]] = { data: () => ({}), computed: {}, watch: {}, methods: {} }
  }
  for (const name of ['ArrowDown', 'ArrowUp', 'Bell']) env[name] = {}
  env.AppConnectionModule.methods.selectConnection = function (id) { this.selectedId = id }
  env.AppConnectionModule.methods.clearSelectedConnection = function () { this.selectedId = '' }
  vm.runInNewContext(script.replace(/^import\s+.*$/gm, '').replace('export default {', 'module.exports = {'), env)
  return module.exports.methods
}

test('Device switch cancel preserves selected client and every window', async () => {
  let closeCount = 0
  const methods = loadAppMethods(async () => { throw new Error('cancel') })
  const ctx = Object.assign({}, methods, {
    selectedId: 'mac-client',
    $refs: { windowTaskbarRef: { getDeviceWindowIds: () => ['screen', 'log'] } },
    closeDeviceWindowsForImplicitChange: () => { closeCount += 1 },
    $nextTick: async () => {},
  })
  await ctx.selectConnection('windows-client')
  assert.equal(ctx.selectedId, 'mac-client')
  assert.equal(closeCount, 0)
})

test('Confirmed switch closes managed device windows first; no-window switching skips prompt', async () => {
  const events = []
  const methods = loadAppMethods(async () => { events.push('confirm') })
  const ctx = Object.assign({}, methods, {
    selectedId: 'mac-client',
    $refs: { windowTaskbarRef: {
      getDeviceWindowIds: () => ['screen', 'log'],
      waitForDeviceWindowsToClose: async () => { events.push('closed'); return true },
    } },
    closeDeviceWindowsForImplicitChange: () => { events.push('close') },
    $nextTick: async () => {},
  })
  await ctx.selectConnection('windows-client')
  assert.equal(ctx.selectedId, 'windows-client')
  assert.deepEqual(events, ['confirm', 'close', 'closed'])
  ctx.$refs.windowTaskbarRef.getDeviceWindowIds = () => []
  await ctx.selectConnection('mac-client')
  assert.deepEqual(events, ['confirm', 'close', 'closed'])
  assert.equal(ctx.selectedId, 'mac-client')
})

test('Titlebar minimize button hides window without dispatching close', () => {
  const entry = fakeDialog('screen')
  const listeners = {}
  const button = {
    style: {}, classList: { add: () => {} },
    setAttribute: () => {},
    addEventListener: (event, handler) => { listeners[event] = handler },
  }
  let appended = null
  const header = {
    querySelector: () => null,
    appendChild: value => { appended = value },
  }
  entry.dialog.querySelector = name => name === '.el-dialog__header' ? header : null
  const sandbox = {
    module: { exports: {} },
    document: {
      querySelectorAll: selector => selector.includes(':not(') ? [] : [entry.dialog],
      createElement: () => button,
    },
    window: { dispatchEvent: () => {}, innerWidth: 1100, innerHeight: 800 },
    Event: class {},
  }
  const script = component.match(/<script>([\s\S]*?)<\/script>/)?.[1]
  vm.runInNewContext(script.replace('export default {', 'module.exports = {'), sandbox)
  const options = sandbox.module.exports
  const events = []
  const manager = Object.assign({}, options.data(), options.methods, {
    _entries: new Map(),
    $emit: (...args) => events.push(args),
  })
  manager.scanWindows()
  assert.equal(appended, button)
  assert.equal(button.title, 'Minimize')
  listeners.click({ stopPropagation() {} })
  assert.equal(entry.host.style.display, 'none')
  assert.equal(manager.windows[0].minimized, true)
  assert.deepEqual(events, [])
})
