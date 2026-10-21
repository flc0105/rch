<template>
  <el-dialog
    v-model="visible"
    :title="title ? `Log Viewer · ${title}` : 'Log Viewer'"
    width="960px"
    top="5vh"
    class="log-viewer-dialog"
    append-to-body
    @closed="stopSession"
  >
    <div class="log-viewer-body">
      <div class="log-viewer-toolbar">
        <div class="log-viewer-file-row">
          <el-button size="small" plain :disabled="!activeClientId" @click="pickerVisible = true">Browse</el-button>
          <code class="log-viewer-path" :title="path">{{ path || 'Choose a remote log file' }}</code>
        </div>
        <div class="log-viewer-actions-row">
          <el-switch v-model="streaming" size="small" active-text="Streaming" @change="onStreamingChange" />
          <el-button size="small" :disabled="!path || loading" :loading="loading" @click="refresh">Refresh</el-button>
          <el-button size="small" @click="clearView">Clear View</el-button>
          <el-button size="small" @click="copyLogs">Copy</el-button>
          <el-checkbox v-model="follow">Follow</el-checkbox>
          <el-checkbox v-model="wrap">Wrap</el-checkbox>
          <el-input v-model="search" size="small" clearable class="log-viewer-search" placeholder="Find in loaded log..." />
        </div>
      </div>
      <div v-if="error" class="log-viewer-error">{{ error }}</div>
      <div ref="output" class="log-viewer-output" :class="{ 'log-viewer-wrap': wrap }" @scroll="onScroll">
        <template v-if="displayLines.length">
          <div v-for="line in displayLines" :key="line.number" class="log-viewer-line">
            <span class="log-viewer-line-number" aria-hidden="true">{{ line.number }}</span>
            <span class="log-viewer-line-text">{{ line.text || ' ' }}</span>
          </div>
        </template>
        <div v-else class="log-viewer-placeholder">{{ search.trim() && content ? 'No matching lines.' : (path ? 'No log content.' : 'Choose a remote log file to begin.') }}</div>
      </div>
      <div class="log-viewer-status">
        <span>{{ statusLabel }}</span>
        <span>UTF-8 · Up to 512 KiB displayed</span>
      </div>
    </div>
    <RemoteFilePicker
      v-model:visible="pickerVisible"
      :selected-id="activeClientId"
      :initial-path="pickerInitialPath"
      selection-mode="file"
      :get-tab-scoped-headers="getTabScopedHeaders"
      @select="onFileSelected"
    />
  </el-dialog>
</template>

<script>
import { ElMessage } from 'element-plus'
import RemoteFilePicker from './RemoteFilePicker.vue'

const MAX_DISPLAY_CHARS = 524288

export default {
  name: 'LogViewerDialog',
  components: { RemoteFilePicker },
  props: {
    selectedId: { type: [String, Number], default: '' },
    tabId: { type: String, default: '' },
    getTabScopedHeaders: { type: Function, default: null },
  },
  data() {
    return {
      visible: false,
      activeClientId: '',
      path: '',
      title: '',
      pickerVisible: false,
      streaming: true,
      follow: true,
      wrap: true,
      search: '',
      content: '',
      status: 'idle',
      error: '',
      loading: false,
      sessionId: '',
      requestGeneration: 0,
      oneShot: false,
      fileExists: null,
      pendingMonitorEvents: [],
    }
  },
  computed: {
    pickerInitialPath() {
      // RemoteFilePicker expects a directory even when the viewer tracks a file.
      const normalized = this.path.replace(/\\/g, '/')
      const index = normalized.lastIndexOf('/')
      if (index < 0) return ''
      if (index === 0) return '/'
      if (index === 2 && /^[a-z]:\//i.test(normalized)) return this.path.slice(0, 3)
      return this.path.slice(0, index)
    },
    displayLines() {
      if (!this.content) return []
      const term = this.search.trim().toLocaleLowerCase()
      return this.content.split('\n')
        .map((text, index) => ({ number: index + 1, text }))
        .filter(line => !term || line.text.toLocaleLowerCase().includes(term))
    },
    statusLabel() {
      if (!this.path) return 'No file selected'
      if (this.status === 'error') return 'Stream error'
      if (this.fileExists === false) return 'Waiting for file'
      if (!this.streaming && this.status === 'idle') return 'Paused'
      if (this.status === 'opening') return 'Connecting…'
      if (this.status === 'open') return this.streaming ? 'Live' : 'Loaded'
      return this.status === 'closed' ? 'Disconnected' : 'Ready'
    },
  },
  beforeUnmount() {
    this.stopSession()
  },
  methods: {
    open(source = {}) {
      this.stopSession()
      this.activeClientId = String(source.clientId || this.selectedId || '').trim()
      this.path = String(source.path || '').trim()
      this.title = String(source.title || '').trim()
      this.streaming = true
      this.follow = true
      this.wrap = true
      this.search = ''
      this.content = ''
      this.error = ''
      this.fileExists = null
      this.status = 'idle'
      this.visible = true
      if (this.path) this.$nextTick(() => this.startSession())
    },
    onFileSelected(selected) {
      const chosen = Array.isArray(selected) ? selected[0] : selected
      const path = String(chosen || '').trim()
      if (!path) return
      this.stopSession()
      this.path = path
      this.content = ''
      this.search = ''
      this.error = ''
      this.fileExists = null
      this.startSession()
    },
    async post(url, data = {}) {
      const headers = { 'Content-Type': 'application/json', 'X-Tab-Id': this.tabId }
      const response = await fetch(url, { method: 'POST', headers, body: JSON.stringify(data) })
      const json = await response.json()
      if (!response.ok || json.code !== 0) throw new Error(json.message || 'Log request failed')
      return json.data || {}
    },
    async startSession(oneShot = false) {
      if (!this.visible || !this.path || !this.activeClientId) return
      const generation = ++this.requestGeneration
      this.loading = true
      this.error = ''
      this.status = 'opening'
      this.oneShot = oneShot
      try {
        const data = await this.post(
          `/api/connections/${encodeURIComponent(this.activeClientId)}/device-monitor/open`,
          {
            channels: ['log_file'],
            intervals: { log_file: 0.25 },
            options: { path: this.path },
          },
        )
        const sessionId = String(data.monitor_session_id || '').trim()
        if (!sessionId) throw new Error('No log session returned')
        if (generation !== this.requestGeneration || !this.visible) {
          await this.closeSession(sessionId)
          return
        }
        this.sessionId = sessionId
        // Client snapshots may reach SSE before this HTTP response is received.
        const pending = this.pendingMonitorEvents
        this.pendingMonitorEvents = []
        pending.forEach(event => {
          if (event.payload.monitor_session_id !== sessionId) return
          if (event.type === 'snapshot') this.handleDeviceMonitorSnapshot(event.payload)
          else this.handleDeviceMonitorStatus(event.payload)
        })
      } catch (e) {
        if (generation === this.requestGeneration) {
          this.error = e.message || 'Could not open log stream'
          this.status = 'error'
        }
      } finally {
        if (generation === this.requestGeneration) this.loading = false
      }
    },
    async closeSession(sessionId) {
      if (!sessionId) return
      try {
        await this.post(`/api/device-monitor/${encodeURIComponent(sessionId)}/close`)
      } catch (_) {
        // Session also closes automatically when its Client disconnects.
      }
    },
    stopSession() {
      this.requestGeneration += 1
      const sessionId = this.sessionId
      this.sessionId = ''
      this.oneShot = false
      this.pendingMonitorEvents = []
      if (sessionId) this.closeSession(sessionId)
    },
    async refresh() {
      if (!this.path) return
      this.stopSession()
      this.content = ''
      this.fileExists = null
      await this.startSession(!this.streaming)
    },
    onStreamingChange(enabled) {
      if (!enabled) {
        this.stopSession()
        this.status = 'idle'
        return
      }
      this.refresh()
    },
    clearView() {
      this.content = ''
    },
    async copyLogs() {
      try {
        await navigator.clipboard.writeText(this.content)
        ElMessage.success('Log copied')
      } catch (_) {
        ElMessage.error('Failed to copy log')
      }
    },
    handleDeviceMonitorSnapshot(payload = {}) {
      if (!this.visible || payload.channel !== 'log_file') return
      if (!this.sessionId) {
        this.queueEarlyMonitorEvent('snapshot', payload)
        return
      }
      if (payload.monitor_session_id !== this.sessionId) return
      const data = payload.data || {}
      this.fileExists = data.exists !== false
      if (data.reset) this.content += '\n— Log file rotated or truncated —\n'
      this.content = this.content.slice(-MAX_DISPLAY_CHARS)
      if (data.content) {
        this.content = (this.content + String(data.content)).slice(-MAX_DISPLAY_CHARS)
        if (this.follow) this.$nextTick(() => this.scrollToBottom())
      }
      this.error = ''
      this.status = 'open'
      if (this.oneShot) {
        this.stopSession()
        this.status = 'idle'
      }
    },
    handleDeviceMonitorStatus(payload = {}) {
      if (!this.visible) return
      if (!this.sessionId) {
        this.queueEarlyMonitorEvent('status', payload)
        return
      }
      if (payload.monitor_session_id !== this.sessionId) return
      if (payload.state === 'error' || payload.state === 'closed') {
        this.status = payload.state
        this.error = String(payload.error || (payload.state === 'closed' ? 'Client disconnected' : 'Log stream unavailable'))
        this.sessionId = ''
      } else if (payload.state === 'open') {
        this.status = 'open'
      }
    },
    queueEarlyMonitorEvent(type, payload) {
      if (!this.loading || this.status !== 'opening' ||
          String(payload.client_id || '') !== this.activeClientId) return
      if (type === 'status' && !payload.channels?.includes('log_file')) return
      // Bound early-event buffering, even when the HTTP response is slow.
      this.pendingMonitorEvents.push({ type, payload })
      if (this.pendingMonitorEvents.length > 16) this.pendingMonitorEvents.shift()
    },
    scrollToBottom() {
      const el = this.$refs.output
      if (el) el.scrollTop = el.scrollHeight
    },
    onScroll(event) {
      const el = event?.target
      if (!el) return
      if (el.scrollHeight - el.scrollTop - el.clientHeight > 36) this.follow = false
    },
  },
}
</script>

<style scoped>
.log-viewer-body { display: flex; flex-direction: column; gap: 8px; min-height: 0; height: min(70vh, 700px); }
.log-viewer-toolbar { display: flex; flex-direction: column; gap: 8px; min-width: 0; padding: 2px 0 6px; }
.log-viewer-file-row, .log-viewer-actions-row { display: flex; align-items: center; gap: 9px; min-width: 0; }
.log-viewer-actions-row { overflow-x: auto; }
.log-viewer-toolbar :deep(.el-button + .el-button) { margin-left: 0; }
.log-viewer-toolbar :deep(.el-checkbox) { margin-right: 0; flex: 0 0 auto; }
.log-viewer-toolbar :deep(.el-switch), .log-viewer-toolbar :deep(.el-button) { flex-shrink: 0; }
.log-viewer-path { flex: 1 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; }
.log-viewer-search { flex: 0 0 160px; width: 160px; margin-left: auto; }
.log-viewer-error { font-size: 12px; color: var(--el-color-danger); }
.log-viewer-output { flex: 1; min-height: 130px; overflow: auto; border: 1px solid var(--el-border-color); border-radius: 7px; background: var(--el-fill-color-light); color: var(--el-text-color-primary); font: 12px/1.55 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
.log-viewer-line { display: flex; width: max-content; min-width: 100%; }
.log-viewer-line-number { position: sticky; left: 0; z-index: 1; flex: 0 0 58px; box-sizing: border-box; text-align: right; padding: 0 10px 0 4px; color: var(--el-text-color-placeholder); background: var(--el-fill-color); border-right: 1px solid var(--el-border-color-lighter); user-select: none; }
.log-viewer-line-text { white-space: pre; padding-left: 10px; padding-right: 12px; }
.log-viewer-wrap .log-viewer-line { width: 100%; min-width: 0; }
.log-viewer-wrap .log-viewer-line-text { min-width: 0; white-space: pre-wrap; overflow-wrap: anywhere; }
.log-viewer-placeholder { padding: 12px; color: var(--el-text-color-secondary); }
.log-viewer-status { display: flex; justify-content: space-between; gap: 12px; flex-wrap: wrap; color: var(--el-text-color-secondary); font-size: 11px; }
</style>
