import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import vm from 'node:vm'

const app = readFileSync(new URL('../src/App.vue', import.meta.url), 'utf8')
const source = readFileSync(new URL('../src/components/ArtifactDialog.vue', import.meta.url), 'utf8')
const template = source.slice(0, source.indexOf('<script>'))
const styles = source.split('<style scoped>')[1]
const script = source.match(/<script>([\s\S]*?)<\/script>/)?.[1]
assert.ok(script)
const sandbox = { ARTIFACT_SCOPE: { SAVED: 'saved', SHARED: 'shared', PREVIEW: 'preview' }, ARTIFACT_FOLDER_ALL: '__all__', DragUploadDialog: {}, File: {}, Folder: {}, FolderOpen: {}, ElMessage: {}, ElMessageBox: {} }
vm.runInNewContext(script.replace(/^import\s+[^\n]*\n/gm, '').replace('export default {', 'globalThis.component = {'), sandbox)
const methods = sandbox.component.methods

function appMethod(name) {
  const match = app.match(new RegExp(`    ${name}\\([^)]*\\) \\{([\\s\\S]*?)\\n    \\},`))
  assert.ok(match, `Missing App.${name}`)
  return vm.runInNewContext(`(function(command) {${match[1]}})`)
}

test('Utilities opens Artifact Manager with standalone context, independent of client selection', () => {
  assert.match(app, /<el-dropdown-item command="artifacts">Artifacts<\/el-dropdown-item>/)
  const handle = appMethod('handleBannerUtilityCommand')
  const openServer = appMethod('openServerArtifactsDialog')
  let option
  const context = {
    selectedId: 'a-live-client',
    openServerArtifactsDialog() { return openServer.call({ $refs: { artifactDialogRef: { open(value) { option = value } } } }) },
  }
  handle.call(context, 'artifacts')
  assert.deepEqual(JSON.parse(JSON.stringify(option)), { standalone: true })
  assert.match(app, /openArtifactDialog\(\) \{\s*return this\.\$refs\.artifactDialogRef\?\.open\(\)/)
})

test('standalone mode hides both device send actions in desktop and mobile menu', async () => {
  const entries = template.match(/v-if="isSharedFileItem\(row\) && !standaloneMode"/g) || []
  assert.equal(entries.length, 4)
  assert.equal((template.match(/command="send-current-device"/g) || []).length, 2)
  assert.equal((template.match(/command="send-current-device-clipboard"/g) || []).length, 2)
  let reloaded = 0
  const state = { standaloneMode: false, artifactActiveTab: 'shared', artifactMachineIdFilter: 'm1', selectedFolderId: 'x', visible: false, getCurrentMachineId: () => 'm-current', loadArtifacts() { reloaded++ } }
  await methods.open.call(state, { standalone: true })
  assert.equal(state.standaloneMode, true)
  assert.equal(state.visible, true)
  assert.equal(state.artifactActiveTab, 'saved')
  assert.equal(reloaded, 1)
  await methods.open.call(state)
  assert.equal(state.standaloneMode, false, 'opening from device toolbar must restore device actions')
  assert.equal(state.artifactMachineIdFilter, 'm-current')
  assert.equal(reloaded, 2)
})

test('standalone mode prevents device send handlers even if invoked programmatically', async () => {
  const ctx = { standaloneMode: true, selectedId: 'a-live-client' }
  await methods.sendArtifactToCurrentDevice.call(ctx, { artifact_id: 'file' })
  await methods.sendArtifactToCurrentDeviceClipboard.call(ctx, { artifact_id: 'file' })
  const send = methods.sendArtifactToCurrentDevice.toString()
  assert.match(send, /if \(this\.standaloneMode\) return[\s\S]*await prepareUploadConflict/)
  assert.match(send, /if \(conflictPolicy === false \|\| this\.standaloneMode/)
})

test('Saved and Shared folder headings have the same fixed height', () => {
  assert.match(styles, /\.artifact-folder-heading\s*\{[^}]*height:\s*34px;[^}]*min-height:\s*34px;/)
  assert.match(template, /v-if="isSharedFilesTab"[^>]*@click="createFolderPrompt"/)
  assert.match(template, /class="artifact-folder-heading"/)
})
