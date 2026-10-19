<template>
  <el-dialog
      v-model="previewDialogVisible"
      :title="previewTitle || 'File Preview'"
      :width="previewDialogWidth"
      :top="previewDialogTop"
      :class="previewDialogClass"
      :show-close="false"
      @close="handlePreviewDialogClose"
  >
    <template #header>
      <div class="preview-dialog-header">
        <span class="preview-dialog-title">{{ previewTitle || 'File Preview' }}</span>
        <div class="preview-header-actions">
          <el-tooltip
              v-if="previewType === 'text'"
              :content="previewFullscreen ? 'Exit Fullscreen' : 'Fullscreen'"
              placement="bottom"
          >
            <button
                type="button"
                class="preview-header-action"
                :aria-label="previewFullscreen ? 'Exit Fullscreen' : 'Fullscreen'"
                @click="togglePreviewFullscreen"
            >
              <el-icon><FullScreen /></el-icon>
            </button>
          </el-tooltip>
          <button
              type="button"
              class="preview-header-action"
              aria-label="Close"
              title="Close"
              @click="previewDialogVisible = false"
          >
            <el-icon><Close /></el-icon>
          </button>
        </div>
      </div>
    </template>
    <div
        v-loading="previewLoading"
        class="preview-wrap"
    >
      <div
          v-if="previewType === 'image' || previewType === 'text'"
          class="preview-toolbar"
      >
        <div class="preview-toolbar-left">
          <template v-if="previewType === 'text'">
            <!--            <el-button-->
            <!--              size="small"-->
            <!--              @click="copyPreviewText"-->
            <!--            >-->
            <!--              Copy-->
            <!--            </el-button>-->

            <el-button
                size="small"
                @click="copyPreviewText"
            >
              Copy
            </el-button>


            <el-button
                v-if="!previewEditMode && !previewTruncated && previewEditable"
                size="small"
                type="primary"
                @click="enterEditMode"
            >
              Edit
            </el-button>


            <template v-else-if="previewEditMode">
              <el-button
                  size="small"
                  type="primary"
                  :loading="previewSaving"
                  @click="saveEditedContent"
              >
                Save
              </el-button>

              <el-dropdown trigger="click" @command="handlePreviewMoreCommand">
                <el-button size="small">More</el-button>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item command="paste">Paste</el-dropdown-item>
                    <el-dropdown-item command="clear">Clear</el-dropdown-item>
                    <el-dropdown-item
                        command="reload"
                        :disabled="previewSaving || previewReloading"
                    >
                      Reload
                    </el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>


              <el-button
                  size="small"
                  @click="cancelEditMode"
              >
                Cancel
              </el-button>


            </template>
          </template>

          <template v-if="previewType === 'image' && previewUrl">
            <el-button
                v-if="previewImageInfo"
                size="small"
                @click="openPreviewImageInfoDialog"
            >
              Image Info
            </el-button>

            <el-button
                size="small"
                @click="openPreviewOriginal"
            >
              Open Original
            </el-button>
          </template>
        </div>

        <div class="preview-toolbar-right">
          <template v-if="previewType === 'text'">
            <div class="preview-info-tags">
              <el-tag
                  size="small"
                  type="primary"
              >
                {{ previewSourceLabel }}
              </el-tag>

              <el-tag
                  size="small"
                  type="info"
              >
                {{ previewFileSize }}
              </el-tag>

              <el-tag
                  size="small"
                  :type="previewFileCodec === 'unknown' ? 'warning' : 'info'"
              >
                {{ previewFileEncoding }}
              </el-tag>

              <el-tag
                  size="small"
                  type="info"
              >
                {{ previewDetectedLanguage }}
              </el-tag>

              <el-tag
                  v-if="previewTruncated"
                  size="small"
                  type="danger"
              >
                Truncated
              </el-tag>
            </div>
          </template>
        </div>
      </div>

      <template v-if="previewType === 'image' && previewUrl">
        <div class="image-preview-box">
          <img
              :src="previewUrl"
              alt="preview"
              class="preview-image"
          >
        </div>
      </template>

      <template v-else-if="previewType === 'text'">
        <!-- Monaco Editor 容器：这个 id 保留，方便调试定位 -->
        <div
            id="monaco-editor-container"
            ref="monacoEditorContainerRef"
            class="monaco-editor-container"
        />
      </template>

      <template v-else-if="previewType === 'unsupported'">
        <div class="empty-state">
          This file type is not supported for preview.
        </div>
      </template>

      <template v-else>
        <div class="empty-state">
          No preview available.
        </div>
      </template>
    </div>
  </el-dialog>

  <PreviewImageInfoDialog
      v-model:visible="previewImageInfoDialogVisible"
      :info="previewImageInfo"
  />
</template>

<script>
import {ElMessage} from 'element-plus'
import {Close, FullScreen} from '@element-plus/icons-vue'
import * as monaco from 'monaco-editor/esm/vs/editor/editor.api'
import EditorWorker from 'monaco-editor/esm/vs/editor/editor.worker?worker'
import JsonWorker from 'monaco-editor/esm/vs/language/json/json.worker?worker'
import CssWorker from 'monaco-editor/esm/vs/language/css/css.worker?worker'
import HtmlWorker from 'monaco-editor/esm/vs/language/html/html.worker?worker'
import TsWorker from 'monaco-editor/esm/vs/language/typescript/ts.worker?worker'
import 'monaco-editor/esm/vs/basic-languages/monaco.contribution'
import 'monaco-editor/esm/vs/language/json/monaco.contribution'
import 'monaco-editor/esm/vs/language/css/monaco.contribution'
import 'monaco-editor/esm/vs/language/html/monaco.contribution'
import 'monaco-editor/esm/vs/language/typescript/monaco.contribution'

// Monaco CDN 版 editor.main 默认包含这些 editor contribution。
// npm ESM 拆包后要显式引入，否则右键菜单等编辑器功能可能缺失。
import 'monaco-editor/esm/vs/editor/contrib/contextmenu/browser/contextmenu'
import 'monaco-editor/esm/vs/editor/contrib/clipboard/browser/clipboard'
import 'monaco-editor/esm/vs/editor/contrib/find/browser/findController'
import 'monaco-editor/esm/vs/editor/contrib/folding/browser/folding'
import 'monaco-editor/esm/vs/editor/contrib/wordHighlighter/browser/wordHighlighter'
import 'monaco-editor/esm/vs/editor/contrib/bracketMatching/browser/bracketMatching'
import 'monaco-editor/esm/vs/editor/contrib/comment/browser/comment'
import 'monaco-editor/esm/vs/editor/contrib/format/browser/formatActions'
import 'monaco-editor/esm/vs/editor/contrib/hover/browser/hover'
import 'monaco-editor/esm/vs/editor/contrib/links/browser/links'
// import 'monaco-editor/esm/vs/editor/contrib/suggest/browser/suggestController'
import 'monaco-editor/min/vs/editor/editor.main.css'
import {formatBytes} from '../utils/formatters.js'
import * as externalToolsApi from '../api/externalToolsApi.js'
import PreviewImageInfoDialog from './PreviewImageInfoDialog.vue'

const monacoEditorStore = new WeakMap()
const monacoInitFrameStore = new WeakMap()
const monacoLayoutFrameStore = new WeakMap()

function getPreviewMonacoEditor(vm) {
  return monacoEditorStore.get(vm) || null
}

function setPreviewMonacoEditor(vm, editor) {
  if (editor) {
    monacoEditorStore.set(vm, editor)
  } else {
    monacoEditorStore.delete(vm)
  }
}

function getStoredFrame(store, vm) {
  return store.get(vm) || null
}

function setStoredFrame(store, vm, frame) {
  if (frame) {
    store.set(vm, frame)
  } else {
    store.delete(vm)
  }
}

function setupMonacoWorkers() {
  if (typeof globalThis === 'undefined') return
  if (globalThis.MonacoEnvironment && globalThis.MonacoEnvironment.__ratConfigured) return

  globalThis.MonacoEnvironment = {
    __ratConfigured: true,

    getWorker(_workerId, label) {
      if (label === 'json') {
        return new JsonWorker()
      }

      if (label === 'css' || label === 'scss' || label === 'less') {
        return new CssWorker()
      }

      if (label === 'html' || label === 'handlebars' || label === 'razor') {
        return new HtmlWorker()
      }

      if (label === 'typescript' || label === 'javascript') {
        return new TsWorker()
      }

      return new EditorWorker()
    },
  }
}

setupMonacoWorkers()

export default {
  name: 'PreviewDialog',

  components: {
    PreviewImageInfoDialog,
    Close,
    FullScreen,
  },

  props: {
    selectedId: {
      type: [String, Number],
      default: '',
    },

    remoteFilesDialogVisible: {
      type: Boolean,
      default: false,
    },
  },

  emits: [
    'remote-directory-maybe-changed',
    'artifacts-maybe-changed',
    'scripts-maybe-changed',
    'background-job-modules-maybe-changed',
    'external-tools-maybe-changed',
  ],

  data() {
    return {
      previewReloading: false,
      previewDialogVisible: false,
      previewFullscreen: false,
      previewLoading: false,
      previewType: '',
      previewTitle: '',
      previewUrl: '',
      previewText: '',
      previewEditMode: false,  // 是否处于编辑模式
      previewSaving: false,    // 保存中状态
      previewFilePath: '',     // 当前编辑的文件路径
      previewRemoteClientId: '',  // Remote Files 预览固定使用打开时的目标设备
      previewOriginalContent: '',  // 原始内容副本（用于取消编辑时恢复）
      previewTruncated: false,     // 是否被截断
      previewEditable: true,       // 文件解码是否无损可编辑
      previewFileCodec: 'utf-8',   // 服务端确认的写回编码（与显示标签分离）
      previewFileSize: '',         // 文件大小显示
      previewFileEncoding: 'UTF-8', // 文件编码
      previewSource: '',  // 'remote_file' 或 'artifact'
      previewArtifactInfo: null,
      previewImageInfo: null,
      previewImageInfoDialogVisible: false,
      previewDetectedLanguage: 'Plain Text', // Monaco 识别语言
      previewLoadSeq: 0,
      monacoInitSeq: 0,
    }
  },

  computed: {
    previewDialogClass() {
      return [
        'fixed-dialog',
        'preview-dialog',
        {'preview-dialog-fullscreen': this.previewFullscreen},
      ]
    },

    previewDialogWidth() {
      return this.previewFullscreen ? '100vw' : '1080px'
    },

    previewDialogTop() {
      return this.previewFullscreen ? '0' : '5vh'
    },

    previewSourceLabel() {
      if (this.previewSource === 'remote_file') {
        return 'Remote File'
      }
      if (this.previewSource === 'artifact') {
        return 'Artifact'
      }
      if (this.previewSource === 'new_shared_file') {
        return 'Artifact'
      }
      if (this.previewSource === 'background_job') {
        return 'Background Job'
      }
      if (this.previewSource === 'server_script') {
        return 'Server Script'
      }
      if (this.previewSource === 'external_tool_meta') {
        return 'External Tool Meta'
      }
      return 'Unknown'
    },
  },

  watch: {
    previewDialogVisible(val) {
      if (!val) {
        this.previewFullscreen = false
        this.cancelPendingMonacoFrames()
        this.blurMonacoEditor()
        this.resetPreviewState()
      }
    },
  },

  beforeUnmount() {
    this.cancelPendingMonacoFrames()
    this.blurMonacoEditor()
    setPreviewMonacoEditor(this, null)
  },

  methods: {
    handlePreviewMoreCommand(command) {
      if (command === 'paste') this.pastePreviewText()
      else if (command === 'clear') this.clearPreviewContent()
      else if (command === 'reload') this.reloadPreviewContent()
    },

    handlePreviewDialogClose() {
      this.previewLoadSeq += 1
      this.monacoInitSeq += 1
      this.previewLoading = false
      this.previewFullscreen = false
      this.previewImageInfoDialogVisible = false
      this.cancelPendingMonacoFrames()
      this.blurMonacoEditor()
      this.previewReloading = false
    },

    initMonacoEditor(content, readOnly = true) {
      this.cancelPendingMonacoFrames()

      const initSeq = this.monacoInitSeq + 1
      this.monacoInitSeq = initSeq

      const lang = this.getLanguageFromFilename(this.previewTitle)
      this.previewDetectedLanguage = this.getLanguageDisplayName(lang)

      this.$nextTick(() => {
        if (!this.previewDialogVisible || this.previewType !== 'text') return
        if (this.monacoInitSeq !== initSeq) return

        const frame = window.requestAnimationFrame(() => {
          setStoredFrame(monacoInitFrameStore, this, null)

          if (!this.previewDialogVisible || this.previewType !== 'text') return
          if (this.monacoInitSeq !== initSeq) return

          const container = this.$refs.monacoEditorContainerRef
          if (!container || !container.isConnected) return

          const editor = getPreviewMonacoEditor(this)
          const editorDom = editor && typeof editor.getDomNode === 'function'
              ? editor.getDomNode()
              : null

          const canReuseEditor = !!(
              editor &&
              editorDom &&
              editorDom.isConnected &&
              container.contains(editorDom)
          )

          if (canReuseEditor) {
            const model = editor.getModel && editor.getModel()

            if (model) {
              model.setValue(content)
              monaco.editor.setModelLanguage(model, lang)
            } else {
              editor.setValue(content)
            }

            // editor.updateOptions({
            //   readOnly,
            //   contextmenu: true,
            // })
            editor.updateOptions({
              readOnly,
              contextmenu: true,
              quickSuggestions: false,
              suggestOnTriggerCharacters: false,
              acceptSuggestionOnEnter: 'off',
              tabCompletion: 'off',
              wordBasedSuggestions: 'off',
              snippetSuggestions: 'none',
              parameterHints: {
                enabled: false,
              },
            })
          } else {
            // 不调用 dispose：避免 Monaco 在当前环境下销毁卡死。
            setPreviewMonacoEditor(this, null)

            const nextEditor = monaco.editor.create(container, {
              value: content,
              language: lang,
              theme: 'vs',
              // readOnly,
              // contextmenu: true,
              // automaticLayout: true,
              // fontSize: 13,
              readOnly,
              contextmenu: true,
              quickSuggestions: false,
              suggestOnTriggerCharacters: false,
              acceptSuggestionOnEnter: 'off',
              tabCompletion: 'off',
              wordBasedSuggestions: 'off',
              snippetSuggestions: 'none',
              parameterHints: {
                enabled: false,
              },
              automaticLayout: true,
              fontSize: 13,


              fontFamily: 'Monaco, Menlo, "Ubuntu Mono", Consolas, monospace',
              lineNumbers: 'on',
              minimap: {enabled: false},
              scrollBeyondLastLine: false,
              wordWrap: 'on',
              renderWhitespace: 'boundary',
              tabSize: 4,
              insertSpaces: true,
            })

            setPreviewMonacoEditor(this, nextEditor)
          }

          const layoutFrame = window.requestAnimationFrame(() => {
            setStoredFrame(monacoLayoutFrameStore, this, null)

            const currentEditor = getPreviewMonacoEditor(this)
            if (currentEditor && this.previewDialogVisible && this.previewType === 'text') {
              currentEditor.layout()
            }
          })

          setStoredFrame(monacoLayoutFrameStore, this, layoutFrame)
        })

        setStoredFrame(monacoInitFrameStore, this, frame)
      })
    },

    togglePreviewFullscreen() {
      this.previewFullscreen = !this.previewFullscreen
      this.schedulePreviewEditorLayout()
    },

    schedulePreviewEditorLayout() {
      this.$nextTick(() => {
        window.requestAnimationFrame(() => {
          const editor = getPreviewMonacoEditor(this)
          if (editor && this.previewDialogVisible && this.previewType === 'text') {
            editor.layout()
          }
        })
      })
    },

    cancelPendingMonacoFrames() {
      const initFrame = getStoredFrame(monacoInitFrameStore, this)
      if (initFrame) {
        window.cancelAnimationFrame(initFrame)
        setStoredFrame(monacoInitFrameStore, this, null)
      }

      const layoutFrame = getStoredFrame(monacoLayoutFrameStore, this)
      if (layoutFrame) {
        window.cancelAnimationFrame(layoutFrame)
        setStoredFrame(monacoLayoutFrameStore, this, null)
      }
    },

    blurMonacoEditor() {
      const editor = getPreviewMonacoEditor(this)

      if (editor && typeof editor.blur === 'function') {
        try {
          editor.blur()
        } catch (_error) {
        }
      }
    },

    // 根据文件名获取语言
    getLanguageFromFilename(filename) {
      if (!filename) return 'plaintext'

      const ext = filename.split('.').pop().toLowerCase()
      const langMap = {
        py: 'python',
        js: 'javascript',
        ts: 'typescript',
        html: 'html',
        css: 'css',
        json: 'json',
        xml: 'xml',
        yaml: 'yaml',
        yml: 'yaml',
        md: 'markdown',
        sh: 'shell',
        bash: 'shell',
        sql: 'sql',
        java: 'java',
        c: 'c',
        cpp: 'cpp',
        h: 'cpp',
        go: 'go',
        rs: 'rust',
        php: 'php',
        rb: 'ruby',
        pl: 'perl',
        lua: 'lua',
        ini: 'ini',
        conf: 'ini',
        log: 'log',
        txt: 'plaintext',
        ps1: 'powershell',
      }

      return langMap[ext] || 'plaintext'
    },

    getLanguageDisplayName(language) {
      const langNameMap = {
        plaintext: 'Plain Text',
        python: 'Python',
        javascript: 'JavaScript',
        typescript: 'TypeScript',
        html: 'HTML',
        css: 'CSS',
        json: 'JSON',
        xml: 'XML',
        yaml: 'YAML',
        markdown: 'Markdown',
        shell: 'Shell',
        sql: 'SQL',
        java: 'Java',
        c: 'C',
        cpp: 'C++',
        go: 'Go',
        rust: 'Rust',
        php: 'PHP',
        ruby: 'Ruby',
        perl: 'Perl',
        lua: 'Lua',
        ini: 'INI',
        log: 'Log',
        powershell: 'Powershell',
      }

      const key = String(language || '').trim().toLowerCase()
      return langNameMap[key] || key || 'Plain Text'
    },

    // 获取编辑器内容
    getMonacoEditorContent() {
      const editor = getPreviewMonacoEditor(this)
      if (editor) {
        return editor.getValue()
      }
      return this.previewText
    },

    // 设置编辑器只读状态
    setMonacoEditorReadOnly(readOnly) {
      const editor = getPreviewMonacoEditor(this)
      if (editor) {
        editor.updateOptions({readOnly})
      }
    },

    enterEditMode() {
      if (this.previewTruncated || !this.previewEditable) return
      this.previewOriginalContent = this.previewText
      this.previewEditMode = true
      // 切换编辑器为可编辑模式
      this.setMonacoEditorReadOnly(false)
    },

    cancelEditMode() {
      this.previewEditMode = false

      // 恢复原始内容
      const editor = getPreviewMonacoEditor(this)
      if (editor) {
        editor.setValue(this.previewOriginalContent)
      }

      this.previewText = this.previewOriginalContent
      this.previewOriginalContent = ''

      // 切换编辑器为只读模式
      this.setMonacoEditorReadOnly(true)
    },

    clearPreviewContent() {
      if (this.previewType !== 'text') {
        ElMessage.warning('Only text content can be cleared')
        return
      }

      if (!this.previewEditMode) {
        ElMessage.warning('Please enter edit mode first')
        return
      }

      const editor = getPreviewMonacoEditor(this)
      if (editor) {
        editor.setValue('')
      }

      this.previewText = ''
    },

    async previewRemoteEntry(row) {
      if (!row || !row.path || row.is_dir || row.is_parent_entry) {
        ElMessage.warning('Please select a file')
        return
      }

      const clientId = String(row.client_id || this.selectedId || '').trim()
      if (!clientId) {
        ElMessage.warning('Please select a device')
        return
      }

      // 记录文件路径和对应设备，避免全局选择变化后写到其他 Client。
      this.previewFilePath = row.path
      this.previewRemoteClientId = clientId
      this.previewSource = 'remote_file'  // 标记来源

      await this.loadPreviewPayload(
          () => fetch(`/api/connections/${encodeURIComponent(clientId)}/remote-files/preview`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({path: row.path}),
          }),
          row.name || 'File Preview',
          clientId,
      )

      // 重置编辑模式
      this.previewEditMode = false
    },

    async previewArtifact(row) {
      if (!row || !row.artifact_id) {
        ElMessage.warning('Invalid artifact')
        return
      }

      this.previewSource = 'artifact'  // 标记来源
      this.previewFilePath = row.artifact_id  // 存储 artifact_id 而不是路径
      this.previewArtifactInfo = row  // 保存 artifact 信息，用于后续刷新

      await this.loadPreviewPayload(
          () => fetch(`/api/artifacts/${encodeURIComponent(row.artifact_id)}/preview`),
          row.original_name || row.stored_name || 'Artifact Preview',
      )

      this.previewEditMode = false
    },

    async previewBackgroundJobFile(file) {
      if (!file) {
        ElMessage.warning('No preview available')
        return
      }

      if (file.artifact_id) {
        await this.loadPreviewPayload(
            () => fetch(`/api/artifacts/${encodeURIComponent(file.artifact_id)}/preview`),
            file.original_name || file.stored_name || 'Job File Preview',
        )
        return
      }

      if (!file.preview_url) {
        ElMessage.warning('No preview available')
        return
      }

      await this.loadPreviewPayload(
          () => fetch(file.preview_url),
          file.original_name || file.stored_name || 'Job File Preview',
      )
    },

    async saveEditedContent() {
      if ((this.previewSource === 'remote_file' || this.previewSource === 'artifact') &&
          (this.previewTruncated || !this.previewEditable)) {
        ElMessage.warning('Editing is disabled for this file')
        return
      }
      const currentContent = this.getMonacoEditorContent()

      // 根据来源选择不同的保存方式
      if (this.previewSource === 'remote_file') {
        await this.saveToRemoteFile(currentContent)
      } else if (this.previewSource === 'artifact') {
        await this.saveToArtifact(currentContent)
      } else if (this.previewSource === 'new_shared_file') {
        await this.saveToNewSharedFile(currentContent)
      } else if (this.previewSource === 'background_job') {
        await this.saveToBackgroundJob(currentContent)
      } else if (this.previewSource === 'server_script') {
        await this.saveToServerScript(currentContent)
      } else if (this.previewSource === 'external_tool_meta') {
        await this.saveToExternalToolMeta(currentContent)
      } else {
        ElMessage.warning('Unknown preview source')
      }
    },

    async saveToExternalToolMeta(content) {
      if (!this.previewFilePath) {
        ElMessage.warning('Invalid external tool id')
        return
      }

      this.previewSaving = true

      try {
        const data = await externalToolsApi.saveExternalToolMetaContent(this.previewFilePath, content)

        ElMessage.success('External tool meta saved successfully')

        this.previewOriginalContent = content
        this.previewText = content
        this.previewEditMode = false
        this.setMonacoEditorReadOnly(true)

        if (data && data.size) {
          this.previewFileSize = formatBytes(data.size)
        }

        this.$emit('external-tools-maybe-changed')
      } catch (e) {
        ElMessage.error(e.message || 'Failed to save external tool meta')
      } finally {
        this.previewSaving = false
      }
    },

    async saveToServerScript(content) {
      if (!this.previewFilePath) {
        ElMessage.warning('Invalid script name')
        return
      }

      this.previewSaving = true

      try {
        const res = await fetch('/api/scripts/save', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            name: this.previewFilePath,
            content,
          }),
        })

        const json = await res.json()
        if (!res.ok || json.code !== 0) {
          throw new Error(json.message || 'Failed to save script')
        }

        ElMessage.success('Script saved successfully')

        this.previewOriginalContent = content
        this.previewText = content
        this.previewEditMode = false
        this.setMonacoEditorReadOnly(true)

        this.$emit('scripts-maybe-changed')
      } catch (e) {
        ElMessage.error(e.message || 'Failed to save script')
      } finally {
        this.previewSaving = false
      }
    },

    async saveToBackgroundJob(content) {
      if (!this.previewFilePath) {
        ElMessage.warning('Invalid job name')
        return
      }

      this.previewSaving = true

      try {
        const res = await fetch('/api/jobs/save', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            name: this.previewFilePath,
            content,
          }),
        })

        const json = await res.json()
        if (!res.ok || json.code !== 0) {
          throw new Error(json.message || 'Failed to save job')
        }

        ElMessage.success('Job saved successfully')

        this.previewOriginalContent = content
        this.previewText = content
        this.previewEditMode = false
        this.setMonacoEditorReadOnly(true)

        // 刷新 Jobs 列表
        this.$emit('background-job-modules-maybe-changed')
      } catch (e) {
        ElMessage.error(e.message || 'Failed to save job')
      } finally {
        this.previewSaving = false
      }
    },

    async saveToRemoteFile(content) {
      const clientId = String(this.previewRemoteClientId || '').trim()
      if (!clientId || !this.previewFilePath) {
        ElMessage.warning('Invalid file path')
        return
      }

      this.previewSaving = true

      try {
        const res = await fetch(`/api/connections/${encodeURIComponent(clientId)}/remote-files/save`, {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            path: this.previewFilePath,
            content,
            encoding: this.previewFileCodec,
          }),
        })

        const json = await res.json()
        if (!res.ok || json.code !== 0) {
          throw new Error(json.message || 'Failed to save file')
        }

        ElMessage.success('File saved successfully')

        this.previewOriginalContent = content
        this.previewText = content
        this.previewEditMode = false
        this.setMonacoEditorReadOnly(true)

        if (this.remoteFilesDialogVisible) {
          this.$emit('remote-directory-maybe-changed')
        }
      } catch (e) {
        ElMessage.error(e.message || 'Failed to save file')
      } finally {
        this.previewSaving = false
      }
    },

    async saveToNewSharedFile(content) {
      const filename = this.normalizeSharedArtifactFilename(this.previewFilePath)
      if (!filename) {
        ElMessage.warning('Invalid file name')
        return
      }

      this.previewSaving = true

      try {
        const formData = new FormData()
        const blob = new Blob([content == null ? '' : String(content)], {
          type: 'text/plain;charset=utf-8',
        })

        // 复用现有 upload artifact 逻辑，不新建/销毁 Monaco 组件。
        if (typeof File === 'function') {
          formData.append('file', new File([blob], filename, {type: blob.type}))
        } else {
          formData.append('file', blob, filename)
        }
        formData.append('artifact_type', 'shared_files')
        formData.append('extra', JSON.stringify({
          source: 'shared_file_editor',
          saved_from: 'artifact_dialog_create_file',
          saved_at: new Date().toISOString(),
        }))

        const res = await fetch('/api/files/upload', {
          method: 'POST',
          body: formData,
        })

        const json = await res.json()
        if (!res.ok || json.code !== 0) {
          throw new Error(json.message || 'Failed to create artifact')
        }

        const artifact = json.data || {}
        ElMessage.success('Artifact created successfully')

        this.previewOriginalContent = content
        this.previewText = content
        this.previewEditMode = false
        this.setMonacoEditorReadOnly(true)
        this.previewFileSize = formatBytes(artifact.size || String(content || '').length)

        if (artifact.artifact_id) {
          this.previewSource = 'artifact'
          this.previewFilePath = artifact.artifact_id
          this.previewArtifactInfo = artifact
          this.previewTitle = artifact.original_name || artifact.stored_name || filename
        }

        this.$emit('artifacts-maybe-changed')
      } catch (e) {
        ElMessage.error(e.message || 'Failed to create artifact')
      } finally {
        this.previewSaving = false
      }
    },

    async saveToArtifact(content) {
      if (!this.previewFilePath) {
        ElMessage.warning('Invalid artifact')
        return
      }

      this.previewSaving = true

      try {
        const res = await fetch(`/api/artifacts/${encodeURIComponent(this.previewFilePath)}/content`, {
          method: 'PUT',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            content,
            encoding: this.previewFileCodec,
          }),
        })

        const json = await res.json()
        if (!res.ok || json.code !== 0) {
          throw new Error(json.message || 'Failed to save artifact')
        }

        ElMessage.success('Artifact saved successfully')

        // 更新本地内容
        this.previewOriginalContent = content
        this.previewText = content
        this.previewEditMode = false
        this.setMonacoEditorReadOnly(true)

        // 更新文件大小显示
        if (json.data && json.data.size) {
          this.previewFileSize = formatBytes(json.data.size)
        }

        // 刷新 Artifact 列表
        this.$emit('artifacts-maybe-changed')

        // 触发 artifact_created 事件，通知其他组件
        if (this.previewArtifactInfo) {
          // 更新本地 artifact 信息
          this.previewArtifactInfo.size = json.data?.size || this.previewArtifactInfo.size
        }
      } catch (e) {
        ElMessage.error(e.message || 'Failed to save artifact')
      } finally {
        this.previewSaving = false
      }
    },

    async loadPreviewPayload(fetcher, fallbackTitle = 'File Preview', remoteClientId = '') {
      this.previewDialogVisible = true
      this.previewLoading = true
      this.resetPreviewState()
      this.previewRemoteClientId = remoteClientId
      this.previewEditMode = false
      this.previewSaving = false
      this.previewOriginalContent = ''
      this.previewImageInfo = null
      this.previewImageInfoDialogVisible = false

      try {
        const res = await fetcher()
        const json = await res.json()

        if (!res.ok || json.code !== 0) {
          throw new Error(json.message || 'Preview failed')
        }

        const data = json.data || {}
        this.previewType = data.type || 'unsupported'
        this.previewTitle = data.name || fallbackTitle
        this.previewImageInfo = data.image_info || null

        if (this.previewType === 'image') {
          this.previewUrl = data.url || ''
        } else if (this.previewType === 'text') {
          this.previewText = data.content || ''
          this.previewTruncated = data.truncated || false
          this.previewEditable = data.editable === true && !this.previewTruncated
          this.previewFileCodec = data.encoding || 'unknown'
          this.previewOriginalContent = this.previewText
          this.previewFileSize = formatBytes(data.size || this.previewText.length)
          this.previewFileEncoding = this.getEncodingDisplayName(this.previewFileCodec)
          this.previewDetectedLanguage = this.getLanguageDisplayName(this.getLanguageFromFilename(this.previewTitle))

          // 等待 DOM 渲染完成后初始化编辑器
          this.$nextTick(() => {
            this.initMonacoEditor(this.previewText, true)
          })
        }
      } catch (e) {
        this.previewDialogVisible = false
        ElMessage.error(e.message || 'Preview failed')
      } finally {
        this.previewLoading = false
      }
    },

    getEncodingDisplayName(codec) {
      const names = {
        'utf-8': 'UTF-8',
        'utf-8-sig': 'UTF-8 with BOM',
        'utf-16-le': 'UTF-16 LE with BOM',
        'utf-16-be': 'UTF-16 BE with BOM',
        'unknown': 'Unknown encoding',
      }
      return names[codec] || 'Unknown encoding'
    },


    async copyPreviewText() {
      const content = this.getMonacoEditorContent()
      if (!content) {
        ElMessage.warning('No content to copy')
        return
      }

      try {
        if (
            window.isSecureContext &&
            navigator.clipboard &&
            typeof navigator.clipboard.writeText === 'function'
        ) {
          await navigator.clipboard.writeText(content)
          ElMessage.success('Content copied')
          return
        }

        this.copyTextFallback(content)
        ElMessage.success('Content copied')
      } catch (e) {
        try {
          this.copyTextFallback(content)
          ElMessage.success('Content copied')
        } catch (fallbackError) {
          ElMessage.error('Failed to copy content')
        }
      }
    },

    copyTextFallback(text) {
      const textarea = document.createElement('textarea')

      textarea.value = String(text || '')
      textarea.setAttribute('readonly', '')
      textarea.style.position = 'fixed'
      textarea.style.left = '-9999px'
      textarea.style.top = '0'
      textarea.style.opacity = '0'

      document.body.appendChild(textarea)

      textarea.focus()
      textarea.select()
      textarea.setSelectionRange(0, textarea.value.length)

      const ok = document.execCommand('copy')

      document.body.removeChild(textarea)

      if (!ok) {
        throw new Error('Fallback copy failed')
      }
    },

    // async copyPreviewText() {
    //   const content = this.getMonacoEditorContent()
    //   if (!content) {
    //     ElMessage.warning('No content to copy')
    //     return
    //   }
    //
    //   try {
    //     await navigator.clipboard.writeText(content)
    //     ElMessage.success('Content copied')
    //   } catch (e) {
    //     ElMessage.error('Failed to copy content')
    //   }
    // },

    openPreviewImageInfoDialog() {
      if (!this.previewImageInfo) {
        ElMessage.warning('No image info available')
        return
      }
      this.previewImageInfoDialogVisible = true
    },

    openPreviewOriginal() {
      if (!this.previewUrl) {
        ElMessage.warning('No image available')
        return
      }
      window.open(this.previewUrl, '_blank')
    },

    buildServerScriptTemplate(scriptName = 'new_script.py') {
      const normalizedScriptName = String(scriptName || 'new_script.py').trim().replace(/\\/g, '/').replace(/^\/+/, '') || 'new_script.py'
      const classBaseName = normalizedScriptName
          .replace(/\.py$/i, '')
          .split('/')
          .pop()
          .split(/[^a-zA-Z0-9]+/)
          .filter(Boolean)
          .map(part => part.charAt(0).toUpperCase() + part.slice(1))
          .join('') || 'NewScript'

      return `SCRIPT_METADATA = {
    "name": "${normalizedScriptName.replace(/\.py$/i, '')}",
    "display_name": "${classBaseName}",
    "description": "Describe what this script does",
    "platforms": ["common"],
    "category": "General",
    "params": [
        {
            "name": "example",
            "type": "string",
            "required": False,
            "default": "",
            "description": "Example parameter"
        }
    ]
}

value = kwargs.get('example', '')
print(value)

# kwargs will be injected by the script runner.
# Example:
# value = kwargs.get('example', '')
`
    },

    normalizeSharedArtifactFilename(filename, fallbackName = 'new_file.txt') {
      let normalized = String(filename || '').trim().replace(/\\/g, '/').replace(/^\/+/, '')
      if (!normalized) {
        normalized = fallbackName
      }
      return normalized
    },

    openNewSharedFileEditor(filename = 'new_file.txt') {
      const normalizedFilename = this.normalizeSharedArtifactFilename(filename)
      if (!normalizedFilename) {
        ElMessage.warning('Invalid file name')
        return
      }

      const content = ''

      this.previewFullscreen = false
      this.previewSource = 'new_shared_file'
      this.previewFilePath = normalizedFilename
      this.previewTitle = normalizedFilename
      this.previewText = content
      this.previewOriginalContent = content
      this.previewArtifactInfo = null
      this.previewType = 'text'
      this.previewTruncated = false
      this.previewFileSize = formatBytes(content.length)
      this.previewFileEncoding = 'UTF-8'
      this.previewFileCodec = 'utf-8'
      this.previewEditable = true
      this.previewDetectedLanguage = this.getLanguageDisplayName(this.getLanguageFromFilename(this.previewTitle))

      this.previewEditMode = true
      this.previewDialogVisible = true

      this.$nextTick(() => {
        this.initMonacoEditor(content, false)
      })
    },

    normalizeServerJobFilename(scriptName, fallbackName = 'new_job.py') {
      let normalized = String(scriptName || '').trim().replace(/\\/g, '/').replace(/^\/+/, '')
      if (!normalized) {
        normalized = fallbackName
      }
      if (!/\.py$/i.test(normalized)) {
        normalized = `${normalized}.py`
      }
      return normalized
    },

    buildServerJobTemplate(scriptName = 'new_job.py') {
      const normalizedScriptName = this.normalizeServerJobFilename(scriptName)
      const classBaseName = normalizedScriptName
          .replace(/\.py$/i, '')
          .split('/')
          .pop()
          .split(/[^a-zA-Z0-9]+/)
          .filter(Boolean)
          .map(part => part.charAt(0).toUpperCase() + part.slice(1))
          .join('') || 'NewBackgroundJob'

      return `JOB_METADATA = {\n    "name": "${normalizedScriptName.replace(/\.py$/i, '')}",\n    "display_name": "${classBaseName}",\n    "description": "Describe what this job does",\n    "platforms": ["mac"],\n    "params": [\n        {\n            "name": "interval_seconds",\n            "type": "integer",\n            "required": False,\n            "default": 10,\n            "min": 1,\n            "description": "Loop interval in seconds"\n        }\n    ]\n}\n\nimport time\n\nfrom client.jobs.core.job import Job\n\n\nclass ${classBaseName}(Job):\n    def __init__(self):\n        super().__init__()\n        self.interval = 10\n\n    def on_context_bound(self):\n        self.interval = int(self.get_job_param("interval_seconds", 10) or 10)\n\n    def run(self):\n        self.mark_running()\n        self.send_to_server(1, "${normalizedScriptName} started")\n\n        try:\n            while not self.stop_event.is_set():\n                self.send_to_server(1, f"heartbeat: {time.strftime('%Y-%m-%d %H:%M:%S')}")\n                time.sleep(self.interval)\n        finally:\n            self.send_to_server(1, "${normalizedScriptName} stopped")\n            self.mark_stopped()\n\n    def stop(self, notify=True):\n        self.request_stop(notify=notify)\n`
    },

    async openExternalToolMetaEditor(toolId) {
      const normalizedToolId = String(toolId || '').trim()
      if (!normalizedToolId) {
        ElMessage.warning('Invalid external tool id')
        return
      }

      try {
        const data = await externalToolsApi.loadExternalToolMetaContent(normalizedToolId)
        const content = data.content || ''

        this.previewSource = 'external_tool_meta'
        this.previewFilePath = normalizedToolId
        this.previewTitle = data.name || `${normalizedToolId}.json`
        this.previewText = content
        this.previewOriginalContent = content
        this.previewType = 'text'
        this.previewTruncated = false
        this.previewFileSize = formatBytes(data.size || content.length)
        this.previewFileEncoding = 'UTF-8'
        this.previewFileCodec = 'utf-8'
        this.previewEditable = true
        this.previewDetectedLanguage = 'JSON'

        this.previewEditMode = true
        this.previewDialogVisible = true

        this.$nextTick(() => {
          this.initMonacoEditor(content, false)
        })
      } catch (e) {
        ElMessage.error(e.message || 'Failed to load external tool meta')
      }
    },

    openNewRemoteScriptEditor(scriptName = 'new_script.py') {
      if (!this.selectedId) {
        ElMessage.warning('Please select a device')
        return
      }

      let normalizedScriptName = String(scriptName || '').trim().replace(/\\/g, '/').replace(/^\/+/, '')
      if (!normalizedScriptName) {
        normalizedScriptName = 'new_script.py'
      }
      if (!/\.py$/i.test(normalizedScriptName)) {
        normalizedScriptName = `${normalizedScriptName}.py`
      }

      const content = this.buildServerScriptTemplate(normalizedScriptName)

      this.previewSource = 'server_script'
      this.previewFilePath = normalizedScriptName
      this.previewTitle = normalizedScriptName
      this.previewText = content
      this.previewOriginalContent = content
      this.previewType = 'text'
      this.previewTruncated = false
      this.previewFileSize = formatBytes(content.length)
      this.previewFileEncoding = 'UTF-8'
      this.previewFileCodec = 'utf-8'
      this.previewEditable = true
      this.previewEditMode = true
      this.previewDialogVisible = true

      this.$nextTick(() => {
        this.initMonacoEditor(content, false)
      })
    },

    openNewRemoteJobEditor(scriptName = 'new_job.py') {
      if (!this.selectedId) {
        ElMessage.warning('Please select a device')
        return
      }

      const normalizedScriptName = this.normalizeServerJobFilename(scriptName)
      const content = this.buildServerJobTemplate(normalizedScriptName)

      this.previewSource = 'background_job'
      this.previewFilePath = normalizedScriptName
      this.previewTitle = normalizedScriptName
      this.previewText = content
      this.previewOriginalContent = content
      this.previewType = 'text'
      this.previewTruncated = false
      this.previewFileSize = formatBytes(content.length)
      this.previewFileEncoding = 'UTF-8'
      this.previewFileCodec = 'utf-8'
      this.previewEditable = true
      this.previewDetectedLanguage = this.getLanguageDisplayName(this.getLanguageFromFilename(this.previewTitle))

      this.previewEditMode = true
      this.previewDialogVisible = true

      this.$nextTick(() => {
        this.initMonacoEditor(content, false)
      })
    },

    async openRemoteScriptEditorInternal(scriptName) {
      if (!this.selectedId) {
        ElMessage.warning('Please select a device')
        return
      }

      let normalizedScriptName = String(scriptName || '').trim().replace(/\\/g, '/').replace(/^\/+/, '')
      if (!normalizedScriptName) {
        ElMessage.warning('Invalid script name')
        return
      }
      if (!/\.py$/i.test(normalizedScriptName)) {
        normalizedScriptName = `${normalizedScriptName}.py`
      }

      try {
        const res = await fetch(`/api/scripts/download?name=${encodeURIComponent(normalizedScriptName)}`)
        if (!res.ok) {
          throw new Error(`Failed to load script: ${res.statusText}`)
        }
        const content = await res.text()

        this.previewSource = 'server_script'
        this.previewFilePath = normalizedScriptName
        this.previewTitle = normalizedScriptName
        this.previewText = content
        this.previewOriginalContent = content
        this.previewType = 'text'
        this.previewTruncated = false
        this.previewFileSize = formatBytes(content.length)
        this.previewFileEncoding = 'UTF-8'
        this.previewFileCodec = 'utf-8'
        this.previewEditable = true
        this.previewDetectedLanguage = this.getLanguageDisplayName(this.getLanguageFromFilename(this.previewTitle))

        this.previewEditMode = true
        this.previewDialogVisible = true

        this.$nextTick(() => {
          this.initMonacoEditor(content, false)
        })
      } catch (e) {
        ElMessage.error(e.message || 'Failed to load script')
      }
    },

    async openRemoteJobEditor(scriptName) {
      if (!this.selectedId) {
        ElMessage.warning('Please select a device')
        return
      }

      let normalizedScriptName = this.normalizeServerJobFilename(scriptName, 'new_job.py')
      if (!normalizedScriptName) {
        ElMessage.warning('Invalid script name')
        return
      }

      try {
        const res = await fetch(`/api/jobs/download?name=${encodeURIComponent(normalizedScriptName)}`)
        if (!res.ok) {
          throw new Error(`Failed to load job: ${res.statusText}`)
        }
        const content = await res.text()

        this.previewSource = 'background_job'
        this.previewFilePath = normalizedScriptName
        this.previewTitle = normalizedScriptName
        this.previewText = content
        this.previewOriginalContent = content
        this.previewType = 'text'
        this.previewTruncated = false
        this.previewFileSize = formatBytes(content.length)
        this.previewFileEncoding = 'UTF-8'
        this.previewFileCodec = 'utf-8'
        this.previewEditable = true
        this.previewDetectedLanguage = this.getLanguageDisplayName(this.getLanguageFromFilename(this.previewTitle))

        this.previewEditMode = true

        this.previewDialogVisible = true

        this.$nextTick(() => {
          this.initMonacoEditor(content, false)
        })
      } catch (e) {
        ElMessage.error(e.message || 'Failed to load job')
      }
    },

    handleBackgroundJobDeleted(normalizedName) {
      if (
          this.previewDialogVisible &&
          (this.previewSource === 'server_job' || this.previewSource === 'background_job')
      ) {
        const currentPreviewName = this.normalizeServerJobFilename(this.previewFilePath || this.previewTitle || '')

        if (currentPreviewName === normalizedName) {
          this.previewDialogVisible = false
        }
      }
    },


    async pastePreviewText() {
      if (this.previewType !== 'text') {
        ElMessage.warning('Only text content can be pasted')
        return
      }

      if (!this.previewEditMode) {
        ElMessage.warning('Please enter edit mode first')
        return
      }

      let text = ''

      try {
        text = await this.readClipboardTextForPaste()
      } catch (_error) {
        ElMessage.warning('当前浏览器不允许按钮读取剪贴板，请尝试使用 Ctrl+V 粘贴')
        return
      }

      if (!text) {
        ElMessage.warning('Clipboard is empty')
        return
      }

      const editor = getPreviewMonacoEditor(this)

      if (!editor) {
        this.previewText = `${text}${this.previewText || ''}`
        this.initMonacoEditor(this.previewText, false)
        ElMessage.success('Content pasted')
        return
      }

      const model = editor.getModel && editor.getModel()

      if (!model) {
        this.previewText = `${text}${this.previewText || ''}`
        this.initMonacoEditor(this.previewText, false)
        ElMessage.success('Content pasted')
        return
      }

      editor.focus()
      editor.pushUndoStop()

      const selection = editor.getSelection && editor.getSelection()

      const hasValidCursor = !!(
          selection &&
          Number.isInteger(selection.startLineNumber) &&
          Number.isInteger(selection.startColumn) &&
          selection.startLineNumber >= 1 &&
          selection.startColumn >= 1
      )

      if (hasValidCursor) {
        editor.trigger('toolbar-paste', 'type', {text})
      } else {
        const insertRange = new monaco.Range(1, 1, 1, 1)

        editor.executeEdits('toolbar-paste', [
          {
            range: insertRange,
            text,
            forceMoveMarkers: true,
          },
        ])

        const endPosition = model.getPositionAt(String(text).length)
        editor.setSelection(
            new monaco.Selection(
                endPosition.lineNumber,
                endPosition.column,
                endPosition.lineNumber,
                endPosition.column,
            ),
        )
      }

      editor.pushUndoStop()
      this.previewText = editor.getValue()

      ElMessage.success('Content pasted')
    },

    async readClipboardTextForPaste() {
      if (
          window.isSecureContext &&
          navigator.clipboard &&
          typeof navigator.clipboard.readText === 'function'
      ) {
        return await navigator.clipboard.readText()
      }

      if (
          window.clipboardData &&
          typeof window.clipboardData.getData === 'function'
      ) {
        return window.clipboardData.getData('Text') || ''
      }

      return await this.readClipboardTextFallbackForWindows()
    },

    readClipboardTextFallbackForWindows() {
      return new Promise((resolve, reject) => {
        const textarea = document.createElement('textarea')

        textarea.value = ''
        textarea.setAttribute('readonly', '')
        textarea.style.position = 'fixed'
        textarea.style.left = '-9999px'
        textarea.style.top = '0'
        textarea.style.opacity = '0'
        textarea.style.pointerEvents = 'none'

        let finished = false

        const cleanup = () => {
          textarea.removeEventListener('paste', handlePaste)
          if (textarea.parentNode) {
            textarea.parentNode.removeChild(textarea)
          }
        }

        const finish = (value) => {
          if (finished) return
          finished = true
          cleanup()
          resolve(value || '')
        }

        const fail = (error) => {
          if (finished) return
          finished = true
          cleanup()
          reject(error)
        }

        const handlePaste = (event) => {
          const text = event.clipboardData
              ? event.clipboardData.getData('text/plain')
              : textarea.value

          event.preventDefault()
          finish(text)
        }

        document.body.appendChild(textarea)
        textarea.addEventListener('paste', handlePaste)
        textarea.focus()

        try {
          const ok = document.execCommand && document.execCommand('paste')

          window.setTimeout(() => {
            if (finished) return

            const text = textarea.value || ''

            if (ok || text) {
              finish(text)
            } else {
              fail(new Error('Paste blocked'))
            }
          }, 120)
        } catch (error) {
          fail(error)
        }
      })
    },

    // reload
    async reloadPreviewContent() {
      if (this.previewType !== 'text') {
        ElMessage.warning('Only text content can be reloaded')
        return
      }

      if (!this.previewEditMode) {
        ElMessage.warning('Please enter edit mode first')
        return
      }

      if (this.previewReloading || this.previewSaving) return

      this.previewReloading = true

      try {
        const data = await this.fetchLatestPreviewTextPayload()
        const content = data.content || ''

        this.applyReloadedPreviewText({
          content,
          name: data.name,
          size: data.size,
          truncated: data.truncated,
          encoding: data.encoding,
          editable: data.editable,
        })

        ElMessage.success('File reloaded')
      } catch (e) {
        ElMessage.error(e.message || 'Failed to reload file')
      } finally {
        this.previewReloading = false
      }
    },

    async fetchLatestPreviewTextPayload() {
      if (this.previewSource === 'remote_file') {
        const clientId = String(this.previewRemoteClientId || '').trim()
        if (!clientId || !this.previewFilePath) {
          throw new Error('Invalid remote file path')
        }

        const res = await fetch(`/api/connections/${encodeURIComponent(clientId)}/remote-files/preview`, {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({path: this.previewFilePath}),
        })

        return await this.parsePreviewTextResponse(res, 'Failed to reload remote file')
      }

      if (this.previewSource === 'artifact') {
        if (!this.previewFilePath) {
          throw new Error('Invalid artifact')
        }

        const res = await fetch(`/api/artifacts/${encodeURIComponent(this.previewFilePath)}/preview`)

        return await this.parsePreviewTextResponse(res, 'Failed to reload artifact')
      }

      if (this.previewSource === 'server_script') {
        if (!this.previewFilePath) {
          throw new Error('Invalid script name')
        }

        const res = await fetch(`/api/scripts/download?name=${encodeURIComponent(this.previewFilePath)}`)

        if (!res.ok) {
          throw new Error(`Failed to reload script: ${res.statusText}`)
        }

        const content = await res.text()

        return {
          content,
          name: this.previewTitle || this.previewFilePath,
          size: content.length,
          truncated: false,
          encoding: 'utf-8',
          editable: true,
        }
      }

      if (this.previewSource === 'background_job') {
        if (!this.previewFilePath) {
          throw new Error('Invalid job name')
        }

        const res = await fetch(`/api/jobs/download?name=${encodeURIComponent(this.previewFilePath)}`)

        if (!res.ok) {
          throw new Error(`Failed to reload job: ${res.statusText}`)
        }

        const content = await res.text()

        return {
          content,
          name: this.previewTitle || this.previewFilePath,
          size: content.length,
          truncated: false,
          encoding: 'utf-8',
          editable: true,
        }
      }

      if (this.previewSource === 'external_tool_meta') {
        if (!this.previewFilePath) {
          throw new Error('Invalid external tool id')
        }

        const data = await externalToolsApi.loadExternalToolMetaContent(this.previewFilePath)
        const content = data.content || ''

        return {
          content,
          name: data.name || this.previewTitle || `${this.previewFilePath}.json`,
          size: data.size || content.length,
          truncated: false,
          encoding: 'utf-8',
          editable: true,
        }
      }

      if (this.previewSource === 'new_shared_file') {
        throw new Error('This file has not been created yet')
      }

      throw new Error('Unknown preview source')
    },

    async parsePreviewTextResponse(res, fallbackMessage = 'Failed to reload file') {
      const json = await res.json()

      if (!res.ok || json.code !== 0) {
        throw new Error(json.message || fallbackMessage)
      }

      const data = json.data || {}

      if (data.type && data.type !== 'text') {
        throw new Error('Reloaded file is not text content')
      }

      return {
        content: data.content || '',
        name: data.name || this.previewTitle,
        size: data.size,
        truncated: data.truncated || false,
        encoding: data.encoding || 'unknown',
        editable: data.editable === true,
      }
    },

    applyReloadedPreviewText(payload) {
      const content = payload.content || ''

      this.previewText = content
      this.previewOriginalContent = content
      this.previewTruncated = payload.truncated || false
      this.previewEditable = payload.editable === true && !this.previewTruncated
      this.previewFileCodec = payload.encoding || 'unknown'

      if (payload.name) {
        this.previewTitle = payload.name
      }

      this.previewFileSize = formatBytes(payload.size || content.length)
      this.previewFileEncoding = this.getEncodingDisplayName(this.previewFileCodec)
      this.previewDetectedLanguage = this.getLanguageDisplayName(this.getLanguageFromFilename(this.previewTitle))

      const editor = getPreviewMonacoEditor(this)
      const lang = this.getLanguageFromFilename(this.previewTitle)

      if (editor) {
        const model = editor.getModel && editor.getModel()

        if (model) {
          model.setValue(content)
          monaco.editor.setModelLanguage(model, lang)
        } else {
          editor.setValue(content)
        }

        editor.updateOptions({readOnly: !this.previewEditable})

        if (typeof editor.setPosition === 'function') {
          editor.setPosition({lineNumber: 1, column: 1})
        }

        editor.focus()
      } else {
        this.initMonacoEditor(content, !this.previewEditable)
      }

      this.previewEditMode = this.previewEditable
    },


    resetPreviewState() {
      this.previewFullscreen = false
      this.previewType = ''
      this.previewTitle = ''
      this.previewUrl = ''
      this.previewText = ''
      this.previewOriginalContent = ''
      this.previewTruncated = false
      this.previewEditable = true
      this.previewFileCodec = 'utf-8'
      this.previewFileEncoding = 'UTF-8'
      this.previewRemoteClientId = ''
      this.previewEditMode = false
      this.previewSaving = false
      this.previewArtifactInfo = null
      this.previewImageInfo = null
      this.previewImageInfoDialogVisible = false
      this.previewDetectedLanguage = 'Plain Text'
      this.previewReloading = false
    },
  },
}
</script>

<style scoped>
/* ========== 文件预览 ========== */
.preview-dialog-header {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.preview-dialog-title {
  color: var(--el-text-color-primary);
  font-size: var(--el-dialog-title-font-size);
  line-height: var(--el-dialog-font-line-height);
}

.preview-header-actions {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: 10px;
}

.preview-header-action {
  width: 32px;
  height: 32px;
  padding: 0;
  border: 0;
  border-radius: 4px;
  background: transparent;
  color: var(--el-color-info);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  line-height: 1;
  cursor: pointer;
  transition: color 0.15s ease, background-color 0.15s ease;
}

.preview-header-action:hover,
.preview-header-action:focus-visible {
  color: var(--el-color-primary);
  background: var(--el-fill-color-light);
  outline: none;
}

.preview-header-action .el-icon {
  width: 18px;
  height: 18px;
}

.preview-wrap {
  min-height: 280px;
  height: 100%;
}

.image-preview-box {
  display: flex;
  justify-content: center;
  align-items: center;
  max-height: 72vh;
  overflow: auto;
  border-radius: 18px;
  background: #fff;
  padding: 14px;
}

.preview-image {
  max-width: 100%;
  max-height: 70vh;
  object-fit: contain;
  border-radius: 12px;
}

/* 预览对话框 */
.preview-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--line);
  flex-wrap: wrap;
  gap: 12px;
}

.preview-toolbar-left {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}

.preview-toolbar-right {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}

.preview-info-tags {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}

.preview-info-tags :deep(.el-tag) {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 0 8px;
  height: 26px;
  line-height: 26px;
}

.preview-info-tags :deep(.el-tag .el-icon) {
  font-size: 14px;
}

/* Element Plus only spaces adjacent buttons; flex gap also covers dropdowns. */
.preview-toolbar-left :deep(.el-button) {
  margin-left: 0;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 6px 16px;
  height: 26px;
}

.preview-toolbar-left :deep(.el-button .el-icon) {
  font-size: 14px;
}

.edit-text-area {
  min-height: 400px;
}

.monaco-editor-container {
  width: 100%;
  height: 74vh;
  min-height: 520px;
  border: 1px solid var(--line);
  border-radius: 12px;
  overflow: hidden;
}

.monaco-editor-container :deep(.monaco-editor) {
  border-radius: 12px;
}

.monaco-editor-container :deep(.monaco-scrollable-element) {
  border-radius: 12px;
}

@media (max-width: 768px), (max-height: 720px) {
  .preview-toolbar {
    flex-direction: column;
    align-items: flex-start;
    flex: 0 0 auto;
    margin-bottom: 10px;
    padding-bottom: 10px;
  }

  .preview-toolbar-left,
  .preview-toolbar-right {
    width: 100%;
  }

  .preview-info-tags {
    justify-content: flex-start;
  }

  .preview-wrap {
    display: flex;
    flex-direction: column;
    min-height: 0;
    height: 100%;
    overflow: hidden;
  }

  .image-preview-box {
    flex: 1 1 auto;
    min-height: 0;
    max-height: none;
  }

  .monaco-editor-container {
    flex: 1 1 auto;
    height: auto;
    min-height: 0;
  }
}
</style>

<style>
.preview-dialog.preview-dialog-fullscreen.el-dialog {
  width: 100vw !important;
  max-width: 100vw !important;
  height: 100dvh !important;
  max-height: 100dvh !important;
  margin: 0 !important;
  top: 0 !important;
  border-radius: 0 !important;
  display: flex !important;
  flex-direction: column !important;
}

.preview-dialog.preview-dialog-fullscreen .el-dialog__header {
  flex: 0 0 auto !important;
  padding: 12px 14px 8px !important;
}

.preview-dialog.preview-dialog-fullscreen .el-dialog__body {
  flex: 1 1 auto !important;
  min-height: 0 !important;
  overflow: hidden !important;
  padding: 10px 12px 12px !important;
  display: flex !important;
  flex-direction: column !important;
}

.preview-dialog.preview-dialog-fullscreen .preview-wrap {
  display: flex !important;
  flex-direction: column !important;
  min-height: 0 !important;
  height: 100% !important;
  overflow: hidden !important;
}

.preview-dialog.preview-dialog-fullscreen .image-preview-box {
  flex: 1 1 auto !important;
  min-height: 0 !important;
  max-height: none !important;
}

.preview-dialog.preview-dialog-fullscreen .monaco-editor-container {
  flex: 1 1 auto !important;
  height: auto !important;
  min-height: 0 !important;
}

@media (max-width: 768px), (max-height: 720px) {
  .preview-dialog.el-dialog {
    width: 100vw !important;
    max-width: 100vw !important;
    height: 100dvh !important;
    max-height: 100dvh !important;
    margin: 0 !important;
    top: 0 !important;
    border-radius: 0 !important;
    display: flex;
    flex-direction: column;
  }

  .preview-dialog .el-dialog__header {
    flex: 0 0 auto;
    padding: 12px 14px 8px;
  }

  .preview-dialog .el-dialog__body {
    flex: 1 1 auto;
    min-height: 0;
    overflow: hidden;
    padding: 10px 12px 12px;
    display: flex;
    flex-direction: column;
  }
}


.monaco-menu-container,
.monaco-menu-container .monaco-menu {
  background: #ffffff !important;
  color: #111827 !important;
  border: 1px solid rgba(15, 23, 42, 0.12) !important;
  border-radius: 10px !important;
  box-shadow: 0 18px 45px rgba(15, 23, 42, 0.22) !important;
  overflow: hidden !important;
  z-index: 3000 !important;
}

.monaco-menu-container .monaco-action-bar .action-item {
  color: #111827 !important;
}

.monaco-menu-container .monaco-action-bar .action-item .action-label {
  color: #111827 !important;
  background: transparent !important;
}

.monaco-menu-container .monaco-action-bar .action-item.focused,
.monaco-menu-container .monaco-action-bar .action-item:hover {
  background: #eef2ff !important;
}

.monaco-menu-container .monaco-action-bar .action-item.disabled .action-label {
  color: #9ca3af !important;
}
</style>