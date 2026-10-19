import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import vm from 'node:vm'

// Exercise the actual component methods without importing Vue/Vite or Monaco browser workers.
function mountDocuments() {
  const source = readFileSync(new URL('../src/components/DocumentsDialog.vue', import.meta.url), 'utf8')
  const script = source.match(/<script>([\s\S]*?)<\/script>/)?.[1]
  assert.ok(script)
  const code = script.split('\n').filter(line => !/^import /.test(line)).join('\n')
    .replace('export default {', 'const component = {') + '\nglobalThis.component = component'

  let createCount = 0
  let disposeCount = 0
  let layoutCount = 0
  const editors = []
  let frameId = 0
  const frames = new Map()
  let timerId = 0
  const timers = new Map()
  const editorHost = { isConnected: true, contains: node => editors.some(editor => editor.dom === node) }

  const monaco = {
    editor: {
      create(host, options) {
        assert.equal(host, editorHost)
        createCount++
        let value = options.value
        const listeners = []
        const editor = {
          dom: { isConnected: true },
          getDomNode() { return this.dom },
          getValue() { return value },
          setValue(text) { value = text; listeners.forEach(listener => listener()) },
          getModel() { return { setValue: text => editor.setValue(text) } },
          onDidChangeModelContent(listener) { listeners.push(listener) },
          layout() { layoutCount++ },
          blur() {},
          dispose() { disposeCount++; throw Error('Monaco dispose must never run') },
        }
        editors.push(editor)
        return editor
      },
    },
  }
  class MarkdownIt {
    constructor() {
      this.renderer = { rules: {} }
      this.utils = { escapeHtml: text => text }
    }
    render(text) { return text }
  }
  const context = {
    monaco, MarkdownIt, EditorWorker: class {},
    ElMessage: { success() {}, error() {} },
    ElMessageBox: {}, Close: {}, FullScreen: {}, Document: {}, Folder: {},
    documentsApi: {},
    setTimeout(callback) { const id = ++timerId; timers.set(id, callback); return id },
    clearTimeout(id) { timers.delete(id) },
    window: {
      requestAnimationFrame(callback) { const id = ++frameId; frames.set(id, callback); return id },
      cancelAnimationFrame(id) { frames.delete(id) },
    },
  }
  vm.runInNewContext(code, context, { filename: 'DocumentsDialog.vue', timeout: 1000 })
  const { component } = context
  const instance = {
    ...component.data(),
    ...component.methods,
    $refs: { editorHost },
    $nextTick(callback) { return Promise.resolve().then(callback) },
  }
  Object.assign(instance, {
    visible: true, currentRoot: 'notes', currentPath: 'sample.md', currentEditable: true,
    currentEncoding: 'utf-8', currentSha256: 'before',
    sourceText: '# Original', originalText: '# Original', previewText: '# Original',
  })
  async function flushFrames() {
    for (let i = 0; i < 10; i++) {
      await Promise.resolve()
      const pending = [...frames.values()]
      frames.clear()
      if (!pending.length) { await Promise.resolve(); if (!frames.size) break; continue }
      for (const callback of pending) callback()
    }
    assert.equal(frames.size, 0, 'animation frames should settle')
  }
  return {
    instance, editors, component, timers, flushFrames, documentsApi: context.documentsApi,
    get createCount() { return createCount },
    get disposeCount() { return disposeCount },
    get layoutCount() { return layoutCount },
  }
}

test('Documents reuses one non-reactive Monaco instance across Edit / Cancel / close / reopen', async () => {
  const app = mountDocuments()
  const { instance } = app
  assert.equal('editor' in instance, false, 'Monaco must not enter reactive component data')

  instance.startEdit()
  await app.flushFrames()
  assert.equal(app.createCount, 1)
  assert.ok(app.layoutCount >= 1)
  app.editors[0].setValue('## Updated')
  assert.equal(instance.sourceText, '## Updated')
  assert.equal(app.timers.size, 1)
  for (const callback of app.timers.values()) callback()
  assert.equal(instance.previewText, '## Updated')

  instance.cancelEdit()
  assert.equal(instance.editing, false)
  assert.equal(instance.sourceText, '# Original')
  instance.startEdit()
  await app.flushFrames()
  assert.equal(app.createCount, 1)
  assert.equal(app.editors[0].getValue(), '# Original')

  instance.onClose()
  assert.equal(instance.editing, false)
  instance.visible = true
  instance.currentPath = 'another.md'
  instance.currentEditable = true
  instance.sourceText = '# Another'
  instance.originalText = '# Another'
  instance.startEdit()
  await app.flushFrames()
  assert.equal(app.createCount, 1)
  assert.equal(app.editors[0].getValue(), '# Another')
  app.component.beforeUnmount.call(instance)
  assert.equal(app.disposeCount, 0)
})

test('Documents cancels Monaco initialization if editing is cancelled or dialog closes before paint', async () => {
  const app = mountDocuments()
  const { instance } = app
  instance.startEdit()
  instance.cancelEdit()
  await app.flushFrames()
  assert.equal(app.createCount, 0)

  instance.startEdit()
  await Promise.resolve() // nextTick schedules the creation frame
  instance.visible = false
  instance.onClose()
  await app.flushFrames()
  assert.equal(app.createCount, 0)
  assert.equal(app.disposeCount, 0)
})

test('Documents keeps Monaco host in the DOM across read/edit transitions', () => {
  const source = readFileSync(new URL('../src/components/DocumentsDialog.vue', import.meta.url), 'utf8')
  assert.match(source, /:destroy-on-close="false"/)
  assert.match(source, /v-show="currentPath && editing" class="documents-split"/)
  assert.doesNotMatch(source, /v-if="editing" class="documents-split"/)
  assert.doesNotMatch(source, /\.dispose\(\)/)
  assert.match(source, /const documentEditorStore = new WeakMap\(\)/)
})

test('Documents keeps the same Monaco instance when switching documents and ignores edits after Cancel', async () => {
  const app = mountDocuments()
  const { instance } = app
  instance.startEdit()
  await app.flushFrames()
  app.editors[0].setValue('# Unsaved edit')
  assert.equal(app.timers.size, 1)
  instance.cancelEdit()
  assert.equal(app.timers.size, 0)
  app.editors[0].setValue('# Stale callback')
  assert.equal(instance.sourceText, '# Original', 'inactive editor cannot change the document state')

  app.documentsApi.readDocument = async () => ({
    encoding: 'utf-8', editable: true, sha256: 'next-sha', content: '# New file',
  })
  await instance.openDocument('notes', 'another.md')
  assert.equal(instance.sourceText, '# New file')
  assert.equal(instance.editing, false)
  instance.startEdit()
  await app.flushFrames()
  assert.equal(app.createCount, 1)
  assert.equal(app.editors[0].getValue(), '# New file')
  assert.equal(app.disposeCount, 0)
})
