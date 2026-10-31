import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import vm from 'node:vm'
import useTaskState from '../src/composables/useTaskState.js'

const read = path => readFileSync(new URL(path, import.meta.url), 'utf8')
function vueOptions(path, injected = {}) {
  const source = read(path)
  const script = source.match(/<script>([\s\S]*?)<\/script>/)?.[1]
  assert.ok(script)
  const js = script.replace(/^import\s+[\s\S]*?\s+from\s+['"][^'"]+['"]\s*$/gm, '')
    .replace('export default {', 'const options = {') + '\nglobalThis.options = options'
  const ctx = { ...injected }
  vm.runInNewContext(js, ctx, { timeout: 1000 })
  return { source, options: ctx.options }
}

const catalogContext = {}
vm.runInNewContext(read('../src/data/toolbarPreferences.js')
  .replaceAll('export const ', 'const ').replaceAll('export function ', 'function ')
  + '\nglobalThis.actions = TOOLBAR_ACTION_CATALOG; globalThis.defaults = DEFAULT_TOOLBAR_PREFERENCES; globalThis.options = TOOLBAR_ACTION_OPTIONS;', catalogContext)

function toolbar(features, prefs = catalogContext.defaults) {
  const { options } = vueOptions('../src/components/TerminalToolbar.vue', {
    ElMessage: {}, ElMessageBox: {}, ToolboxDialog: {},
    TOOLBAR_ACTION_CATALOG: catalogContext.actions,
    TOOLBAR_ACTION_OPTIONS: catalogContext.options,
    DEFAULT_TOOLBAR_PREFERENCES: catalogContext.defaults,
    cloneToolbarPreferences: () => prefs,
    normalizeToolbarPreferences: x => x,
    normalizeToolboxPlatform: () => 'mac',
    isQuickActionSupportedOnPlatform: () => true,
    isScriptSupportedOnPlatform: () => true,
  })
  const events = []
  const instance = Object.assign({}, options.data(), options.methods, {
    currentConnection: features === undefined ? {} : { feature_manifest: features },
    selectedId: 'abc', currentConnectionOffline: false, toolboxPinsLoaded: false,
    $emit: value => events.push(value),
  })
  for (const key of ['deviceActionDisabled', 'toolbarActions', 'moreActions', 'toolboxActions', 'toolboxCurrentPlatform']) {
    Object.defineProperty(instance, key, { get: () => options.computed[key].call(instance) })
  }
  return { instance, events }
}

test('explicitly unsupported features disappear across Toolbar, More, and Toolbox', () => {
  const prefs = {
    toolbar: ['pty', 'clipboard', 'remote-files', 'screen-view'],
    more: ['screen-view', 'pty', 'clipboard', 'info'],
    quick_actions_pinned: [], toolbox_shortcuts: [],
  }
  const { instance, events } = toolbar({ pty: false, screen_view: false, clipboard: false }, prefs)
  assert.deepEqual(Array.from(instance.toolbarActions, item => item.id), ['remote-files'])
  assert.deepEqual(Array.from(instance.moreActions, item => item.id), ['info'])
  const toolboxIds = Array.from(instance.toolboxActions, item => item.id)
  for (const id of ['pty', 'clipboard', 'screen-view']) {
    assert.ok(!toolboxIds.includes(id))
    instance.runAction(id)
    assert.equal(instance.isActionDisabled(id), true)
  }
  assert.deepEqual(events, [])
  assert.ok(toolboxIds.includes('manage-pins'))
  assert.ok(toolboxIds.includes('connection-history'))
  // The selected client changes: action lists recompute without changing saved preferences.
  instance.currentConnection = { feature_manifest: { pty: true, clipboard: true, screen_view: true } }
  assert.deepEqual(Array.from(instance.toolbarActions, item => item.id), prefs.toolbar)
  assert.deepEqual(Array.from(instance.moreActions, item => item.id), prefs.more)
  assert.ok(instance.toolboxActions.some(item => item.id === 'screen-view'))
})


test('External Tools and Process Manager are hidden by their individual features', () => {
  const prefs = {
    toolbar: ['external-tools', 'processes', 'info'],
    more: ['processes', 'external-tools', 'log-viewer', 'quick-actions'],
    quick_actions_pinned: [], toolbox_shortcuts: [],
  }
  const { instance, events } = toolbar({ external_tool: false, process_monitor: false }, prefs)
  assert.deepEqual(Array.from(instance.toolbarActions, item => item.id), ['info'])
  assert.deepEqual(Array.from(instance.moreActions, item => item.id), ['log-viewer', 'quick-actions'])
  for (const id of ['external-tools', 'processes']) {
    assert.equal(instance.toolboxActions.some(item => item.id === id), false)
    assert.equal(instance.isActionDisabled(id), true)
    instance.runAction(id)
  }
  assert.deepEqual(events, [])
  instance.currentConnection = { feature_manifest: { external_tool: true, process_monitor: true } }
  assert.deepEqual(Array.from(instance.toolbarActions, item => item.id), prefs.toolbar)
  assert.deepEqual(Array.from(instance.moreActions, item => item.id), prefs.more)
})

test('Process Manager Dashboard link follows process_monitor but leaves Dashboard content', () => {
  const source = read('../src/components/ConnectionInfoDialogs.vue')
  assert.match(source, /feature_manifest\?\.process_monitor === false\) return/)
  assert.match(source, /Device Dashboard/)
  assert.match(read('../src/App.vue'), /openProcessDialog\(sortBy = ''\) \{\s*if \(this\.currentConnection\?\.feature_manifest\?\.process_monitor === false\) return/)
})

test('missing manifest or missing individual flag retains existing toolbar behavior', () => {
  assert.ok(toolbar(undefined).instance.toolbarActions.some(item => item.id === 'pty'))
  assert.ok(toolbar({ watchdog: false }).instance.toolbarActions.some(item => item.id === 'clipboard'))
  assert.ok(toolbar({ watchdog: false }).instance.toolbarActions.some(item => item.id === 'screen-view'))
})

test('Screen View also hides its secondary Clipboard entry when unavailable', () => {
  const { source, options } = vueOptions('../src/components/ScreenViewDialog.vue', {
    ElMessage: {}, Close: {}, FullScreen: {}, screenViewApi: {},
    FullJpegScreenRenderer: {}, KeyframeDeltaScreenRenderer: {},
  })
  assert.match(source, /@command="handleClipboardCommand"[^>]*v-if="clipboardSupported"/)
  assert.equal(options.computed.clipboardSupported.call({ currentConnection: { feature_manifest: { clipboard: false } } }), false)
  assert.equal(options.computed.clipboardSupported.call({ currentConnection: { feature_manifest: { clipboard: true } } }), true)
  assert.equal(options.computed.clipboardSupported.call({ currentConnection: {} }), true)
})

const { options: barOptions, source: barSource } = vueOptions('../src/components/CommandInputBar.vue', {
  ElMessage: {}, TerminalConnectionContext: {},
  formatTerminalCancelRequestedLine() {}, formatTerminalCommandFailedLine() {},
})
const getPolicy = (text, manifest, candidates = []) => barOptions.methods.getSubmittedCommandCancelPolicy.call({
  currentConnection: { command_manifest: manifest },
  commandCandidates: candidates,
  commandCandidatesLoadedFor: 'abc', selectedId: 'abc',
}, text)

test('only explicitly none commands disable Cancel; ACMD subcommands are token-matched', () => {
  const manifest = [
    { name: 'set', cancel_policy: 'none' },
    { name: 'acmd help', cancel_policy: 'none' },
    { name: 'acmd ping', cancel_policy: 'cooperative' },
    { name: 'shell', cancel_policy: 'process' },
    { name: 'pyexec', cancel_policy: 'none' },
    { name: 'script exec', cancel_policy: 'none' },
  ]
  assert.equal(getPolicy('set PROCESS_RECOVERY_WATCHDOG_ENABLED true', manifest), 'none')
  assert.equal(getPolicy('acmd help --verbose', manifest), 'none')
  assert.equal(getPolicy('ACMD   ping --host example.com', manifest), '')
  assert.equal(getPolicy('acmd helper', manifest), '')
  assert.equal(getPolicy('shell ls -la', manifest), '')
  assert.equal(getPolicy('pyexec print(1)', manifest), '')
  assert.equal(getPolicy('script exec demo', manifest), '')
  assert.equal(getPolicy('http get /', [{ name: 'http', cancel_policy: 'none' }]), '')
  assert.equal(getPolicy('unknown_tool --flag', manifest), '')
  assert.equal(getPolicy('clear', [{ name: 'clear', cancel_policy: 'cooperative' }]), '')
  assert.equal(getPolicy('clear', [{ name: 'clear' }]), '')
  assert.equal(getPolicy('alias-run 12', [], [{ name: 'alias-run', cancel_policy: 'none' }]), 'none')
  assert.match(barSource, /:disabled="!hasRunningWebTask \|\| currentActiveTaskCancelPolicy === 'none'"/)
  assert.match(barSource, /this\.getSubmittedCommandCancelPolicy\(text\)/)
})

test('cancel policy stays on its Task ID, isolated by device; new/unknown tasks may cancel', () => {
  const state = { ...useTaskState.data(), ...useTaskState.methods, selectedId: 'A' }
  state.setActiveTask('A', 'task-1', 'none')
  state.setActiveTask('B', 'task-2', '')
  assert.equal(useTaskState.computed.currentActiveTaskCancelPolicy.call(state), 'none')
  state.selectedId = 'B'
  assert.equal(useTaskState.computed.currentActiveTaskCancelPolicy.call(state), '')
  state.selectedId = 'A'
  state.markTaskCompleted('A', 'task-1')
  assert.equal(useTaskState.computed.currentActiveTaskCancelPolicy.call(state), '')
  state.setActiveTask('A', 'task-1', 'none') // late response to completed task
  assert.equal(useTaskState.computed.currentActiveTaskId.call(state), '')
  state.setActiveTask('A', 'task-3', 'none')
  state.setActiveTask('A', 'task-4') // task from another UI entry
  assert.equal(useTaskState.computed.currentActiveTaskCancelPolicy.call(state), '')
  state.clearActiveTask('A', 'task-3') // stale complete must not clear task-4
  assert.equal(useTaskState.computed.currentActiveTaskId.call(state), 'task-4')
  assert.match(read('../src/App.vue'), /:current-active-task-cancel-policy="currentActiveTaskCancelPolicy"/)
})


test('terminal submission attaches the matched policy to task ID and blocks cancel only for none', async () => {
  const sends = []
  const cancellations = []
  const globals = {
    ElMessage: { success() {}, error(error) { throw Error(String(error)) } },
    TerminalConnectionContext: {}, formatTerminalCancelRequestedLine: () => 'requested',
    formatTerminalCommandFailedLine: x => String(x),
    sendCommandApi: async (...args) => { sends.push(args); return { task_id: 'task-from-set' } },
    cancelTask: async id => { cancellations.push(id) },
  }
  const { options } = vueOptions('../src/components/CommandInputBar.vue', globals)
  const events = []
  const state = Object.assign({}, options.data(), options.methods, {
    commandText: 'set PROCESS_RECOVERY_WATCHDOG_ENABLED true',
    selectedId: 'abc',
    currentConnection: { command_manifest: [{ name: 'set', cancel_policy: 'none' }] },
    currentActiveTaskId: '', currentActiveTaskCancelPolicy: '',
    commandCandidatesLoadedFor: '',
    $emit: (...args) => events.push(args),
    closeAutocomplete() {}, clearAutocompleteNavigationState() {},
    clearCommandCompletionCandidateCache() {},
    async loadCommandCandidates() {}, getTabScopedHeaders() { return {} },
  })
  await options.methods.sendCommand.call(state)
  assert.equal(sends.length, 1)
  assert.deepEqual(events.find(item => item[0] === 'set-active-task'), ['set-active-task', 'abc', 'task-from-set', 'none', ''])
  state.currentActiveTaskId = 'task-from-set'
  state.currentActiveTaskCancelPolicy = 'none'
  await options.methods.cancelCurrentTask.call(state)
  assert.deepEqual(cancellations, [])
  state.currentActiveTaskCancelPolicy = ''
  await options.methods.cancelCurrentTask.call(state)
  assert.deepEqual(cancellations, ['task-from-set'])
})
