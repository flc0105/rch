<template>
  <el-dialog
    v-model="visible"
    title="Documents"
    :width="fullscreen ? '100vw' : '1180px'"
    :top="fullscreen ? '0' : '4vh'"
    :class="['documents-dialog', { 'documents-dialog-fullscreen': fullscreen }]"
    :show-close="false"
    append-to-body
    :destroy-on-close="false"
    :close-on-click-modal="false"
    :close-on-press-escape="false"
    @close="onClose"
  >
    <template #header>
      <div class="documents-header">
        <strong>Documents</strong>
        <div class="documents-header-actions">
          <el-tooltip :content="fullscreen ? 'Exit Fullscreen' : 'Fullscreen'" placement="bottom">
            <button type="button" class="documents-header-action" :aria-label="fullscreen ? 'Exit Fullscreen' : 'Fullscreen'" @click="toggleFullscreen">
              <el-icon><FullScreen /></el-icon>
            </button>
          </el-tooltip>
          <button type="button" class="documents-header-action" aria-label="Close" @click="requestClose">
            <el-icon><Close /></el-icon>
          </button>
        </div>
      </div>
    </template>

    <div class="documents-layout">
      <aside class="documents-sidebar">
        <div class="documents-side-actions">
          <el-button size="small" @click="reloadRoots" :loading="loading">Refresh</el-button>
          <el-button size="small" @click="makeItem('file')" :disabled="!selectedRoot">New File</el-button>
          <el-button size="small" @click="makeItem('directory')" :disabled="!selectedRoot">New Folder</el-button>
        </div>
        <div class="documents-tree" v-loading="loading">
          <el-tree
            v-if="roots.length"
            :key="treeVersion"
            ref="treeRef"
            node-key="key"
            lazy
            :load="loadChildren"
            :props="{ label: 'name', isLeaf: 'leaf' }"
            highlight-current
            :expand-on-click-node="false"
            @node-click="selectNode"
          >
            <template #default="{ data }">
              <span class="documents-tree-entry">
                <el-icon v-if="data.type === 'file'"><Document /></el-icon>
                <el-icon v-else><Folder /></el-icon>
                <span :title="data.name">{{ data.name }}</span>
              </span>
            </template>
          </el-tree>
          <el-empty v-else-if="!loading" description="No document roots" :image-size="80" />
        </div>
      </aside>
      <section class="documents-main" v-loading="reading || saving">
        <div v-if="currentPath" class="documents-editor-toolbar">
          <span class="documents-location" :title="currentPath">{{ currentRoot }} / {{ currentPath }}</span>
          <el-tag size="small" :type="currentEditable ? 'info' : 'warning'">{{ currentEncoding }}</el-tag>
          <el-button size="small" v-if="!editing && currentEditable" type="primary" @click="startEdit">Edit</el-button>
          <template v-else-if="editing">
            <div class="documents-live-preview-control">
              <span>Live Preview</span>
              <el-switch v-model="livePreviewEnabled" aria-label="Live Preview" />
            </div>
            <el-button size="small" type="primary" :loading="saving" @click="save">Save</el-button>
            <el-button size="small" :disabled="saving" @click="cancelEdit">Cancel</el-button>
          </template>
          <el-button size="small" :disabled="reading || saving" @click="reloadDocument">Reload</el-button>
        </div>
        <!-- Keep Monaco's host attached across Edit/Cancel and dialog reopen; disposal can freeze the page. -->
        <div v-show="currentPath && editing" class="documents-split" :class="{ 'documents-split-source-only': !livePreviewEnabled }">
          <div ref="editorHost" class="documents-monaco"></div>
          <article v-if="editing && livePreviewEnabled" class="documents-markdown" @click="followMarkdownLink" v-html="renderedMarkdown"></article>
        </div>
        <article v-if="currentPath && !editing" ref="readerView" class="documents-markdown documents-reader" @click="followMarkdownLink" v-html="renderedMarkdown"></article>
        <el-empty v-if="!currentPath" description="Select a Markdown document" />
      </section>
    </div>
  </el-dialog>
</template>

<script>
import { ElMessage, ElMessageBox } from 'element-plus'
import { Close, FullScreen, Document, Folder } from '@element-plus/icons-vue'
import * as monaco from 'monaco-editor/esm/vs/editor/editor.api'
import EditorWorker from 'monaco-editor/esm/vs/editor/editor.worker?worker'
import 'monaco-editor/esm/vs/basic-languages/monaco.contribution'
import 'monaco-editor/esm/vs/editor/contrib/contextmenu/browser/contextmenu'
import 'monaco-editor/esm/vs/editor/contrib/find/browser/findController'
import 'monaco-editor/esm/vs/editor/contrib/folding/browser/folding'
import 'monaco-editor/min/vs/editor/editor.main.css'
import MarkdownIt from 'markdown-it'
import * as documentsApi from '../api/documentsApi.js'

const markdown = new MarkdownIt({ html: false, linkify: false, typographer: false })
// Markdown documents are local files, not a trusted HTML/script source.
markdown.renderer.rules.image = (tokens, idx) => markdown.utils.escapeHtml(tokens[idx].content || '')
markdown.renderer.rules.link_open = (tokens, idx, options, env, self) => {
  tokens[idx].attrSet('rel', 'noopener noreferrer')
  return self.renderToken(tokens, idx, options)
}

// Monaco instances must stay out of Vue's reactive data, as in PreviewDialog.
const documentEditorStore = new WeakMap()
const editorInitFrameStore = new WeakMap()
const editorLayoutFrameStore = new WeakMap()

function getDocumentEditor(vm) { return documentEditorStore.get(vm) || null }
function setDocumentEditor(vm, editor) {
  if (editor) documentEditorStore.set(vm, editor)
  else documentEditorStore.delete(vm)
}

function setupEditorWorker() {
  if (globalThis.MonacoEnvironment) return
  // PreviewDialog configures the language-specific workers separately.
  globalThis.MonacoEnvironment = { getWorker: () => new EditorWorker() }
}

export default {
  name: 'DocumentsDialog',
  components: { Close, FullScreen, Document, Folder },
  data() {
    return {
      visible: false,
      fullscreen: false,
      loading: false,
      reading: false,
      saving: false,
      roots: [],
      treeVersion: 0,
      selectedRoot: '',
      selectedDirectory: '',
      currentRoot: '',
      currentPath: '',
      currentEncoding: '',
      currentEditable: false,
      currentSha256: '',
      originalText: '',
      sourceText: '',
      previewText: '',
      previewTimer: null,
      livePreviewEnabled: true,
      editing: false,
      editorInitSeq: 0,
      documentRequestId: 0,
    }
  },
  computed: {
    dirty() { return this.editing && this.sourceText !== this.originalText },
    renderedMarkdown() {
      // Even if evaluated outside the template, disabled live preview must never render.
      if (this.editing && !this.livePreviewEnabled) return ''
      return markdown.render(this.editing ? this.previewText : this.originalText)
    },
  },
  watch: {
    livePreviewEnabled(enabled) {
      clearTimeout(this.previewTimer)
      this.previewTimer = null
      if (enabled && this.editing) this.previewText = this.sourceText
      if (this.editing) this.scheduleEditorLayout()
    },
  },
  methods: {
    async open() {
      this.visible = true
      await this.reloadRoots()
    },
    async reloadRoots() {
      this.loading = true
      try {
        const result = await documentsApi.listDocumentRoots()
        this.roots = result.items || []
        this.treeVersion++
      } catch (error) { ElMessage.error(error.message || 'Cannot load documents') }
      finally { this.loading = false }
    },
    async loadChildren(node, resolve) {
      if (node.level === 0) {
        resolve(this.roots.map(root => ({ key: `${root.id}:`, root_id: root.id, name: root.label, type: 'root', path: '', leaf: false })))
        return
      }
      try {
        const { root_id, path } = node.data
        const result = await documentsApi.listDocumentTree(root_id, path)
        resolve((result.items || []).map(item => ({
          ...item, root_id, key: `${root_id}:${item.path}`, leaf: item.type === 'file',
        })))
      } catch (error) {
        ElMessage.error(error.message || 'Cannot load directory')
        resolve([])
      }
    },
    async askDiscard() {
      if (!this.dirty) return true
      try {
        await ElMessageBox.confirm('Discard unsaved changes?', 'Unsaved Changes', { type: 'warning', confirmButtonText: 'Discard' })
        return true
      } catch { return false }
    },
    async selectNode(data) {
      if (this.saving || this.reading) return
      if (data.type === 'file' && data.path === this.currentPath && data.root_id === this.currentRoot) return
      if (!(await this.askDiscard())) return
      if (this.editing) this.cancelEdit()
      this.selectedRoot = data.root_id
      this.selectedDirectory = data.type === 'file' ? data.path.split('/').slice(0, -1).join('/') : data.path
      if (data.type !== 'file') return
      await this.openDocument(data.root_id, data.path)
    },
    async openDocument(rootId, path) {
      const requestId = ++this.documentRequestId
      this.reading = true
      try {
        const item = await documentsApi.readDocument(rootId, path)
        if (requestId !== this.documentRequestId || !this.visible) return
        this.suspendEditor()
        this.currentRoot = rootId
        this.currentPath = path
        this.selectedRoot = rootId
        this.selectedDirectory = path.split('/').slice(0, -1).join('/')
        this.currentEncoding = item.encoding
        this.currentEditable = item.editable === true
        this.currentSha256 = item.sha256
        this.originalText = item.content
        this.sourceText = item.content
        this.previewText = item.content
        this.editing = false
        await this.$nextTick()
        if (requestId !== this.documentRequestId || !this.visible) return
        // Never reuse the previous document's reading position.
        if (this.$refs.readerView) this.$refs.readerView.scrollTop = 0
        // Sidebar selection is best-effort: never block the document reader on lazy folders.
        void this.selectDocumentInTree(rootId, path, requestId).catch(() => {})
      } catch (error) {
        if (requestId === this.documentRequestId) ElMessage.error(error.message || 'Cannot open document')
      } finally {
        if (requestId === this.documentRequestId) this.reading = false
      }
    },
    async selectDocumentInTree(rootId, path, requestId) {
      // Element Plus Tree is lazy: an internal Markdown link can target a node
      // whose parents have not been expanded in the sidebar yet.
      const tree = this.$refs.treeRef
      if (!tree) return
      let currentPath = ''
      let node = tree.getNode(`${rootId}:`)
      const parts = path.split('/').filter(Boolean)
      for (const part of parts) {
        if (requestId !== this.documentRequestId || !this.visible || !node) return
        if (!node.loaded || !node.expanded) {
          await new Promise(resolve => node.expand(resolve))
        }
        currentPath = currentPath ? `${currentPath}/${part}` : part
        node = tree.getNode(`${rootId}:${currentPath}`)
      }
      if (requestId === this.documentRequestId && node) tree.setCurrentKey(`${rootId}:${path}`)
    },
    async reloadDocument() {
      if (!this.currentPath || this.saving || this.reading || !(await this.askDiscard())) return
      await this.openDocument(this.currentRoot, this.currentPath)
    },
    startEdit() {
      if (!this.visible || !this.currentPath || !this.currentEditable || this.editing) return
      if (this.livePreviewEnabled) this.previewText = this.sourceText
      this.editing = true
      this.initEditor(this.sourceText)
    },
    initEditor(content) {
      this.cancelPendingEditorFrames()
      const seq = this.editorInitSeq
      this.$nextTick(() => {
        if (seq !== this.editorInitSeq || !this.visible || !this.editing) return
        const frame = window.requestAnimationFrame(() => {
          editorInitFrameStore.delete(this)
          if (seq !== this.editorInitSeq || !this.visible || !this.editing) return
          const host = this.$refs.editorHost
          if (!host || !host.isConnected) return

          const editor = getDocumentEditor(this)
          const dom = editor?.getDomNode?.()
          if (dom?.isConnected && host.contains(dom)) {
            const model = editor.getModel?.()
            if (model) model.setValue(content)
            else editor.setValue(content)
          } else {
            // Mirror PreviewDialog: do not dispose; destruction has caused freezes.
            setDocumentEditor(this, null)
            setupEditorWorker()
            const nextEditor = monaco.editor.create(host, {
              value: content,
              language: 'markdown',
              theme: 'vs',
              automaticLayout: true,
              minimap: { enabled: false },
              fontSize: 13,
              scrollBeyondLastLine: false,
              wordWrap: 'on',
            })
            setDocumentEditor(this, nextEditor)
            nextEditor.onDidChangeModelContent(() => {
              if (!this.visible || !this.editing || getDocumentEditor(this) !== nextEditor) return
              this.sourceText = nextEditor.getValue()
              clearTimeout(this.previewTimer)
              this.previewTimer = null
              if (this.livePreviewEnabled) {
                this.previewTimer = setTimeout(() => {
                  this.previewTimer = null
                  if (this.editing && this.livePreviewEnabled) this.previewText = this.sourceText
                }, 150)
              }
            })
          }
          this.scheduleEditorLayout()
        })
        editorInitFrameStore.set(this, frame)
      })
    },
    scheduleEditorLayout() {
      const previous = editorLayoutFrameStore.get(this)
      if (previous != null) window.cancelAnimationFrame(previous)
      editorLayoutFrameStore.delete(this)
      this.$nextTick(() => {
        if (!this.visible || !this.editing) return
        const frame = window.requestAnimationFrame(() => {
          editorLayoutFrameStore.delete(this)
          if (this.visible && this.editing) getDocumentEditor(this)?.layout()
        })
        editorLayoutFrameStore.set(this, frame)
      })
    },
    cancelPendingEditorFrames() {
      ++this.editorInitSeq
      for (const store of [editorInitFrameStore, editorLayoutFrameStore]) {
        const frame = store.get(this)
        if (frame != null) window.cancelAnimationFrame(frame)
        store.delete(this)
      }
    },
    suspendEditor() {
      this.cancelPendingEditorFrames()
      clearTimeout(this.previewTimer)
      this.previewTimer = null
      // Do not call dispose: PreviewDialog avoids it for the same freeze issue.
      const editor = getDocumentEditor(this)
      if (editor?.blur) {
        try { editor.blur() } catch { /* Ignore an editor that is already detached. */ }
      }
    },
    cancelEdit() {
      this.suspendEditor()
      this.editing = false
      this.sourceText = this.originalText
      this.previewText = this.originalText
    },
    async save() {
      if (!this.currentPath || !this.editing || this.saving) return
      this.saving = true
      try {
        const result = await documentsApi.saveDocument({
          root_id: this.currentRoot,
          path: this.currentPath,
          content: this.sourceText,
          encoding: this.currentEncoding,
          sha256: this.currentSha256,
        })
        this.currentSha256 = result.sha256
        this.originalText = this.sourceText
        this.cancelEdit()
        ElMessage.success('Document saved')
      } catch (error) { ElMessage.error(error.message || 'Save failed') }
      finally { this.saving = false }
    },
    async makeItem(type) {
      if (!this.selectedRoot || this.saving || this.reading || !(await this.askDiscard())) return
      if (this.editing) this.cancelEdit()
      const isFile = type === 'file'
      let answer
      try {
        answer = await ElMessageBox.prompt(isFile ? 'Markdown file name' : 'Folder name', isFile ? 'New File' : 'New Folder', {
          inputPlaceholder: isFile ? 'notes.md' : 'Folder',
          inputValidator: value => !value || value.includes('/') || value.includes('\\') || value === '.' || value === '..' ? 'Enter a valid name' : true,
        })
      } catch { return }
      let name = answer.value.trim()
      if (!name) return
      if (isFile && !name.toLowerCase().endsWith('.md')) name += '.md'
      const path = [this.selectedDirectory, name].filter(Boolean).join('/')
      try {
        if (isFile) {
          await documentsApi.createDocument({ root_id: this.selectedRoot, path })
          this.treeVersion++
          await this.$nextTick()
          await this.openDocument(this.selectedRoot, path)
        } else {
          await documentsApi.createDocumentDirectory({ root_id: this.selectedRoot, path })
          this.treeVersion++
        }
      } catch (error) { ElMessage.error(error.message || 'Cannot create item') }
    },
    async followMarkdownLink(event) {
      if (this.saving || this.reading) return
      const link = event.target.closest('a[href]')
      if (!link) return
      event.preventDefault()
      const raw = link.getAttribute('href') || ''
      if (/^https?:\/\//i.test(raw)) {
        window.open(raw, '_blank', 'noopener,noreferrer')
        return
      }
      if (raw.startsWith('#') || raw.startsWith('/') || /^[a-z][a-z0-9+.-]*:/i.test(raw)) return
      let linkedPath
      try { linkedPath = decodeURIComponent(raw.split('#')[0]) }
      catch { return }
      const normalized = [this.currentPath.split('/').slice(0, -1).join('/'), linkedPath]
        .filter(Boolean).join('/')
      const components = []
      for (const component of normalized.split('/')) {
        if (component === '..') components.pop()
        else if (component && component !== '.') components.push(component)
      }
      const path = components.join('/')
      if (!path.toLowerCase().endsWith('.md') || !(await this.askDiscard())) return
      await this.openDocument(this.currentRoot, path)
    },
    toggleFullscreen() { this.fullscreen = !this.fullscreen; this.scheduleEditorLayout() },
    async requestClose() {
      if (this.saving || this.reading) return
      if (await this.askDiscard()) this.visible = false
    },
    onClose() {
      this.documentRequestId++
      this.reading = false
      this.suspendEditor()
      this.editing = false
      this.fullscreen = false
      this.currentPath = ''
      this.currentRoot = ''
      this.selectedRoot = ''
      this.selectedDirectory = ''
      this.originalText = ''
      this.sourceText = ''
      this.previewText = ''
      this.currentSha256 = ''
      this.currentEncoding = ''
      this.currentEditable = false
    },
  },
  beforeUnmount() {
    this.suspendEditor()
    setDocumentEditor(this, null)
  },
}
</script>

<style>
.documents-dialog .el-dialog__body { padding-top: 10px; }
.documents-header { display: flex; align-items: center; justify-content: space-between; }
.documents-header-actions { display: flex; gap: 6px; }
.documents-header-action { border: none; background: transparent; cursor: pointer; color: var(--el-text-color-regular); font-size: 16px; width: 28px; height: 28px; }
.documents-layout { display: grid; grid-template-columns: 260px minmax(0, 1fr); gap: 12px; height: min(74vh, 800px); min-height: 400px; }
.documents-sidebar { display: flex; flex-direction: column; min-height: 0; border: 1px solid var(--el-border-color); border-radius: 5px; }
.documents-side-actions { padding: 10px; display: flex; flex-wrap: wrap; gap: 5px; border-bottom: 1px solid var(--el-border-color); }
.documents-side-actions .el-button { margin-left: 0; }
.documents-tree { padding: 9px; flex: 1; overflow: auto; min-height: 0; }
.documents-tree-entry { display: inline-flex; align-items: center; gap: 6px; font-size: 13px; }
.documents-main { display: flex; flex-direction: column; min-width: 0; min-height: 0; border: 1px solid var(--el-border-color); border-radius: 5px; }
.documents-editor-toolbar { padding: 10px; display: flex; align-items: center; gap: 8px; border-bottom: 1px solid var(--el-border-color); }
.documents-editor-toolbar .el-button { margin-left: 0; }
.documents-live-preview-control { display: inline-flex; align-items: center; gap: 7px; white-space: nowrap; font-size: 12px; }
.documents-location { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 13px; }
.documents-split { display: grid; grid-template-columns: 1fr 1fr; min-height: 0; flex: 1; }
.documents-split.documents-split-source-only { grid-template-columns: minmax(0, 1fr); grid-template-rows: minmax(0, 1fr); }
.documents-split.documents-split-source-only .documents-monaco { border-right: 0; border-bottom: 0; }
.documents-monaco { height: 100%; min-width: 0; min-height: 0; border-right: 1px solid var(--el-border-color); }
.documents-markdown { padding: 20px 25px; overflow: auto; min-height: 0; overflow-wrap: anywhere; line-height: 1.65; font-size: 14px; }
.documents-reader { flex: 1; }
.documents-markdown h1, .documents-markdown h2, .documents-markdown h3 { margin: 0.9em 0 0.45em; font-weight: 600; }
.documents-markdown h1 { font-size: 1.8em; }
.documents-markdown h2 { font-size: 1.4em; }
.documents-markdown h3 { font-size: 1.15em; }
.documents-markdown p { margin: 0.5em 0; }
.documents-markdown pre { padding: 12px; background: var(--el-fill-color-light); border-radius: 5px; overflow: auto; }
.documents-markdown code { font-family: Menlo, Consolas, monospace; font-size: 0.92em; }
.documents-markdown blockquote { border-left: 3px solid var(--el-border-color); padding-left: 12px; color: var(--el-text-color-secondary); }
.documents-markdown table { border-collapse: collapse; }
.documents-markdown td, .documents-markdown th { border: 1px solid var(--el-border-color); padding: 5px 10px; }
.documents-dialog.documents-dialog-fullscreen.el-dialog { width: 100vw !important; height: 100dvh !important; margin: 0 !important; display: flex; flex-direction: column; border-radius: 0; }
.documents-dialog.documents-dialog-fullscreen .el-dialog__body { flex: 1; min-height: 0; display: flex; flex-direction: column; }
.documents-dialog.documents-dialog-fullscreen .documents-layout { flex: 1; min-height: 0; height: 100%; }
@media(max-width: 740px) { .documents-layout { grid-template-columns: 185px minmax(0, 1fr); } .documents-split { grid-template-columns: 1fr; grid-template-rows: 1fr 1fr; } .documents-monaco { border-right: 0; border-bottom: 1px solid var(--el-border-color); } }
</style>
