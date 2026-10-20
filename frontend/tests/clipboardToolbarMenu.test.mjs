import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import { test } from 'node:test'

const read = path => readFileSync(new URL(path, import.meta.url), 'utf8')

function optionsFrom(file, globals = {}) {
  const vue = read(file)
  const script = vue.match(/<script>([\s\S]*?)<\/script>/)?.[1]
  assert.ok(script)
  const js = script.replace(/^import\s+[\s\S]*?\s+from\s+['"][^'"]+['"]\s*$/gm, '')
    .replace('export default {', 'const options = {') + '\nglobalThis.options = options'
  const context = { ...globals }
  vm.runInNewContext(js, context, { timeout: 1000 })
  return { options: context.options, vue }
}

function toolbar() {
  const source = read('../src/data/toolbarPreferences.js')
  const ctx = {}
  vm.runInNewContext(source.replaceAll('export const ', 'const ')
    .replaceAll('export function ', 'function ')
    + '\nglobalThis.catalog = TOOLBAR_ACTION_CATALOG; globalThis.defaults = DEFAULT_TOOLBAR_PREFERENCES;', ctx)
  const { options, vue } = optionsFrom('../src/components/TerminalToolbar.vue', {
    ElMessage: { warning() {} }, ElMessageBox: {}, ToolboxDialog: {},
    TOOLBAR_ACTION_CATALOG: ctx.catalog, DEFAULT_TOOLBAR_PREFERENCES: ctx.defaults,
    cloneToolbarPreferences: p => ({ ...p, toolbar: [...p.toolbar], more: [...p.more] }),
    normalizeToolbarPreferences: p => p,
  })
  const emitted = []
  const state = Object.assign({}, options.data(), options.methods, {
    currentConnectionOffline: false, selectedId: 'device',
    $emit(...args) { emitted.push(args) },
  })
  Object.defineProperty(state, 'deviceActionDisabled', {
    get() { return options.computed.deviceActionDisabled.call(state) },
  })
  return { state, options, emitted, vue }
}

test('Clipboard dropdown exists only on direct toolbar button; More keeps its normal item', () => {
  const { vue } = toolbar()
  assert.match(vue, /v-else-if="action.id === 'clipboard'"\s+trigger="hover"/)
  assert.match(vue, /@command="handleClipboardDropdownCommand"/)
  assert.match(vue, /<el-dropdown-item command="get"[^>]*>Get<\/el-dropdown-item>/)
  assert.match(vue, /<el-dropdown-item command="send"[^>]*>Send<\/el-dropdown-item>/)
  const more = vue.match(/<template v-for="action in moreActions"[\s\S]*?<\/template>/)?.[0]
  assert.match(more, /:command="`action:\$\{action.id\}`"/)
  assert.doesNotMatch(more, /handleClipboardDropdownCommand/)
})

test('Toolbar Clipboard Get/Send goes through existing open event; More/Toolbox default to Get', () => {
  const { state, emitted } = toolbar()
  state.handleClipboardDropdownCommand('get')
  state.handleClipboardDropdownCommand('send')
  state.runAction('clipboard')
  state.handleMoreCommand('action:clipboard')
  assert.deepEqual(emitted, [
    ['open-clipboard', 'get'], ['open-clipboard', 'send'],
    ['open-clipboard'], ['open-clipboard'],
  ])
  state.handleClipboardDropdownCommand('bogus')
  assert.equal(emitted.length, 4)
})

test('Device offline disables both Clipboard choices', () => {
  const { state, emitted } = toolbar()
  state.selectedId = ''
  state.handleClipboardDropdownCommand('send')
  assert.equal(emitted.length, 0)
})

test('Clipboard dialog opens Send directly without fetching remote clipboard, Get retains original load', async () => {
  const { options, vue } = optionsFrom('../src/components/ClipboardDialog.vue', { Loading: {} })
  assert.match(vue, /<el-tab-pane label="Get" name="get">/)
  assert.match(vue, /<el-tab-pane label="Send" name="send">/)
  const calls = []
  const dialog = Object.assign({}, options.data(), options.methods, {
    selectedId: 'device',
    resetRemotePayload() { calls.push('reset') },
    clearComposer() { calls.push('clear') },
    async loadCapabilities() { calls.push('capabilities') },
    async loadRemoteClipboard() { calls.push('remote') },
  })
  await dialog.open('send')
  assert.equal(dialog.mode, 'send')
  assert.equal(dialog.visible, true)
  assert.deepEqual(calls, ['reset', 'clear', 'capabilities'])
  calls.length = 0
  await dialog.open()
  assert.equal(dialog.mode, 'get')
  assert.deepEqual(calls, ['reset', 'clear', 'capabilities', 'remote'])
  assert.match(read('../src/App.vue'), /openClipboardDialog\(tab = 'get'\)\s*\{\s*return this\.\$refs\.clipboardDialogRef\?\.open\(tab\)/)
})
