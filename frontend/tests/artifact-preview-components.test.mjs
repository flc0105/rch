import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import * as formatters from '../src/utils/formatters.js'
import * as artifactPresentation from '../src/utils/artifactPresentation.js'
import * as artifactConstants from '../src/data/artifactConstants.js'
import { PREVIEW_SOURCE_OPERATIONS } from '../src/utils/previewSources.js'
import { normalizeServerJobFilename } from '../src/utils/jobFilename.js'

const root = new URL('../src/', import.meta.url)
const read = path => readFileSync(new URL(path, root), 'utf8')
const plain = value => JSON.parse(JSON.stringify(value))
const response = data => ({ ok: true, async json() { return { code: 0, data } } })
const textPayload = (name, content, extra = {}) => ({ type: 'text', name, content, size: content.length, editable: true, encoding: 'utf-8', ...extra })
function deferred() {
  let resolve, reject
  const promise = new Promise((a, b) => { resolve = a; reject = b })
  return { promise, resolve, reject }
}

// Evaluate the actual Options API modules; only DOM/transport/UI boundaries are stubbed.
function loadComponent(name, dependencies = {}) {
  const source = read(`components/${name}.vue`).match(/<script>([\s\S]*?)<\/script>/)[1]
  const errors = [], notices = [], events = []
  const env = {
    ...formatters, ...artifactPresentation, ...artifactConstants, PREVIEW_SOURCE_OPERATIONS, normalizeServerJobFilename,
    ElMessage: { error: x => errors.push(x), warning: x => notices.push(x), success: x => notices.push(x), info: x => notices.push(x) },
    console, AbortController, FormData, Blob, File, window: { cancelAnimationFrame() {} },
    ...dependencies,
  }
  const evaluate = (code, filename) => vm.runInNewContext(`(() => {\n${code.replace(/^import .*$/gm, '').replace('export default', 'return')}\n})()`, env, { filename })
  const modules = []
  for (const [, binding, path] of source.matchAll(/^import (\w+) from ['"](\.\.\/composables\/use(?:Artifact|Preview)[^'"]+\.js)['"]$/gm)) {
    env[binding] = evaluate(read(path.replace('../', '')), path)
    modules.push(env[binding])
  }
  for (const [, binding] of source.matchAll(/^import (\w+) from .*\.vue['"]$/gm)) env[binding] = {}
  Object.assign(env, { Close: {}, FullScreen: {}, Folder: {}, FolderOpen: {} })
  const component = evaluate(source, name)
  assert.equal(component.mixins?.length || 0, modules.length)
  for (let i = 0; i < modules.length; i++) assert.equal(component.mixins[i], modules[i])
  const options = [...modules, component]
  const instance = { ...Object.assign({}, ...options.map(part => part.data?.())), selectedId: 'client-a', currentConnection: { machine_id: 'machine-a' }, machineAliasMap: {}, $refs: {}, $emit: (...args) => events.push(args), $nextTick: cb => { cb?.(); return Promise.resolve() } }
  const names = new Set()
  for (const part of options) {
    for (const [key, method] of Object.entries(part.methods || {})) {
      assert.ok(!names.has(key), `duplicate method ownership: ${key}`)
      names.add(key)
      instance[key] = method.bind(instance)
    }
    for (const [key, getter] of Object.entries(part.computed || {})) {
      assert.ok(!names.has(key), `duplicate computed ownership: ${key}`)
      names.add(key)
      Object.defineProperty(instance, key, { get: getter.bind(instance), configurable: true })
    }
  }
  if (name === 'PreviewDialog') {
    let visible = instance.previewDialogVisible
    Object.defineProperty(instance, 'previewDialogVisible', { get: () => visible, set: value => {
      if (visible === value) return
      visible = value
      component.watch.previewDialogVisible.handler.call(instance, value)
    } })
    // Unit tests for content and transport do not require Monaco/DOM; a separate test drives the real lifecycle.
    instance.initMonacoEditor = () => {}
  }
  return { instance, errors, notices, events, modules, component }
}

test('Artifact catalog discards stale results and retains machine/tab/folder filtering', async () => {
  const old = deferred(), latest = deferred()
  let calls = 0
  const { instance: ui, errors } = loadComponent('ArtifactDialog', { listArtifacts: () => (++calls === 1 ? old.promise : latest.promise) })
  const first = ui.loadArtifacts(), second = ui.loadArtifacts()
  latest.resolve(response({ items: [
    { artifact_id: 'a', artifact_type: 'saved', machine_id: 'machine-a', folder_id: 'folder-a', original_name: 'new.txt' },
    { artifact_id: 'b', artifact_type: 'saved', machine_id: 'machine-b', folder_id: 'folder-a' },
    { artifact_id: 'c', artifact_type: 'shared', folder_id: 'shared-root' },
  ], folders: [{ folder_id: 'folder-a', name: 'Downloads', artifact_type: 'saved' }] }))
  await second
  old.resolve(response({ items: [] }))
  await first
  ui.artifactMachineIdFilter = 'machine-a'
  ui.selectedFolderId = 'folder-a'
  assert.deepEqual(plain(ui.filteredArtifactItems.map(x => x.artifact_id)), ['a'])
  assert.equal(ui.artifactCountMap.saved, 1)
  assert.equal(ui.artifactCountMap.shared, 1)
  assert.equal(ui.artifactLoading, false)
  assert.deepEqual(errors, [])
})

test('Artifact Clear passes the confirmed type, machine and folder even if selection changes', async () => {
  const confirm = deferred(), calls = []
  const { instance: ui } = loadComponent('ArtifactDialog', {
    ElMessageBox: { confirm: () => confirm.promise },
    clearArtifacts: (...args) => { calls.push(args); return Promise.resolve(response({ deleted_count: 1 })) },
    listArtifacts: async () => response({}),
  })
  ui.artifactMachineIdFilter = 'machine-a'
  ui.selectedFolderId = 'folder-a'
  const work = ui.clearCurrentArtifacts()
  ui.artifactActiveTab = 'shared'; ui.selectedFolderId = 'folder-b'; ui.artifactMachineIdFilter = ''
  confirm.resolve(); await work
  assert.deepEqual(calls, [['saved', 'machine-a', 'folder-a']])
  assert.equal(ui.artifactClearing, false)
})

test('Artifact info response cannot reopen a closed manager or overwrite the selected details', async () => {
  const old = deferred(), latest = deferred()
  const { instance: ui } = loadComponent('ArtifactDialog', { getArtifactDetail: id => id === 'old' ? old.promise : latest.promise })
  ui.visible = true
  const a = ui.openArtifactInfoDialog({ artifact_id: 'old' })
  const b = ui.openArtifactInfoDialog({ artifact_id: 'new' })
  latest.resolve(response({ artifact_id: 'new', size: 20 })); await b
  old.resolve(response({ artifact_id: 'old' })); await a
  assert.equal(ui.artifactInfoItem.artifact_id, 'new')
  const again = ui.openArtifactInfoDialog({ artifact_id: 'new' })
  ui.handleVisibleChange(false); await again
  assert.equal(ui.artifactInfoDialogVisible, false)
  assert.equal(ui.artifactInfoItem, null)
})

test('Artifact and image details share one renderer, with independent metadata labels', () => {
  const sections = artifactPresentation.formatArtifactInfoSections({ original_name: 'example.txt', size: 42, extra: { z: true, a: 'first' } })
  assert.deepEqual(sections.map(x => x.title), ['Basic', 'Extras'])
  assert.deepEqual(sections[1].items.map(x => x.key), ['a', 'z'])
  assert.match(sections[0].items.find(x => x.key === 'size').value, /42 bytes/)
  assert.match(read('components/ArtifactDialog.vue'), /<FileInfoDialog\b/)
  assert.match(read('components/PreviewImageInfoDialog.vue'), /<FileInfoDialog\b/)
  const list = read('components/ArtifactFileList.vue'), menu = read('components/ArtifactActionMenu.vue')
  assert.equal((list.match(/<ArtifactActionMenu\b/g) || []).length, 2)
  for (const action of ['info', 'rename', 'move', 'send-current-device', 'send-current-device-clipboard', 'delete']) {
    assert.ok(menu.includes(`command="${action}"`))
  }
})

test('opening a second Preview ignores a late remote payload and binds Artifact ID', async () => {
  const remote = deferred(), artifact = deferred()
  const { instance: ui, errors } = loadComponent('PreviewDialog', {
    fetch: () => remote.promise, previewArtifact: () => artifact.promise,
  })
  const first = ui.previewRemoteEntry({ path: '/first.txt', name: 'first.txt', client_id: 'client-a' })
  const second = ui.previewArtifact({ artifact_id: 'artifact-b', original_name: 'b.txt' })
  artifact.resolve(response(textPayload('b.txt', 'B'))); await second
  remote.resolve(response(textPayload('first.txt', 'A', { artifact_id: 'cache-a' }))); await first
  assert.equal(ui.previewSource, 'artifact')
  assert.equal(ui.previewFilePath, 'artifact-b')
  assert.equal(ui.previewRemoteClientId, '')
  assert.equal(ui.previewCacheArtifactId, '')
  assert.equal(ui.previewText, 'B')
  assert.equal(ui.previewLoading, false)
  assert.deepEqual(errors, [])
})

test('closing Preview invalidates an in-flight read; URL-only Job attachment has no save route', async () => {
  const pending = deferred()
  const { instance: ui } = loadComponent('PreviewDialog', {
    previewArtifact: () => pending.promise,
    previewBackgroundJobFile: async () => response(textPayload('job.txt', 'attachment')),
  })
  const old = ui.previewArtifact({ artifact_id: 'a' })
  ui.previewDialogVisible = false
  pending.resolve(response(textPayload('a.txt', 'a'))); await old
  assert.equal(ui.previewDialogVisible, false)
  assert.equal(ui.previewFilePath, '')
  await ui.previewBackgroundJobFile({ preview_url: '/job-preview' })
  assert.equal(ui.previewSource, 'job_attachment')
  assert.equal(ui.previewEditable, false)
  assert.equal(ui.previewFilePath, '')
  assert.equal(ui.previewText, 'attachment')
})

test('Remote save uses the opened Client/path/encoding and late completion cannot modify a new editor', async () => {
  const pending = deferred(), calls = []
  const { instance: ui, events } = loadComponent('PreviewDialog', {
    fetch: (url, options) => {
      calls.push([url, options])
      return url.endsWith('/save') ? pending.promise : Promise.resolve(response(textPayload('file.txt', 'original', { encoding: 'utf-16-le' })))
    },
  })
  ui.remoteFilesDialogVisible = true
  await ui.editRemoteEntry({ path: '/test/file.txt', client_id: 'client-a' })
  ui.selectedId = 'client-b'
  ui.previewText = 'edited'
  const save = ui.saveEditedContent()
  assert.equal(calls[1][0], '/api/connections/client-a/remote-files/save')
  assert.deepEqual(JSON.parse(calls[1][1].body), { path: '/test/file.txt', content: 'edited', encoding: 'utf-16-le' })
  ui.openNewSharedFileEditor('new.txt', 'folder-b')
  ui.previewText = 'new unsaved'
  pending.resolve(response({})); await save
  assert.equal(ui.previewSource, 'new_shared_file')
  assert.equal(ui.previewText, 'new unsaved')
  assert.equal(ui.previewEditMode, true)
  assert.ok(events.some(x => x[0] === 'remote-directory-maybe-changed'))
})

test('shared editor creates an Artifact in the selected folder and subsequent Save uses its ID', async () => {
  const calls = []
  const { instance: ui } = loadComponent('PreviewDialog', {
    uploadArtifact: async body => { calls.push(['create', body]); return response({ artifact_id: 'created-id', original_name: 'new.txt', size: 4 }) },
    saveArtifactContent: async (...args) => { calls.push(['save', ...args]); return response({ size: 7 }) },
  })
  ui.openNewSharedFileEditor('new.txt', 'shared-folder')
  ui.previewText = 'test'
  await ui.saveEditedContent()
  assert.equal(calls[0][1].get('folder_id'), 'shared-folder')
  assert.equal(calls[0][1].get('artifact_type'), 'shared')
  assert.equal(ui.previewFilePath, 'created-id')
  assert.equal(ui.previewSource, 'artifact')
  ui.enterEditMode(); ui.previewText = 'updated'
  await ui.saveEditedContent()
  assert.deepEqual(calls[1], ['save', 'created-id', 'updated', 'utf-8'])
})

test('resource loads, clipboard paste and reload cannot update a newer Preview session', async () => {
  const meta = deferred(), clipboard = deferred(), reload = deferred()
  const { instance: ui } = loadComponent('PreviewDialog', {
    externalToolsApi: { loadExternalToolMetaContent: () => meta.promise },
    previewArtifact: async () => response(textPayload('a.txt', 'a')),
  })
  const load = ui.openExternalToolMetaEditor('tool-a')
  ui.openNewSharedFileEditor('other.txt', '')
  meta.resolve({ name: 'tool.json', content: '{}' }); await load
  assert.equal(ui.previewTitle, 'other.txt')
  ui.readClipboardTextForPaste = () => clipboard.promise
  const paste = ui.pastePreviewText()
  ui.openNewSharedFileEditor('third.txt', '')
  clipboard.resolve('late text'); await paste
  assert.equal(ui.previewText, '')
  await ui.previewArtifact({ artifact_id: 'artifact-a' }); ui.enterEditMode()
  ui.fetchLatestPreviewTextPayload = () => reload.promise
  const pending = ui.reloadPreviewContent()
  ui.openNewSharedFileEditor('fourth.txt', '')
  reload.resolve(textPayload('a.txt', 'old content')); await pending
  assert.equal(ui.previewTitle, 'fourth.txt')
  assert.equal(ui.previewText, '')
  assert.equal(ui.previewEditMode, true)
})

test('Monaco keeps worker setup and reuses editor, but a new session cannot read the previous model', () => {
  let content = '', frameId = 0
  const frames = new Map(), container = { isConnected: true, contains: () => true }
  const dom = { isConnected: true }
  const editor = {
    getDomNode: () => dom, getValue: () => content, setValue: value => { content = value },
    getModel: () => ({ setValue: value => { content = value } }), updateOptions() {}, layout() {},
  }
  const { instance: ui, modules } = loadComponent('PreviewDialog', {
    window: { requestAnimationFrame: cb => { const id = ++frameId; frames.set(id, cb); return id }, cancelAnimationFrame: id => frames.delete(id) },
    monaco: { editor: { create: (_, opts) => { content = opts.value; return editor }, setModelLanguage() {} } },
  })
  ui.initMonacoEditor = modules[0].methods.initMonacoEditor.bind(ui)
  ui.$refs.monacoEditorContainerRef = container
  ui.openNewSharedFileEditor('old.txt', '')
  for (const [id, callback] of [...frames]) { frames.delete(id); callback() }
  editor.setValue('previous model')
  assert.equal(ui.getMonacoEditorContent(), 'previous model')
  ui.openNewSharedFileEditor('new.txt', '')
  assert.equal(ui.getMonacoEditorContent(), '')
  for (const [id, callback] of [...frames]) { frames.delete(id); callback() }
  assert.equal(ui.getMonacoEditorContent(), '')
})


test('Monaco delayed initialization honors current text and edit state', async () => {
  const frames = new Map(), options = []
  let frameId = 0, content = ''
  const container = { isConnected: true, contains: () => true }
  const editor = { getValue: () => content, getDomNode: () => ({ isConnected: true }), layout() {}, updateOptions: o => options.push(o), getModel: () => ({ setValue: v => { content = v } }) }
  const { instance: ui, modules } = loadComponent('PreviewDialog', {
    previewArtifact: async () => response(textPayload('a.txt', 'stale')),
    window: { requestAnimationFrame: cb => { const id = ++frameId; frames.set(id, cb); return id }, cancelAnimationFrame: id => frames.delete(id) },
    monaco: { editor: { create: (_, opts) => { content = opts.value; options.push(opts); return editor }, setModelLanguage() {} } },
  })
  ui.initMonacoEditor = modules[0].methods.initMonacoEditor.bind(ui)
  ui.$refs.monacoEditorContainerRef = container
  await ui.previewArtifact({ artifact_id: 'a' })
  assert.equal(ui.previewText, 'stale')
  assert.equal(ui.previewEditMode, false)
  ui.enterEditMode(); ui.clearPreviewContent()
  for (const [id, callback] of [...frames]) { frames.delete(id); callback() }
  assert.equal(content, '')
  assert.equal(options[0].readOnly, false)
})
test('saving an earlier snapshot preserves newer edits and reports zero byte files', async () => {
  const pending = deferred()
  const { instance: ui } = loadComponent('PreviewDialog', {
    previewArtifact: async () => response(textPayload('a.txt', 'old')),
    saveArtifactContent: () => pending.promise,
  })
  await ui.previewArtifact({ artifact_id: 'a', size: 3 }); ui.enterEditMode()
  ui.previewText = ''
  const save = ui.saveEditedContent()
  ui.previewText = 'new typing'
  pending.resolve(response({ size: 0 })); await save
  assert.equal(ui.previewText, 'new typing')
  assert.equal(ui.previewOriginalContent, '')
  assert.equal(ui.previewEditMode, true)
  assert.equal(ui.previewFileSize, formatters.formatBytes(0))
  ui.cancelEditMode()
  assert.equal(ui.previewText, '')
})


test('Shared Clear confirms recursive scope and reports both files and folders', async () => {
  const confirmations = [], calls = []
  const { instance: ui, notices } = loadComponent('ArtifactDialog', {
    ElMessageBox: { confirm: async message => confirmations.push(message) },
    clearArtifacts: (...args) => { calls.push(args); return Promise.resolve(response({ deleted_count: 2, deleted_folder_count: 3 })) },
    listArtifacts: async () => response({ folders: [{ folder_id: 'a', artifact_type: 'shared', name: 'A' }] }),
  })
  ui.artifactActiveTab = 'shared'; ui.selectedFolderId = 'a'
  await ui.clearCurrentArtifacts()
  assert.deepEqual(calls, [['shared', '', 'a']])
  assert.match(confirmations[0], /files and subfolders/)
  assert.match(confirmations[0], /This folder will be kept/)
  assert.equal(ui.selectedFolderId, 'a')
  assert.deepEqual(notices, ['Cleared 2 file(s), 3 folder(s)'])
})

test('Delete Folder confirms descendants and leaves a valid selection after refresh', async () => {
  const calls = [], confirmations = []
  const { instance: ui } = loadComponent('ArtifactDialog', {
    ElMessageBox: { confirm: async message => confirmations.push(message) },
    deleteArtifactFolder: id => { calls.push(id); return Promise.resolve(response({ deleted_count: 2, deleted_folder_count: 2 })) },
    listArtifacts: async () => response({ folders: [] }),
  })
  ui.artifactActiveTab = 'shared'; ui.selectedFolderId = 'a'
  ui.artifactFolders = [{ folder_id: 'a', artifact_type: 'shared', name: 'A' }]
  await ui.deleteSelectedFolder()
  assert.deepEqual(calls, ['a'])
  assert.match(confirmations[0], /all its files and subfolders/)
  assert.equal(ui.selectedFolderId, '')
})
