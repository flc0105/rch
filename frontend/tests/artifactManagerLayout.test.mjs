import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import vm from 'node:vm'

const source = readFileSync(new URL('../src/components/ArtifactDialog.vue', import.meta.url), 'utf8')
const template = source.slice(source.indexOf('<template>'), source.indexOf('<script>'))
const script = source.match(/<script>([\s\S]*?)<\/script>/)?.[1]
assert.ok(script)
const sandbox = { DragUploadDialog: {}, File: {}, Folder: {}, FolderOpen: {}, ElMessage: {}, ElMessageBox: {} }
vm.runInNewContext(script.replace(/^import\s+[^\n]*\n/gm, '')
  .replace('export default {', 'globalThis.component = {'), sandbox)
const component = sandbox.component

test('full-width toolbar keeps controls together before the folder tree and file table', () => {
  const tabs = template.indexOf('class="artifact-tabs"')
  const toolbar = template.indexOf('class="artifact-dialog-toolbar"')
  const sidebar = template.indexOf('class="artifact-folder-sidebar"')
  const panel = template.indexOf('class="artifact-main-panel"')
  const table = template.indexOf('class="dialog-table-shell"')
  assert.ok(tabs < toolbar && toolbar < sidebar && sidebar < panel && panel < table)
  const actions = template.slice(toolbar, sidebar)
  for (const label of ['Create File', 'Upload', 'Refresh', 'Clear', 'Rename Folder', 'Delete Folder']) {
    assert.ok(actions.includes(label), label)
  }
  assert.ok(actions.includes('placeholder="Search"'))
  assert.ok(actions.includes('placeholder="Filter by device"'))
  assert.ok(!template.includes('placeholder="Source"'))
  assert.ok(!template.includes('artifact-filter-row'))
  assert.ok(!template.includes('artifact-folder-actions'))
  assert.match(actions, /v-if="isSharedFilesTab"[^>]*@click="createSharedFilePrompt"/)
  assert.match(actions, /v-if="isSharedFilesTab"[^>]*@click="triggerSharedFileUpload"/)
  assert.match(actions, /type="danger" :loading="artifactClearing"/)
})

test('all file, folder, and bulk-action handlers stay reachable', () => {
  for (const handler of [
    'loadArtifacts', 'deleteSelectedArtifacts', 'clearCurrentArtifacts',
    'createSharedFilePrompt', 'triggerSharedFileUpload', 'createFolderPrompt',
    'renameFolderPrompt', 'deleteSelectedFolder', 'handleMachineFilterChange',
    'handleFolderSelect', 'handleArtifactSelectionChange', 'deleteArtifact',
  ]) {
    assert.match(template, new RegExp(`(?:@click|@change|@node-click|@selection-change)="${handler}\\b`), handler)
  }
  for (const label of ['Saved Files', 'Shared Files', 'All Files', 'New Folder',
    'Create File', 'Upload', 'Refresh', 'Clear', 'Preview', 'Download', 'More',
    'Size', 'Created', 'Actions']) assert.ok(source.includes(label), label)
})

test('file table uses compact non-wrapping columns and Lucide icons', () => {
  const start = template.indexOf('class="dialog-table-shell"')
  const end = template.indexOf('class="mobile-file-list-shell"', start)
  const table = template.slice(start, end)
  assert.ok(!table.includes('label="Hostname"'))
  assert.ok(!table.includes('label="Folder"'))
  assert.ok(!table.includes('fixed="right"'))
  assert.match(table, /<File :size="16"/)
  assert.match(template, /<Folder v-else :size="15"/)
  assert.match(source, /\.dialog-table-shell :deep\(\.el-table \.cell\)[\s\S]*white-space:\s*nowrap;/)
  assert.ok(table.includes('min-width="240"'))
  assert.ok(table.includes('label="Size"') && table.includes('label="Created"'))
  assert.ok(table.includes('label="Actions"'))
})

test('location label follows selected folder ID and stays All Files at root', () => {
  const ctx = { selectedFolderId: '', artifactFolders: [
    { folder_id: 'a', name: 'Projects', scope: 'saved' },
  ] }
  assert.equal(component.computed.currentFolderLabel.call(ctx), 'All Files')
  ctx.selectedFolderId = 'a'
  assert.equal(component.computed.currentFolderLabel.call(ctx), 'Projects')
  ctx.selectedFolderId = 'missing'
  assert.equal(component.computed.currentFolderLabel.call(ctx), 'All Files')
})
