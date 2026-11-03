import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import {
  getBackgroundJobCatalog, getBackgroundJobs, getBackgroundJobDetail,
  startBackgroundJob, stopBackgroundJob, deleteBackgroundJobRecord,
  uploadServerJob, deleteServerJob, saveServerJob, downloadServerJob,
  previewBackgroundJobFile,
} from '../src/api/backgroundJobsApi.js'
import {
  listArtifacts, uploadArtifact, renameArtifact, sendArtifactToClient,
  deleteArtifact, clearArtifacts, previewArtifact, saveArtifactContent,
  saveCommandOutputArtifact,
} from '../src/api/artifactsApi.js'

const response = { ok: true, json: async () => ({ code: 0, data: {} }) }
async function capture(action) {
  const original = globalThis.fetch
  const calls = []
  globalThis.fetch = async (url, options = {}) => {
    calls.push({ url, options })
    return response
  }
  try {
    const returned = await action()
    assert.strictEqual(returned, response, 'return the original Response')
    assert.equal(calls.length, 1, 'one request per API call')
    return calls[0]
  } finally {
    globalThis.fetch = original
  }
}
const jsonBody = call => JSON.parse(call.options.body)
const jsonHeader = call => assert.equal(call.options.headers['Content-Type'], 'application/json')

// Client/job identities may contain reserved URI characters: encode separately.
test('background job reads and record deletion preserve paths and methods', async () => {
  const base = '/api/connections/c%2F%E4%B8%80/background-jobs'
  for (const [fn, endpoint] of [
    [() => getBackgroundJobCatalog('c/一'), `${base}/catalog`],
    [() => getBackgroundJobs('c/一'), base],
    [() => getBackgroundJobDetail('c/一', 'job/1 #'), `${base}/job%2F1%20%23`],
  ]) {
    const call = await capture(fn)
    assert.equal(call.url, endpoint)
    assert.equal(call.options.method, undefined)
  }
  const del = await capture(() => deleteBackgroundJobRecord('c/一', 'job/1 #'))
  assert.equal(del.url, `${base}/job%2F1%20%23`)
  assert.equal(del.options.method, 'DELETE')
})

test('background job start preserves scoped headers, origin and execution mode payload', async () => {
  const tabHeaders = { 'Content-Type': 'application/json', 'X-RCH-Tab-ID': 'tab/42' }
  const params = { location: '文件/a.py', count: 0 }
  for (const mode of ['inproc', 'subprocess']) {
    const call = await capture(() => startBackgroundJob('a/b', 'network/ping', params, mode, tabHeaders))
    assert.equal(call.url, '/api/connections/a%2Fb/background-jobs/start')
    assert.equal(call.options.method, 'POST')
    assert.equal(call.options.headers['X-RCH-Origin'], 'web_ui')
    assert.equal(call.options.headers['X-RCH-Tab-ID'], 'tab/42')
    jsonHeader(call)
    assert.deepEqual(jsonBody(call), { job_name: 'network/ping', params, execution_mode: mode })
  }
})

test('background job stop retains job_key and web origin (not job_id)', async () => {
  const call = await capture(() => stopBackgroundJob('c/1', 'network/ping@abc'))
  assert.equal(call.url, '/api/connections/c%2F1/background-jobs/stop')
  assert.equal(call.options.method, 'POST')
  jsonHeader(call)
  assert.equal(call.options.headers['X-RCH-Origin'], 'web_ui')
  assert.deepEqual(jsonBody(call), { job_key: 'network/ping@abc' })
})

test('job library upload/edit/download/delete and server-supplied preview URL', async () => {
  const form = new FormData()
  form.append('file', new Blob(['print(1)']), 'job.py')
  const upload = await capture(() => uploadServerJob(form))
  assert.equal(upload.url, '/api/jobs/upload')
  assert.equal(upload.options.method, 'POST')
  assert.strictEqual(upload.options.body, form)
  assert.equal(upload.options.headers, undefined)
  const del = await capture(() => deleteServerJob('folder/job.py'))
  assert.equal(del.url, '/api/jobs/delete')
  assert.equal(del.options.method, 'DELETE')
  jsonHeader(del)
  assert.deepEqual(jsonBody(del), { name: 'folder/job.py' })
  const save = await capture(() => saveServerJob('folder/job.py', 'print("x")'))
  assert.equal(save.url, '/api/jobs/save')
  assert.equal(save.options.method, 'POST')
  assert.deepEqual(jsonBody(save), { name: 'folder/job.py', content: 'print("x")' })
  const read = await capture(() => downloadServerJob('folder/a & b.py'))
  assert.equal(read.url, '/api/jobs/download?name=folder%2Fa%20%26%20b.py')
  const preview = await capture(() => previewBackgroundJobFile('/api/jobs/preview?token=a%2Fb'))
  assert.equal(preview.url, '/api/jobs/preview?token=a%2Fb')
})

test('artifact list, preview, delete use unchanged endpoints and encoded identities', async () => {
  const list = await capture(listArtifacts)
  assert.equal(list.url, '/api/artifacts')
  assert.equal(list.options.method, undefined)
  const read = await capture(() => previewArtifact('id/空 格'))
  assert.equal(read.url, '/api/artifacts/id%2F%E7%A9%BA%20%E6%A0%BC/preview')
  const del = await capture(() => deleteArtifact('id/空 格'))
  assert.equal(del.url, '/api/artifacts/id%2F%E7%A9%BA%20%E6%A0%BC')
  assert.equal(del.options.method, 'DELETE')
})

test('artifact uploads retain multipart FormData with optional scoped headers', async () => {
  const form = new FormData()
  form.append('artifact_type', 'shared_files')
  const scoped = { 'X-RCH-Tab-ID': 'tab1' }
  const fromDialog = await capture(() => uploadArtifact(form, scoped))
  assert.equal(fromDialog.url, '/api/files/upload')
  assert.equal(fromDialog.options.method, 'POST')
  assert.strictEqual(fromDialog.options.body, form)
  assert.strictEqual(fromDialog.options.headers, scoped)
  const fromPreview = await capture(() => uploadArtifact(form))
  assert.equal(fromPreview.options.headers, undefined)
  assert.strictEqual(fromPreview.options.body, form)
})

test('artifact rename and send-to preserve tab headers and complete original payload', async () => {
  const headers = { 'Content-Type': 'application/json', 'X-RCH-Tab-ID': 'tab1' }
  const rename = await capture(() => renameArtifact('id/1', 'new.txt', headers))
  assert.equal(rename.url, '/api/artifacts/id%2F1/rename')
  assert.equal(rename.options.method, 'POST')
  assert.equal(rename.options.headers['X-RCH-Tab-ID'], 'tab1')
  assert.deepEqual(jsonBody(rename), { name: 'new.txt', original_name: 'new.txt' })
  const send = await capture(() => sendArtifactToClient('id/1', 'client/7', 'C:\\Temp Folder', headers))
  assert.equal(send.url, '/api/artifacts/id%2F1/send-to-client')
  assert.equal(send.options.method, 'POST')
  assert.equal(send.options.headers['X-RCH-Tab-ID'], 'tab1')
  assert.deepEqual(jsonBody(send), { client_id: 'client/7', target_path: 'C:\\Temp Folder' })
})

test('artifact clear is scoped by category and optional machine, output/save content unchanged', async () => {
  const clear = await capture(() => clearArtifacts('command_output', 'm/1'))
  assert.equal(clear.url, '/api/artifacts/clear')
  assert.equal(clear.options.method, 'POST')
  jsonHeader(clear)
  assert.deepEqual(jsonBody(clear), { type: 'command_output', machine_id: 'm/1' })
  const all = await capture(() => clearArtifacts('shared_files'))
  assert.deepEqual(jsonBody(all), { type: 'shared_files', machine_id: '' })
  const content = await capture(() => saveArtifactContent('id/1', '文字', 'utf-8'))
  assert.equal(content.url, '/api/artifacts/id%2F1/content')
  assert.equal(content.options.method, 'PUT')
  jsonHeader(content)
  assert.deepEqual(jsonBody(content), { content: '文字', encoding: 'utf-8' })
  const payload = { content: 'output\n', category: 'job_output', job_id: 'job/1', extra: { format: 'json' } }
  const output = await capture(() => saveCommandOutputArtifact(payload))
  assert.equal(output.url, '/api/artifacts/command-output/save')
  assert.equal(output.options.method, 'POST')
  assert.deepEqual(jsonBody(output), payload)
})

test('Jobs and Artifact component request sites use their domain API without inline fetch', () => {
  const source = name => readFileSync(new URL(`../src/components/${name}.vue`, import.meta.url), 'utf8')
  for (const name of ['BackgroundJobsDialog', 'BackgroundJobDetailDialog', 'ArtifactDialog', 'TerminalOutput']) {
    const file = source(name)
    assert.doesNotMatch(file, /\bfetch\s*\(/, `${name} must use its domain API`)
  }
  const preview = source('PreviewDialog')
  assert.match(preview, /from ['"]\.\.\/api\/backgroundJobsApi\.js['"]/) 
  assert.match(preview, /from ['"]\.\.\/api\/artifactsApi\.js['"]/) 
  assert.doesNotMatch(preview, /fetch\s*\(['"]\/api\/(?:jobs|artifacts|files\/upload)/)
  assert.doesNotMatch(preview, /fetch\s*\(`\/api\/(?:jobs|artifacts)/)
  const info = source('ConnectionInfoDialogs')
  assert.match(info, /getBackgroundJobs\(clientId\)/)
  assert.doesNotMatch(info, /fetch\s*\(`\/api\/connections\/\$\{encodeURIComponent\(clientId\)\}\/background-jobs/)
})
