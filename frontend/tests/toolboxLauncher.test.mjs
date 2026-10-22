import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import { test } from 'node:test'

const source = file => readFileSync(new URL(file, import.meta.url), 'utf8')

function readOptions(path, globals = {}) {
  const vue = source(path)
  const script = vue.match(/<script>([\s\S]*?)<\/script>/)?.[1]
  assert.ok(script, 'Vue SFC must include an ordinary script')
  const js = script.replace(/^import\s+[\s\S]*?\s+from\s+['"][^'"]+['"]\s*$/gm, '')
    .replace('export default {', 'const options = {') + '\nglobalThis.options = options'
  const iconImports = path.includes('ToolboxDialog.vue')
    ? (script.match(/import \{([\s\S]*?)\} from ['"]@lucide\/vue['"]/)?.[1] || '').split(',').map(name => name.trim()).filter(Boolean)
    : []
  const context = { ...Object.fromEntries(iconImports.map(name => [name, {}])), ...globals,
    TOOLBOX_SHORTCUT_ICONS: [], isScriptSupportedOnPlatform: () => true, isQuickActionSupportedOnPlatform: () => true }
  vm.runInNewContext(js, context, { timeout: 1000 })
  return { options: context.options, vue }
}

const catalogSource = source('../src/data/toolbarPreferences.js')
function getCatalog() {
  const ctx = {}
  vm.runInNewContext(catalogSource
    .replaceAll('export const ', 'const ')
    .replaceAll('export function ', 'function ')
    + '\nglobalThis.catalog = TOOLBAR_ACTION_CATALOG; globalThis.defaults = DEFAULT_TOOLBAR_PREFERENCES; globalThis.options = TOOLBAR_ACTION_OPTIONS;',
    ctx, { timeout: 1000 })
  return { actions: ctx.catalog, defaults: ctx.defaults, actionOptions: ctx.options }
}

function mountToolbar() {
  const { actions, defaults, actionOptions } = getCatalog()
  const events = []
  let dropdownCloses = 0
  const { options, vue } = readOptions('../src/components/TerminalToolbar.vue', {
    ElMessage: { warning() { throw Error('Unexpected warning') } },
    ElMessageBox: {}, ToolboxDialog: {},
    DEFAULT_TOOLBAR_PREFERENCES: defaults,
    TOOLBAR_ACTION_CATALOG: actions,
    TOOLBAR_ACTION_OPTIONS: actionOptions,
    cloneToolbarPreferences: p => ({ toolbar: [...p.toolbar], more: [...p.more], quick_actions_pinned: [] }),
    normalizeToolbarPreferences: p => p,
    normalizeToolboxPlatform: value => value, isScriptSupportedOnPlatform: () => true, isQuickActionSupportedOnPlatform: () => true,
  })
  const instance = Object.assign({}, options.data(), options.methods, {
    currentConnectionOffline: false, selectedId: 'client-1',
    $emit(event) { events.push(event) },
    $refs: { moreDropdown: { handleClose() { dropdownCloses++ } } },
    loadToolboxPinOptions() {},
  })
  // Vue normally provides computed getters; mount their dependencies in this method-level harness.
  Object.defineProperty(instance, 'deviceActionDisabled', {
    get() { return options.computed.deviceActionDisabled.call(instance) },
  })
  return { instance, options, events, get dropdownCloses() { return dropdownCloses }, vue }
}

test('Toolbox includes the shared Log Viewer action and original Lucide icon choices', () => {
  const { actions, defaults } = getCatalog()
  assert.equal(actions.length, 17)
  const ids = [...defaults.toolbar, ...defaults.more]
  assert.equal(new Set(ids).size, 17)
  assert.deepEqual(Array.from(actions, item => item.icon), [
    'folder-open', 'archive', 'monitor', 'file-code', 'history', 'terminal',
    'monitor-play', 'clipboard', 'wrench', 'scroll-text', 'calendar-clock', 'bot', 'activity',
    'key-round', 'book-open', 'code-2', 'zap',
  ])
  const { vue } = readOptions('../src/components/ToolboxDialog.vue', { Search: {}, Settings2: {}, Close: {}, FolderOpen: {}, Archive: {}, Monitor: {}, FileCode: {}, History: {}, Terminal: {}, MonitorPlay: {}, Clipboard: {}, Wrench: {}, ScrollText: {}, CalendarClock: {}, Bot: {}, Activity: {}, KeyRound: {}, BookOpen: {}, Code2: {}, Zap: {}, Rocket: {}, Play: {}, ShieldCheck: {}, Plus: {} })
  assert.match(vue, /grid-template-columns: repeat\(6, minmax\(0, 1fr\)\)/)
  assert.doesNotMatch(vue, /@closed="\$emit\('closed'\)"/, 'launch should not wait for closing animation')
  assert.doesNotMatch(vue, /draggable|@dragstart|@drop=/, 'drag-to-sort is next version only')
  assert.match(vue, /@click="action.disabled \? null : \(action.shortcut \? \$emit\('launch-pin', action.shortcut\)/)
})

test('More hover preserves the original menu while click opens Toolbox', () => {
  const app = mountToolbar()
  assert.match(app.vue, /ref="moreDropdown"\s+trigger="hover"/)
  assert.match(app.vue, /@click\.stop="openToolbox"/)
  assert.match(app.vue, /@command="handleMoreCommand"/)
  app.instance.openToolbox()
  assert.equal(app.dropdownCloses, 1)
  assert.equal(app.instance.toolboxVisible, true)
  app.instance.handleMoreCommand('action:documents')
  app.instance.handleMoreCommand('settings')
  assert.deepEqual(app.events, ['open-documents', 'open-settings'])
})

test('Toolbox launches tools immediately without waiting for the close animation', () => {
  const app = mountToolbar()
  const ids = Array.from(app.options.computed.toolboxActions.call(app.instance), item => item.id)
  assert.equal(ids.length, 17)
  assert.equal(ids[0], 'remote-files')
  assert.equal(ids.at(-1), 'quick-actions')

  app.instance.openToolbox()
  app.instance.launchToolboxAction('documents')
  assert.equal(app.instance.toolboxVisible, false)
  assert.deepEqual(app.events, ['open-documents'], 'tool launches synchronously without a closed event')

  // A rapid second click during closing must not open a second dialog.
  app.instance.launchToolboxAction('processes')
  assert.deepEqual(app.events, ['open-documents'])

  app.instance.openToolbox()
  app.instance.launchToolboxAction('processes')
  assert.deepEqual(app.events, ['open-documents', 'open-processes'])
  app.instance.openToolbox()
  app.instance.launchToolboxAction('settings')
  assert.equal(app.events.at(-1), 'open-settings')
  assert.equal(app.instance.toolboxVisible, false)
})

test('Toolbox closes its own window before synchronously dispatching the target tool', () => {
  const app = mountToolbar()
  let closedAtDispatch = false
  app.instance.$emit = event => {
    if (event === 'open-screen-view') {
      closedAtDispatch = !app.instance.toolboxVisible
    }
    app.events.push(event)
  }
  app.instance.openToolbox()
  app.instance.launchToolboxAction('screen-view')
  assert.equal(closedAtDispatch, true)
  assert.deepEqual(app.events, ['open-screen-view'])
})

test('Device tools remain disabled and cannot launch from Toolbox', () => {
  const app = mountToolbar()
  app.instance.selectedId = ''
  const entries = app.options.computed.toolboxActions.call(app.instance)
  assert.equal(entries.find(item => item.id === 'pty').disabled, true)
  assert.equal(entries.find(item => item.id === 'remote-files').disabled, true)
  assert.equal(entries.find(item => item.id === 'documents').disabled, false)
  app.instance.openToolbox()
  app.instance.launchToolboxAction('pty')
  assert.equal(app.instance.toolboxVisible, true, 'disabled entry must not close Toolbox')
  app.instance.launchToolboxAction('documents')
  assert.deepEqual(app.events, ['open-documents'])
})

test('Toolbox search is case-insensitive and does not mutate order or preferences', () => {
  const { options } = readOptions('../src/components/ToolboxDialog.vue', { Search: {}, Settings2: {}, Close: {}, FolderOpen: {}, Archive: {}, Monitor: {}, FileCode: {}, History: {}, Terminal: {}, MonitorPlay: {}, Clipboard: {}, Wrench: {}, ScrollText: {}, CalendarClock: {}, Bot: {}, Activity: {}, KeyRound: {}, BookOpen: {}, Code2: {}, Zap: {}, Rocket: {}, Play: {}, ShieldCheck: {}, Plus: {} })
  const actions = getCatalog().actions
  const instance = { ...options.data(), query: '  KEY  ', actions }
  const matched = options.computed.filteredActions.call(instance)
  assert.deepEqual(Array.from(matched, item => item.id), ['keychains'])
  assert.equal(options.computed.filteredActions.call({ ...instance, query: '' }).length, 17)
  assert.equal(actions.length, 17)
})

test('npm ci lock root matches lucide dependency (no hand-written integrity)', () => {
  const pkg = JSON.parse(source('../package.json'))
  const lock = JSON.parse(source('../package-lock.json'))
  assert.equal(pkg.dependencies['@lucide/vue'], '^1.55.0')
  assert.equal(lock.packages[''].dependencies['@lucide/vue'], pkg.dependencies['@lucide/vue'])
  assert.equal(lock.packages['node_modules/@lucide/vue'].version, '1.55.0')
  assert.match(lock.packages['node_modules/@lucide/vue'].resolved, /registry\.npmjs\.org\/\@lucide\/vue\/\-\/vue-1\.55\.0\.tgz/)
  assert.equal('integrity' in lock.packages['node_modules/@lucide/vue'], false)
})

test('Toolbox header aligns Settings and Close using the Screen View header layout', () => {
  const toolbox = source('../src/components/ToolboxDialog.vue')
  const screen = source('../src/components/ScreenViewDialog.vue')

  assert.match(toolbox, /:show-close="false"/, 'do not mix Element Plus absolute close button with custom header actions')
  assert.match(toolbox, /class="toolbox-header-actions"/)
  assert.match(toolbox, /class="toolbox-header-action"[^>]*aria-label="Settings"[^>]*@click="\$emit\('launch', 'settings'\)"/)
  assert.match(toolbox, /class="toolbox-header-action"\s+aria-label="Close"[\s\S]*?@click="\$emit\('update:visible', false\)"/)
  assert.match(toolbox, /<el-icon><Close \/><\/el-icon>/)
  assert.doesNotMatch(toolbox, /@closed="\$emit\('closed'\)"/, 'do not delay launch until close transition ends')
  assert.match(toolbox, /\.toolbox-header-actions \{[^}]*display: flex;[^}]*align-items: center;[^}]*gap: 10px;/)
  assert.match(toolbox, /\.toolbox-header-action \{[^}]*width: 32px;[^}]*height: 32px;/)
  assert.match(screen, /\.screen-view-header-actions \{[^}]*gap: 10px;/)
  assert.match(screen, /\.screen-view-header-action \{[^}]*width: 32px;[^}]*height: 32px;/)
  assert.doesNotMatch(toolbox, /toolbox-settings|padding-right: 25px;/)
})


test('Toolbar and Toolbox share Screen View and Clipboard options without opening a dialog', () => {
  const app = mountToolbar()
  const entries = app.options.computed.toolboxActions.call(app.instance)
  assert.deepEqual(Array.from(entries.find(item => item.id === 'screen-view').menuOptions, option => option.id), ['new-tab'])
  assert.deepEqual(Array.from(entries.find(item => item.id === 'clipboard').menuOptions, option => option.id), ['get', 'send'])
  assert.match(app.vue, /@command="handleScreenViewDropdownCommand"/)
  app.instance.handleScreenViewDropdownCommand('new-tab')
  assert.deepEqual(app.events, ['open-screen-view-tab'])
  app.instance.openToolbox()
  app.instance.launchToolboxAction('screen-view', 'new-tab')
  assert.equal(app.instance.toolboxVisible, false)
  assert.deepEqual(app.events, ['open-screen-view-tab', 'open-screen-view-tab'])
  app.instance.openToolbox()
  app.instance.launchToolboxAction('clipboard', 'send')
  assert.deepEqual(app.events.at(-1), 'open-clipboard')
})

test('Toolbox uses one pointer-anchored context menu and preserves shared toolbar actions', () => {
  const icons = { Search: {}, Settings2: {}, Close: {}, FolderOpen: {}, Archive: {}, Monitor: {}, FileCode: {}, History: {}, Terminal: {}, MonitorPlay: {}, Clipboard: {}, Wrench: {}, ScrollText: {}, CalendarClock: {}, Bot: {}, Activity: {}, KeyRound: {}, BookOpen: {}, Code2: {}, Zap: {}, Rocket: {}, Play: {}, ShieldCheck: {}, Plus: {} }
  const listeners = []
  const fakeWindow = {
    innerWidth: 500, innerHeight: 300,
    addEventListener: (...args) => listeners.push(['add', ...args]),
    removeEventListener: (...args) => listeners.push(['remove', ...args]),
  }
  const fakeDocument = {
    addEventListener: (...args) => listeners.push(['add', ...args]),
    removeEventListener: (...args) => listeners.push(['remove', ...args]),
  }
  const { vue, options } = readOptions('../src/components/ToolboxDialog.vue', { ...icons, window: fakeWindow, document: fakeDocument })
  assert.match(vue, /@contextmenu\.prevent\.stop="openContextMenu\(\$event, action\)"/)
  assert.match(vue, /<teleport to="body">/)
  assert.match(vue, /class="toolbox-context-menu"/)
  assert.match(vue, /role="menu"/)
  assert.match(vue, /handleContextCommand\(contextMenuAction, 'open'\)/)
  assert.match(vue, /v-for="option in contextMenuAction\.menuOptions \|\| \[\]"/)
  assert.doesNotMatch(vue, /trigger="contextmenu"|<el-dropdown-item command="open">/, 'no independently-open Element Plus dropdowns')
  assert.match(vue, /\.toolbox-context-menu \{[\s\S]*?position: fixed;/)

  const events = []
  const inside = {}
  const instance = Object.assign({}, options.data(), options.methods, {
    $emit: (...args) => events.push(args),
    $nextTick: callback => callback(),
    $refs: { contextMenu: {
      getBoundingClientRect: () => ({ width: 180, height: 115 }),
      contains: target => target === inside,
    } },
  })
  const screen = { id: 'screen-view', disabled: false, menuOptions: [{ id: 'new-tab', label: 'Open in New Tab' }] }
  const clipboard = { id: 'clipboard', disabled: false, menuOptions: [{ id: 'get', label: 'Get' }, { id: 'send', label: 'Send' }] }

  // The menu follows the click, not the icon's bounding rectangle.
  instance.openContextMenu({ clientX: 99, clientY: 71 }, screen)
  assert.equal(instance.contextMenuAction.id, 'screen-view')
  assert.deepEqual([instance.contextMenuX, instance.contextMenuY], [99, 71])
  // Right-clicking another icon replaces the existing menu. Clamp near viewport edges.
  instance.openContextMenu({ clientX: 491, clientY: 298 }, clipboard)
  assert.equal(instance.contextMenuAction.id, 'clipboard')
  assert.deepEqual([instance.contextMenuX, instance.contextMenuY], [312, 177])
  instance.onOutsidePointerDown({ target: inside })
  assert.equal(instance.contextMenuAction.id, 'clipboard', 'clicks inside the menu must not dismiss it')
  instance.handleContextCommand(clipboard, 'send')
  assert.equal(instance.contextMenuAction, null)
  assert.deepEqual(events, [['launch', 'clipboard', 'send']])

  instance.openContextMenu({ clientX: 33, clientY: 44 }, screen)
  const escape = { key: 'Escape', prevented: false, stopped: false,
    preventDefault() { this.prevented = true }, stopPropagation() { this.stopped = true } }
  instance.onGlobalKeydown(escape)
  assert.equal(instance.contextMenuAction, null)
  assert.equal(escape.prevented && escape.stopped, true)
  instance.openContextMenu({ clientX: 55, clientY: 66 }, screen)
  instance.onOutsidePointerDown({ target: {} })
  assert.equal(instance.contextMenuAction, null)
  instance.openContextMenu({ clientX: 55, clientY: 66 }, screen)
  instance.onViewportScroll({ target: {} })
  assert.equal(instance.contextMenuAction, null)
  instance.openContextMenu({ clientX: 55, clientY: 66 }, screen)
  options.watch.visible.call(instance, false)
  assert.equal(instance.contextMenuAction, null)
  const disabled = { id: 'screen-view', disabled: true }
  instance.openContextMenu({ clientX: 9, clientY: 9 }, disabled)
  assert.equal(instance.contextMenuAction, null)
  instance.handleContextCommand(disabled, 'open')
  assert.equal(events.length, 1, 'disabled entries cannot launch')

  // Only one document-level listener set is installed, and it is cleaned up.
  options.mounted.call(instance)
  options.beforeUnmount.call(instance)
  assert.equal(listeners.filter(entry => entry[0] === 'add').length, 4)
  assert.equal(listeners.filter(entry => entry[0] === 'remove').length, 4)
  assert.match(source('../src/App.vue'), /@open-screen-view-tab="openScreenViewInNewTab"/)
  assert.match(source('../src/App.vue'), /viewer\.openInNewTab\(\)/)
})
