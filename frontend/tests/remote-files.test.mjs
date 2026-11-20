import assert from 'node:assert/strict'
import test from 'node:test'

import { downloadRemoteClipboardFiles } from '../src/api/clipboardApi.js'
import { listRemoteDirectory, pasteRemoteFiles } from '../src/api/remoteFilesApi.js'

function requests(t, data = {}) {
  const received = []
  const response = { ok: true, json: async () => ({ code: 0, data }) }
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    received.push({ url: new URL(url, 'https://rch.example'), options })
    return response
  })
  return { received, response }
}

test('remote directory read preserves Unicode, path separators and the cancellation signal', async (t) => {
  const { received, response } = requests(t)
  const abort = new AbortController()
  const path = 'C:\\New Folder\\文件'
  assert.equal(await listRemoteDirectory('tab/client', { path, search: 'a b', page: 2 },
    { signal: abort.signal }), response)
  const [{ url, options }] = received
  assert.equal(url.pathname, '/api/connections/tab%2Fclient/remote-files')
  assert.equal(url.searchParams.get('path'), path)
  assert.equal(url.searchParams.get('search'), 'a b')
  assert.equal(url.searchParams.get('page'), '2')
  assert.equal(options.signal, abort.signal)
})

test('mutation sends the chosen conflict policy and declares its web origin', async (t) => {
  const { received } = requests(t)
  const body = { paths: ['/src/报告.zip'], destination_dir: '/target', operation: 'move', conflict: 'keep_both' }
  await pasteRemoteFiles('client', body)
  const [{ url, options }] = received
  assert.equal(url.pathname, '/api/connections/client/remote-files/paste')
  assert.equal(options.method, 'POST')
  assert.deepEqual(JSON.parse(options.body), body)
  assert.equal(options.headers['X-RCH-Origin'], 'web_ui')
})

test('multi-item Clipboard export requests the shared ZIP route in the Clipboard category', async (t) => {
  const { received } = requests(t, { artifact: { artifact_id: 'zip' } })
  const paths = ['/work/报告.zip', '/work/docs']
  assert.equal((await downloadRemoteClipboardFiles('client', paths)).artifact.artifact_id, 'zip')
  const [{ url, options }] = received
  assert.equal(url.pathname, '/api/connections/client/remote-files/download-zip')
  assert.equal(options.headers['X-RCH-Feature'], 'clipboard')
  assert.deepEqual(JSON.parse(options.body), { paths, archive_name: '' })
})
