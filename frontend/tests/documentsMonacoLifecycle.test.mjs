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
  let renderCount = 0
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
    render(text) { renderCount++; return text }
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
    get renderCount() { return renderCount },
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

test('Live Preview off skips rendering, stops debounce, and expands Monaco without disposal', async () => {
  const app = mountDocuments()
  const { instance, component } = app
  const render = () => component.computed.renderedMarkdown.call(instance)
  const toggle = enabled => {
    instance.livePreviewEnabled = enabled
    component.watch.livePreviewEnabled.call(instance, enabled)
  }

  assert.equal(instance.livePreviewEnabled, true)
  assert.equal(render(), '# Original')
  assert.equal(app.renderCount, 1)
  instance.startEdit()
  await app.flushFrames()
  app.editors[0].setValue('# Pending')
  assert.equal(app.timers.size, 1)
  const staleRefresh = [...app.timers.values()][0]

  toggle(false)
  assert.equal(app.timers.size, 0, 'pending Markdown preview refresh must be cancelled')
  staleRefresh() // Even a callback already queued for execution cannot refresh a disabled preview.
  assert.equal(instance.previewText, '# Original')
  assert.equal(render(), '', 'disabled preview must never call markdown.render')
  assert.equal(app.renderCount, 1)
  app.editors[0].setValue('# Edited while off')
  assert.equal(instance.sourceText, '# Edited while off')
  assert.equal(app.timers.size, 0, 'typing while off must not schedule a preview refresh')
  assert.equal(instance.previewText, '# Original', 'disabled mode should not keep updating preview text')
  assert.equal(render(), '')
  assert.equal(app.renderCount, 1)

  toggle(true)
  await app.flushFrames()
  assert.equal(instance.previewText, '# Edited while off', 're-enable must use latest Monaco content')
  assert.equal(render(), '# Edited while off')
  assert.equal(app.renderCount, 2)
  assert.equal(app.createCount, 1, 'preview toggle must not recreate Monaco')
  assert.equal(app.disposeCount, 0)
})

test('read-only view and reopened documents render even when Live Preview is disabled', async () => {
  const app = mountDocuments()
  const { instance, component } = app
  const render = () => component.computed.renderedMarkdown.call(instance)
  instance.livePreviewEnabled = false
  instance.startEdit()
  await app.flushFrames()
  app.editors[0].setValue('# New draft')
  assert.equal(render(), '')
  assert.equal(app.renderCount, 0)
  instance.cancelEdit()
  assert.equal(render(), '# Original', 'Cancel returns to a rendered read-only view')
  assert.equal(app.renderCount, 1)

  app.documentsApi.readDocument = async () => ({
    encoding: 'utf-8', editable: true, sha256: 'opened-sha', content: '# Reopened',
  })
  await instance.openDocument('notes', 'other.md')
  assert.equal(render(), '# Reopened', 'opening another document must render in read-only mode')
  assert.equal(app.renderCount, 2)
  instance.startEdit()
  await app.flushFrames()
  assert.equal(app.createCount, 1, 'editor still uses the existing Monaco instance')
  assert.equal(render(), '', 'preview choice remains off in editing mode')
  assert.equal(app.renderCount, 2)
  assert.equal(app.disposeCount, 0)
})

test('Live Preview switch is available only in edit mode and hides the Markdown article when off', () => {
  const source = readFileSync(new URL('../src/components/DocumentsDialog.vue', import.meta.url), 'utf8')
  assert.match(source, /<template v-else-if="editing">[\s\S]*?<el-switch v-model="livePreviewEnabled"/)
  assert.match(source, /<article v-if="editing && livePreviewEnabled" class="documents-markdown"/)
  assert.match(source, /:class="\{ 'documents-split-source-only': !livePreviewEnabled \}"/)
  assert.match(source, /\.documents-split\.documents-split-source-only \{ grid-template-columns: minmax\(0, 1fr\)/)
  assert.match(source, /<article v-if="currentPath && !editing" ref="readerView" class="documents-markdown documents-reader"/)
})

test('Save while live preview is off returns to the up-to-date read-only Markdown rendering', async () => {
  const app = mountDocuments()
  const { instance, component } = app
  let submitted
  app.documentsApi.saveDocument = async payload => {
    submitted = payload
    return { sha256: 'saved-sha' }
  }
  instance.livePreviewEnabled = false
  instance.startEdit()
  await app.flushFrames()
  app.editors[0].setValue('## Saved without live preview')
  assert.equal(app.renderCount, 0)
  await instance.save()
  assert.equal(instance.editing, false)
  assert.equal(instance.originalText, '## Saved without live preview')
  assert.equal(submitted.content, '## Saved without live preview')
  assert.equal(instance.currentSha256, 'saved-sha')
  assert.equal(component.computed.renderedMarkdown.call(instance), '## Saved without live preview')
  assert.equal(app.renderCount, 1)
  assert.equal(app.disposeCount, 0)
})


test('opening a different document resets reader scroll and selects lazily expanded Markdown path', async () => {
  const app = mountDocuments()
  const { instance } = app
  instance.$refs.readerView = { scrollTop: 900 }
  const nodes = new Map()
  const tree = {
    selected: '',
    getNode(key) { return nodes.get(key) || null },
    setCurrentKey(key) { this.selected = key },
  }
  function makeNode(key, nextKey) {
    return {
      loaded: false, expanded: false,
      expand(done) {
        this.loaded = true
        this.expanded = true
        if (nextKey) nodes.set(nextKey, makeNode(nextKey, nextKey === 'notes:guide' ? 'notes:guide/intro.md' : null))
        done()
      },
    }
  }
  nodes.set('notes:', makeNode('notes:', 'notes:guide'))
  nodes.set('notes:overview.md', makeNode('notes:overview.md', null))
  instance.$refs.treeRef = tree
  app.documentsApi.readDocument = async () => ({
    content: '# New', encoding: 'utf-8', editable: true, sha256: 'new',
  })
  await instance.openDocument('notes', 'guide/intro.md')
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(instance.$refs.readerView.scrollTop, 0)
  assert.equal(tree.selected, 'notes:guide/intro.md')
  instance.$refs.readerView.scrollTop = 555
  const e = {
    preventDefault() { this.prevented = true },
    target: { closest: () => ({ getAttribute: () => '../overview.md' }) },
  }
  // Link from guide/intro.md to overview.md in the root.
  await instance.followMarkdownLink(e)
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(e.prevented, true)
  assert.equal(instance.currentPath, 'overview.md')
  assert.equal(instance.$refs.readerView.scrollTop, 0)
})
