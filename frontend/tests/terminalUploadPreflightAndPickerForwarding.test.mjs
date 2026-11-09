import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import { createTerminalOperation, operationHeaders } from '../src/utils/terminalOperation.js'
import { formatTerminalCommandFinishedLine } from '../src/composables/terminalMarkers.js'

const source = name => readFileSync(new URL(`../src/components/${name}`, import.meta.url), 'utf8')

function component(name, callbacks) {
  const tag = source(name).match(/<script>([\s\S]*?)<\/script>/)?.[1]
  assert.ok(tag)
  const env = {
    createTerminalOperation, operationHeaders, formatTerminalCommandFinishedLine,
    ElMessage: { error() {}, warning() {}, success() {} },
    ElMessageBox: { confirm: async () => {} },
    prepareUploadConflict: callbacks.prepareUploadConflict,
    uploadRemoteFileToClient: async () => { throw Error('Upload should not execute') },
    sendArtifactToClient: async () => { throw Error('Artifact send should not execute') },
    RemotePinsDialog: {}, RemoteZipPeekDialog: {}, MoreFilled: {}, DragUploadDialog: {},
    formatBytesValue: value => value,
  }
  vm.runInNewContext(tag.replace(/^import\s+[\s\S]*?\s+from\s+['"][^'"]+['"]\s*;?\s*$/gm, '')
    .replace('export default {', 'globalThis.component = {'), env, { filename: name })
  const emitted = []
  const instance = {
    ...env.component.data(),
    selectedId: 'client-1', remoteFilesClientId: 'client-1',
    remoteFilesCurrentPath: '/somewhere',
    currentConnection: { client_id: 'client-1', cwd: '/somewhere' },
    getCurrentDeviceCwd: () => '/somewhere', formatArtifactName: () => 'report.zip',
    formatCurrentDeviceLabel: () => 'Device', formatCurrentDeviceCwd: () => '/somewhere',
    getTabScopedHeaders: () => ({}), buildRequestHeaders: () => ({}),
    $emit: (...args) => emitted.push(args),
  }
  for (const [n, fn] of Object.entries(env.component.methods)) instance[n] = fn.bind(instance)
  return { instance, emitted }
}

const calls = emitted => emitted.filter(item => item[0] === 'append-output')
const texts = emitted => calls(emitted).map(item => item[2])

for (const [name, methodName, wantStart] of [
  ['RemoteFilesDialog.vue', 'handleUploadChange', '> [Remote Upload] report.zip -> /somewhere'],
  ['RemoteFilePicker.vue', 'handleRemoteUploadChange', '> [Remote Upload] report.zip -> /somewhere'],
]) {
  test(`${name}: preflight error has typed header, failure, completion`, async () => {
    const { instance, emitted } = component(name, { prepareUploadConflict: async () => { throw Error('Inspect unreachable') } })
    await instance[methodName]({ target: { files: [{ name:'report.zip', size:100 }], value:'report.zip' } })
    const rows = calls(emitted)
    assert.equal(rows.length, 3)
    assert.equal(rows[0][2], wantStart)
    assert.match(rows[1][2], /\[Upload failed\] Inspect unreachable/)
    assert.match(rows[2][2], /\[Command finished\].*\(Failed\)$/)
    assert.equal(rows[0][3], 'command')
    assert.equal(rows[0][4].operation.operation_id, rows[1][4].operation_id)
    assert.equal(rows[1][4].operation_id, rows[2][4].operation_id)
    assert.equal(rows[2][4].event_type, 'completed')
    assert.ok(!emitted.some(item => item[0] === 'set-active-task'))
  })

  test(`${name}: cancelled conflict prompt does not create a terminal operation`, async () => {
    const { instance, emitted } = component(name, { prepareUploadConflict: async () => false })
    await instance[methodName]({ target: { files: [{ name:'report.zip' }], value:'report.zip' } })
    assert.deepEqual(texts(emitted), [])
  })
}

test('Artifact Send: failed conflict preflight gets matching start and terminal failed status', async () => {
  const { instance, emitted } = component('ArtifactDialog.vue', {
    prepareUploadConflict: async () => { throw Error('Conflict scan unavailable') },
  })
  await instance.sendArtifactToCurrentDevice({ artifact_id: 'artifact-1' })
  assert.equal(calls(emitted).length, 3)
  assert.equal(texts(emitted)[0], '> [Artifact Send] artifact -> client-1 :: /somewhere')
  assert.match(texts(emitted)[1], /\[Artifact send failed\] Conflict scan unavailable/)
  assert.match(texts(emitted)[2], /\[Command finished\].*\(Failed\)/)
  assert.equal(calls(emitted)[0][4].operation.operation_id, calls(emitted)[2][4].operation_id)
})

// Compile and execute the actual forwarding method bodies without mounting unrelated dialogs.
function forwardingMethod(fileName, name, params) {
  const text = source(fileName)
  const start = text.indexOf(`${name}(`)
  assert.ok(start > 0, `${fileName} ${name}`)
  const open = text.indexOf('{', start)
  let balance = 0, end = -1
  for (let i = open; i < text.length; i++) {
    if (text[i] === '{') balance++
    if (text[i] === '}' && --balance === 0) { end = i; break }
  }
  assert.ok(end > open)
  return new Function(...params, text.slice(open + 1, end))
}

for (const name of ['ScriptRunDialog.vue', 'BackgroundJobStartDialog.vue',
  'BackgroundJobsDialog.vue', 'ExternalToolManagerDialog.vue', 'ScriptLibraryDialog.vue']) {
  test(`${name}: Remote Folder Picker preserves operation metadata and task identity`, () => {
    const emitted = [], ctx = { $emit(...args) { emitted.push(args) } }
    const a = forwardingMethod(name, 'forwardAppendOutput', ['clientId','line','kind','meta'])
    const t = forwardingMethod(name, 'forwardSetActiveTask', ['clientId','taskId','cancelPolicy','historyEntryId','operationId'])
    const meta = { operation: { operation_id: 'op-xyz', kind: 'transfer' } }
    a.call(ctx, 'client-1', '> [Remote Upload] file.zip -> /somewhere', 'command', meta)
    t.call(ctx, 'client-1', 'task-1', '', '', 'op-xyz')
    assert.equal(emitted[0][4], meta)
    assert.equal(emitted[1][5], 'op-xyz')
  })
}
