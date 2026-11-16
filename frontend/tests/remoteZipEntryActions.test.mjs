import assert from 'node:assert/strict'
import { test } from 'node:test'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import { downloadRemoteZipEntry, extractRemoteZip } from '../src/api/remoteFilesApi.js'

const source = readFileSync(new URL('../src/components/RemoteZipEntryActions.vue', import.meta.url), 'utf8')
const script = source.match(/<script>([\s\S]*?)<\/script>/)?.[1]
assert.ok(script)
const notifications = []
const sandbox = {
  RemoteFilePicker: {},
  ElMessage: {
    success(message) { notifications.push(['success', message]) },
    error(message) { notifications.push(['error', message]) },
  },
  ElMessageBox: { confirm: async () => {} },
  downloadRemoteZipEntry, extractRemoteZip,
  prepareExtractConflict: async () => null,
  window: { open(url) { notifications.push(['open', url]) } },
}
vm.runInNewContext(script.replace(/^import[^\n]*\n/gm, '').replace('export default {', 'globalThis.component = {'), sandbox)
const options = sandbox.component
const response = data => ({ok: true, json: async () => ({code: 0, data})})
const create = () => {
  const instance = {
    ...options.data(), selectedId: 'c', archivePath: '/home/archive.zip',
    $nextTick: async () => {}, $emit(name) { notifications.push(['event', name]) },
  }
  for (const [key, fn] of Object.entries(options.methods)) instance[key] = fn.bind(instance)
  return instance
}

async function withFetch(handler) {
  const previous = globalThis.fetch
  globalThis.fetch = handler
  try { await handler.run() } finally { globalThis.fetch = previous }
}

test('remote ZIP file download uses an Artifact, without temporary remote filesystem writes', async () => {
  notifications.length = 0
  const actor = create()
  const requests = []
  const fake = (url, opts) => {
    requests.push([url, opts])
    return Promise.resolve(response({artifact: {artifact_id: 'abc', download_url: '/download/abc'}}))
  }
  fake.run = async () => {
    await actor.downloadEntry({path:'deep/binary.dat',entry_name:'deep/binary.dat',name:'binary.dat',is_dir:false})
  }
  await withFetch(fake)
  assert.equal(requests.length, 1)
  assert.equal(requests[0][0], '/api/connections/c/remote-files/download-zip-entry')
  assert.equal(JSON.parse(requests[0][1].body).entry_name, 'deep/binary.dat')
  assert.deepEqual(notifications.filter(item => item[0] === 'open'), [['open','/download/abc']])
  assert.ok(notifications.some(item => item[1] === 'artifacts-maybe-changed'))
  assert.equal(actor.downloading, false)
  await actor.downloadEntry({path:'folder',name:'folder',is_dir:true})
  assert.equal(requests.length, 1, 'directory must not trigger direct download')
})

test('selecting a folder carries the selected archive directory to the existing extract route', async () => {
  notifications.length = 0
  const actor = create()
  actor.extractEntry({path:'root/nested', name:'nested', is_dir:true})
  assert.equal(actor.folderPickerVisible, true)
  assert.equal(actor.pickerInitialPath, '/home')
  assert.equal(actor.pendingEntry.path, 'root/nested')
  const requests = []
  const fake = (url, opts) => {
    requests.push([url, opts])
    return Promise.resolve(response({extracted_to:'/target/nested'}))
  }
  fake.run = async () => { await actor.extractToFolder('/target') }
  await withFetch(fake)
  assert.equal(requests.length, 1)
  assert.equal(requests[0][0], '/api/connections/c/remote-files/extract-zip')
  assert.equal(JSON.parse(requests[0][1].body).destination_dir, '/target')
  assert.equal(JSON.parse(requests[0][1].body).entry_name, 'root/nested')
  assert.ok(notifications.some(item => item[1] === 'remote-directory-maybe-changed'))
  assert.equal(actor.extracting, false)
})

test('closing selection clears pending directory without dispatching extraction', () => {
  const actor = create()
  actor.extractEntry({path:'folder',name:'folder',is_dir:true})
  actor.cancelSelection()
  assert.equal(actor.folderPickerVisible, false)
  assert.equal(actor.pendingEntry, null)
  assert.match(source, /selection-mode="folder"/)
  assert.doesNotMatch(source, /allow-current-folder/)
  assert.match(source, /:append-to-body="true"/)
})


test('folder picker starts at the actual root for Windows and POSIX archive paths', () => {
  const actor = create()
  actor.archivePath = 'C:\\archive.zip'
  actor.extractEntry({path: 'file.txt', name: 'file.txt', is_dir: false})
  assert.equal(actor.pickerInitialPath, 'C:\\')
  actor.archivePath = '/archive.zip'
  actor.extractEntry({path: 'file.txt', name: 'file.txt', is_dir: false})
  assert.equal(actor.pickerInitialPath, '/')
})


test('changing the client during confirmation prevents extraction into the stale session', async () => {
  const actor = create()
  actor.extractEntry({path: 'src', name: 'src', is_dir: true})
  const originalConfirm = sandbox.ElMessageBox.confirm
  sandbox.ElMessageBox.confirm = async () => { actor.selectedId = 'other-client' }
  let called = false
  const fake = () => { called = true; return Promise.resolve(response({})) }
  fake.run = async () => { await actor.extractToFolder('/target') }
  try {
    await withFetch(fake)
    assert.equal(called, false)
    assert.equal(actor.extracting, false)
  } finally {
    sandbox.ElMessageBox.confirm = originalConfirm
  }
})
