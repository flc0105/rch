import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import vm from 'node:vm'

const source = readFileSync(new URL('../src/components/ArtifactDialog.vue', import.meta.url), 'utf8')
const template = source.slice(0, source.indexOf('<script>'))
const script = source.match(/<script>([\s\S]*?)<\/script>/)?.[1]
assert.ok(script, 'ArtifactDialog must contain an Options API script')

const sandbox = {
  ARTIFACT_TYPE: Object.freeze({ SAVED: 'saved', SHARED: 'shared', PREVIEW: 'preview' }),
  ARTIFACT_FOLDER_ALL: '__all__',
  DragUploadDialog: {}, File: {}, Folder: {}, FolderOpen: {},
  ElMessage: {}, ElMessageBox: {},
}
vm.runInNewContext(
  script.replace(/^import\s+[^\n]*\n/gm, '').replace('export default {', 'globalThis.component = {'),
  sandbox,
)
const component = sandbox.component

test('every artifact constant referenced in the template is exposed by the Options API component', () => {
  const data = component.data()
  const publicNames = new Set([
    ...Object.keys(data),
    ...Object.keys(component.computed || {}),
    ...Object.keys(component.methods || {}),
    ...Object.keys(component.props || {}),
  ])
  const constants = new Set(template.match(/\bARTIFACT_[A-Z_]+\b/g) || [])
  assert.deepEqual([...constants].sort(), ['ARTIFACT_FOLDER_ALL', 'ARTIFACT_TYPE'])
  for (const name of constants) {
    assert.ok(publicNames.has(name), `${name} referenced in template but unavailable on Vue Options API render context`)
  }
  assert.equal(data.ARTIFACT_TYPE.SAVED, 'saved')
  assert.equal(data.ARTIFACT_TYPE.SHARED, 'shared')
  assert.equal(data.ARTIFACT_FOLDER_ALL, '__all__')
})
