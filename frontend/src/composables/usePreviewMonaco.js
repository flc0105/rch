import { ElMessage } from 'element-plus'
import { copyTextFallback } from '../utils/clipboard.js'
import { formatBytes } from '../utils/formatters.js'
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

const monacoEditorStore = new WeakMap()
const monacoInitFrameStore = new WeakMap()
const monacoLayoutFrameStore = new WeakMap()
const monacoTruncationZoneStore = new WeakMap()

function getPreviewMonacoEditor(vm) {
  return vm.monacoReadySession === vm.previewLoadSeq ? monacoEditorStore.get(vm) || null : null
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
  methods: {
    initMonacoEditor() {
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

          // The toolbar can change content or edit mode before this frame runs.
          const content = this.previewText
          const readOnly = !this.previewEditMode
          const container = this.$refs.monacoEditorContainerRef
          if (!container || !container.isConnected) return

          const editor = monacoEditorStore.get(this) || null
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

          this.monacoReadySession = this.previewLoadSeq
          this.updateMonacoTruncationZone(getPreviewMonacoEditor(this))

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

    updateMonacoTruncationZone(editor) {
      if (!editor?.changeViewZones) return
      editor.changeViewZones(accessor => {
        const oldZone = monacoTruncationZoneStore.get(editor)
        if (oldZone) accessor.removeZone(oldZone)
        monacoTruncationZoneStore.delete(editor)
        const model = editor.getModel?.()
        if (!this.previewTruncated || !model) return
        const node = document.createElement('div')
        node.className = 'preview-truncation-zone'
        node.textContent = '… Preview truncated'
        monacoTruncationZoneStore.set(editor, accessor.addZone({
          afterLineNumber: model.getLineCount(),
          heightInPx: 26,
          domNode: node,
        }))
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
      const editor = monacoEditorStore.get(this) || null

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
      if (this.previewSaving || this.previewReloading) return
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

        copyTextFallback(content)
        ElMessage.success('Content copied')
      } catch (e) {
        try {
          copyTextFallback(content)
          ElMessage.success('Content copied')
        } catch (fallbackError) {
          ElMessage.error('Failed to copy content')
        }
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

    async pastePreviewText() {
      if (this.previewType !== 'text') {
        ElMessage.warning('Only text content can be pasted')
        return
      }

      if (!this.previewEditMode) {
        ElMessage.warning('Please enter edit mode first')
        return
      }

      const seq = this.previewLoadSeq
      let text = ''

      try {
        text = await this.readClipboardTextForPaste()
      } catch (_error) {
        if (this.isPreviewSessionCurrent(seq)) ElMessage.warning('当前浏览器不允许按钮读取剪贴板，请尝试使用 Ctrl+V 粘贴')
        return
      }

      if (!this.isPreviewSessionCurrent(seq) || !this.previewEditMode) return
      if (!text) {
        ElMessage.warning('Clipboard is empty')
        return
      }

      const editor = getPreviewMonacoEditor(this)

      if (!editor) {
        this.previewText = `${text}${this.previewText || ''}`
        this.initMonacoEditor()
        ElMessage.success('Content pasted')
        return
      }

      const model = editor.getModel && editor.getModel()

      if (!model) {
        this.previewText = `${text}${this.previewText || ''}`
        this.initMonacoEditor()
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
        this.updateMonacoTruncationZone(editor)

        if (typeof editor.setPosition === 'function') {
          editor.setPosition({lineNumber: 1, column: 1})
        }

        editor.focus()
      } else {
        this.initMonacoEditor()
      }

      this.previewEditMode = this.previewEditable
    },


  },
  beforeUnmount() {
    this.cancelPendingMonacoFrames()
    this.blurMonacoEditor()
    setPreviewMonacoEditor(this, null)
  },

}
