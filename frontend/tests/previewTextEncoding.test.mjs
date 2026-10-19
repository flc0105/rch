import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import {dirname, resolve} from 'node:path'
import {fileURLToPath} from 'node:url'
import vm from 'node:vm'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const source = readFileSync(resolve(root, 'src/components/PreviewDialog.vue'), 'utf8')
const script = source.match(/<script>([\s\S]*?)<\/script>/)?.[1]
assert.ok(script)
const fetchCalls = []
const messages = []
let response = null
const sandbox = {
  console,
  PreviewImageInfoDialog: {},
  FullScreen: {},
  Close: {},
  formatBytes: value => `${value} B`,
  ElMessage: {success: message => messages.push(message),
    warning: message => messages.push(message), error: message => messages.push(message)},
  fetch: async (url, options) => {
    fetchCalls.push({url, options})
    return response
  },
}
vm.runInNewContext(script.replace(/^import\s+[^\n]*\n/gm, '').replace('export default {', 'globalThis.component = {'), sandbox)
const comp = sandbox.component
function makeVm() {
  const vmState = {...comp.data(),
    $nextTick: callback => callback(),
    $emit: () => {},
    previewFilePath: 'aid',
    previewSource: 'artifact',
    previewTitle: 'file.txt',
    initCalls: [],
    initMonacoEditor(text, readOnly) {this.initCalls.push({text, readOnly})},
    setMonacoEditorReadOnly(readOnly) {this.readOnly = readOnly},
    getMonacoEditorContent() {return 'Edited 世界'},
    getLanguageDisplayName: str => str,
    getLanguageFromFilename: () => 'plaintext',
  }
  for (const [key, method] of Object.entries(comp.methods)) {
    if (!(key in vmState)) vmState[key] = method.bind(vmState)
  }
  return vmState
}

assert.match(source, /!previewEditMode && !previewTruncated && previewEditable/)
assert.doesNotMatch(source, /- Edit disabled/)
assert.doesNotMatch(source, /Full content/)
assert.match(source, /:type="previewFileCodec === 'unknown' \? 'warning' : 'info'"/)
assert.match(source, /<template #header>/)
assert.match(source, /<el-icon><FullScreen \/><\/el-icon>/)
assert.match(source, /<el-icon><Close \/><\/el-icon>/)
assert.match(source, /@command="handlePreviewMoreCommand"/)
// Copy, Save, More (dropdown) and Cancel must have one consistent gap.
assert.match(source, /\.preview-toolbar-left\s*\{[^}]*\bgap:\s*8px\s*;/)
assert.match(source, /\.preview-toolbar-left\s+:deep\(\.el-button\)\s*\{[^}]*\bmargin-left:\s*0\s*;/)
assert.match(source, /<el-dropdown-item command="paste">Paste<\/el-dropdown-item>/)
assert.match(source, /<el-dropdown-item command="clear">Clear<\/el-dropdown-item>/)
assert.match(source, /command="reload"/)
assert.match(source, />\s*Truncated\s*<\/el-tag>/)
assert.doesNotMatch(source, /preview-fullscreen-toggle/)
const vmActions = makeVm()
const invoked = []
vmActions.pastePreviewText = () => invoked.push('paste')
vmActions.clearPreviewContent = () => invoked.push('clear')
vmActions.reloadPreviewContent = () => invoked.push('reload')
for (const command of ['paste', 'clear', 'reload']) vmActions.handlePreviewMoreCommand(command)
assert.deepEqual(invoked, ['paste', 'clear', 'reload'])
assert.doesNotMatch(source, /detectEncoding\(/)
const fakePayload = data => ({ok: true, json: async () => ({code: 0, data})})

const vmUnknown = makeVm()
response = fakePayload({type: 'text', name: 'gbk.txt', content: '�', truncated: false,
  encoding: 'unknown', editable: false})
await vmUnknown.loadPreviewPayload(() => sandbox.fetch('/preview'))
assert.equal(vmUnknown.previewFileEncoding, 'Unknown encoding')
assert.equal(vmUnknown.previewFileCodec, 'unknown')
assert.equal(vmUnknown.previewEditable, false)
assert.deepEqual(vmUnknown.initCalls.map(x => x.readOnly), [true])
vmUnknown.enterEditMode()
assert.equal(vmUnknown.previewEditMode, false)
const saveAttempts = fetchCalls.length
await vmUnknown.saveEditedContent()
assert.equal(fetchCalls.length, saveAttempts)
assert.ok(messages.includes('Editing is disabled for this file'))

for (const [codec, label] of [
  ['utf-8', 'UTF-8'], ['utf-8-sig', 'UTF-8 with BOM'],
  ['utf-16-le', 'UTF-16 LE with BOM'], ['utf-16-be', 'UTF-16 BE with BOM']]) {
  const state = makeVm()
  response = fakePayload({type: 'text', name: 'file.txt', content: 'One\r\nTwo',
    encoding: codec, editable: true, truncated: false})
  await state.loadPreviewPayload(() => sandbox.fetch('/preview'))
  assert.equal(state.previewFileEncoding, label)
  assert.equal(state.previewFileCodec, codec)
  assert.equal(state.previewEditable, true)
  state.enterEditMode()
  assert.equal(state.previewEditMode, true)
  response = fakePayload({size: 12})
  await state.saveEditedContent()
  const posted = fetchCalls.at(-1)
  assert.equal(JSON.parse(posted.options.body).encoding, codec)
  assert.equal(JSON.parse(posted.options.body).content, 'Edited 世界')
  assert.equal(state.previewEditMode, false)
}

const vmRemote = makeVm()
vmRemote.previewSource = 'remote_file'
vmRemote.previewRemoteClientId = 'client-1'
vmRemote.previewFilePath = '/tmp/file.txt'
vmRemote.previewFileCodec = 'utf-16-be'
response = fakePayload({})
await vmRemote.saveToRemoteFile('Changed')
assert.equal(JSON.parse(fetchCalls.at(-1).options.body).encoding, 'utf-16-be')

const vmReload = makeVm()
vmReload.previewEditMode = true
vmReload.previewEditable = true
vmReload.applyReloadedPreviewText({content:'�', encoding:'unknown', editable:false})
assert.equal(vmReload.previewEditMode, false)
assert.equal(vmReload.previewEditable, false)
assert.equal(vmReload.initCalls.at(-1).readOnly, true)
vmReload.applyReloadedPreviewText({content:'hello', encoding:'utf-8', editable:true, truncated:false})
assert.equal(vmReload.previewEditMode, true)
assert.equal(vmReload.initCalls.at(-1).readOnly, false)
vmReload.applyReloadedPreviewText({content:'...truncated', encoding:'utf-8', editable:false, truncated:true})
assert.equal(vmReload.previewEditMode, false)

const remoteLoad = makeVm()
remoteLoad.previewFilePath = ''
remoteLoad.previewRemoteClientId = ''
remoteLoad.selectedId = 'client-A'
response = fakePayload({type:'text', name:'remote.txt', content:'hello',
  encoding:'utf-8', editable:true, truncated:false})
await remoteLoad.previewRemoteEntry({path:'/tmp/remote.txt', name:'remote.txt', client_id:'client-B'})
assert.equal(remoteLoad.previewRemoteClientId, 'client-B')
assert.equal(remoteLoad.previewFilePath, '/tmp/remote.txt')
response = fakePayload({})
await remoteLoad.saveToRemoteFile('hello again')
assert.match(fetchCalls.at(-1).url, /client-B/)

// Moving from unknown-encoding preview to a new file/source must not inherit readonly.
const nextSource = makeVm()
nextSource.previewFileCodec = 'unknown'
nextSource.previewEditable = false
nextSource.openNewSharedFileEditor('new.txt')
assert.equal(nextSource.previewFileCodec, 'utf-8')
assert.equal(nextSource.previewEditable, true)
assert.equal(nextSource.previewEditMode, true)

console.log('Preview text strict encoding, readonly, reload and save requests passed')
