import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import vm from 'node:vm'

const source = readFileSync(new URL('../src/components/ArtifactDialog.vue', import.meta.url), 'utf8')
const script = source.match(/<script>([\s\S]*?)<\/script>/)?.[1]
assert.ok(script)
const constants = { SAVED: 'saved', SHARED: 'shared', PREVIEW: 'preview' }
const context = { ARTIFACT_TYPE: constants, ARTIFACT_FOLDER_ALL: '__all__', DragUploadDialog: {}, File: {}, Folder: {}, FolderOpen: {}, ElMessage: {}, ElMessageBox: {} }
vm.runInNewContext(script.replace(/^import\s+[^\n]*\n/gm, '').replace('export default {', 'globalThis.component = {'), context)
const component = context.component

const files = [
  { artifact_id: 'a1', machine_id: 'machine-a', artifact_type: 'saved', folder_id: 'saved:screenshots' },
  { artifact_id: 'a2', machine_id: 'machine-a', artifact_type: 'saved', folder_id: 'saved:inbox' },
  { artifact_id: 'b1', machine_id: 'machine-b', artifact_type: 'saved', folder_id: 'saved:screenshots' },
  { artifact_id: 's1', machine_id: '', artifact_type: 'shared', folder_id: 'folder-one' },
]
function state() {
  const instance = { ...component.data(), currentConnection: { machine_id: 'machine-a' }, artifactItems: files, artifactFolders: [], standaloneMode: false, isSharedFilesTab: false }
  for (const [name, method] of Object.entries(component.methods)) instance[name] = method.bind(instance)
  instance.loadArtifacts = async () => {}
  return instance
}
const visibleIds = instance => component.computed.filteredArtifactItems.call(instance).map(x => x.artifact_id)
const counts = instance => component.computed.artifactCountMap.call(instance)

test('device toolbar entry selects current machine and Saved count reflects that machine', async () => {
  const instance = state()
  await instance.open()
  assert.equal(instance.artifactMachineIdFilter, 'machine-a')
  assert.deepEqual(visibleIds(instance), ['a1', 'a2'])
  assert.deepEqual({ ...counts(instance) }, { saved: 2, shared: 1 })
})

test('changing filter synchronizes list and Saved count; selected rows are cleared', async () => {
  const instance = state()
  await instance.open()
  instance.selectedArtifactIds = ['a1']
  instance.artifactMachineIdFilter = 'machine-b'
  instance.handleMachineFilterChange()
  assert.deepEqual(visibleIds(instance), ['b1'])
  assert.deepEqual({ ...counts(instance) }, { saved: 1, shared: 1 })
  assert.equal(instance.selectedArtifactIds.length, 0)
  instance.artifactMachineIdFilter = ''
  instance.handleMachineFilterChange()
  assert.deepEqual(visibleIds(instance), ['a1', 'a2', 'b1'])
  assert.equal(counts(instance).saved, 3)
})

test('current selected device switching while open resynchronizes filter without stale deletion selection', async () => {
  const instance = state()
  await instance.open()
  instance.selectedArtifactIds = ['a2']
  instance.selectedFolderId = 'saved:inbox'
  component.watch['currentConnection.machine_id'].call(instance, 'machine-b')
  assert.equal(instance.artifactMachineIdFilter, 'machine-b')
  assert.equal(instance.selectedFolderId, '')
  assert.equal(instance.selectedArtifactIds.length, 0)
  assert.deepEqual(visibleIds(instance), ['b1'])
  assert.equal(counts(instance).saved, 1)
})

test('standalone Utilities entry displays all Saved and Shared without following current device', async () => {
  const instance = state()
  await instance.open({ standalone: true })
  assert.equal(instance.artifactMachineIdFilter, '')
  assert.equal(counts(instance).saved, 3)
  component.watch['currentConnection.machine_id'].call(instance, 'machine-b')
  assert.equal(instance.artifactMachineIdFilter, '')
  instance.artifactActiveTab = 'shared'
  instance.isSharedFilesTab = true
  assert.deepEqual(visibleIds(instance), ['s1'])
})

test('Agent Outputs Listener cell is narrower and remains single-line truncated', () => {
  const dialog = readFileSync(new URL('../src/components/AgentOutputsDialog.vue', import.meta.url), 'utf8')
  assert.match(dialog, /label="Listener"\s+width="120"\s+show-overflow-tooltip/)
  assert.match(dialog, /class="agent-output-ellipsis" :title="row.listener_name \|\| '-'/)
})
