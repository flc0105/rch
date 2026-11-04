import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import { test } from 'node:test'

const read = path => readFileSync(new URL(path, import.meta.url), 'utf8')
const source = read('../src/components/ClipboardDialog.vue')

function componentOptions() {
  const src = source.match(/<script>([\s\S]*?)<\/script>/)[1]
  const js = src.replace(/^import\s+[\s\S]*?\s+from\s+['"][^'"]+['"]\s*$/gm, '')
    .replace('export default {', 'const options = {') + '\nglobalThis.options = options'
  const globals = { Loading: {}, RemoteZipPeekDialog: {} }
  vm.runInNewContext(js, globals)
  return globals.options
}

test('Clipboard file preview uses existing remote preview, ZIP peek, and skips directory', () => {
  assert.match(source, /v-if="!file.is_directory"[\s\S]*?@click="previewRemoteFile\(file\)"/)
  assert.match(source, /<RemoteZipPeekDialog/)
  assert.match(read('../src/App.vue'), /<ClipboardDialog[\s\S]*?@preview-file="previewRemoteEntry"/)
  const emitted = []
  const opened = []
  const obj = {
    selectedId: 'device-1',
    $emit: (...args) => emitted.push(args),
    $refs: { remoteZipPeekDialogRef: { open: row => opened.push(row) } },
  }
  const preview = componentOptions().methods.previewRemoteFile
  preview.call(obj, { path: 'C:\\Temp\\中文 文件.txt', name: '中文 文件.txt', is_directory: false })
  assert.equal(emitted.length, 1)
  assert.equal(emitted[0][0], 'preview-file')
  assert.equal(emitted[0][1].client_id, 'device-1')
  preview.call(obj, { path: 'C:\\Temp\\abc.zip', name: 'abc.zip', is_directory: false })
  assert.equal(opened.length, 1)
  preview.call(obj, { path: 'C:\\Temp\\folder', is_directory: true })
  assert.equal(opened.length, 1)
  assert.equal(emitted.length, 1)
})
