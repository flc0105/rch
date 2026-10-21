import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import vm from 'node:vm'
import { uploadRemoteFileToClient } from '../src/api/transferApi.js'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const originalFetch = globalThis.fetch
const originalXHR = globalThis.XMLHttpRequest
const originalWindow = globalThis.window
const logs = []
let xhrMode = 'success'
let started = 0
let postCount = 0

class FakeXHR {
  constructor() {
    this.headers = {}
    this.listeners = {}
    this.status = 200
    this.responseText = JSON.stringify({code: 0, data: {task_id: 'task-123'}})
  }
  open(method, url) {
    this.method = method
    this.url = url
  }
  setRequestHeader(k, v) { this.headers[k] = v }
  addEventListener(k, cb) { this.listeners[k] = cb }
  send(file) {
    postCount++
    assert.equal(this.method, 'POST')
    assert.equal(this.url, 'http://test.example:8086/api/transfers/browser-upload/tr-1/content')
    assert.equal(this.headers['Content-Type'], 'application/octet-stream')
    assert.equal(this.headers['X-RCH-Transfer-Token'], 'token-123')
    assert.equal(file.name, 'report.txt')
    if (xhrMode === 'error') return this.listeners.error()
    if (xhrMode === 'abort') return this.listeners.abort()
    if (xhrMode === 'invalid') this.responseText = 'bad JSON'
    if (xhrMode === 'rejected') this.responseText = JSON.stringify({code: 1, message: 'Denied'})
    this.listeners.load()
  }
}

globalThis.XMLHttpRequest = FakeXHR
globalThis.window = { location: { href: 'http://test.example:8085/console' } }
globalThis.fetch = async (url, options) => {
  logs.push({url, options})
  if (url === '/api/transfers/browser-upload') {
    started++
    assert.equal(options.headers['X-Tab-Id'], 'tab-42')
    assert.deepEqual(JSON.parse(options.body), {
      client_id: 'client-A', filename: 'report.txt', total_bytes: 17,
      destination_path: '/home/test',
    })
    return {ok: true, json: async () => ({code: 0, data: {
      transfer_id: 'tr-1', browser_upload_port: 8086,
      browser_upload_path: '/api/transfers/browser-upload/tr-1/content',
      browser_upload_token: 'token-123',
    }})}
  }
  if (url === '/api/transfers/tr-1/browser-upload') {
    assert.equal(options.method, 'PATCH')
    assert.equal(options.headers['X-Tab-Id'], 'tab-42')
    assert.equal(JSON.parse(options.body).state, 'failed')
    return {ok: true, json: async () => ({code: 0, data: {}})}
  }
  throw new Error(`Unexpected fetch ${url}`)
}

const file = {name: 'report.txt', size: 17}
const headers = {'X-Tab-Id': 'tab-42'}
try {
  const result = await uploadRemoteFileToClient({file, clientId: 'client-A', destinationPath: '/home/test', headers})
  assert.equal(result.task_id, 'task-123')
  assert.equal(started, 1)
  assert.equal(postCount, 1)
  assert.equal(logs.filter(c => c.options.method === 'PATCH').length, 0)

  for (const mode of ['error', 'abort', 'invalid', 'rejected']) {
    xhrMode = mode
    await assert.rejects(
      uploadRemoteFileToClient({file, clientId: 'client-A', destinationPath: '/home/test', headers}),
      /Browser upload connection failed|Browser upload was cancelled|Upload returned an invalid response|Denied/,
    )
  }
  assert.equal(started, 5)
  assert.equal(postCount, 5)
  assert.equal(logs.filter(c => c.options.method === 'PATCH').length, 4)
} finally {
  globalThis.fetch = originalFetch
  globalThis.XMLHttpRequest = originalXHR
  globalThis.window = originalWindow
}

function component(fileName) {
  const source = readFileSync(resolve(root, 'src/components', fileName), 'utf8')
  const script = source.match(/<script>([\s\S]*?)<\/script>/)?.[1]
  assert.ok(script)
  assert.match(source, /uploadRemoteFileToClient\(/)
  assert.doesNotMatch(source, /\/api\/connections\/\$\{encodeURIComponent\(this\.selectedId\)\}\/upload/)
  let called = []
  let events = []
  const sandbox = {
    ElMessage: {warning() {}, error(e) {throw Error(e)}, success() {}},
    ElMessageBox: {}, RemotePinsDialog: {}, RemoteZipPeekDialog: {},
    formatBytesValue: (x) => x,
    uploadRemoteFileToClient: async (args) => {
      called.push(args)
      return {task_id: 'task-shared'}
    },
  }
  vm.runInNewContext(
    script.replace(/^import[^\n]*\n/gm, '').replace('export default {', 'globalThis.component = {'),
    sandbox,
  )
  const def = sandbox.component
  const state = {...def.data(), selectedId: 'client-A', remoteFilesClientId: 'client-A',
    remoteFilesCurrentPath: '/home/test',
    getTabScopedHeaders: () => ({'X-Tab-Id': 'tab-42'}),
    $emit: (...args) => events.push(args),
  }
  for (const [name, method] of Object.entries(def.methods)) state[name] = method.bind(state)
  return {state, called, events}
}

const picker = component('RemoteFilePicker.vue')
const dialog = component('RemoteFilesDialog.vue')
const event = {target: {files: [file], value: 'report.txt'}}
await picker.state.handleRemoteUploadChange(event)
assert.equal(picker.called.length, 1)
assert.deepEqual(JSON.parse(JSON.stringify(picker.called[0])), {
  file, clientId: 'client-A', destinationPath: '/home/test',
  headers: {...headers, 'X-RCH-Origin': 'web_ui', 'X-RCH-Feature': 'remote_file_picker'},
})
assert.equal(event.target.value, '')
assert.equal(picker.state.remoteUploadLoading, false)
assert.ok(picker.events.some(([name, info]) => name === 'upload-started' && info.source === 'remote_file_picker' && info.taskId === 'task-shared'))
const event2 = {target: {files: [file], value: 'report.txt'}}
await dialog.state.handleUploadChange(event2)
assert.equal(dialog.called.length, 1)
assert.deepEqual(JSON.parse(JSON.stringify(dialog.called[0])), {
  file, clientId: 'client-A', destinationPath: '/home/test',
  headers: {...headers, 'X-RCH-Origin': 'web_ui', 'X-RCH-Feature': 'remote_files'},
})
assert.equal(event2.target.value, '')
assert.equal(dialog.state.remoteUploadLoading, false)
assert.ok(dialog.events.some(([name, info]) => name === 'upload-started' && info.taskId === 'task-shared'))
console.log('Shared remote upload API: 8086, Transfer Center creation, failure, both dialogs passed')
