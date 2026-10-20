<template>
  <el-dialog
    v-model="processDialogVisible"
    title="Process Manager"
    width="1100px"
    top="5vh"
    class="fixed-dialog process-dialog"
    modal-class="process-overlay"
    @closed="handleProcessDialogClosed"
  >
    <div class="fixed-dialog-body process-dialog-body">
      <div class="process-toolbar">
        <div class="process-toolbar-left">
          <el-button
            size="small"
            class="toolbar-btn"
            :loading="processActiveTab === 'apps' ? appsLoading : processesLoading"
            @click="refreshProcessManager"
          >
            Refresh
          </el-button>

          <el-input
            v-model="processFilterText"
            placeholder="Filter by PID, PPID, name, username"
            size="small"
            class="process-dialog-filter-input"
            clearable
          />
        </div>

        <div class="process-toolbar-right">
          <span class="process-count">{{ processManagerSummaryText }}</span>
        </div>
      </div>

      <el-tabs
        v-model="processActiveTab"
        class="process-tabs"
      >
        <el-tab-pane
          :label="processTabLabel"
          name="processes"
        >
          <div class="process-table-shell">
            <el-table
              ref="processTable"
              :data="filteredProcesses"
              :default-sort="processSort"
              @sort-change="onProcessSortChange"
              v-loading="processesLoading"
              stripe
              height="100%"
              table-layout="fixed"
            >
              <el-table-column
                prop="pid"
                label="PID"
                width="90"
                align="center"
                sortable="custom"
              />

              <el-table-column
                prop="ppid"
                label="PPID"
                width="90"
                align="center"
              />

              <el-table-column
                prop="name"
                label="Name"
                min-width="220"
                sortable="custom"
                show-overflow-tooltip
              />

              <el-table-column prop="cpu_percent" label="CPU %" width="100" align="center" sortable="custom">
                <template #default="{ row }">{{ formatUsagePercent(row.cpu_percent) }}</template>
              </el-table-column>

              <el-table-column prop="memory_percent" label="Memory %" width="135" align="center" sortable="custom">
                <template #default="{ row }">{{ formatUsagePercent(row.memory_percent) }}</template>
              </el-table-column>

              <el-table-column
                prop="username"
                label="Username"
                min-width="145"
                show-overflow-tooltip
              />

              <el-table-column
                prop="status"
                label="Status"
                width="130"
                align="center"
              />

              <el-table-column
                label="Actions"
                width="180"
                align="center"
                fixed="right"
              >
                <template #default="{ row }">
                  <div class="process-action-buttons">
                    <el-button
                      size="small"
                      link
                      type="primary"
                      @click="openProcessDetail(row.pid)"
                    >
                      Details
                    </el-button>

                    <el-button
                      size="small"
                      link
                      type="danger"
                      @click="killProcess(row.pid, row.name)"
                    >
                      Terminate
                    </el-button>
                  </div>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </el-tab-pane>

        <el-tab-pane
          :label="appTabLabel"
          name="apps"
        >
          <div class="process-table-shell">
            <el-table
              :data="filteredApps"
              :default-sort="appSort"
              @sort-change="onAppSortChange"
              v-loading="appsLoading"
              stripe
              height="100%"
              table-layout="fixed"
            >
              <el-table-column
                prop="pid"
                label="PID"
                width="100"
                align="center"
                sortable="custom"
              />

              <el-table-column
                prop="name"
                label="Name"
                min-width="240"
                sortable="custom"
                show-overflow-tooltip
              />

              <el-table-column prop="cpu_percent" label="CPU %" width="100" align="center" sortable="custom">
                <template #default="{ row }">{{ formatUsagePercent(row.cpu_percent) }}</template>
              </el-table-column>

              <el-table-column prop="memory_percent" label="Memory %" width="135" align="center" sortable="custom">
                <template #default="{ row }">{{ formatUsagePercent(row.memory_percent) }}</template>
              </el-table-column>

              <el-table-column
                prop="status"
                label="Status"
                min-width="160"
                show-overflow-tooltip
              />

              <el-table-column
                label="Actions"
                width="180"
                align="center"
                fixed="right"
              >
                <template #default="{ row }">
                  <div class="process-action-buttons">
                    <el-button
                      size="small"
                      link
                      type="primary"
                      @click="openProcessDetail(row.pid)"
                    >
                      Details
                    </el-button>

                    <el-button
                      size="small"
                      link
                      type="danger"
                      @click="killApp(row.pid, row.name)"
                    >
                      Terminate
                    </el-button>
                  </div>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </el-tab-pane>
      </el-tabs>
    </div>
  </el-dialog>

  <el-dialog
    v-model="processDetailDialogVisible"
    title="Process Details"
    width="980px"
    top="6vh"
    class="fixed-dialog process-detail-dialog"
    modal-class="process-detail-overlay"
    @closed="handleProcessDetailClosed"
  >
    <div
      v-loading="processDetailLoading"
      class="fixed-dialog-body process-detail-body"
    >
      <template v-if="processDetail && !processDetailLoading">
        <section class="process-detail-section">
          <div class="process-detail-section-title">
            Basic Info
          </div>

          <div class="process-detail-basic-grid">
            <div
              v-for="item in processDetailBasicRows"
              :key="item.key"
              class="process-detail-basic-row"
            >
              <div class="process-detail-basic-label">
                {{ item.label }}
              </div>

              <div class="process-detail-basic-value">
                {{ item.value }}
              </div>
            </div>
          </div>
        </section>

        <section class="process-detail-section">
          <div class="process-detail-section-title">
            Command Line
          </div>

          <div class="process-command-line mono">
            {{ processDetailCommandLineText || '-' }}
          </div>
        </section>

        <section class="process-detail-section">
          <div class="process-detail-section-title">
            Network Connections ({{ (processDetail.connections || []).length }})
          </div>

          <div class="process-detail-table-shell">
            <el-table
              :data="processDetail.connections || []"
              stripe
              border
              empty-text="No network connections"
              table-layout="fixed"
            >
              <el-table-column
                prop="local_address"
                label="Local Address"
                min-width="180"
                show-overflow-tooltip
              />

              <el-table-column
                prop="remote_address"
                label="Remote Address"
                min-width="180"
                show-overflow-tooltip
              />

              <el-table-column
                prop="status"
                label="Status"
                width="140"
                align="center"
              />

              <el-table-column
                prop="family"
                label="Family"
                width="180"
                align="center"
              />
            </el-table>
          </div>
        </section>

        <section class="process-detail-section process-open-files-section">
          <div class="process-detail-section-title">
            Open Files ({{ (processDetail.open_files || []).length }})
          </div>

          <div class="process-open-files-list">
            <div
              v-if="!(processDetail.open_files || []).length"
              class="process-open-files-empty"
            >
              No open files
            </div>

            <div
              v-for="(item, index) in visibleOpenFiles"
              :key="`${item.path || 'file'}-${index}`"
              class="process-open-file-row"
              :title="item.path || ''"
            >
              <div class="process-open-file-icon" aria-hidden="true">
                <el-icon><Document /></el-icon>
              </div>

              <div class="process-open-file-path mono">
                {{ item.path || '-' }}
              </div>
            </div>

            <button
              v-if="openFilesHiddenCount > 0 || openFilesExpanded"
              type="button"
              class="process-open-files-toggle"
              @click="openFilesExpanded = !openFilesExpanded"
            >
              {{ openFilesExpanded ? 'Show less' : `Show ${openFilesHiddenCount} more` }}
            </button>
          </div>
        </section>
      </template>
    </div>
  </el-dialog>
</template>

<script>
import { ElMessage, ElMessageBox } from 'element-plus'
import { Document } from '@element-plus/icons-vue'
import { sortProcessRows } from '../utils/processSorting.js'

export default {
  name: 'ProcessDialogs',

  components: { Document },

  props: {
    selectedId: {
      type: [String, Number],
      default: '',
    },
    tabId: {
      type: String,
      default: '',
    },
  },

  data() {
    return {
      processDialogVisible: false,
      processActiveTab: 'processes',
      // 进程数据
      processes: [],
      processesLoading: false,
      processesSnapshotReceived: false,
      // 应用数据
      apps: [],
      appsLoading: false,
      appsSnapshotReceived: false,
      // 过滤
      processFilterText: '',
      processSort: { prop: 'pid', order: 'ascending' },
      appSort: { prop: 'name', order: 'ascending' },
      processMonitorSessionId: '',
      processMonitorStarting: false,
      processMonitorError: '',
      processDetailDialogVisible: false,
      processDetailLoading: false,
      processDetail: null,
      processDetailPid: 0,
      processDetailMonitorSessionId: '',
      processDetailMonitorStarting: false,
      openFilesExpanded: false,
    }
  },

  watch: {
    processActiveTab() {
      if (!this.processDialogVisible) return
      void this.updateProcessMonitorChannel()
    },
    selectedId() {
      if (!this.processDialogVisible) return
      void this.handleSelectedDeviceChanged()
    },
  },

  computed: {
    processManagerVisibleCount() {
      return this.processActiveTab === 'apps'
        ? this.filteredApps.length
        : this.filteredProcesses.length
    },

    processManagerTotalCount() {
      return this.processActiveTab === 'apps'
        ? this.apps.length
        : this.processes.length
    },

    processManagerSummaryText() {
      const liveSuffix = this.processMonitorSessionId ? ' · Live 1s' : ''
      if (this.processActiveTab === 'apps') {
        return `Showing ${this.processManagerVisibleCount} / ${this.processManagerTotalCount} applications${liveSuffix}`
      }

      return `Showing ${this.processManagerVisibleCount} / ${this.processManagerTotalCount} processes${liveSuffix}`
    },

    processTabLabel() {
      return this.processesSnapshotReceived
        ? `All Processes (${this.filteredProcesses.length})`
        : 'All Processes'
    },

    appTabLabel() {
      return this.appsSnapshotReceived
        ? `Applications (${this.filteredApps.length})`
        : 'Applications'
    },

    filteredProcesses() {
      if (!this.processes.length) return []
      if (!this.processFilterText) return sortProcessRows(this.processes, this.processSort)

      const kw = this.processFilterText.toLowerCase()
      return sortProcessRows(this.processes.filter(p =>
        String(p.pid).includes(kw) ||
        String(p.ppid ?? '').includes(kw) ||
        (p.name || '').toLowerCase().includes(kw) ||
        (p.username || '').toLowerCase().includes(kw)
      ), this.processSort)
    },

    filteredApps() {
      if (!this.apps.length) return []
      if (!this.processFilterText) return sortProcessRows(this.apps, this.appSort)

      const kw = this.processFilterText.toLowerCase()
      return sortProcessRows(this.apps.filter(a =>
        String(a.pid).includes(kw) ||
        (a.name || '').toLowerCase().includes(kw) ||
        (a.username || '').toLowerCase().includes(kw)
      ), this.appSort)
    },

    processDetailBasicRows() {
      const detail = this.processDetail || {}
      const fieldMap = [
        ['pid', 'PID'],
        ['name', 'Name'],
        ['username', 'User'],
        ['status', 'Status'],
        ['ppid', 'Parent PID'],
        ['exe', 'Executable Path'],
        ['cwd', 'Working Directory'],
        ['create_time', 'Create Time'],
        ['cpu_percent', 'CPU %'],
        ['memory_percent', 'Memory %'],
        ['num_threads', 'Threads'],
        ['num_fds', 'FD Count'],
        ['num_handles', 'Handle Count'],
      ]

      return fieldMap
        .filter(([key]) => detail[key] !== undefined && detail[key] !== null && detail[key] !== '')
        .map(([key, label]) => ({ key, label, value: this.formatProcessDetailValue(detail[key]) }))
    },

    processDetailCommandLineText() {
      const cmdline = (this.processDetail && this.processDetail.cmdline) || []
      if (!Array.isArray(cmdline) || !cmdline.length) return ''
      return cmdline.join(' ')
    },

    visibleOpenFiles() {
      const items = (this.processDetail && this.processDetail.open_files) || []
      if (!Array.isArray(items)) return []
      return this.openFilesExpanded ? items : items.slice(0, 10)
    },

    openFilesHiddenCount() {
      const items = (this.processDetail && this.processDetail.open_files) || []
      if (!Array.isArray(items) || this.openFilesExpanded) return 0
      return Math.max(0, items.length - 10)
    },
  },

  mounted() {
    window.addEventListener('pagehide', this.handleProcessMonitorPageHide)
  },

  beforeUnmount() {
    window.removeEventListener('pagehide', this.handleProcessMonitorPageHide)
    void this.stopProcessMonitor()
    void this.stopProcessDetailMonitor()
  },

  methods: {
    formatUsagePercent(value) {
      return value === null || value === undefined || !Number.isFinite(Number(value))
        ? '-'
        : `${Number(value).toFixed(1)}%`
    },

    onProcessSortChange({ prop, order }) {
      this.processSort = { prop: prop || 'pid', order: order || 'ascending' }
    },

    onAppSortChange({ prop, order }) {
      this.appSort = { prop: prop || 'name', order: order || 'ascending' }
    },

    open(sortBy = '') {
      if (!this.selectedId) {
        ElMessage.warning('Please select a device first')
        return
      }

      if (sortBy === 'cpu_percent' || sortBy === 'memory_percent') {
        this.processActiveTab = 'processes'
        this.processSort = { prop: sortBy, order: 'descending' }
      }
      this.processDialogVisible = true
      if (sortBy === 'cpu_percent' || sortBy === 'memory_percent') {
        this.$nextTick(() => this.$refs.processTable?.sort(sortBy, 'descending'))
      }
      this.processes = []
      this.apps = []
      this.processesSnapshotReceived = false
      this.appsSnapshotReceived = false
      this.processDetail = null
      this.processFilterText = ''
      void this.startProcessMonitor()
    },

    handleProcessDialogClosed() {
      // A previous close transition must not stop a newly reopened dialog.
      if (this.processDialogVisible) return
      void this.stopProcessMonitor()
    },

    handleProcessMonitorPageHide() {
      void this.stopProcessMonitor(true)
      void this.stopProcessDetailMonitor(true)
    },

    async handleSelectedDeviceChanged() {
      await this.stopProcessDetailMonitor()
      await this.stopProcessMonitor()
      this.processDetailDialogVisible = false
      this.processDetail = null
      this.processDetailPid = 0
      this.processes = []
      this.apps = []
      this.processesSnapshotReceived = false
      this.appsSnapshotReceived = false
      if (this.selectedId) await this.startProcessMonitor()
    },

    async refreshProcessManager() {
      await this.restartProcessMonitor()
    },

    getMonitorHeaders(extra = {}) {
      const headers = { ...extra }
      if (this.tabId) headers['X-Tab-Id'] = this.tabId
      return headers
    },

    processMonitorChannel() {
      return this.processActiveTab === 'apps' ? 'apps' : 'processes'
    },

    async startProcessMonitor() {
      if (!this.processDialogVisible || !this.selectedId) return
      if (this.processMonitorSessionId || this.processMonitorStarting) return

      const channel = this.processMonitorChannel()
      this.processMonitorStarting = true
      this.processMonitorError = ''
      if (channel === 'apps') this.appsLoading = true
      else this.processesLoading = true

      try {
        const res = await fetch(
          `/api/connections/${encodeURIComponent(this.selectedId)}/device-monitor/open`,
          {
            method: 'POST',
            headers: this.getMonitorHeaders({ 'Content-Type': 'application/json' }),
            body: JSON.stringify({
              channels: [channel],
              intervals: { [channel]: 1 },
            }),
          },
        )
        const json = await res.json()
        if (!res.ok || json.code !== 0) {
          throw new Error(json.message || 'Failed to open process monitor')
        }

        const sessionId = String(json.data?.monitor_session_id || '').trim()
        if (!sessionId) throw new Error('Process monitor did not return a session id')
        this.processMonitorSessionId = sessionId

        if (!this.processDialogVisible) {
          await this.stopProcessMonitor()
        } else if (this.processMonitorChannel() !== channel) {
          await this.updateProcessMonitorChannel()
        }
      } catch (e) {
        this.processMonitorError = e?.message || 'Failed to open process monitor'
        this.processesLoading = false
        this.appsLoading = false
        ElMessage.error(this.processMonitorError)
      } finally {
        this.processMonitorStarting = false
      }
    },

    async updateProcessMonitorChannel() {
      const channel = this.processMonitorChannel()
      if (channel === 'apps') this.appsLoading = true
      else this.processesLoading = true

      const sessionId = String(this.processMonitorSessionId || '').trim()
      if (!sessionId) {
        await this.startProcessMonitor()
        return
      }

      try {
        const res = await fetch(`/api/device-monitor/${encodeURIComponent(sessionId)}/config`, {
          method: 'POST',
          headers: this.getMonitorHeaders({ 'Content-Type': 'application/json' }),
          body: JSON.stringify({
            channels: [channel],
            intervals: { [channel]: 1 },
          }),
        })
        const json = await res.json()
        if (!res.ok || json.code !== 0) {
          throw new Error(json.message || 'Failed to update process monitor')
        }
      } catch (e) {
        this.processMonitorError = e?.message || 'Failed to update process monitor'
        if (channel === 'apps') this.appsLoading = false
        else this.processesLoading = false
        ElMessage.error(this.processMonitorError)
      }
    },

    async stopProcessMonitor(keepalive = false) {
      const sessionId = String(this.processMonitorSessionId || '').trim()
      this.processMonitorSessionId = ''
      this.processMonitorStarting = false
      if (!sessionId) return

      try {
        await fetch(`/api/device-monitor/${encodeURIComponent(sessionId)}/close`, {
          method: 'POST',
          headers: this.getMonitorHeaders(),
          keepalive: Boolean(keepalive),
        })
      } catch (_e) {
      }
    },

    async restartProcessMonitor() {
      await this.stopProcessMonitor()
      await this.startProcessMonitor()
    },

    async openProcessDetail(pid) {
      // if (!this.selectedId || !pid) return;
      if (!this.selectedId || !pid) return
      await this.stopProcessDetailMonitor()
      this.processDetailDialogVisible = true
      this.processDetailLoading = true
      this.openFilesExpanded = false
      this.processDetailPid = Number(pid) || 0
      this.processDetail = {
        pid: this.processDetailPid,
        connections: [],
        open_files: [],
      }
      await this.startProcessDetailMonitor(this.processDetailPid)
    },

    handleProcessDetailClosed() {
      void this.stopProcessDetailMonitor()
      this.processDetail = null
      this.processDetailPid = 0
      this.processDetailLoading = false
      this.openFilesExpanded = false
    },

    async startProcessDetailMonitor(pid) {
      if (!this.selectedId || !pid || this.processDetailMonitorStarting) return
      this.processDetailMonitorStarting = true

      try {
        const res = await fetch(
          `/api/connections/${encodeURIComponent(this.selectedId)}/device-monitor/open`,
          {
            method: 'POST',
            headers: this.getMonitorHeaders({ 'Content-Type': 'application/json' }),
            body: JSON.stringify({
              channels: ['process_detail', 'process_connections', 'process_open_files'],
              intervals: {
                process_detail: 1,
                process_connections: 2,
                process_open_files: 3,
              },
              options: { pid: Number(pid) },
            }),
          },
        )
        const json = await res.json()
        if (!res.ok || json.code !== 0) {
          throw new Error(json.message || 'Failed to open process detail monitor')
        }

        const sessionId = String(json.data?.monitor_session_id || '').trim()
        if (!sessionId) throw new Error('Process detail monitor did not return a session id')
        this.processDetailMonitorSessionId = sessionId

        if (!this.processDetailDialogVisible) {
          await this.stopProcessDetailMonitor()
        }
      } catch (e) {
        ElMessage.error(e?.message || 'Failed to load process detail')
        this.processDetailLoading = false
        this.processDetailDialogVisible = false
      } finally {
        this.processDetailMonitorStarting = false
      }
    },

    async stopProcessDetailMonitor(keepalive = false) {
      const sessionId = String(this.processDetailMonitorSessionId || '').trim()
      this.processDetailMonitorSessionId = ''
      this.processDetailMonitorStarting = false
      if (!sessionId) return

      try {
        await fetch(`/api/device-monitor/${encodeURIComponent(sessionId)}/close`, {
          method: 'POST',
          headers: this.getMonitorHeaders(),
          keepalive: Boolean(keepalive),
        })
      } catch (_e) {
      }
    },

    handleDeviceMonitorSnapshot(payload = {}) {
      if (String(payload.client_id || '') !== String(this.selectedId || '')) return
      const sessionId = String(payload.monitor_session_id || '')
      const channel = String(payload.channel || '').trim().toLowerCase()
      const data = payload.data && typeof payload.data === 'object' ? payload.data : {}

      if (sessionId === String(this.processMonitorSessionId || '')) {
        if (channel === 'processes') {
          this.processes = Array.isArray(data.items) ? data.items : []
          this.processesSnapshotReceived = true
          this.processesLoading = false
        } else if (channel === 'apps') {
          this.apps = Array.isArray(data.items) ? data.items : []
          this.appsSnapshotReceived = true
          this.appsLoading = false
        }

        const errorText = String(data.error || '').trim()
        if (errorText && errorText !== this.processMonitorError) {
          this.processMonitorError = errorText
          ElMessage.error(errorText)
        } else if (!errorText) {
          this.processMonitorError = ''
        }
        return
      }

      if (sessionId !== String(this.processDetailMonitorSessionId || '')) return
      if (!this.processDetailDialogVisible) return

      if (channel === 'process_detail') {
        this.processDetail = {
          ...(this.processDetail || {}),
          ...data,
        }
        this.processDetailLoading = false
        return
      }

      if (Number(data.pid || 0) !== Number(this.processDetailPid || 0)) return
      if (channel === 'process_connections') {
        this.processDetail = {
          ...(this.processDetail || {}),
          connections: Array.isArray(data.items) ? data.items : [],
        }
      } else if (channel === 'process_open_files') {
        this.processDetail = {
          ...(this.processDetail || {}),
          open_files: Array.isArray(data.items) ? data.items : [],
        }
      }
    },

    handleDeviceMonitorStatus(payload = {}) {
      const sessionId = String(payload.monitor_session_id || '')
      const state = String(payload.state || payload.status || '').trim().toLowerCase()

      if (sessionId === String(this.processMonitorSessionId || '')) {
        if (state === 'error') {
          const message = String(payload.error || 'Process monitor failed')
          this.processMonitorError = message
          this.processesLoading = false
          this.appsLoading = false
          ElMessage.error(message)
        } else if (state === 'closed') {
          this.processMonitorSessionId = ''
        }
        return
      }

      if (sessionId !== String(this.processDetailMonitorSessionId || '')) return
      if (state === 'error') {
        ElMessage.error(String(payload.error || 'Process detail monitor failed'))
        this.processDetailLoading = false
        this.processDetailDialogVisible = false
      } else if (state === 'closed') {
        this.processDetailMonitorSessionId = ''
      }
    },

    formatProcessDetailValue(value) {
      if (value === null || value === undefined || value === '') return '-'
      if (typeof value === 'number') return String(value)
      return String(value)
    },

    async killProcess(pid, name) {
      try {
        await ElMessageBox.confirm(
          `Terminate process "${name}" (PID: ${pid})?`,
          'Terminate Process',
          {
            type: 'warning',
            confirmButtonText: 'Terminate',
            cancelButtonText: 'Cancel',
          }
        )

        const res = await fetch(`/api/connections/${encodeURIComponent(this.selectedId)}/processes/${encodeURIComponent(pid)}/kill`, { method: 'POST' })
        const json = await res.json()
        if (res.ok && json.code === 0) {
          ElMessage.success(`Process "${name}" (PID: ${pid}) terminated`)
          this.processes = this.processes.filter(item => Number(item.pid) !== Number(pid))
          this.apps = this.apps.filter(item => Number(item.pid) !== Number(pid))
          if (Number(this.processDetailPid) === Number(pid)) {
            this.processDetailDialogVisible = false
          }
        } else {
          throw new Error(json.message)
        }
      } catch (e) {
        if (e !== 'cancel') ElMessage.error(`Unable to terminate process: ${e.message || 'Unknown error'}`)
      }
    },

    async killApp(pid, name) {
      try {
        await ElMessageBox.confirm(
          `Terminate application "${name}" (PID: ${pid})?`,
          'Terminate Application',
          {
            type: 'warning',
            confirmButtonText: 'Terminate',
            cancelButtonText: 'Cancel',
          }
        )

        const res = await fetch(`/api/connections/${encodeURIComponent(this.selectedId)}/apps/${encodeURIComponent(pid)}/kill`, { method: 'POST' })
        const json = await res.json()
        if (res.ok && json.code === 0) {
          ElMessage.success(`Application "${name}" (PID: ${pid}) terminated`)
          this.apps = this.apps.filter(item => Number(item.pid) !== Number(pid))
          this.processes = this.processes.filter(item => Number(item.pid) !== Number(pid))
          if (Number(this.processDetailPid) === Number(pid)) {
            this.processDetailDialogVisible = false
          }
        } else {
          throw new Error(json.message)
        }
      } catch (e) {
        if (e !== 'cancel') ElMessage.error(`Unable to terminate application: ${e.message || 'Unknown error'}`)
      }
    },
  },
}
</script>

<style scoped>


.process-dialog-filter-input :deep(.el-input__wrapper) {
  min-height: 32px;
  height: 32px;
  border-radius: 10px;
}


.process-dialog-body {
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
  width: 100%;
  height: 100%;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  box-sizing: border-box;
}

.process-toolbar {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  min-width: 0;
  gap: 12px;
  margin-bottom: 12px;
  box-sizing: border-box;
}

.process-toolbar :deep(.el-button.toolbar-btn) {
  height: 32px;
  min-height: 32px;
  padding: 0 12px;
  border-radius: 10px;
  margin: 0;
}

.process-toolbar-left,
.process-toolbar-right {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}

.process-toolbar-left {
  flex: 1 1 auto;
}

.process-toolbar-right {
  flex: 0 0 auto;
  justify-content: flex-end;
  margin-left: auto;
}

.process-count {
  font-size: 13px;
  color: #666;
  white-space: nowrap;
}

.process-dialog-filter-input {
  width: 280px;
  max-width: 100%;
}

.process-tabs {
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
  width: 100%;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}

.process-tabs :deep(.el-tabs__header) {
  flex: 0 0 auto;
  width: 100%;
  margin-bottom: 12px;
}

.process-tabs :deep(.el-tabs__content) {
  display: flex;
  flex: 1 1 auto;
  width: 100%;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}

.process-tabs :deep(.el-tab-pane) {
  flex: 1 1 auto;
  width: 100%;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}

.process-table-shell {
  width: 100%;
  height: 100%;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}

.process-table-shell :deep(.el-table) {
  width: 100% !important;
  height: 100% !important;
}

.process-table-shell :deep(.el-table__inner-wrapper),
.process-table-shell :deep(.el-table__body-wrapper) {
  min-height: 0;
}

.process-action-buttons {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  flex-wrap: nowrap;
}

.process-action-buttons :deep(.el-button) {
  margin: 0;
}

.process-detail-body {
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
  width: 100%;
  min-width: 0;
  min-height: 0;
  overflow-y: auto;
  overflow-x: hidden;
  padding-right: 4px;
  box-sizing: border-box;
}

.process-detail-section {
  flex: 0 0 auto;
  margin-bottom: 18px;
}

.process-detail-section:last-child {
  margin-bottom: 0;
}

.process-detail-section-title {
  margin-bottom: 10px;
  font-size: 14px;
  font-weight: 600;
  color: var(--text);
}

.process-detail-basic-grid {
  display: flex;
  flex-direction: column;
}

.process-detail-basic-row {
  display: grid;
  grid-template-columns: 180px minmax(0, 1fr);
  gap: 12px;
  padding: 8px 0;
  border-bottom: 1px solid #ebeef5;
}

.process-detail-basic-label {
  color: #606266;
  font-weight: 500;
}

.process-detail-basic-value {
  min-width: 0;
  word-break: break-word;
}

.process-command-line {
  padding: 10px 12px;
  border-radius: 8px;
  background: #f5f7fa;
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}

.process-detail-table-shell {
  width: 100%;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}

.process-detail-table-shell :deep(.el-table) {
  width: 100% !important;
}

.process-open-files-list {
  border: 1px solid #e4e7ed;
  border-radius: 10px;
  background: #fff;
  overflow: hidden;
}

.process-open-files-empty {
  padding: 18px 16px;
  color: #909399;
  text-align: center;
  font-size: 13px;
}

.process-open-file-row {
  display: grid;
  grid-template-columns: 24px minmax(0, 1fr);
  align-items: center;
  gap: 8px;
  min-width: 0;
  padding: 8px 12px;
  border-bottom: 1px solid #f0f2f5;
  transition: background-color 0.16s ease, color 0.16s ease;
}

.process-open-file-row:hover {
  background: #f7f9fc;
}

.process-open-file-row:last-of-type {
  border-bottom: 0;
}

.process-open-file-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  color: #a3adbd;
  font-size: 14px;
}

.process-open-file-path {
  min-width: 0;
  overflow: hidden;
  color: #4b5565;
  font-size: 12px;
  line-height: 1.45;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.process-open-file-row:hover .process-open-file-path {
  color: #303846;
}

.process-open-files-toggle {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  min-height: 34px;
  padding: 7px 12px;
  border: 0;
  border-top: 1px solid #f0f2f5;
  background: #fff;
  color: var(--el-color-primary);
  font: inherit;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: background-color 0.16s ease;
}

.process-open-files-toggle:hover {
  background: #f7f9fc;
}

.process-open-files-toggle:focus-visible {
  outline: 2px solid var(--el-color-primary-light-5);
  outline-offset: -2px;
}

@media (max-width: 768px) {
  .process-toolbar {
    align-items: stretch;
    flex-direction: column;
  }

  .process-toolbar-left,
  .process-toolbar-right,
  .process-dialog-filter-input {
    width: 100%;
  }

  .process-toolbar-left {
    flex-wrap: wrap;
  }

  .process-toolbar-right {
    justify-content: flex-start;
    margin-left: 0;
  }

  .process-detail-basic-row {
    grid-template-columns: 1fr;
    gap: 4px;
  }
}
</style>

<style>
/* ProcessDialogs: 固定弹窗高度，表格内部滚动，避免内容把页面撑长。 */
.process-overlay .el-dialog {
  height: 78vh !important;
  max-height: 78vh !important;
  display: flex !important;
  flex-direction: column !important;
  overflow: hidden !important;
}

.process-overlay .el-dialog__header {
  flex: 0 0 auto !important;
}

.process-overlay .el-dialog__body {
  display: flex !important;
  flex: 1 1 auto !important;
  width: 100% !important;
  min-width: 0 !important;
  min-height: 0 !important;
  overflow: hidden !important;
  box-sizing: border-box !important;
}

.process-overlay .process-dialog-body {
  flex: 1 1 auto !important;
  width: 100% !important;
  min-height: 0 !important;
}

.process-overlay .el-table {
  width: 100% !important;
}

.process-overlay .el-table__body-wrapper {
  overflow-y: auto !important;
}

.process-detail-overlay .el-dialog {
  height: 78vh !important;
  max-height: 78vh !important;
  display: flex !important;
  flex-direction: column !important;
  overflow: hidden !important;
}

.process-detail-overlay .el-dialog__header {
  flex: 0 0 auto !important;
}

.process-detail-overlay .el-dialog__body {
  display: flex !important;
  flex: 1 1 auto !important;
  width: 100% !important;
  min-width: 0 !important;
  min-height: 0 !important;
  overflow: hidden !important;
  box-sizing: border-box !important;
}

.process-detail-overlay .process-detail-body {
  flex: 1 1 auto !important;
  width: 100% !important;
  min-height: 0 !important;
}

@media (max-width: 768px) {
  .process-overlay .el-dialog,
  .process-detail-overlay .el-dialog {
    width: 100vw !important;
    max-width: 100vw !important;
    height: 100dvh !important;
    max-height: 100dvh !important;
    margin: 0 !important;
    border-radius: 0 !important;
  }

  .process-overlay .el-dialog__header,
  .process-detail-overlay .el-dialog__header {
    padding: 14px 16px 10px !important;
  }

  .process-overlay .el-dialog__body,
  .process-detail-overlay .el-dialog__body {
    padding: 10px 12px 12px !important;
  }
}
</style>