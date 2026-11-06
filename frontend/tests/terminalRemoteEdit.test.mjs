import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import vm from 'node:vm'

const commandSource = readFileSync(new URL('../src/components/CommandInputBar.vue', import.meta.url), 'utf8')
const appSource = readFileSync(new URL('../src/App.vue', import.meta.url), 'utf8')
const previewSource = readFileSync(new URL('../src/components/PreviewDialog.vue', import.meta.url), 'utf8')
const commandScript = commandSource.match(/<script>([\s\S]*?)<\/script>/)?.[1]
const previewScript = previewSource.match(/<script>([\s\S]*?)<\/script>/)?.[1]
assert.ok(commandScript && previewScript)

const warnings = []
const errors = []
const commandSandbox = { TerminalConnectionContext: {}, ElMessage: {
  warning: message => warnings.push(message), success() {}, error: message => errors.push(message),
}, setTimeout }
vm.runInNewContext(commandScript.replace(/^import\s+[\s\S]*?\s+from\s+['"][^'"]+['"]\s*;?\s*$/gm, '')
  .replace('export default {', 'globalThis.component = {'), commandSandbox)
const commandMethods = commandSandbox.component.methods

function terminal() {
  const events = []
  const ctx = { ...commandMethods, selectedId: 'device-1', commandText: '',
    $emit: (...args) => events.push(args), }
  return { ctx, events }
}

test('edit is handled only in Web terminal and supports client paths and quoting', () => {
  for (const [command, expectedPath] of [
    ['edit test.txt', 'test.txt'],
    ['EDIT ./test/folder/file.txt', './test/folder/file.txt'],
    ['edit /Users/flc/Desktop/aa.txt', '/Users/flc/Desktop/aa.txt'],
    ['edit "my notes.txt"', 'my notes.txt'],
    ["edit 'my notes.txt'", 'my notes.txt'],
    ['edit C:\\Work\\hello world.txt', 'C:\\Work\\hello world.txt'],
    ['edit "C:\\\\A Folder\\\\config.json"', 'C:\\A Folder\\config.json'],
  ]) {
    const { ctx, events } = terminal()
    ctx.commandText = command
    assert.equal(ctx.handleLocalFrontendCommand(command), true)
    assert.equal(events.length, 1)
    assert.equal(events[0][0], 'edit-remote-file')
    assert.equal(events[0][1].client_id, 'device-1')
    assert.equal(events[0][1].path, expectedPath)
    assert.equal(ctx.commandText, '')
  }
  const { ctx, events } = terminal()
  assert.equal(ctx.handleLocalFrontendCommand('editor file.txt'), false)
  assert.equal(ctx.handleLocalFrontendCommand('clear'), true)
  assert.deepEqual(events.map(item => item[0]), ['clear-output'])
})

test('edit missing or malformed path is not sent to a client', () => {
  for (const command of ['edit', 'edit ', 'edit "unclosed']) {
    const { ctx, events } = terminal()
    assert.equal(ctx.handleLocalFrontendCommand(command), true)
    assert.equal(events.length, 0)
  }
  assert.equal(warnings.filter(text => text.includes('Usage: edit')).length, 3)
})

test('App routes edit through the lazy shared preview dialog', () => {
  assert.match(appSource, /@edit-remote-file="editRemoteFile"/)
  assert.match(appSource, /editRemoteFile\(row\)\s*\{\s*return this\.callOptionalDialog\('preview', 'editRemoteEntry', row\)/)
  assert.match(appSource, /previewRemoteEntry\(row\)\s*\{\s*return this\.callOptionalDialog\('preview', 'previewRemoteEntry', row\)/)
})

const requests = []
let nextResponse = null
const previewSandbox = {
  console, ArchivePreviewPanel: {}, PreviewImageInfoDialog: {}, Close: {}, FullScreen: {},
  formatBytes: value => `${value} B`,
  ElMessage: { error: message => errors.push(message), warning: message => warnings.push(message), success() {} },
  fetch: async (url, options) => {
    requests.push({ url, options })
    return nextResponse
  },
}
vm.runInNewContext(previewScript.replace(/^import\s+[^\n]*\n/gm, '')
  .replace('export default {', 'globalThis.component = {'), previewSandbox)
const previewComponent = previewSandbox.component
const payload = data => ({ ok: true, json: async () => ({ code: 0, data }) })

function preview() {
  const state = {
    ...previewComponent.data(), selectedId: 'different-device',
    initCalls: [],
    $nextTick: fn => { if (fn) fn(); return Promise.resolve() },
    getLanguageDisplayName: value => value,
    getLanguageFromFilename: () => 'plaintext',
    initMonacoEditor(content, readOnly) { this.initCalls.push({ content, readOnly }) },
    getMonacoEditorContent() { return 'Saved from Monaco' },
    setMonacoEditorReadOnly(readOnly) { this.lastReadOnly = readOnly },
    $emit() {},
  }
  for (const [name, method] of Object.entries(previewComponent.methods)) {
    if (!(name in state)) state[name] = method.bind(state)
  }
  return state
}

test('terminal edit opens Monaco editable directly; Save uses existing remote file endpoint', async () => {
  const state = preview()
  nextResponse = payload({ type: 'text', name: 'config.json', content: '{"hello":1}',
    encoding: 'utf-8', editable: true, truncated: false })
  await state.editRemoteEntry({ path: './config.json', client_id: 'device-1' })
  assert.equal(requests.at(-1).url, '/api/connections/device-1/remote-files/preview')
  assert.equal(JSON.parse(requests.at(-1).options.body).path, './config.json')
  assert.equal(state.previewRemoteClientId, 'device-1')
  assert.equal(state.previewFilePath, './config.json')
  assert.equal(state.previewSource, 'remote_file')
  assert.equal(state.previewDialogVisible, true)
  assert.equal(state.previewEditMode, true)
  assert.equal(state.initCalls.at(-1).readOnly, false)
  nextResponse = payload({ message: 'saved' })
  await state.saveEditedContent()
  assert.equal(requests.at(-1).url, '/api/connections/device-1/remote-files/save')
  assert.equal(JSON.parse(requests.at(-1).options.body).content, 'Saved from Monaco')
  assert.equal(JSON.parse(requests.at(-1).options.body).encoding, 'utf-8')
  assert.equal(state.previewEditMode, false)
})

test('terminal edit rejects truncated, unsupported and uneditable payloads before showing Monaco', async () => {
  const invalid = [
    [{ type: 'text', content: 'partial', truncated: true, editable: false }, 'exceeds'],
    [{ type: 'image', url: '/image.png' }, 'Only text'],
    [{ type: 'archive', artifact_id: 'zipped' }, 'Only text'],
    [{ type: 'unsupported' }, 'Only text'],
    [{ type: 'text', editable: false, truncated: false }, 'cannot be edited'],
  ]
  for (const [data, part] of invalid) {
    const state = preview()
    const errorsBefore = errors.length
    nextResponse = payload(data)
    await state.editRemoteEntry({ path: '/tmp/readme.txt', client_id: 'device-1' })
    assert.equal(state.previewDialogVisible, false)
    assert.equal(state.previewEditMode, false)
    assert.equal(state.initCalls.length, 0)
    assert.equal(errors.length, errorsBefore + 1)
    assert.ok(errors.at(-1).includes(part), errors.at(-1))
  }
})

test('Remote Files Browser preview remains read-only, including truncated preview', async () => {
  const state = preview()
  nextResponse = payload({ type: 'text', name: 'notes.txt', content: 'text', editable: true,
    encoding: 'utf-8', truncated: false })
  await state.previewRemoteEntry({ path: '/tmp/notes.txt', client_id: 'device-1' })
  assert.equal(state.previewDialogVisible, true)
  assert.equal(state.previewEditMode, false)
  assert.equal(state.initCalls.at(-1).readOnly, true)
  const huge = preview()
  nextResponse = payload({ type: 'text', content: 'prefix', editable: false, truncated: true })
  await huge.previewRemoteEntry({ path: '/tmp/big.txt', client_id: 'device-1' })
  assert.equal(huge.previewDialogVisible, true)
  assert.equal(huge.previewTruncated, true)
  assert.equal(huge.initCalls.at(-1).readOnly, true)
})
