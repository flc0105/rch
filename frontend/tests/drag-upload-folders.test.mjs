import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import { joinRemotePath } from '../src/utils/remotePaths.js'
import {
  collectTransferAttachments, collectDirectoryPickerAttachments,
  flattenUploadAttachments,
} from '../src/utils/browserFileEntries.js'

const read = file => readFileSync(new URL(file, import.meta.url), 'utf8')
const plain = value => JSON.parse(JSON.stringify(value))

function dir(name, children) {
  return { name, isDirectory: true, createReader() {
    let index = 0
    return { readEntries(ok) {
      // Browser APIs return bounded pages; do not assume a single readEntries call.
      ok(index < children.length ? children.slice(index++, index) : [])
    } }
  } }
}
function file(name) {
  const data = { name, size: 17 }
  return { name, isFile: true, file(ok) { ok(data) } }
}

test('dragged files, nested directories and empty folders preserve relative paths', async () => {
  const root = dir('docs', [file('a.txt'), dir('images', [file('b.png')]), dir('empty', [])])
  const dropped = await collectTransferAttachments({
    items: [
      { kind: 'file', webkitGetAsEntry: () => root },
      { kind: 'file', webkitGetAsEntry: () => file('loose.log') },
    ],
  })
  assert.deepEqual(dropped.map(x => x.kind), ['directory', 'file'])
  const plan = flattenUploadAttachments(dropped)
  assert.deepEqual(plan.directories, ['docs', 'docs/empty', 'docs/images'])
  assert.deepEqual(plan.files.map(x => x.relativePath), ['docs/a.txt', 'docs/images/b.png', 'loose.log'])
})

test('invalid directory paths and mixed root files are validated', () => {
  const plan = flattenUploadAttachments([{ kind: 'file', name: 'root.txt', file: { name: 'root.txt' } }])
  assert.deepEqual(plan.files.map(x => x.relativePath), ['root.txt'])
  assert.throws(() => flattenUploadAttachments([{ kind: 'directory', name: 'bad', directories: ['../outside'], files: [] }]), /Invalid upload path/)
  assert.throws(() => flattenUploadAttachments([{ kind: 'file', name: 'x/y', file: {} }]), /Invalid upload path/)
})

function method(fileName, name, next) {
  const source = read(`../src/components/${fileName}.vue`)
  const start = source.indexOf(`    async ${name}(`)
  const end = source.indexOf(`    async ${next}(`, start + 1)
  assert.ok(start >= 0 && end > start, `method ${name} exists`)
  return source.slice(start, end).trim().replace(/,\s*$/, '')
}

test('Shared Files submits one multipart batch for nested folders and 100 files', async () => {
  const calls = []
  const errors = []
  class FakeFormData {
    constructor() { this.values = [] }
    append(...args) { this.values.push(args) }
  }
  const upload = vm.runInNewContext(`({ ${method('ArtifactDialog', 'uploadSharedFiles', 'handleArtifactMoreCommand')} }).uploadSharedFiles`, {
    flattenUploadAttachments, FormData: FakeFormData, AbortController,
    inspectSharedUpload: async () => ({}), expectData: async () => ({ conflicts: [] }),
    resolveConflictPolicies: async (_, count) => Array(count).fill('stop'),
    uploadSharedBatch: async body => {
      calls.push(body.values)
      return { code: 0, data: { files_uploaded: 100, folders_created: 3 } }
    },
    ElMessage: { success() {}, error(message) { errors.push(message) } },
  })
  const ui = {
    isSharedFilesTab: true, sharedFileUploading: false, sharedFileUploadDialogVisible: true,
    selectedFolderId: 'target-parent', async loadArtifacts() {}, buildJsonHeaders: () => ({}),
  }
  const files = Array.from({ length: 100 }, (_, i) => ({ file: { name: `f-${i}.txt` }, relativePath: `docs/sub/f-${i}.txt` }))
  await upload.call(ui, [{ kind: 'directory', name: 'docs',
    directories: ['docs', 'docs/empty', 'docs/sub'], files }])
  assert.equal(calls.length, 1)
  const values = calls[0]
  assert.equal(values.filter(x => x[0] === 'files').length, 100)
  assert.deepEqual(JSON.parse(values.find(x => x[0] === 'paths')[1]), files.map(x => x.relativePath))
  assert.deepEqual(JSON.parse(values.find(x => x[0] === 'directories')[1]), ['docs', 'docs/empty', 'docs/sub'])
  assert.equal(values.find(x => x[0] === 'folder_id')[1], 'target-parent')
  assert.deepEqual(errors, [])
  assert.equal(ui.sharedFileUploadDialogVisible, false)
})

function vueComponent(file, env = {}) {
  env = { joinRemotePath, TERMINAL_REMOTE_UPLOAD_PREFIX: '[Remote Upload]',
    formatTerminalCommandFinishedLine: (command, result) => `[Command finished] ${command} (${result})`,
    conflictsEnabled: async () => true,
    prepareRemoteUploadPlan: async (_, __, plan) => ({ ...plan, reused: new Set(), files: plan.files.map(entry => ({ ...entry, policy: 'stop' })) }),
    isBrowserUploadBatchCancelled: () => false,
    listRemoteDirectory: async () => ({ ok: false, json: async () => ({ code: 1 }) }),
    ...env }
  const script = read(`../src/components/${file}.vue`).match(/<script>([\s\S]*?)<\/script>/)[1]
  return vm.runInNewContext(`(${script.replace(/^import .*$/gm, '').replace('export default', '')})`, env)
}
function instance(component, extra = {}) {
  const o = { ...component.data(), ...extra }
  for (const [key, method] of Object.entries(component.methods || {})) if (!(key in extra)) o[key] = method.bind(o)
  for (const [key, method] of Object.entries(component.computed || {})) Object.defineProperty(o, key, { get: () => method.call(o) })
  return o
}

test('multi-select Copy To and Move To use existing path-array paste workflow', async () => {
  const requests = []
  const c = vueComponent('RemoteFilesDialog', {
    RemotePinsDialog: {}, RemoteFilePicker: {}, DragUploadDialog: {}, MoreFilled: {}, OPEN_TRANSFER_CENTER_KEY: 'x',
    ElMessage: { success() {}, warning() {}, error(e) { throw Error(e) }, info() {} },
    preparePasteConflicts: async () => ({}),
    pasteRemoteFiles: async (_, req) => { requests.push(plain(req)); return { ok: true, json: async () => ({ code: 0, data: { failed: 0 } }) } },
  })
  const ui = instance(c, {
    visible: true,
    remoteFilesClientId: 'client',
    remoteFilesCurrentPath: '/source',
    remoteSelectedPaths: ['/source/a', '/source/sub'],
    async refreshRemoteDirectory() {},
  })
  ui.handleRemoteToolbarMoreCommand('copy_to_selected')
  await ui.handleDestinationSelected('/destination')
  ui.handleRemoteToolbarMoreCommand('move_to_selected')
  await ui.handleDestinationSelected('/destination')
  assert.deepEqual(requests, [
    { paths: ['/source/a', '/source/sub'], destination_dir: '/destination', operation: 'copy' },
    { paths: ['/source/a', '/source/sub'], destination_dir: '/destination', operation: 'move' },
  ])
})

test('Remote drag upload submits every file to Windows/POSIX subpaths in one batch', async () => {
  const created = []
  const transferred = []
  const finalized = []
  const c = vueComponent('RemoteFilesDialog', {
    RemotePinsDialog: {}, RemoteFilePicker: {}, DragUploadDialog: {}, MoreFilled: {}, OPEN_TRANSFER_CENTER_KEY: 'x',
    flattenUploadAttachments,
    createTerminalOperation: () => ({ operation_id: 'one-batch' }),
    operationHeaders: (_op, headers) => headers,
    showTransferStartedToast: () => {},
    startBrowserUploadBatch: async () => ({}),
    finalizeBrowserUploadBatch: async (args, headers) => { finalized.push({ ...plain(args), headers: plain(headers) }) },
    makeRemoteDirectory: async (_, path) => { created.push(path); return { ok: true, json: async () => ({ code: 0 }) } },
    prepareUploadConflict: async () => 'stop',
    uploadRemoteFileToClient: async args => {
      transferred.push(plain({ root: args.destinationPath, name: args.file.name, batchId: args.batchId,
        batchIndex: args.batchIndex, batchTotal: args.batchTotal }))
      return { task_id: `task-${args.batchIndex}` }
    },
    ElMessage: { success() {}, warning() {}, error(e) { throw Error(e) } },
  })
  for (const root of ['/root', 'C:\\root']) {
    const events = []
    const ui = instance(c, {
      visible: true, remoteFilesClientId: 'client', remoteFilesCurrentPath: root,
      dragUploadVisible: true, getTabScopedHeaders: () => ({ 'X-Tab-Id': 'tab' }),
      $emit: (event, ...args) => events.push([event, ...args]),
      async refreshRemoteDirectory() {},
    })
    const items = Array.from({ length: 100 }, (_, i) => ({ file: { name: `f-${i}.txt` }, relativePath: `docs/inner/f-${i}.txt` }))
    await ui.handleDragUpload([{ kind: 'directory', name: 'docs', directories: ['docs', 'docs/inner'], files: items }])
    assert.equal(ui.dragUploadVisible, false)
    assert.equal(ui.dragUploadLoading, false)
    assert.equal(events.filter(x => x[0] === 'append-output').length, 1)
    assert.match(events.find(x => x[0] === 'append-output')?.[2] || '', /\[Remote Upload\] 100 file\(s\)/)
  }
  assert.deepEqual(created, ['/root/docs', '/root/docs/inner', 'C:\\root\\docs', 'C:\\root\\docs\\inner'])
  assert.equal(transferred.length, 200)
  assert.deepEqual(transferred.map(x => x.batchIndex), [...Array(100).keys(), ...Array(100).keys()])
  assert.ok(transferred.every(x => x.batchId === 'one-batch' && x.batchTotal === 100))
  assert.equal(transferred[199].name, 'f-99.txt')
  assert.equal(finalized.length, 2)
  assert.ok(finalized.every(item => item.batchId === 'one-batch' && item.folderCount === 2 && !item.error))
  assert.ok(finalized.every(item => item.headers['X-Tab-Id'] === 'tab'))
})

test('Remote directory reuse validates existing path; a failed batch leaves selection open', async () => {
  const calls = []
  const errors = []
  const finalized = []
  const c = vueComponent('RemoteFilesDialog', {
    RemotePinsDialog: {}, RemoteFilePicker: {}, DragUploadDialog: {}, MoreFilled: {}, OPEN_TRANSFER_CENTER_KEY: 'x',
    flattenUploadAttachments,
    createTerminalOperation: () => ({ operation_id: 'test' }), operationHeaders: (_, h) => h,
    makeRemoteDirectory: async () => ({ ok: false, json: async () => ({ code: 1, message: 'Already exists' }) }),
    listRemoteDirectory: async (_, req) => { calls.push(req.path); return { ok: true, json: async () => ({ code: 0, data: { current_path: req.path } }) } },
    prepareRemoteUploadPlan: async (_, __, plan) => ({ ...plan, reused: new Set(['existing']), files: plan.files.map(entry => ({ ...entry, policy: 'stop' })) }),
    uploadRemoteFileToClient: async () => { throw Error('Network failed') },
    startBrowserUploadBatch: async () => ({}),
    finalizeBrowserUploadBatch: async (args) => { finalized.push(plain(args)) },
    ElMessage: { success() {}, warning() {}, error(error) { errors.push(error) } },
  })
  const ui = instance(c, {
    visible: true, remoteFilesClientId: 'client', remoteFilesCurrentPath: '/root', dragUploadVisible: true,
    getTabScopedHeaders: () => ({ 'X-Tab-Id': 'tab' }), $emit: () => {},
  })
  await ui.handleDragUpload([{ kind: 'directory', name: 'existing', directories: ['existing'], files: [
    { relativePath: 'existing/file', file: { name: 'file' } },
  ] }])
  assert.deepEqual(calls, ['/root/existing'])
  assert.equal(ui.dragUploadVisible, true)
  assert.equal(ui.dragUploadLoading, false)
  assert.match(errors[0], /Network failed/)
  assert.equal(finalized.length, 1)
  assert.match(finalized[0].error, /Network failed/)
})

test('DragUploadDialog keeps the original single click-to-select dropzone', () => {
  const source = read('../src/components/DragUploadDialog.vue')
  assert.match(source, /class="drag-upload-dropzone"[\s\S]*?@click="openFilePicker"/)
  assert.match(source, /@drop\.prevent="handleDrop"/)
  assert.match(source, /Choose folder/)
  assert.match(source, /webkitdirectory/)
  assert.match(source, /openFolderPicker/)
})

test('Remote batch stages all 100 browser uploads through the real Transfer API promise path', async () => {
  const source = read('../src/api/transferApi.js')
  const payloads = []
  const staged = []
  class FakeXHR {
    constructor() { this.handlers = {}; this.status = 0; this.responseText = '' }
    open(_method, url) { this.url = url }
    setRequestHeader() {}
    addEventListener(key, cb) { this.handlers[key] = cb }
    send(file) {
      staged.push({ url: this.url, name: file.name })
      queueMicrotask(() => {
        this.status = 200
        this.responseText = JSON.stringify({ code: 0, data: { task_id: `task-${staged.length}` } })
        this.handlers.load()
      })
    }
  }
  const fetch = async (url, opts) => {
    if (url !== '/api/transfers/browser-upload') throw Error(`Unexpected request ${url}`)
    const data = JSON.parse(opts.body)
    payloads.push(data)
    return { ok: true, json: async () => ({ code: 0, data: {
      transfer_id: `t-${payloads.length}`, browser_upload_token: 'token',
      browser_upload_path: `/api/transfers/browser-upload/t-${payloads.length}/content`,
    } }) }
  }
  const sourceApi = source.replace(/^export (async )?function /gm, '$1function ')
  const api = vm.runInNewContext(`(() => { ${sourceApi}; return { uploadRemoteFileToClient } })()`,
    { fetch, XMLHttpRequest: FakeXHR, Map, Promise, console })
  const c = vueComponent('RemoteFilesDialog', {
    RemotePinsDialog: {}, RemoteFilePicker: {}, DragUploadDialog: {}, MoreFilled: {}, OPEN_TRANSFER_CENTER_KEY: 'x',
    flattenUploadAttachments, createTerminalOperation: () => ({ operation_id: 'real-transfer-batch' }),
    makeRemoteDirectory: async () => ({ ok: true, json: async () => ({ code: 0 }) }),
    prepareUploadConflict: async () => 'stop', uploadRemoteFileToClient: api.uploadRemoteFileToClient,
    startBrowserUploadBatch: async () => ({}),
    showTransferStartedToast: () => {}, finalizeBrowserUploadBatch: async () => {},
    ElMessage: { success() {}, warning() {}, error(e) { throw Error(e) } },
  })
  const ui = instance(c, {
    visible: true, remoteFilesClientId: 'client', remoteFilesCurrentPath: '/root',
    dragUploadVisible: true, getTabScopedHeaders: () => ({ 'X-Tab-Id': 'tab' }),
    $emit: () => {}, async refreshRemoteDirectory() {},
  })
  const entries = Array.from({ length: 100 }, (_, i) => ({
    file: { name: `file-${i}.txt`, size: 1 }, relativePath: `docs/file-${i}.txt`,
  }))
  await ui.handleDragUpload([{ kind: 'directory', name: 'docs', directories: ['docs'], files: entries }])
  assert.equal(staged.length, 100)
  assert.equal(payloads.length, 100)
  assert.equal(payloads[99].filename, 'file-99.txt')
  assert.equal(payloads[99].destination_path, '/root/docs')
  assert.deepEqual(payloads.map(p => p.batch_index), [...Array(100).keys()])
  assert.ok(payloads.every(p => p.batch_id === 'real-transfer-batch' && p.batch_total === 100))
  assert.equal(ui.dragUploadVisible, false)
})

test('batch finalization uses one server call carrying the tab and batch identity', async () => {
  const source = read('../src/api/transferApi.js')
  const requests = []
  const fetch = async (url, opts) => {
    requests.push({ url, method: opts.method, headers: opts.headers, body: JSON.parse(opts.body) })
    return { ok: true, json: async () => ({ code: 0, data: { batch_id: 'batch-123' } }) }
  }
  const code = source.replace(/^export (async )?function /gm, '$1function ')
  const api = vm.runInNewContext(`(() => { ${code}; return { finalizeBrowserUploadBatch } })()`, { fetch, Map })
  await api.finalizeBrowserUploadBatch({ clientId: 'client-1', batchId: 'batch-123', folderCount: 2 }, { 'X-Tab-Id': 'tab-1' })
  assert.deepEqual(plain(requests), [{
    url: '/api/transfers/browser-upload-batch/finalize', method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Tab-Id': 'tab-1' },
    body: { client_id: 'client-1', batch_id: 'batch-123', folder_count: 2, error: '' },
  }])
})

test('dragging a single loose file uses the original Upload handler without a Batch', async () => {
  const events = []
  const c = vueComponent('RemoteFilesDialog', {
    RemotePinsDialog: {}, RemoteFilePicker: {}, DragUploadDialog: {}, MoreFilled: {}, OPEN_TRANSFER_CENTER_KEY: 'x',
    flattenUploadAttachments,
    startBrowserUploadBatch: () => { throw Error('Single file must not create a Batch') },
    ElMessage: { warning() {}, error(e) { throw Error(e) } },
  })
  const ui = instance(c, {
    visible: true, dragUploadVisible: true, remoteFilesClientId: 'client',
    remoteFilesCurrentPath: '/target',
    async uploadSelectedFile(file) {
      events.push(['upload', file.name]); return true
    },
    async refreshRemoteDirectory() { events.push(['refresh']) },
  })
  await ui.handleDragUpload([{ kind: 'file', name: 'one.png', file: { name: 'one.png' } }])
  assert.deepEqual(events, [['upload', 'one.png'], ['refresh']])
  assert.equal(ui.dragUploadVisible, false)
})

test('batch conflicts reuse Skip, Keep Both and Stop decisions before creating transfers', async () => {
  const order = []
  let scope
  const c = vueComponent('RemoteFilesDialog', {
    RemotePinsDialog: {}, RemoteFilePicker: {}, DragUploadDialog: {}, MoreFilled: {}, OPEN_TRANSFER_CENTER_KEY: 'x',
    flattenUploadAttachments, createTerminalOperation: () => ({ operation_id: 'conflict-batch' }),
    startBrowserUploadBatch: async args => order.push(['start', args.files.length]),
    finalizeBrowserUploadBatch: async args => order.push(['finalize', args.error]),
    prepareRemoteUploadPlan: async (_, __, plan) => ({ ...plan, reused: new Set(), files: plan.files.filter(entry => entry.file.name !== 'skip.txt').map(entry => ({ ...entry, policy: entry.file.name === 'copy.txt' ? 'keep_both' : 'stop' })) }),
    uploadRemoteFileToClient: async args => order.push(['file', args.file.name, args.conflictPolicy]),
    showTransferStartedToast: () => {},
    ElMessage: { success() {}, warning() {}, error(e) { throw Error(e) } },
  })
  const ui = instance(c, {
    visible: true, remoteFilesClientId: 'client', remoteFilesCurrentPath: '/root', dragUploadVisible: true,
    getTabScopedHeaders: () => ({ 'X-Tab-Id': 'tab' }), $emit: () => {},
    async refreshRemoteDirectory() {},
  })
  const files = ['skip.txt', 'copy.txt', 'new.txt'].map(name => ({ file: { name }, relativePath: name }))
  await ui.handleDragUpload(files.map(({ file }) => ({ kind: 'file', name: file.name, file })))
  assert.deepEqual(order, [
    ['start', 2], ['file', 'copy.txt', 'keep_both'], ['file', 'new.txt', 'stop'], ['finalize', ''],
  ])

  order.length = 0
  const stopUi = instance(c, {
    visible: true, remoteFilesClientId: 'client', remoteFilesCurrentPath: '/root', dragUploadVisible: true,
    getTabScopedHeaders: () => ({ 'X-Tab-Id': 'tab' }), $emit: () => {},
    async refreshRemoteDirectory() {},
  })
  // A cancelled or Stop decision aborts the entire submission before any transfer starts.
  const stopErrors = []
  const stopOutput = []
  const stopComponent = vueComponent('RemoteFilesDialog', {
    RemotePinsDialog: {}, RemoteFilePicker: {}, DragUploadDialog: {}, MoreFilled: {}, OPEN_TRANSFER_CENTER_KEY: 'x',
    flattenUploadAttachments, createTerminalOperation: () => ({ operation_id: 'stop-batch' }),
    prepareRemoteUploadPlan: async () => false,
    startBrowserUploadBatch: () => { throw Error('should not create a batch') },
    ElMessage: { success() {}, warning() {}, error(e) { stopErrors.push(e) } },
  })
  for (const [key, fn] of Object.entries(stopComponent.methods)) stopUi[key] = fn.bind(stopUi)
  stopUi.$emit = (event, ...args) => stopOutput.push([event, ...args])
  await stopUi.handleDragUpload(files.map(({ file }) => ({ kind: 'file', name: file.name, file })))
  assert.equal(order.length, 0)
  assert.deepEqual(stopErrors, [])
  assert.equal(stopOutput.filter(row => row[0] === 'append-output').length, 0)
})

test('shared conflict policy resolver retains Skip for batches and Stop for cancellation', async () => {
  const source = read('../src/utils/remoteFileConflicts.js')
  const expectData = read('../src/utils/fileConflictDecisions.js').match(/async function expectData\(response, label\) \{[\s\S]*?\n\}/)?.[0]
  const prepareUpload = source.match(/export async function prepareUploadConflict\([\s\S]*?\n\}/)?.[0]
  assert.ok(expectData && prepareUpload)
  let answer = 'skip'
  let inspectCount = 0
  const resolve = vm.runInNewContext(`(() => { ${expectData}\n${prepareUpload.replace('export ', '')}\nreturn prepareUploadConflict })()`, {
    conflictsEnabled: async () => true,
    isBrowserUploadBatchCancelled: () => false,
    listRemoteDirectory: async () => ({ ok: false, json: async () => ({ code: 1 }) }),
    inspectRemoteUpload: async () => {
      inspectCount++
      return { ok: true, json: async () => ({ code: 0, data: { conflicts: [{ target: '/dest/file', allowed_actions: ['stop', 'skip', 'keep_both'] }] } }) }
    },
    chooseConflict: async () => answer,
  })
  assert.equal(await resolve('client', '/dest', 'file', { allowSkip: true }), 'skip')
  assert.equal(await resolve('client', '/dest', 'file'), false)
  answer = 'keep_both'
  assert.equal(await resolve('client', '/dest', 'file', { allowSkip: true }), 'keep_both')
  answer = 'stop'
  assert.equal(await resolve('client', '/dest', 'file', { allowSkip: true }), false)
  assert.equal(await resolve('client', '/dest', 'file', { promptEnabled: false }), 'stop')
  assert.equal(inspectCount, 4)
})


test('directory picker restores ancestors and rejects ambiguous duplicate selection', () => {
  const file = { name: 'a.txt', size: 7, webkitRelativePath: 'docs/sub/a.txt' }
  const roots = collectDirectoryPickerAttachments([file])
  assert.deepEqual(flattenUploadAttachments(roots).directories, ['docs', 'docs/sub'])
  assert.equal(flattenUploadAttachments(roots).totalBytes, 7)
  assert.throws(() => flattenUploadAttachments([...roots, ...roots]), /Duplicate selected item/)
})

test('mixed drag falls back per item and refuses unreadable items instead of dropping them', async () => {
  const items = [{ kind: 'file', webkitGetAsEntry: () => file('a.txt') }, { kind: 'file', getAsFile: () => ({ name: 'b.txt', size: 3 }) }]
  assert.deepEqual((await collectTransferAttachments({ items })).map(x => x.name), ['a.txt', 'b.txt'])
  await assert.rejects(collectTransferAttachments({ items: [...items, { kind: 'file' }] }), /Cannot read all/)
  assert.deepEqual(flattenUploadAttachments([{ kind: 'directory', name: 'root', directories: ['root/sub/empty'], files: [] }]).directories, ['root', 'root/sub', 'root/sub/empty'])
})

test('remote tree preflight inspects once and skips descendants of a conflicting folder', async () => {
  const source = read('../src/utils/remoteFileConflicts.js')
  const body = source.slice(source.indexOf('export async function prepareRemoteUploadPlan')).replace('export ', '')
  let inspected = 0
  const resolve = vm.runInNewContext(`(() => { ${body}; return prepareRemoteUploadPlan })()`, {
    conflictsEnabled: async () => true, expectData: async x => x,
    inspectRemoteUploadPlan: async (_, __, paths, dirs) => { inspected++; return { folder_conflicts: [{ source: 'root/sub', allowed_actions: ['stop', 'skip'] }], conflicts: [{ index: 0, source: 'root/sub/a' }] } },
    chooseConflict: async conflict => { assert.equal(conflict.source, 'root/sub'); return 'skip' },
  })
  const plan = { directories: ['root','root/sub'], files: [{ relativePath: 'root/sub/a' }, { relativePath: 'root/b' }] }
  const result = await resolve('c', '/dest', plan)
  assert.equal(inspected, 1)
  assert.deepEqual(plain(result.directories), ['root'])
  assert.deepEqual(plain(result.files), [{ relativePath: 'root/b', policy: 'stop' }])
})

test('native folder selection accepts multiple roots and repeated picks accumulate alongside files', () => {
  const source = read('../src/components/DragUploadDialog.vue')
  const component = vm.runInNewContext(`(${source.match(/<script>([\s\S]*?)<\/script>/)[1].replace(/^import .*$/gm, '').replace('export default', '')})`, {
    collectDirectoryPickerAttachments, flattenUploadAttachments, ElMessage: { error(message) { throw Error(message) } },
  })
  const ui = instance(component, { modelValue: true, multiple: true, allowDirectories: true, loading: false, progress: null })
  const change = files => ({ target: { files, value: 'chosen' } })
  const picked = path => ({ name: path.split('/').at(-1), size: 7, webkitRelativePath: path })
  const first = change([picked('docs/a.txt'), picked('photos/b.png')])
  ui.handleFolderInputChange(first)
  assert.equal(first.target.value, '')
  ui.handleFolderInputChange(change([picked('logs/sub/c.log')]))
  ui.handleInputChange(change([{ name:'loose.txt', size: 3 }]))
  assert.deepEqual(plain(ui.selectedItems.map(x => x.name)), ['docs','photos','logs','loose.txt'])
  assert.deepEqual(plain(ui.selectionSummary.directories), ['docs','logs','photos','logs/sub'])
  assert.equal(ui.selectionSummary.totalBytes,24)
  ui.loading = true
  ui.handleFolderInputChange(change([picked('ignored/d')]))
  assert.equal(ui.selectedItems.length,4)
  assert.match(source, /webkitdirectory multiple/)
  assert.match(source, /Choose files/)
  assert.match(source, /Choose again to add more files or folders/)
  assert.equal(ui.displayProgress,null)
  ui.progress = 33.4
  assert.equal(ui.displayProgress,33)
  ui.progress = 108
  assert.equal(ui.displayProgress,100)
  assert.match(source, /:indeterminate="displayProgress === null"/)
})
