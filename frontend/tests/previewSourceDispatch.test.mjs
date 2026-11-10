import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import {test} from 'node:test'
import vm from 'node:vm'

const source = readFileSync(new URL('../src/components/PreviewDialog.vue', import.meta.url), 'utf8')
const script = source.match(/<script>([\s\S]*?)<\/script>/)?.[1]
assert.ok(script)
const warnings = []
const sandbox = {
  ElMessage: {warning: value => warnings.push(value), error() {}, success() {}},
  PreviewImageInfoDialog: {}, ArchivePreviewPanel: {}, RemoteZipEntryActions: {}, Close: {}, FullScreen: {},
  formatBytes: value => `${value} B`,
}
vm.runInNewContext(script.replace(/^import\s+[^\n]*\n/gm, '')
  .replace('export default {', 'globalThis.component = {'), sandbox)
const component = sandbox.component
const cases = [
  ['remote_file', 'Remote File', 'saveToRemoteFile', 'fetchLatestRemoteFileTextPayload'],
  ['artifact', 'Artifact', 'saveToArtifact', 'fetchLatestArtifactTextPayload'],
  ['new_shared_file', 'Artifact', 'saveToNewSharedFile', null],
  ['background_job', 'Background Job', 'saveToBackgroundJob', 'fetchLatestBackgroundJobTextPayload'],
  ['server_script', 'Server Script', 'saveToServerScript', 'fetchLatestServerScriptTextPayload'],
  ['external_tool_meta', 'External Tool Meta', 'saveToExternalToolMeta', 'fetchLatestExternalToolMetaTextPayload'],
]

function stateFor(sourceName) {
  const state = {
    ...component.data(),
    previewSource: sourceName,
    previewEditable: true,
    getMonacoEditorContent: () => 'new content',
  }
  for (const [name, method] of Object.entries(component.methods)) state[name] = method.bind(state)
  state.getMonacoEditorContent = () => 'new content'
  return state
}

test('all six preview sources use the same declared label/save/reload contract', async () => {
  for (const [name, label, save, reload] of cases) {
    const state = stateFor(name)
    const calls = []
    state[save] = async content => calls.push([save, content])
    assert.equal(component.computed.previewSourceLabel.call(state), label)
    await state.saveEditedContent()
    assert.deepEqual(calls, [[save, 'new content']])
    if (reload) {
      state[reload] = async () => ({source: name})
      assert.equal((await state.fetchLatestPreviewTextPayload()).source, name)
    } else {
      await assert.rejects(state.fetchLatestPreviewTextPayload(), /not been created yet/)
    }
  }
})

test('truncated or noneditable existing files refuse save without invoking any save handler', async () => {
  for (const sourceName of ['remote_file', 'artifact']) {
    const state = stateFor(sourceName)
    state.previewTruncated = true
    state.saveToRemoteFile = state.saveToArtifact = () => { throw Error('must not save') }
    await state.saveEditedContent()
    state.previewTruncated = false
    state.previewEditable = false
    await state.saveEditedContent()
  }
  assert.equal(warnings.filter(x => x === 'Editing is disabled for this file').length, 4)
})

test('unknown source shows same warning, without reading editor or invoking any save', async () => {
  const state = stateFor('not_supported')
  state.getMonacoEditorContent = () => { throw Error('must not access editor') }
  assert.equal(component.computed.previewSourceLabel.call(state), 'Unknown')
  await state.saveEditedContent()
  await assert.rejects(state.fetchLatestPreviewTextPayload(), /Unknown preview source/)
  assert.equal(warnings.at(-1), 'Unknown preview source')
})
