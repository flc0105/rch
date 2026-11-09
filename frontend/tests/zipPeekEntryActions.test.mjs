import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import { downloadRemoteZipEntry, extractRemoteZip } from '../src/api/remoteFilesApi.js'

const source = name => readFileSync(new URL(`../src/components/${name}`, import.meta.url), 'utf8')
const evaluate = (file, globals) => {
  const text = source(file).match(/<script>([\s\S]*?)<\/script>/)?.[1]
  assert.ok(text)
  const code = text.replace(/^import\s+[^\n]*\n/gm, '').replace('export default {', 'globalThis.component = {')
  vm.runInNewContext(code, globals)
  return globals.component
}
const instance = (component, overrides = {}) => {
  const target = {...(component.data?.() || {}), $refs: {}, $emit: () => {}, $nextTick: async () => {}, ...overrides}
  for (const [name, fn] of Object.entries(component.methods || {})) target[name] = fn.bind(target)
  return target
}

async function capture(call) {
  const originalFetch = globalThis.fetch
  const events = []
  globalThis.fetch = (url, options) => { events.push({url, options}); return Promise.resolve({ok: true}) }
  try { await call(); return events[0] } finally { globalThis.fetch = originalFetch }
}

test('ZIP entry API separates full download from read-only preview and reuses extraction endpoint', async () => {
  const download = await capture(() => downloadRemoteZipEntry('client /1', '/Downloads/文件.zip', 'sub/file.bin'))
  assert.equal(download.url, '/api/connections/client%20%2F1/remote-files/download-zip-entry')
  assert.deepEqual(JSON.parse(download.options.body), {path:'/Downloads/文件.zip', entry_name:'sub/file.bin'})
  assert.equal(download.options.headers['X-RCH-Origin'], 'web_ui')
  const extract = await capture(() => extractRemoteZip('client /1', {
    path: '/Downloads/文件.zip', destination_dir: '/target', entry_name:'root/sub',
  }))
  assert.equal(extract.url, '/api/connections/client%20%2F1/remote-files/extract-zip')
  assert.deepEqual(JSON.parse(extract.options.body), {
    path:'/Downloads/文件.zip', destination_dir:'/target', entry_name:'root/sub',
  })
})

test('archive tree remembers selected folder and keeps file actions independent of text preview', async () => {
  const panel = instance(evaluate('ArchivePreviewPanel.vue', {formatBytesValue: String}))
  let reads = 0
  panel.readEntry = async () => { reads++; return {ok:true,json:async()=>({code:0,data:{type:'binary'}})} }
  panel.inspect = async () => ({ok:true,json:async()=>({code:0,data:{tree:[]}})})
  await panel.loadArchive()
  await panel.handleTreeNodeClick({path:'root/sub', name:'sub', is_dir:true})
  assert.equal(panel.selectedEntry.path, 'root/sub')
  assert.equal(reads, 0)
  await panel.handleTreeNodeClick({path:'root/a.bin', entry_name:'root/a.bin', name:'a.bin', is_dir:false})
  assert.equal(reads, 1)
  assert.equal(panel.selectedEntry.path, 'root/a.bin')
  assert.match(source('ArchivePreviewPanel.vue'), /@click="\$emit\('download-entry', selectedEntry\)"/)
  assert.match(source('ArchivePreviewPanel.vue'), /@click="\$emit\('extract-entry', selectedEntry\)"/)
})

test('file transfer opens downloaded artifact and folder extraction sends the selected subtree to chosen directory', async () => {
  const calls = [], messages = [], notifications = []
  const component = evaluate('RemoteZipEntryActions.vue', {
    RemoteFilePicker: {},
    ElMessage: {success: value => messages.push(value), error: err => {throw new Error(err)}},
    ElMessageBox: {confirm: async (...args) => calls.push(['confirm',...args])},
    downloadRemoteZipEntry: async (...args) => {calls.push(['download',...args]); return {ok:true,json:async()=>({code:0,data:{artifact:{artifact_id:'abc',download_url:'/dl/abc'}}})}},
    extractRemoteZip: async (...args) => {calls.push(['extract',...args]); return {ok:true,json:async()=>({code:0,data:{extracted_to:'/target/sub'}})}},
    window: {open: (...args) => calls.push(['open',...args])},
  })
  const action = instance(component, {selectedId: 'client-1', archivePath:'C:\\zip\\example.zip', $emit: name => notifications.push(name)})
  await action.downloadEntry({name:'blob.bin',path:'folder/blob.bin',entry_name:'folder/blob.bin',is_dir:false})
  assert.deepEqual(calls[0], ['download','client-1','C:\\zip\\example.zip','folder/blob.bin'])
  assert.deepEqual(calls[1], ['open','/dl/abc','_blank'])
  assert.equal(notifications[0], 'artifacts-maybe-changed')
  action.extractEntry({name:'sub',path:'folder/sub',is_dir:true})
  assert.equal(action.folderPickerVisible, true)
  assert.equal(action.pickerInitialPath, 'C:\\zip')
  await action.extractToFolder('/target')
  assert.equal(calls[2][0], 'confirm')
  assert.deepEqual(JSON.parse(JSON.stringify(calls[3][2])), {path:'C:\\zip\\example.zip', destination_dir:'/target', entry_name:'folder/sub'})
  assert.equal(notifications[1], 'remote-directory-maybe-changed')
  assert.equal(action.pendingEntry, null)
})

test('folder picker adds optional current folder selection without changing ordinary callers', () => {
  const component = evaluate('RemoteFilePicker.vue', {listRemoteDirectory(){}, getRemoteSystemPaths(){}, ElMessage:{}, ElMessageBox:{},formatBytesValue(){},uploadRemoteFileToClient(){}})
  assert.equal(component.props.allowCurrentFolder.default, false)
  assert.equal(component.props.appendToBody.default, false)
  const selections=[]
  const picker=instance(component, {allowCurrentFolder:true, selectionMode:'folder', multiple:false,
    remoteFilesCurrentPath:'/target', remoteFilesLoading:false, $emit:(...a)=>selections.push(a)})
  picker.selectCurrentFolder()
  assert.deepEqual(selections, [['select','/target'], ['update:visible',false]])
})

test('both remote ZIP preview entry points wire actions; artifact archive preview stays read-only', () => {
  assert.match(source('RemoteZipPeekDialog.vue'), /<RemoteZipEntryActions/)
  assert.match(source('RemoteZipPeekDialog.vue'), /entry-actions @download-entry=/)
  const preview=source('PreviewDialog.vue')
  assert.match(preview, /:entry-actions="previewSource === 'remote_file'"/)
  assert.match(preview, /v-if="previewSource === 'remote_file'"\s+ref="archiveActionsRef"/)
  assert.match(source('RemoteZipEntryActions.vue'), /selection-mode="folder"/)
})
