import assert from 'node:assert/strict'
import { test } from 'node:test'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'
import {
  listRemoteDirectory, getRemoteSystemPaths, pasteRemoteFiles, createRemoteZip,
  extractRemoteZip, inspectRemoteZip, readRemoteZipEntry, makeRemoteDirectory,
  renameRemoteFile, downloadRemoteFile, downloadRemoteZip, deleteRemoteFile,
  deleteRemoteEntries,
} from '../src/api/remoteFilesApi.js'
import {
  listRemotePinnedPaths, saveRemotePinnedPath, deleteRemotePinnedPath,
} from '../src/api/remotePinsApi.js'

const testDir = dirname(fileURLToPath(import.meta.url))

async function capture(call) {
  const oldFetch = globalThis.fetch
  const calls = []
  const response = { ok: true, status: 200, json: async () => ({code: 0, data: {}}) }
  globalThis.fetch = (url, options = {}) => { calls.push({url, options}); return Promise.resolve(response) }
  try {
    const result = await call()
    assert.strictEqual(result, response, 'API must preserve raw Response for existing UI handlers')
    assert.equal(calls.length, 1)
    return calls[0]
  } finally {
    globalThis.fetch = oldFetch
  }
}

test('directory listing preserves query values and abort signal', async () => {
  const abort = new AbortController()
  const {url, options} = await capture(() => listRemoteDirectory('a/b', {
    path: 'C:\\New Folder\\文件', page: 3, pageSize: 70, showHidden: true,
    search: 'abc def', recursive: true,
  }, { signal: abort.signal }))
  assert.equal(new URL(url, 'http://localhost').pathname, '/api/connections/a%2Fb/remote-files')
  const params = new URL(url, 'http://localhost').searchParams
  assert.equal(params.get('path'), 'C:\\New Folder\\文件')
  assert.equal(params.get('page'), '3')
  assert.equal(params.get('page_size'), '70')
  assert.equal(params.get('show_hidden'), 'true')
  assert.equal(params.get('search'), 'abc def')
  assert.equal(params.get('recursive'), 'true')
  assert.strictEqual(options.signal, abort.signal)
  const picker = await capture(() => listRemoteDirectory('c', {page: 1, pageSize: 50}))
  const pickerParams = new URL(picker.url, 'http://localhost').searchParams
  assert.equal(pickerParams.get('show_hidden'), 'false')
  assert.equal(pickerParams.has('search'), false)
  assert.equal(pickerParams.has('recursive'), false)
})

test('remote file operations preserve endpoint, method, body and web origin', async () => {
  const base = '/api/connections/c%20d/remote-files'
  const cases = [
    [() => pasteRemoteFiles('c d', {paths:['/a'], destination_dir:'/b', operation:'move'}), '/paste', 'POST', {paths:['/a'], destination_dir:'/b', operation:'move'}],
    [() => createRemoteZip('c d', {paths:['/a'], destination_dir:'/b', archive_name:'x.zip'}), '/create-zip', 'POST', {paths:['/a'], destination_dir:'/b', archive_name:'x.zip'}],
    [() => extractRemoteZip('c d', {path:'/x.zip', destination_dir:'/b'}), '/extract-zip', 'POST', {path:'/x.zip', destination_dir:'/b'}],
    [() => makeRemoteDirectory('c d', '/new'), '/mkdir', 'POST', {path:'/new'}],
    [() => renameRemoteFile('c d', '/a', 'b'), '/rename', 'POST', {old_path:'/a', new_name:'b'}],
    [() => downloadRemoteZip('c d', ['/a'], {'X-RCH-Tab-ID':'one'}), '/download-zip', 'POST', {paths:['/a'],archive_name:''}],
    [() => deleteRemoteEntries('c d', ['/a']), '/batch', 'DELETE', {paths:['/a']}],
  ]
  for (const [fn,suffix,method,body] of cases) {
    const {url,options} = await capture(fn)
    assert.equal(url,base+suffix)
    assert.equal(options.method,method)
    assert.deepEqual(JSON.parse(options.body),body)
    assert.equal(options.headers['Content-Type'],'application/json')
    assert.equal(options.headers['X-RCH-Origin'],'web_ui')
  }
  const download = await capture(() => downloadRemoteFile('c d', '/a b', {'X-RCH-Tab-ID':'one'}))
  assert.equal(download.options.method,'POST')
  assert.equal(download.options.headers['X-RCH-Tab-ID'],'one')
  assert.equal(download.options.headers['X-RCH-Origin'],'web_ui')
  assert.equal(new URL(download.url, 'http://localhost').searchParams.get('path'), '/a b')
  const remove = await capture(() => deleteRemoteFile('c d', '/a b'))
  assert.equal(remove.options.method,'DELETE')
  assert.equal(new URL(remove.url, 'http://localhost').searchParams.get('path'), '/a b')
  assert.equal(remove.options.headers['X-RCH-Origin'],'web_ui')
})

test('read-only remote ZIP and system path operations keep their existing endpoints', async () => {
  const paths = await capture(() => getRemoteSystemPaths('c d'))
  assert.equal(paths.url, '/api/connections/c%20d/system-paths')
  const peek = await capture(() => inspectRemoteZip('c d', '/a.zip'))
  assert.equal(peek.url, '/api/connections/c%20d/remote-files/zip-peek')
  assert.deepEqual(JSON.parse(peek.options.body), {path:'/a.zip'})
  assert.equal(peek.options.method, 'POST')
  assert.equal(peek.options.headers['X-RCH-Origin'], undefined)
  const entry = await capture(() => readRemoteZipEntry('c d', '/a.zip', 'folder/1.txt'))
  assert.equal(entry.url, '/api/connections/c%20d/remote-files/zip-entry')
  assert.deepEqual(JSON.parse(entry.options.body), {path:'/a.zip', entry_name:'folder/1.txt'})
})

test('pinned paths keep no-store reads and POST/PUT/DELETE contracts', async () => {
  const base = '/api/connections/c%20d/pinned_paths'
  const reload = await capture(() => listRemotePinnedPaths('c d', {cache:'no-store'}))
  assert.equal(reload.url, base)
  assert.equal(reload.options.cache, 'no-store')
  const create = await capture(() => saveRemotePinnedPath('c d', {display_name:'name', path:'/x'}))
  assert.equal(create.url,base)
  assert.equal(create.options.method, 'POST')
  assert.equal(create.options.headers['Content-Type'], 'application/json')
  const rename = await capture(() => saveRemotePinnedPath('c d', {original_display_name:'old',display_name:'new',path:'/x'}, 'PUT'))
  assert.equal(rename.options.method,'PUT')
  const remove = await capture(() => deleteRemotePinnedPath('c d','named item'))
  assert.equal(remove.options.method,'DELETE')
  assert.deepEqual(JSON.parse(remove.options.body),{display_name:'named item'})
})

test('remote file dialogs use feature API rather than inline transport', () => {
  for (const name of ['RemoteFilesDialog.vue','RemotePinsDialog.vue','RemoteZipPeekDialog.vue','RemoteFilePicker.vue']) {
    const content=readFileSync(resolve(testDir, '../src/components', name),'utf-8')
    assert.doesNotMatch(content,/\bfetch\s*\(/,`${name} should not construct fetch calls`)
  }
})
