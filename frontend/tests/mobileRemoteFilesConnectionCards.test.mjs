import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import { test } from 'node:test'

const read = path => readFileSync(new URL(path, import.meta.url), 'utf8')
function optionsFrom(path, globals = {}) {
  const vue = read(path)
  const script = vue.match(/<script>([\s\S]*?)<\/script>/)?.[1]
  assert.ok(script, `${path} should contain a component script`)
  const js = script.replace(/^import\s+[\s\S]*?\s+from\s+['"][^'"]+['"]\s*;?\s*$/gm, '')
    .replace('export default {', 'const options = {') + '\nglobalThis.options = options'
  const context = { MoreFilled: {}, ...globals }
  vm.runInNewContext(js, context, { timeout: 1000 })
  return { vue, options: context.options }
}

test('Remote Files mobile toolbar uses one compact action dropdown and keeps desktop toolbar', () => {
  const { vue, options } = optionsFrom('../src/components/RemoteFilesDialog.vue', {
    RemotePinsDialog: {}, RemoteZipPeekDialog: {}, formatBytesValue: value => String(value), uploadRemoteFileToClient() {},
    ElMessage: {}, ElMessageBox: {},
  })
  assert.equal(options.data().remoteMobileViewMode, 'card')
  assert.match(vue, /class="remote-mobile-tools-dropdown"[\s\S]*?class="remote-mobile-tools-button"/)
  assert.match(vue, /class="remote-mobile-search-row"[\s\S]*?class="remote-mobile-search-input"/)
  assert.match(vue, /command="view_card"[\s\S]*?command="view_list"/)
  assert.match(vue, /class="remote-files-toolbar"[\s\S]*?Quick Jump/)
  for (const command of ['refresh', 'up', 'root', 'input_navigate', 'new_folder', 'upload', 'download_selected', 'delete_selected', 'toggle_recursive', 'toggle_pin', 'manage_pins', 'copy', 'cut', 'create_zip', 'paste', 'clear_clipboard', 'toggle_select_all', 'clear_selection', 'toggle_hidden']) {
    assert.match(vue, new RegExp(`command="${command}"`), `${command} should be available from the mobile action dropdown or its shared action menu`)
  }
  assert.ok(vue.indexOf('class="remote-mobile-breadcrumb-row"') < vue.indexOf('class="remote-mobile-search-row"'), 'mobile search must sit below the breadcrumb row')
  assert.match(vue, /class="remote-mobile-pagination"[\s\S]*?aria-label="Previous page"[\s\S]*?aria-label="Next page"/)
  assert.match(vue, /popper-class="remote-mobile-tools-popper"/)
  assert.doesNotMatch(vue, /Show tools|Hide tools|remote-mobile-view-switch/)
  assert.match(vue, /v-if="remoteMobileViewMode === 'card'"[\s\S]*?class="mobile-file-card"/)
  assert.match(vue, /class="remote-mobile-file-row"[\s\S]*?class="remote-mobile-file-more-button"/)
  assert.match(vue, /:disabled="row\.is_parent_entry"[\s\S]*?row\.is_dir \? '📁' : '📄'/)
  assert.match(vue, /row\.is_dir \? '-' : formatBytes\(row\.size\)/)
  assert.match(vue, /remote-mobile-file-checkbox" @click\.stop[\s\S]*?:disabled="row\.is_parent_entry"/)
  const cardStart = vue.indexOf('class="mobile-file-card"')
  const cardEnd = vue.indexOf('class="mobile-file-card-top"', cardStart)
  assert.ok(cardStart >= 0 && cardEnd > cardStart)
  assert.doesNotMatch(vue.slice(cardStart, cardEnd), /v-if="!row\.is_parent_entry"/)
  const listStart = vue.indexOf('class="remote-mobile-file-row"')
  const listEnd = vue.indexOf('class="remote-mobile-file-row-main"', listStart)
  assert.ok(listStart >= 0 && listEnd > listStart)
  assert.doesNotMatch(vue.slice(listStart, listEnd), /v-if="!row\.is_parent_entry" class="remote-mobile-file-checkbox"/)
  for (const action of ['open', 'preview', 'download', 'rename', 'copy', 'cut', 'copy_path', 'extract', 'delete']) {
    assert.match(vue, new RegExp(`command="${action}"`), `${action} action should remain available`)
  }
  assert.match(vue, /\.remote-files-toolbar\s*\{\s*display:\s*none !important;/)
  assert.match(vue, /\.remote-mobile-pagination\s*\{\s*display:\s*flex;/)
})

test('Remote Files compact page range is stable at the beginning, middle, and end', () => {
  const { options } = optionsFrom('../src/components/RemoteFilesDialog.vue', {
    RemotePinsDialog: {}, RemoteZipPeekDialog: {}, formatBytesValue: value => String(value), uploadRemoteFileToClient() {},
    ElMessage: {}, ElMessageBox: {},
  })
  const pageItems = (page, totalPages) => options.computed.remoteMobilePageItems.call({ remoteFilesPage: page, remoteFilesTotalPages: totalPages })
  assert.deepEqual(JSON.parse(JSON.stringify(pageItems(1, 10).map(item => item.page ?? item.type))), [1, 2, 3, 4, 'ellipsis', 10])
  assert.deepEqual(JSON.parse(JSON.stringify(pageItems(6, 10).map(item => item.page ?? item.type))), [1, 'ellipsis', 5, 6, 7, 'ellipsis', 10])
  assert.deepEqual(JSON.parse(JSON.stringify(pageItems(10, 10).map(item => item.page ?? item.type))), [1, 'ellipsis', 7, 8, 9, 10])
  assert.deepEqual(JSON.parse(JSON.stringify(pageItems(1, 3).map(item => item.page ?? item.type))), [1, 2, 3])
})

test('Remote Files mobile dropdown dispatches toolbar actions and Card/List choices', () => {
  const { options } = optionsFrom('../src/components/RemoteFilesDialog.vue', {
    RemotePinsDialog: {}, RemoteZipPeekDialog: {}, formatBytesValue: value => String(value), uploadRemoteFileToClient() {},
    ElMessage: {}, ElMessageBox: {},
  })
  const calls = []
  const instance = {
    ...options.data(),
    ...options.methods,
    refreshRemoteDirectory: () => calls.push('refresh'),
    goToRemoteParent: () => calls.push('up'),
    createRemoteDirectory: () => calls.push('new_folder'),
    triggerRemoteUpload: () => calls.push('upload'),
    downloadSelectedRemoteEntries: () => calls.push('download_selected'),
    deleteSelectedRemoteEntries: () => calls.push('delete_selected'),
    jumpToPath: command => calls.push(['jump', command]),
    handleRemoteToolbarMoreCommand: command => calls.push(['more', command]),
    handleRemoteSearchRecursiveChange: () => calls.push('recursive_changed'),
  }
  instance.handleRemoteMobileToolsCommand('refresh')
  instance.handleRemoteMobileToolsCommand('up')
  instance.handleRemoteMobileToolsCommand('new_folder')
  instance.handleRemoteMobileToolsCommand('upload')
  instance.handleRemoteMobileToolsCommand('download_selected')
  instance.handleRemoteMobileToolsCommand('delete_selected')
  instance.handleRemoteMobileToolsCommand('view_list')
  instance.handleRemoteMobileToolsCommand('view_card')
  instance.handleRemoteMobileToolsCommand('toggle_recursive')
  instance.handleRemoteMobileToolsCommand('root')
  instance.handleRemoteMobileToolsCommand({ type: 'pinned_jump', path: '/saved' })
  instance.handleRemoteMobileToolsCommand('toggle_hidden')
  assert.equal(instance.remoteMobileViewMode, 'card')
  assert.equal(instance.remoteSearchRecursive, true)
  assert.deepEqual(JSON.parse(JSON.stringify(calls)), [
    'refresh', 'up', 'new_folder', 'upload', 'download_selected', 'delete_selected',
    'recursive_changed', ['jump', 'root'], ['jump', { type: 'pinned_jump', path: '/saved' }], ['more', 'toggle_hidden'],
  ])
})

test('Remote Files list row opens directories, leaves file-row taps inert, and routes menu actions', () => {
  const { options } = optionsFrom('../src/components/RemoteFilesDialog.vue', {
    RemotePinsDialog: {}, RemoteZipPeekDialog: {}, formatBytesValue: value => String(value), uploadRemoteFileToClient() {},
    ElMessage: {}, ElMessageBox: {},
  })
  const calls = []
  const instance = {
    ...options.data(),
    ...options.methods,
    enterRemoteDirectory: row => calls.push(['enter', row.path]),
    goToRemoteParent: () => calls.push(['parent']),
    previewRow: row => calls.push(['preview', row.path]),
    downloadRemoteEntry: row => calls.push(['download', row.path]),
    handleRemoteMoreAction: (command, row) => calls.push([command, row.path]),
  }
  instance.handleRemoteMobileListRowClick({ path: '/folder', is_dir: true })
  instance.handleRemoteMobileListRowClick({ path: '/file.txt', is_dir: false })
  instance.handleRemoteMobileListRowClick({ path: '/parent', is_dir: true, is_parent_entry: true })
  instance.handleRemoteMobileListAction('preview', { path: '/file.txt' })
  instance.handleRemoteMobileListAction('download', { path: '/file.txt' })
  instance.handleRemoteMobileListAction('rename', { path: '/folder' })
  assert.deepEqual(JSON.parse(JSON.stringify(calls)), [
    ['enter', '/folder'], ['parent'], ['preview', '/file.txt'], ['download', '/file.txt'], ['rename', '/folder'],
  ])
})

test('Connection History mobile cards preserve session detail and activity controls while desktop table remains', () => {
  const { vue, options } = optionsFrom('../src/components/MachineConnectionHistoryDialog.vue', {
    ElMessage: {}, getMachineConnectionCommands() {}, getMachineConnectionHistory() {},
    diffDateTimeMs: () => 0, formatDateTimeStandard: value => value, formatLaunchMode: () => 'user_service',
  })
  assert.match(vue, /class="machine-history-mobile-list"/)
  assert.match(vue, /class="machine-history-table"/)
  for (const field of ['Hostname', 'Address', 'OS', 'User', 'Process', 'Launch mode', 'Build', 'Last seen', 'Termination', 'cwd']) {
    assert.match(vue, new RegExp(`>${field}<`), `${field} should remain in mobile details`)
  }
  assert.match(vue, /@click="toggleMobileSessionDetails\(row\)"/)
  assert.match(vue, /@click="loadSessionCommands\(row, true\)"/)
  assert.match(vue, /@media \(max-width: 768px\)\s*\{[\s\S]*?\.machine-history-table\s*\{\s*display:\s*none/s)
  assert.match(vue, /\.machine-history-mobile-list\s*\{\s*display:\s*flex/s)

  const instance = { ...options.data(), ...options.methods }
  const loaded = []
  instance.loadSessionCommands = row => loaded.push(row.client_id)
  const session = { client_id: 'client-1', command_count: 2, command_loaded: false, command_loading: false }
  instance.toggleMobileSessionDetails(session)
  assert.equal(instance.isMobileSessionExpanded(session), true)
  assert.deepEqual(loaded, ['client-1'])
  instance.toggleMobileSessionDetails(session)
  assert.equal(instance.isMobileSessionExpanded(session), false)
})
