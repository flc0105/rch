import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'

const read = path => readFileSync(new URL(path, import.meta.url), 'utf8')
const transferSource = read('../src/api/transferApi.js')

function buildUploadApi() {
  const requests = []
  const xhrs = []
  let nextId = 0
  class FakeXHR {
    constructor() {
      this.handlers = {}
      this.status = 0
      this.responseText = ''
      this.aborted = false
      xhrs.push(this)
    }
    open(method, url) { this.method = method; this.url = url }
    setRequestHeader() {}
    addEventListener(name, cb) { this.handlers[name] = cb }
    send(file) { this.sentFile = file; this.sent = true }
    abort() { this.aborted = true; this.handlers.abort?.() }
    finish(data = { task_id: 'task-1' }) {
      this.status = 200
      this.responseText = JSON.stringify({ code: 0, data })
      this.handlers.load?.()
    }
  }
  async function fetch(url, options) {
    requests.push({ url, options })
    if (url === '/api/transfers/browser-upload') {
      const id = `transfer-${++nextId}`
      return { ok: true, json: async () => ({ code: 0, data: {
        transfer_id: id,
        browser_upload_token: `token-${id}`,
        browser_upload_path: `/api/transfers/browser-upload/${id}/content`,
      } }) }
    }
    if (url.includes('reject-cancel') && url.endsWith('/cancel')) {
      return { ok: false, json: async () => ({ code: 1, message: 'Cannot cancel transfer' }) }
    }
    if (url.endsWith('/cancel')) {
      return { ok: true, json: async () => ({ code: 0, data: { state: 'cancelled' } }) }
    }
    return { ok: true, json: async () => ({ code: 0, data: {} }) }
  }
  const evaluatedSource = transferSource.replace(/^export (async )?function /gm, '$1function ')
  const api = vm.runInNewContext(`(() => { ${evaluatedSource}; return { uploadRemoteFileToClient, cancelTransfer } })()`,
    { fetch, XMLHttpRequest: FakeXHR, Map, Promise, console })
  return { ...api, requests, xhrs }
}

const nextTurn = () => new Promise(resolve => setImmediate(resolve))
async function awaitXhr(api, count = 1) {
  for (let i = 0; i < 20 && api.xhrs.length < count; i++) await nextTurn()
  assert.equal(api.xhrs.length, count)
  return api.xhrs[count - 1]
}

function getUploadMethod(componentName) {
  const component = read(`../src/components/${componentName}.vue`)
  const methodName = componentName === 'RemoteFilesDialog' ? 'handleUploadChange' : 'handleRemoteUploadChange'
  const next = componentName === 'RemoteFilesDialog' ? 'async loadRemoteDirectory(' : 'async loadQuickJumpPaths('
  const start = component.indexOf(`    async ${methodName}(event) {`)
  assert.ok(start >= 0, `${componentName} upload handler exists`)
  const end = component.indexOf(next, start)
  assert.ok(end > start)
  const snippet = component.slice(start, end).trim().replace(/,\s*$/, '')
  return { methodName, snippet }
}

for (const componentName of ['RemoteFilesDialog', 'RemoteFilePicker']) {
  test(`${componentName}: browser upload begins toast immediately; Cancel aborts XHR and unlocks Upload`, async () => {
    const api = buildUploadApi()
    const toasts = []
    const messages = { info: [], error: [] }
    const events = []
    const { methodName, snippet } = getUploadMethod(componentName)
    const handler = vm.runInNewContext(`({ ${snippet} }).${methodName}`, {
      prepareUploadConflict: async () => 'stop',
      createTerminalOperation: () => ({ operation_id: 'op-1' }),
      operationHeaders: (operation, headers) => headers,
      uploadRemoteFileToClient: api.uploadRemoteFileToClient,
      showTransferStartedToast: text => toasts.push(text),
      formatTerminalCommandFinishedLine: () => 'Finished',
      ElMessage: {
        info: message => messages.info.push(message),
        error: message => messages.error.push(message),
        warning: () => {},
      },
    })
    const ui = {
      selectedId: 'device-1', remoteFilesClientId: 'device-1', remoteFilesCurrentPath: '/tmp',
      remoteUploadLoading: false, getTabScopedHeaders: () => ({}), buildRequestHeaders: () => ({}),
      openTransferCenterFromToast: () => {},
      $emit: (...args) => events.push(args),
    }
    const event = { target: { files: [{ name: 'big.bin', size: 1000 }], value: 'big.bin' } }
    const pending = handler.call(ui, event)
    assert.equal(ui.remoteUploadLoading, true)
    const xhr = await awaitXhr(api)
    assert.equal(xhr.sent, true)
    assert.deepEqual(toasts, ['Upload started: big.bin'])
    assert.equal(ui.remoteUploadLoading, true, 'browser -> Server is still in progress')
    assert.ok(!events.some(evt => evt[0] === 'upload-started'), 'no Client task yet')
    await api.cancelTransfer('transfer-1', 'tab-1')
    assert.equal(xhr.aborted, true)
    await pending
    assert.equal(ui.remoteUploadLoading, false, 'upload control is released even if XHR had not finished')
    assert.equal(event.target.value, '')
    assert.equal(messages.info[0], 'Upload cancelled')
    assert.equal(messages.error.length, 0)
    assert.ok(events.some(evt => evt[0] === 'append-output' && evt[4]?.execution_status === 'cancelled'))
    assert.equal(api.requests.filter(req => req.options?.method === 'PATCH').length, 0,
      'cancellation is never overwritten by a browser-upload failure PATCH')
  })
}

test('successful upload only emits started after XHR.send and returns task after browser staging completes', async () => {
  const api = buildUploadApi()
  const started = []
  let finished = false
  const pending = api.uploadRemoteFileToClient({
    file: { name: 'hello.txt', size: 5 }, clientId: 'device-1', destinationPath: '/tmp',
    onStarted: ({ transferId }) => started.push(transferId),
  }).then(value => { finished = true; return value })
  const xhr = await awaitXhr(api)
  assert.equal(xhr.sent, true)
  assert.deepEqual(started, ['transfer-1'])
  assert.equal(finished, false)
  xhr.finish({ task_id: 'task-42' })
  assert.equal((await pending).task_id, 'task-42')
  assert.equal(finished, true)
})

test('failed cancel request does not terminate an otherwise continuing browser upload', async () => {
  const api = buildUploadApi()
  const pending = api.uploadRemoteFileToClient({ file: { name: 'test', size: 1 }, clientId: 'one', destinationPath: '/tmp' })
  const xhr = await awaitXhr(api)
  await assert.rejects(api.cancelTransfer('reject-cancel'), /Cannot cancel transfer/)
  assert.equal(xhr.aborted, false)
  xhr.finish({ task_id: 't' })
  assert.equal((await pending).task_id, 't')
})

test('cancelling one of two uploads does not abort or poison the other upload', async () => {
  const api = buildUploadApi()
  const a = api.uploadRemoteFileToClient({ file: { name: 'a', size: 2 }, clientId: 'one', destinationPath: '/tmp' })
  const b = api.uploadRemoteFileToClient({ file: { name: 'b', size: 3 }, clientId: 'one', destinationPath: '/tmp' })
  const first = await awaitXhr(api, 2)
  assert.equal(first.sent, true)
  await api.cancelTransfer('transfer-1')
  await assert.rejects(a, error => error?.name === 'AbortError')
  assert.equal(api.xhrs[0].aborted, true)
  assert.equal(api.xhrs[1].aborted, false)
  api.xhrs[1].finish({ task_id: 'task-b' })
  assert.equal((await b).task_id, 'task-b')
})

test('ordinary browser upload failure still reports a failed transfer via existing API', async () => {
  const api = buildUploadApi()
  const upload = api.uploadRemoteFileToClient({ file: { name: 'f', size: 2 }, clientId: 'one', destinationPath: '/tmp' })
  const xhr = await awaitXhr(api)
  xhr.handlers.error?.()
  await assert.rejects(upload, /Browser upload connection failed/)
  await nextTurn()
  const patch = api.requests.find(item => item.options?.method === 'PATCH')
  assert.ok(patch)
  assert.equal(JSON.parse(patch.options.body).state, 'failed')
})
