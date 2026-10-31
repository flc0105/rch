<template>
  <el-dialog
    v-model="visible"
    :width="ptyFullscreen ? '100vw' : '900px'"
    :top="ptyFullscreen ? '0' : '6vh'"
    :class="['fixed-dialog', 'pty-dialog', { 'pty-dialog-fullscreen': ptyFullscreen }]"
    :show-close="false"
    modal-class="pty-overlay"
    @close="closePtyDialog"
    @closed="handlePtyDialogClosed"
  >
    <template #header>
      <div class="pty-dialog-header">
        <span class="pty-dialog-title">Remote PTY</span>
        <div class="pty-header-actions">
          <el-tooltip :content="ptyFullscreen ? 'Exit Fullscreen' : 'Fullscreen'" placement="bottom">
            <button
              type="button"
              class="pty-header-action"
              :aria-label="ptyFullscreen ? 'Exit Fullscreen' : 'Fullscreen'"
              @click="togglePtyFullscreen"
            >
              <el-icon><FullScreen /></el-icon>
            </button>
          </el-tooltip>
          <button type="button" class="pty-header-action" aria-label="Close" title="Close" @click="visible = false">
            <el-icon><Close /></el-icon>
          </button>
        </div>
      </div>
    </template>
    <div class="fixed-dialog-body pty-shell">
      <div class="pty-toolbar">
        <div class="pty-toolbar-left">
          <span class="pty-badge">
            {{ connectionLabel }}
          </span>

          <span class="pty-badge pty-badge-status">
            {{ statusText }}
          </span>

          <span
            v-if="ptyError"
            class="pty-error-text"
          >
            {{ ptyError }}
          </span>
        </div>

        <div class="pty-toolbar-right">
          <el-input
            v-model="shellPath"
            size="small"
            clearable
            class="pty-shell-input"
            placeholder="default / zsh / cmd.exe / powershell.exe"
            :disabled="ptyLoading || ptyClosing"
            @keyup.enter="switchPtyShell"
          />

          <el-button
            size="small"
            :loading="ptyClosing || ptyLoading"
            :disabled="!ptySessionId"
            @click="switchPtyShell"
          >
            Switch
          </el-button>

          <el-dropdown trigger="click" @command="handlePtyMoreCommand">
            <el-button size="small">More</el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="focus" :disabled="!ptyTerm">Focus</el-dropdown-item>
                <el-dropdown-item command="paste" :disabled="!ptySessionId || ptyClosing">Paste</el-dropdown-item>
                <el-dropdown-item command="copy" :disabled="!ptyTerm">Copy</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </div>

      <div
        class="pty-screen-shell xterm-shell"
        @click="focusPtyInput"
      >
        <div
          ref="ptyTerminalRef"
          class="pty-terminal-host"
        />
      </div>

      <div class="pty-hint">
        Powered by xterm.js. Supports ANSI control sequences, vim/less/top style full-screen apps, sudo prompts, paste and resize.
      </div>
    </div>
  </el-dialog>

  <!-- Safari/iOS may disallow clipboard reads on HTTP: use native Paste in this input. -->
  <el-dialog
    v-model="ptyPasteVisible"
    title="Paste into PTY"
    width="420px"
    append-to-body
    @opened="$refs.ptyPasteInput?.focus()"
  >
    <textarea
      ref="ptyPasteInput"
      v-model="ptyPasteText"
      class="pty-paste-input"
      rows="5"
      placeholder="Tap and hold here to paste"
    />
    <template #footer>
      <el-button @click="ptyPasteVisible = false">Cancel</el-button>
      <el-button type="primary" :disabled="!ptyPasteText || !ptySessionId" @click="sendPtyPastedText(ptyPasteText)">Paste</el-button>
    </template>
  </el-dialog>
</template>

<script>
import { ElMessage } from 'element-plus'
import { FullScreen, Close } from '@element-plus/icons-vue'
import { getPtyBufferText } from '../utils/ptyText.js'
import { webSocketUrl } from '../api/streamApi.js'
import { Terminal } from 'xterm'
import { FitAddon } from 'xterm-addon-fit'
import 'xterm/css/xterm.css'

export default {
  name: 'PtyDialog',
  components: { FullScreen, Close },

  props: {
    selectedId: {
      type: [String, Number],
      default: '',
    },

    currentConnection: {
      type: Object,
      default: null,
    },

    getTabScopedHeaders: {
      type: Function,
      default: null,
    },
  },

  data() {
    return {
      visible: false,
      ptyFullscreen: false,
      ptyPasteVisible: false,
      ptyPasteText: '',
      shellPath: '',
      ptyLoading: false,
      ptyClosing: false,
      ptySessionId: '',
      ptySeq: 0,
      ptyStatus: '',
      ptyError: '',
      ptyTerm: null,
      ptyFitAddon: null,
      ptyInputQueue: '',
      ptyFlushTimer: null,
      ptyLastCols: 0,
      ptyLastRows: 0,
      ptyWs: null,
      ptyWsPath: '',
      ptyUserClosing: false,
      _ptyResizeTimer: null,
      _ptyWindowResizeHandler: null,
    }
  },

  computed: {
    connectionLabel() {
      const connection = this.currentConnection || {}
      return connection.hostname || connection.client_id || 'No device'
    },

    statusText() {
      return this.ptyStatus || 'idle'
    },
  },

  beforeUnmount() {
    this.ptyPasteVisible = false
    this.resetPtyInputQueue()
    this.clearPtyResizeTimer()
    this.sendPtyWs({ type: 'close' })
    this.closePtySocket()
    this.disposePtyTerminal()
  },

  methods: {
    async open() {
      if (!this.selectedId) {
        ElMessage.warning('Please select a device')
        return
      }

      if (this.ptyLoading || this.ptyClosing) return

      this.visible = true
      this.ptyFullscreen = false
      this.ptyPasteVisible = false
      this.ptyPasteText = ''
      this.ptyUserClosing = false
      this.shellPath = ''

      try {
        await this.$nextTick()
        this.initPtyTerminal()
        await this.openPtySession('')
      } catch (e) {
        this.ptyStatus = 'error'
        this.ptyError = e?.message || String(e)
        ElMessage.error(this.ptyError || 'Failed to open PTY')
      }
    },

    normalizeShellRequest(value) {
      const shell = String(value || '').trim()
      return shell.toLowerCase() === 'default' ? '' : shell
    },

    async openPtySession(shell = '') {
      if (this.ptyLoading) return

      this.ptyLoading = true
      this.ptySessionId = ''
      this.ptySeq = 0
      this.ptyStatus = 'opening'
      this.ptyError = ''
      this.ptyUserClosing = false
      this.closePtySocket()
      this.resetPtyInputQueue()

      try {
        this.clearPtyTerminal()
        ElMessage({ type: 'info', message: 'Opening PTY session...', duration: 1200 })

        const dims = this.fitPtyTerminalAndGetSize()
        const res = await fetch(`/api/connections/${encodeURIComponent(this.selectedId)}/pty/open`, {
          method: 'POST',
          headers: this.buildJsonHeaders({ 'Content-Type': 'application/json' }),
          body: JSON.stringify({
            cols: dims.cols,
            rows: dims.rows,
            shell,
          }),
        })
        const json = await res.json()
        if (!res.ok || json.code !== 0) {
          throw new Error(json.message || 'Failed to open PTY')
        }

        this.ptySessionId = json.data?.pty_session_id || ''
        this.ptyStatus = json.data?.status || 'opening'
        this.ptyLastCols = dims.cols
        this.ptyLastRows = dims.rows
        this.ptyWsPath = json.data?.ws_path || ''

        this.openPtySocket()
        this.syncPtyShellFromSession(this.ptySessionId)
        this.focusPtyInput()
        this.schedulePtyResize()
      } finally {
        this.ptyLoading = false
      }
    },

    async switchPtyShell() {
      if (this.ptyLoading || this.ptyClosing || !this.ptySessionId) return

      const nextShell = this.normalizeShellRequest(this.shellPath)
      const previousSessionId = this.ptySessionId

      this.ptyClosing = true
      this.ptyUserClosing = true
      this.resetPtyInputQueue()
      this.clearPtyResizeTimer()
      this.ptyStatus = 'closing'

      try {
        const res = await fetch(`/api/pty/${encodeURIComponent(previousSessionId)}/close`, {
          method: 'POST',
          headers: this.buildJsonHeaders({ 'Content-Type': 'application/json' }),
          body: '{}',
        })
        const json = await res.json()
        if (!res.ok || json.code !== 0) {
          throw new Error(json.message || 'Failed to close current PTY')
        }

        await this.waitForPtyClosed(previousSessionId)
        this.closePtySocket()

        this.ptySessionId = ''
        this.ptyWsPath = ''
        this.ptyUserClosing = false
        this.ptyClosing = false
        await this.openPtySession(nextShell)
      } catch (e) {
        this.ptyStatus = 'error'
        this.ptyError = e?.message || 'Failed to switch PTY shell'
        ElMessage.error(this.ptyError)
      } finally {
        this.ptyClosing = false
        this.ptyUserClosing = false
      }
    },

    async syncPtyShellFromSession(ptySessionId, timeoutMs = 3000) {
      const sessionId = String(ptySessionId || '').trim()
      if (!sessionId) return

      const deadline = Date.now() + timeoutMs
      while (Date.now() < deadline && this.ptySessionId === sessionId) {
        try {
          const res = await fetch(`/api/pty/${encodeURIComponent(sessionId)}/poll?after_seq=${encodeURIComponent(this.ptySeq || 0)}`, {
            headers: this.buildJsonHeaders(),
          })
          const json = await res.json()
          if (!res.ok || json.code !== 0) return

          const shell = String(json.data?.shell || '').trim()
          if (shell) {
            this.shellPath = shell
            return
          }

          const status = String(json.data?.status || '').trim().toLowerCase()
          if (status === 'closed' || status === 'error') return
        } catch (_) {
          return
        }

        await new Promise(resolve => setTimeout(resolve, 60))
      }
    },

    async waitForPtyClosed(ptySessionId, timeoutMs = 5000) {
      const deadline = Date.now() + timeoutMs

      while (Date.now() < deadline) {
        const res = await fetch(`/api/pty/${encodeURIComponent(ptySessionId)}/poll?after_seq=0`, {
          headers: this.buildJsonHeaders(),
        })
        const json = await res.json()
        if (!res.ok || json.code !== 0) {
          throw new Error(json.message || 'Failed to wait for PTY shutdown')
        }

        const status = String(json.data?.status || '').trim().toLowerCase()
        if (status === 'closed' || status === 'error') return
        await new Promise(resolve => setTimeout(resolve, 80))
      }

      throw new Error('Current PTY did not stop in time')
    },

    async closePtyDialog() {
      this.ptyPasteVisible = false
      if (this.ptyClosing) {
        this.visible = false
        return
      }

      this.ptyClosing = true
      this.resetPtyInputQueue()
      this.clearPtyResizeTimer()
      this.ptyUserClosing = true
      this.sendPtyWs({ type: 'close' })
      this.closePtySocket()

      const ptyId = this.ptySessionId
      this.visible = false
      this.ptySessionId = ''
      this.ptyStatus = 'closed'

      if (!ptyId) {
        this.disposePtyTerminal()
        this.ptyClosing = false
        return
      }

      try {
        await fetch(`/api/pty/${encodeURIComponent(ptyId)}/close`, {
          method: 'POST',
          headers: this.buildJsonHeaders({ 'Content-Type': 'application/json' }),
          body: '{}',
        })
      } catch (_) {
      } finally {
        this.disposePtyTerminal()
        this.ptyClosing = false
      }
    },

    handlePtyDialogClosed() {
      this.visible = false
      this.ptyFullscreen = false
      this.ptyPasteVisible = false
      this.ptyPasteText = ''
      this.resetPtyInputQueue()
      this.clearPtyResizeTimer()
      this.closePtySocket()
      this.ptySessionId = ''
      this.disposePtyTerminal()
    },

    buildJsonHeaders(extra = {}) {
      if (typeof this.getTabScopedHeaders === 'function') {
        return this.getTabScopedHeaders(extra)
      }

      return extra
    },

    initPtyTerminal() {
      if (this.ptyTerm) return
      const host = this.$refs.ptyTerminalRef
      if (!host) return

      const term = new Terminal({
        cursorBlink: true,
        convertEol: false,
        scrollback: 5000,
        fontSize: 12,
        lineHeight: 1.32,
        fontFamily: "'JetBrains Mono', 'SFMono-Regular', 'Cascadia Mono', 'Menlo', 'Consolas', monospace",
        theme: {
          background: '#000000',
          foreground: '#e5e7eb',
          cursor: '#e5e7eb',
          cursorAccent: '#000000',
          selectionBackground: 'rgba(148, 163, 184, 0.28)',
        },
        allowTransparency: false,
      })

      const fitAddon = new FitAddon()
      term.loadAddon(fitAddon)
      term.open(host)

      try { fitAddon.fit() } catch (_) {}

      term.onData((data) => {
        this.queuePtyInput(data)
      })

      term.onTitleChange((title) => {
        if (title) this.ptyStatus = this.ptyStatus || 'open'
      })

      this.ptyTerm = term
      this.ptyFitAddon = fitAddon

      this._ptyWindowResizeHandler = () => {
        this.schedulePtyResize()
      }
      window.addEventListener('resize', this._ptyWindowResizeHandler, { passive: true })
    },

    disposePtyTerminal() {
      if (this._ptyWindowResizeHandler) {
        window.removeEventListener('resize', this._ptyWindowResizeHandler)
        this._ptyWindowResizeHandler = null
      }

      this.clearPtyResizeTimer()

      if (this.ptyTerm) {
        try { this.ptyTerm.dispose() } catch (_) {}
        this.ptyTerm = null
      }

      this.ptyFitAddon = null
      this.ptyLastCols = 0
      this.ptyLastRows = 0
    },

    clearPtyResizeTimer() {
      if (this._ptyResizeTimer) {
        clearTimeout(this._ptyResizeTimer)
        this._ptyResizeTimer = null
      }
    },

    clearPtyTerminal() {
      if (this.ptyTerm) {
        try { this.ptyTerm.clear() } catch (_) {}
        try { this.ptyTerm.reset() } catch (_) {}
      }
    },

    writePtyOutput(text) {
      if (!text) return
      if (this.ptyTerm) {
        this.ptyTerm.write(text)
      }
    },

    togglePtyFullscreen() {
      this.ptyFullscreen = !this.ptyFullscreen
      this.$nextTick(() => this.schedulePtyResize())
    },

    handlePtyMoreCommand(command) {
      if (command === 'focus') this.focusPtyInput()
      else if (command === 'paste') void this.pasteIntoPty()
      else if (command === 'copy') void this.copyPtyOutput()
    },

    async pasteIntoPty() {
      if (!this.ptySessionId || this.ptyClosing) return
      try {
        if (!window.isSecureContext || typeof navigator.clipboard?.readText !== 'function') {
          throw new Error('Clipboard read requires a secure context')
        }
        const text = await navigator.clipboard.readText()
        if (!text) {
          ElMessage.warning('Clipboard is empty')
          return
        }
        if (this.visible && this.ptySessionId) this.sendPtyPastedText(text)
      } catch (_) {
        if (!this.visible || !this.ptySessionId) return
        // iOS Safari and non-secure LAN origins can reject clipboard.readText.
        // Let the user invoke the native Paste action in an editable textarea.
        this.ptyPasteText = ''
        this.ptyPasteVisible = true
      }
    },

    sendPtyPastedText(text) {
      if (!this.ptySessionId || !text) return
      // Use the same UTF-8/base64 input queue as xterm's normal keyboard input.
      this.queuePtyInput(String(text))
      this.ptyPasteVisible = false
      this.ptyPasteText = ''
      this.$nextTick(() => this.focusPtyInput())
    },

    async copyPtyOutput() {
      const text = getPtyBufferText(this.ptyTerm)
      if (!text) {
        ElMessage.warning('No PTY output to copy')
        return
      }
      try {
        if (window.isSecureContext && typeof navigator.clipboard?.writeText === 'function') {
          await navigator.clipboard.writeText(text)
        } else {
          const textarea = document.createElement('textarea')
          textarea.value = text
          textarea.setAttribute('readonly', '')
          textarea.style.position = 'fixed'
          textarea.style.opacity = '0'
          document.body.appendChild(textarea)
          try {
            textarea.focus()
            textarea.select()
            textarea.setSelectionRange(0, text.length)
            if (!document.execCommand('copy')) throw new Error('Copy failed')
          } finally {
            textarea.remove()
          }
        }
        ElMessage.success('PTY output copied')
      } catch (_) {
        ElMessage.error('Cannot access clipboard')
      }
    },

    focusPtyInput() {
      if (this.ptyTerm) {
        try { this.ptyTerm.focus() } catch (_) {}
      }
    },

    fitPtyTerminalAndGetSize() {
      if (this.ptyFitAddon) {
        try { this.ptyFitAddon.fit() } catch (_) {}
      }
      const cols = Math.max(20, Number(this.ptyTerm?.cols || 120))
      const rows = Math.max(5, Number(this.ptyTerm?.rows || 32))
      return { cols, rows }
    },

    schedulePtyResize() {
      if (!this.visible || !this.ptySessionId || !this.ptyWs || this.ptyWs.readyState !== WebSocket.OPEN) return

      this.clearPtyResizeTimer()
      this._ptyResizeTimer = setTimeout(() => {
        this._ptyResizeTimer = null
        if (!this.visible || !this.ptySessionId) return
        const size = this.fitPtyTerminalAndGetSize()
        this.sendPtyResize(size.cols, size.rows)
      }, 80)
    },

    sendPtyResize(cols, rows) {
      if (!this.ptySessionId) return
      const normalizedCols = Math.max(20, Number(cols || 0))
      const normalizedRows = Math.max(5, Number(rows || 0))
      if (!normalizedCols || !normalizedRows) return
      if (this.ptyLastCols === normalizedCols && this.ptyLastRows === normalizedRows) return
      this.ptyLastCols = normalizedCols
      this.ptyLastRows = normalizedRows
      this.sendPtyWs({ type: 'resize', cols: normalizedCols, rows: normalizedRows })
    },

    buildPtyWsUrl() {
      const raw = String(this.ptyWsPath || '').trim()

      if (!raw) {
        return ''
      }

      // 后端如果直接返回 ws:// 或 wss://，直接使用
      if (/^wss?:\/\//i.test(raw)) {
        return raw
      }

      // 后端如果返回 /api/xxx/ws，就通过 Vite dev server 代理
      const path = raw.startsWith('/') ? raw : `/${raw}`
      return webSocketUrl(path)
    },

    openPtySocket() {
      this.closePtySocket()

      if (!this.ptyWsPath) {
        this.ptyStatus = 'error'
        this.ptyError = 'PTY websocket path is empty'
        ElMessage.error(this.ptyError)
        return
      }

      const url = this.buildPtyWsUrl()

      if (!url) {
        this.ptyStatus = 'error'
        this.ptyError = 'Invalid PTY websocket URL'
        ElMessage.error(this.ptyError)
        return
      }

      const ws = new WebSocket(url)
      let connectedOnce = false
      let openedNotified = false
      this.ptyWs = ws

      const isCurrentSocket = () => this.ptyWs === ws

      const applyChunks = (chunks) => {
        if (!Array.isArray(chunks)) return

        chunks.forEach((chunk) => {
          const seq = Number(chunk?.seq || 0)
          if (seq > this.ptySeq) this.ptySeq = seq

          const text = String(chunk?.text || '')
          if (text) this.writePtyOutput(text)
        })
      }

      const applySessionStatus = (payload = {}) => {
        const status = String(payload.status || '').trim().toLowerCase()
        const shell = String(payload.shell || '').trim()

        if (shell) this.shellPath = shell
        if (!status) return

        this.ptyStatus = status
        if (payload.error) this.ptyError = payload.error

        if (status === 'open') {
          this.ptyError = ''

          if (!openedNotified) {
            openedNotified = true
            ElMessage({
              type: 'success',
              message: 'PTY connected',
              duration: 1200,
            })
          }
        }
      }

      ws.onopen = () => {
        if (!isCurrentSocket()) return

        // WebSocket 建立只代表传输通道可用，PTY 仍需等待 Client 真正回报 opened。
        connectedOnce = true
        this.focusPtyInput()
        this.schedulePtyResize()
      }

      ws.onmessage = (event) => {
        if (!isCurrentSocket()) return

        try {
          const payload = JSON.parse(String(event.data || '{}'))

          if (payload.type === 'output') {
            applyChunks(payload.chunks)
          }

          if (payload.type === 'snapshot' || payload.type === 'pty_update') {
            applyChunks(payload.chunks)
          }

          applySessionStatus(payload)

          if (payload.seq) {
            this.ptySeq = Math.max(this.ptySeq, Number(payload.seq || 0))
          }

          if (
            payload.type === 'status' ||
            payload.type === 'snapshot' ||
            payload.type === 'pty_update' ||
            payload.type === 'output'
          ) {
            if (payload.status === 'closed' || payload.status === 'error') {
              this.closePtySocket()
            }
          }
        } catch (e) {
          console.error('PTY ws message parse failed', e)
        }
      }

      ws.onerror = (event) => {
        if (!isCurrentSocket()) return

        console.error('PTY WS error:', event)
        this.ptyError = this.ptyError || 'PTY websocket error'

        if (!connectedOnce) {
          this.ptyStatus = 'error'
        }
      }

      ws.onclose = (event) => {
        if (!isCurrentSocket()) return

        console.log('PTY WS closed:', {
          code: event.code,
          reason: event.reason,
          wasClean: event.wasClean,
        })

        const unexpected =
          !this.ptyUserClosing &&
          this.visible &&
          this.ptyStatus !== 'error'

        if (
          this.visible &&
          this.ptyStatus !== 'closed' &&
          this.ptyStatus !== 'error'
        ) {
          this.ptyStatus = openedNotified ? 'closed' : 'error'
        }

        this.ptyWs = null

        if (unexpected) {
          ElMessage({
            type: openedNotified ? 'warning' : 'error',
            message: openedNotified
              ? 'PTY disconnected'
              : 'PTY connection failed',
            duration: 1800,
          })
        }
      }
    },

    closePtySocket() {
      if (this.ptyWs) {
        try { this.ptyWs.close() } catch (_) {}
        this.ptyWs = null
      }
    },

    sendPtyWs(payload) {
      if (!this.ptyWs || this.ptyWs.readyState !== WebSocket.OPEN) return
      try {
        this.ptyWs.send(JSON.stringify(payload || {}))
      } catch (_) {}
    },

    queuePtyInput(raw) {
      if (!this.ptySessionId || !raw) return
      this.ptyInputQueue = `${this.ptyInputQueue || ''}${raw}`
      if (this.ptyFlushTimer) return
      this.ptyFlushTimer = setTimeout(() => this.flushPtyInputQueue(), 10)
    },

    resetPtyInputQueue() {
      this.ptyInputQueue = ''
      if (this.ptyFlushTimer) {
        clearTimeout(this.ptyFlushTimer)
        this.ptyFlushTimer = null
      }
    },

    flushPtyInputQueue() {
      const payload = this.ptyInputQueue || ''
      this.ptyInputQueue = ''
      this.ptyFlushTimer = null
      if (!this.ptySessionId || !payload) return
      const encoded = this.encodePtyInput(payload)
      this.sendPtyWs({ type: 'input', data: encoded })
    },

    encodePtyInput(raw) {
      const bytes = new TextEncoder().encode(String(raw || ''))
      let binary = ''
      const chunkSize = 0x8000
      for (let i = 0; i < bytes.length; i += chunkSize) {
        const chunk = bytes.subarray(i, i + chunkSize)
        binary += String.fromCharCode(...chunk)
      }
      return btoa(binary)
    },
  },
}
</script>

<style scoped>
.pty-dialog-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.pty-dialog-title {
  color: var(--el-text-color-primary);
  font-size: var(--el-dialog-title-font-size);
  line-height: var(--el-dialog-font-line-height);
}

.pty-header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.pty-header-action {
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
  cursor: pointer;
}

.pty-header-action:hover,
.pty-header-action:focus-visible {
  color: var(--el-color-primary);
  background: var(--el-fill-color-light);
  outline: none;
}

.pty-paste-input {
  box-sizing: border-box;
  display: block;
  width: 100%;
  max-width: 100%;
  font: inherit;
  padding: 10px;
  border-radius: 6px;
  border: 1px solid var(--el-border-color);
  color: var(--el-text-color-primary);
  background: var(--el-fill-color-blank);
  resize: vertical;
}

.pty-shell {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  gap: 10px;
}

.pty-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex: 0 0 auto;
}

.pty-toolbar-left,
.pty-toolbar-right {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  min-width: 0;
}

.pty-badge {
  display: inline-flex;
  align-items: center;
  padding: 4px 8px;
  border-radius: 999px;
  background: rgba(148, 163, 184, 0.16);
  font-size: 12px;
  line-height: 18px;
}

.pty-badge-status {
  text-transform: capitalize;
}

.pty-shell-input {
  width: 220px;
}

.pty-error-text {
  color: #dc2626;
  font-size: 12px;
}

.pty-screen-shell {
  position: relative;
  min-height: 520px;
  border-radius: 14px;
  border: 1px solid rgba(255, 255, 255, 0.12);
  background: #000000;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.03);
  overflow: hidden;
  flex: 1 1 auto;
}

.xterm-shell {
  padding: 0;
  padding-bottom: 14px;
  background: #000000;
}

.pty-terminal-host {
  width: 100%;
  height: 100%;
  min-height: 480px;
  padding: 16px 18px 16px 16px;
  box-sizing: border-box;
}

.pty-terminal-host :deep(.xterm) {
  padding-right: 8px;
}

.pty-terminal-host :deep(.xterm-viewport) {
  overflow-y: auto !important;
  background: #000000 !important;
  scrollbar-gutter: stable;
}

.pty-terminal-host :deep(.xterm-viewport::-webkit-scrollbar) {
  width: 10px;
}

.pty-terminal-host :deep(.xterm-viewport::-webkit-scrollbar-track) {
  background: rgba(255, 255, 255, 0.04);
  border-radius: 999px;
}

.pty-terminal-host :deep(.xterm-viewport::-webkit-scrollbar-thumb) {
  background: rgba(148, 163, 184, 0.42);
  border-radius: 999px;
  border: 2px solid transparent;
  background-clip: padding-box;
}

.pty-terminal-host :deep(.xterm-viewport::-webkit-scrollbar-thumb:hover) {
  background: rgba(148, 163, 184, 0.62);
  border: 2px solid transparent;
  background-clip: padding-box;
}

.pty-terminal-host :deep(.xterm-screen),
.pty-terminal-host :deep(.xterm-helpers) {
  width: calc(100% - 8px) !important;
}

.pty-hint {
  flex: 0 0 auto;
  font-size: 12px;
  color: #94a3b8;
}

@media (max-width: 768px) {
  .pty-toolbar {
    flex: 0 0 auto;
    flex-direction: column;
    align-items: stretch;
  }

  .pty-toolbar-left,
  .pty-toolbar-right,
  .pty-shell-input {
    width: 100%;
  }

  .pty-screen-shell {
    flex: 1 1 auto;
    min-height: 0;
  }

  .pty-terminal-host {
    height: 100%;
    min-height: 0;
    padding: 12px 14px 12px 12px;
  }

  .pty-hint {
    display: none;
  }
}

.el-button+.el-button {
  margin:0 !important;
}
</style>

<style>
.pty-overlay .el-dialog.pty-dialog-fullscreen {
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

.pty-overlay .pty-dialog-fullscreen .el-dialog__header { flex: 0 0 auto !important; }
.pty-overlay .pty-dialog-fullscreen .el-dialog__body {
  flex: 1 1 auto !important;
  min-height: 0 !important;
  display: flex !important;
  flex-direction: column !important;
  overflow: hidden !important;
}
.pty-overlay .pty-dialog-fullscreen .pty-shell { flex: 1 1 auto; min-height: 0; }
.pty-overlay .pty-dialog-fullscreen .pty-screen-shell { min-height: 0; }
.pty-overlay .pty-dialog-fullscreen .pty-terminal-host { min-height: 0; }

/* PtyDialog: xterm 由组件内部管理，弹窗只负责固定高度和内部滚动。 */
.pty-overlay .el-dialog {
  overflow: hidden !important;
}

.pty-overlay .el-dialog__body {
  padding-top: 10px !important;
  overflow: hidden !important;
}

/*@media (max-width: 768px), (max-height: 720px) {*/
@media (max-width: 768px) {
  .pty-overlay .el-dialog {
    width: 100vw !important;
    max-width: 100vw !important;
    height: 100dvh !important;
    max-height: 100dvh !important;
    margin: 0 !important;
    border-radius: 0 !important;
    display: flex !important;
    flex-direction: column !important;
  }

  .pty-overlay .el-dialog__header {
    flex: 0 0 auto !important;
    padding: 14px 16px 10px !important;
  }

  .pty-overlay .el-dialog__body {
    display: flex !important;
    flex: 1 1 auto !important;
    min-height: 0 !important;
    padding: 8px 12px 12px !important;
    overflow: hidden !important;
  }

  .pty-overlay .pty-shell {
    flex: 1 1 auto !important;
    min-height: 0 !important;
  }
}



@media (min-width: 769px) {
  .pty-overlay .el-dialog {
    width: 900px !important;
    max-width: calc(100vw - 32px) !important;
    height: 78vh !important;
    max-height: 78vh !important;
    margin: 6vh auto 0 !important;
    border-radius: var(--el-border-radius-small) !important;
    display: flex !important;
    flex-direction: column !important;
  }

  .pty-overlay .el-dialog__body {
    flex: 1 1 auto !important;
    min-height: 0 !important;
    padding-top: 10px !important;
    overflow: hidden !important;
  }
}

</style>