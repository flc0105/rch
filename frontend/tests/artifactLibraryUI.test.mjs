import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import vm from 'node:vm'

const source = readFileSync(new URL('../src/components/ArtifactDialog.vue', import.meta.url), 'utf8')
const script = source.match(/<script>([\s\S]*?)<\/script>/)?.[1]
assert.ok(script)
const sandbox = { ARTIFACT_SCOPE: { SAVED: 'saved', SHARED: 'shared', PREVIEW: 'preview' }, ARTIFACT_FOLDER_ALL: '__all__', DragUploadDialog: {}, File: {}, Folder: {}, FolderOpen: {}, ElMessage: { warning() {}, error() {}, success() {} }, ElMessageBox: {} }
vm.runInNewContext(script.replace(/^import\s+[^\n]*\n/gm, '')
  .replace('export default {', 'globalThis.component = {'), sandbox)
const c = sandbox.component

function state() {
  const s = { ...c.data(), currentConnection: null, machineAliasMap: {}, selectedId: '' }
  for (const [name, fn] of Object.entries(c.methods)) s[name] = fn.bind(s)
  return s
}

test('Saved Files opens on All Files without a duplicate source filter', () => {
  const s = state()
  assert.equal(s.artifactActiveTab, 'saved')
  assert.equal(s.selectedFolderId, '')
  assert.ok(!Object.hasOwn(s, 'artifactSourceFilter'))
  assert.equal(c.computed.artifactSourceOptions, undefined)
})

test('folder ID and device filter work without an overlapping source filter', () => {
  const s = state()
  s.artifactFolders = [
    { folder_id: 'saved:screenshots', name: 'Screenshots', scope: 'saved', parent_id: null, preset: 1 },
    { folder_id: 'saved:downloads', name: 'Downloads', scope: 'saved', parent_id: null, preset: 1 },
  ]
  s.artifactItems = [
    { artifact_id: 'a', scope: 'saved', category: 'screenshots', folder_id: 'saved:screenshots', machine_id: 'm1', original_name: 'a.png' },
    { artifact_id: 'b', scope: 'saved', category: 'downloads', folder_id: 'saved:downloads', machine_id: 'm1', original_name: 'b.png' },
    { artifact_id: 'c', scope: 'saved', category: 'downloads', folder_id: 'saved:downloads', machine_id: 'm2', original_name: 'c.zip' },
    { artifact_id: 'd', scope: 'shared', folder_id: null, original_name: 'd.zip' },
  ]
  assert.equal(c.computed.filteredArtifactItems.call(s).length, 3)
  s.selectedFolderId = 'saved:downloads'
  assert.equal(c.computed.filteredArtifactItems.call(s).length, 2)
  s.artifactMachineIdFilter = 'm1'
  assert.equal(c.computed.filteredArtifactItems.call(s)[0].artifact_id, 'b')
  assert.equal(c.computed.folderTreeNodes.call(s)[0].name, 'All Files')
})

test('switching top-level file space resets directory selection', async () => {
  const s = state()
  s.selectedFolderId = 'saved:screenshots'
  s.loadArtifacts = async () => {}
  await s.handleActiveTabChange('shared')
  assert.equal(s.artifactActiveTab, 'shared')
  assert.equal(s.selectedFolderId, '')
})

test('Artifact UI keeps file move targets tied to folder IDs, not names', () => {
  const s = state()
  s.artifactFolders = [
    { folder_id: 'root-a', name: 'Team', parent_id: null, scope: 'shared' },
    { folder_id: 'root-b', name: 'Client', parent_id: null, scope: 'shared' },
    { folder_id: 'child-a', name: 'Reports', parent_id: 'root-a', scope: 'shared' },
    { folder_id: 'child-b', name: 'Reports', parent_id: 'root-b', scope: 'shared' },
  ]
  assert.equal(s.folderFolderPath(s.artifactFolders[2]), 'Team / Reports')
  assert.equal(s.folderFolderPath(s.artifactFolders[3]), 'Client / Reports')
})

test('only Shared Files exposes Move, even when an old menu action is dispatched', async () => {
  const s = state()
  s.moveDialogVisible = false
  s.moveArtifactPrompt = c.methods.moveArtifactPrompt.bind(s)
  await c.methods.handleArtifactMoreCommand.call(s, { artifact_id: 'a', scope: 'saved' }, 'move')
  assert.equal(s.moveDialogVisible, false)
  await c.methods.handleArtifactMoreCommand.call(s, { artifact_id: 'b', scope: 'shared' }, 'move')
  assert.equal(s.moveDialogVisible, true)
  assert.match(source, /v-if="isSharedFileItem\(row\)" command="move"/)
})
