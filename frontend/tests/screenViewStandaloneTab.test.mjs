import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import { test } from 'node:test'

const read = path => readFileSync(new URL(path, import.meta.url), 'utf8')
function component(path, globals = {}) {
  const source = read(path)
  const script = source.match(/<script>([\s\S]*?)<\/script>/)?.[1]
  assert.ok(script)
  const js = script.replace(/^import\s+[\s\S]*?\s+from\s+['"][^'"]+['"]\s*$/gm, '')
    .replace('export default {', 'const options = {') + '\nglobalThis.options = options'
  const context = { ...globals }
  vm.runInNewContext(js, context, { timeout: 1000 })
  return { source, options: context.options }
}

const screenGlobals = {
  ElMessage: { warning() {} }, Close: {}, FullScreen: {}, screenViewApi: {},
  FullJpegScreenRenderer: {}, KeyframeDeltaScreenRenderer: {},
}

test('More offers Open in New Tab while existing screenshot/restart remain', async () => {
  const { source, options } = component('../src/components/ScreenViewDialog.vue', screenGlobals)
  assert.match(source, /<el-dropdown-item command="screenshot"/)
  assert.match(source, /<el-dropdown-item command="restart"/)
  assert.match(source, /<el-dropdown-item v-if="!standalone" command="open-new-tab">Open in New Tab<\/el-dropdown-item>/)
  assert.equal(options.props.standalone.default, false)
  let opened = 0
  let restarted = 0
  await options.methods.handleMoreCommand.call({ openInNewTab() { opened++ }, restartView() { restarted++ } }, 'open-new-tab')
  assert.equal(opened, 1)
  assert.equal(restarted, 0)
  await options.methods.handleMoreCommand.call({ restartView() { restarted++ } }, 'restart')
  assert.equal(restarted, 1)
})

test('new tab uses same-origin client-only URL; successful popup releases original session', () => {
  const opened = []
  const tab = { opener: 'original' }
  const window = { location: { origin: 'https://example.test' }, open(...args) { opened.push(args); return tab } }
  const { options } = component('../src/components/ScreenViewDialog.vue', { ...screenGlobals, window, URL })
  const dialog = { targetClientId: 'device/1', visible: true }
  options.methods.openInNewTab.call(dialog)
  assert.equal(opened.length, 1)
  assert.equal(opened[0][1], '_blank')
  assert.equal(new URL(opened[0][0]).searchParams.get('screen_view_client'), 'device/1')
  assert.deepEqual(Array.from(new URL(opened[0][0]).searchParams.keys()), ['screen_view_client'])
  assert.equal(tab.opener, null)
  assert.equal(dialog.visible, false)
})

test('popup blocker preserves original Screen View', () => {
  const warnings = []
  const { options } = component('../src/components/ScreenViewDialog.vue', {
    ...screenGlobals, URL,
    window: { location: { origin: 'https://example.test' }, open() { return null } },
    ElMessage: { warning: value => warnings.push(value) },
  })
  const dialog = { targetClientId: 'client-123', visible: true }
  options.methods.openInNewTab.call(dialog)
  assert.equal(dialog.visible, true)
  assert.equal(warnings.length, 1)
})

test('standalone mode retains original renderer/input/controls and adds floating overlay', () => {
  const { source, options } = component('../src/components/ScreenViewDialog.vue', screenGlobals)
  assert.match(source, /:modal="!standalone"/)
  assert.match(source, /\{ 'screen-view-dialog-fullscreen': this.fullscreen \|\| this.standalone \}/)
  assert.match(source, /\.screen-view-dialog\.screen-view-dialog-standalone \.screen-view-toolbar\s*\{\s*position: absolute;/)
  assert.match(source, /\.screen-view-dialog\.screen-view-dialog-standalone \.screen-view-canvas\s*\{[\s\S]*?height: 100%/)
  assert.match(source, /<FullJpegScreenRenderer/)
  assert.match(source, /<KeyframeDeltaScreenRenderer/)
  assert.match(source, /@pointerdown="handlePointerDown"/)
  assert.match(source, /@keydown="handleKeyDown"/)
  assert.match(source, /@click="\$emit\('open-clipboard', 'get'\)"/)
  assert.match(source, /<el-dropdown-item command="send">Send<\/el-dropdown-item>/)
  assert.match(source, /<el-switch[\s\S]*?v-model="controlEnabled"/)
  assert.match(source, /v-model="fps"/)
  assert.match(source, /v-model="quality"/)
  assert.equal(options.computed.screenDialogWidth.call({ standalone: true, fullscreen: false }), '100vw')
  assert.equal(options.computed.screenDialogTop.call({ standalone: true, fullscreen: false }), '0')
  assert.ok(options.computed.screenDialogClass.call({ standalone: true, fullscreen: false }).some(x => x['screen-view-dialog-standalone']))
})

test('standalone overlay stays hidden until top-edge hover and remains available for dropdowns', () => {
  const { source, options } = component('../src/components/ScreenViewDialog.vue', screenGlobals)
  assert.match(source, /class="screen-view-toolbar-host"/)
  assert.match(source, /screen-view-toolbar-host-standalone/)
  assert.match(source, /\.screen-view-dialog\.screen-view-dialog-standalone \.screen-view-toolbar-host\s*\{[\s\S]*?height: 12px;/)
  assert.match(source, /\.screen-view-dialog\.screen-view-dialog-standalone \.screen-view-toolbar\s*\{[\s\S]*?opacity: 0;[\s\S]*?pointer-events: none;/)
  assert.match(source, /\.screen-view-toolbar-host:hover \.screen-view-toolbar/)
  assert.match(source, /\.screen-view-toolbar-popup-active \.screen-view-toolbar/)
  assert.match(source, /@visible-change="onToolbarPopupVisible\('fps', \$event\)"/)
  assert.match(source, /@visible-change="onToolbarPopupVisible\('quality', \$event\)"/)
  assert.match(source, /@visible-change="onToolbarPopupVisible\('clipboard', \$event\)"/)
  assert.match(source, /@visible-change="onToolbarPopupVisible\('more', \$event\)"/)
  const dialog = { standalone: true, toolbarPopoverStates: { fps: false, quality: false, clipboard: false, more: false } }
  assert.equal(options.computed.standaloneToolbarPopupOpen.call(dialog), false)
  options.methods.onToolbarPopupVisible.call(dialog, 'more', true)
  assert.equal(options.computed.standaloneToolbarPopupOpen.call(dialog), true)
  options.methods.onToolbarPopupVisible.call(dialog, 'clipboard', true)
  options.methods.onToolbarPopupVisible.call(dialog, 'more', false)
  assert.equal(options.computed.standaloneToolbarPopupOpen.call(dialog), true)
  options.methods.onToolbarPopupVisible.call(dialog, 'clipboard', false)
  assert.equal(options.computed.standaloneToolbarPopupOpen.call(dialog), false)
  options.methods.onToolbarPopupVisible.call(dialog, 'unknown', true)
  assert.equal(options.computed.standaloneToolbarPopupOpen.call(dialog), false)
  dialog.standalone = false
  options.methods.onToolbarPopupVisible.call(dialog, 'fps', true)
  assert.equal(dialog.toolbarPopoverStates.fps, false)
})

test('standalone entry loads the same Screen View and Clipboard dialogs, with no second implementation', async () => {
  const title = { title: '' }
  const { source, options } = component('../src/ScreenViewTab.vue', {
    ScreenViewDialog: {}, ClipboardDialog: {},
    URLSearchParams, window: { location: { search: '?screen_view_client=client-7' } },
    listConnections: async () => [{ client_id: 'client-7', hostname: 'test-Mac' }],
    document: title,
  })
  assert.match(source, /<ScreenViewDialog[\s\S]*?standalone[\s\S]*?@open-clipboard="openClipboardDialog"/)
  assert.match(source, /<ClipboardDialog[\s\S]*?:selected-id="clientId"/)
  const events = []
  const dialog = {
    clientId: 'client-7', connection: null,
    $refs: {
      screenViewDialogRef: { open() { events.push('open-screen') } },
      clipboardDialogRef: { open(tab) { events.push('clipboard:'+tab) } },
    },
  }
  await options.mounted.call(dialog)
  assert.equal(dialog.connection.hostname, 'test-Mac')
  assert.equal(title.title, 'Screen View · test-Mac')
  options.methods.openClipboardDialog.call(dialog, 'send')
  assert.deepEqual(events, ['open-screen', 'clipboard:send'])
  const main = read('../src/main.js')
  assert.match(main, /screen_view_client/)
  assert.match(main, /import\('\.\/ScreenViewTab\.vue'\)/)
  assert.match(main, /import\('\.\/App\.vue'\)/)
  assert.match(read('../src/../index.html'), /src="\/auth\.js"/)
})
