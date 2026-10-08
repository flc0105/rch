<template>
  <section class="watchdog-panel">
    <div class="watchdog-panel-scroll">
      <header class="watchdog-heading">
        <div>
          <div class="watchdog-eyebrow">AGENT SUPERVISION</div>
          <h3>Watchdog</h3>
          <p>Health and recovery controls for this connection</p>
        </div>
        <el-button :loading="loading" :disabled="!clientId" size="small" @click="loadStatus">
          Refresh
        </el-button>
      </header>

      <div v-if="loading && !status" class="watchdog-loading">
        <el-skeleton :rows="5" animated />
      </div>
      <div v-else-if="error" class="watchdog-unavailable">
        <strong>Status unavailable</strong>
        <span>{{ error }}</span>
        <el-button size="small" @click="loadStatus">Try again</el-button>
      </div>
      <template v-else-if="status">
        <div class="watchdog-hero" :class="`watchdog-hero-${healthTone}`">
          <span class="watchdog-state-dot" aria-hidden="true"></span>
          <div class="watchdog-hero-copy">
            <strong>{{ healthTitle }}</strong>
            <span>{{ healthSubtitle }}</span>
          </div>
          <div class="watchdog-worker-meta">
            <span>Supervisor process</span>
            <strong>{{ status.watchdog_pid ?? '—' }}</strong>
          </div>
        </div>

        <div class="watchdog-modes">
          <article class="watchdog-mode-card">
            <div class="watchdog-card-head">
              <div>
                <h4>Remote control</h4>
                <p>Responds to HTTP management commands</p>
              </div>
              <span class="watchdog-state-tag" :class="{ 'is-on': status.remote_enabled }">
                {{ status.remote_enabled ? 'Enabled' : 'Disabled' }}
              </span>
            </div>
            <div class="watchdog-card-stats">
              <div>
                <span>Check interval</span>
                <strong>{{ duration(status.remote_interval_s) }}</strong>
              </div>
              <div>
                <span>Supervisor</span>
                <strong>{{ workerStatus }}</strong>
              </div>
            </div>
          </article>

          <article class="watchdog-mode-card">
            <div class="watchdog-card-head">
              <div>
                <h4>Local recovery</h4>
                <p>Monitors agent heartbeats on this device</p>
              </div>
              <span class="watchdog-state-tag" :class="{ 'is-on': status.local_enabled }">
                {{ status.local_enabled ? 'Enabled' : 'Disabled' }}
              </span>
            </div>
            <div class="watchdog-card-stats">
              <div>
                <span>Heartbeat</span>
                <strong>{{ duration(status.local_heartbeat_interval_s) }}</strong>
              </div>
              <div>
                <span>Timeout</span>
                <strong>{{ duration(status.local_timeout_s) }}</strong>
              </div>
            </div>
            <p v-if="status.local_enabled" class="watchdog-feeder">
              Heartbeat sender: {{ status.local_feeder_alive ? 'Active' : 'Not running' }}
              <span v-if="status.local_feeder_thread">· {{ status.local_feeder_thread }}</span>
            </p>
          </article>
        </div>

        <div class="watchdog-details">
          <div class="watchdog-details-top">
            <span>Agent process</span>
            <strong>{{ status.main_pid ?? '—' }}</strong>
          </div>
          <el-collapse v-model="expandedSections" class="watchdog-diagnostics">
            <el-collapse-item title="Connection & diagnostic paths" name="paths">
              <div class="watchdog-path-list">
                <div v-if="status.remote_control_url">
                  <span>Control endpoint (agent-side)</span>
                  <code>{{ status.remote_control_url }}</code>
                </div>
                <div v-if="status.remote_log">
                  <span>Remote activity log</span>
                  <code>{{ status.remote_log }}</code>
                </div>
                <div v-if="status.local_heartbeat_file">
                  <span>Local heartbeat file</span>
                  <code>{{ status.local_heartbeat_file }}</code>
                </div>
                <div v-if="status.local_log">
                  <span>Local activity log</span>
                  <code>{{ status.local_log }}</code>
                </div>
              </div>
            </el-collapse-item>
          </el-collapse>
        </div>
      </template>
    </div>

    <footer class="watchdog-toolbar">
      <div class="watchdog-toolbar-title">
        <strong>HTTP control</strong>
        <span>{{ actionHint }}</span>
      </div>
      <div v-if="actionsLoading" class="watchdog-actions-loading">Loading actions…</div>
      <div v-else-if="actionsError" class="watchdog-actions-error">
        {{ actionsError }}
        <el-button link type="primary" size="small" @click="loadActions">Retry</el-button>
      </div>
      <div v-else-if="actions.length" class="watchdog-action-buttons">
        <el-tooltip
          v-for="action in actions"
          :key="action.action"
          :content="action.description || action.label"
          placement="top"
        >
          <span class="watchdog-action-holder">
            <el-button
              :type="action.action === 'kill' ? 'danger' : 'default'"
              :disabled="!canControl || !!pendingAction"
              :loading="pendingAction === action.action"
              size="small"
              @click="confirmAction(action)"
            >
              {{ action.label || action.action }}
            </el-button>
          </span>
        </el-tooltip>
      </div>
      <span v-else class="watchdog-actions-empty">No control actions available</span>
    </footer>
  </section>
</template>

<script>
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  getWatchdogStatus,
  getHttpControlActions,
  queueHttpControlAction,
} from '../api/connectionsApi.js'

export default {
  name: 'WatchdogInfoPanel',
  props: {
    clientId: { type: [String, Number], default: '' },
    currentConnection: { type: Object, default: null },
  },
  data() {
    return {
      status: null,
      loading: false,
      error: '',
      actions: [],
      actionsLoading: false,
      actionsError: '',
      pendingAction: '',
      expandedSections: [],
    }
  },
  computed: {
    enabled() {
      return Boolean(this.status?.remote_enabled || this.status?.local_enabled)
    },
    workerStatus() {
      return this.status?.watchdog_alive ? 'Running' : 'Stopped'
    },
    healthTone() {
      if (!this.enabled) return 'off'
      return this.status?.watchdog_alive ? 'healthy' : 'warning'
    },
    healthTitle() {
      if (!this.enabled) return 'Watchdog is disabled'
      return this.status?.watchdog_alive ? 'Supervisor is running' : 'Supervisor is not running'
    },
    healthSubtitle() {
      if (!this.enabled) return 'Both remote control and local recovery are turned off.'
      if (!this.status?.watchdog_alive) return 'A watchdog mode is enabled, but its supervisor process is unavailable.'
      if (this.status.remote_enabled && this.status.local_enabled) return 'Remote control and local recovery are enabled.'
      return this.status.remote_enabled ? 'Remote control is enabled.' : 'Local recovery is enabled.'
    },
    connectionOffline() {
      return this.currentConnection?.connection_state === 'offline' || Boolean(this.currentConnection?.disconnected_at)
    },
    canControl() {
      return !this.connectionOffline && !this.loading && !this.error &&
        Boolean(this.status?.remote_enabled && this.status?.watchdog_alive)
    },
    actionHint() {
      if (this.connectionOffline) return 'Agent is offline'
      if (!this.status || this.error) return 'Status required before sending commands'
      if (!this.status.remote_enabled) return 'Enable remote watchdog to use these actions'
      if (!this.status.watchdog_alive) return 'Supervisor is not running'
      return 'Commands are delivered through the remote watchdog'
    },
  },
  mounted() {
    void this.loadStatus()
    void this.loadActions()
  },
  methods: {
    duration(value) {
      return value == null || !Number.isFinite(Number(value)) ? '—' : `${value} s`
    },
    async loadStatus() {
      if (!this.clientId || this.loading) return
      this.loading = true
      this.error = ''
      this.status = null
      const requestedId = this.clientId
      try {
        const data = await getWatchdogStatus(requestedId)
        if (requestedId !== this.clientId) return
        if (!data || typeof data !== 'object' || Array.isArray(data) || !('watchdog_alive' in data)) {
          throw new Error('Invalid watchdog status response')
        }
        this.status = data
      } catch (error) {
        if (requestedId === this.clientId) this.error = error.message || 'Could not fetch watchdog status'
      } finally {
        this.loading = false
      }
    },
    async loadActions() {
      this.actionsLoading = true
      this.actionsError = ''
      try {
        const data = await getHttpControlActions()
        if (!Array.isArray(data)) throw new Error('Invalid control action response')
        this.actions = data.filter(item => item && typeof item.action === 'string' && item.action)
      } catch (error) {
        this.actions = []
        this.actionsError = error.message || 'Could not load actions'
      } finally {
        this.actionsLoading = false
      }
    },
    async confirmAction(action) {
      if (!this.canControl || this.pendingAction) return
      const clientId = this.clientId
      try {
        await ElMessageBox.confirm(
          `${action.description || `Run ${action.label || action.action}?`}\n\nTarget: ${this.currentConnection?.hostname || clientId}`,
          `Confirm ${action.label || action.action}`,
          {
            type: 'warning',
            confirmButtonText: `Run ${action.label || action.action}`,
            cancelButtonText: 'Cancel',
            distinguishCancelAndClose: true,
          },
        )
      } catch {
        return
      }
      if (clientId !== this.clientId || !this.canControl || this.pendingAction) return
      this.pendingAction = action.action
      try {
        await queueHttpControlAction(clientId, action.action)
        ElMessage.success(`${action.label || action.action} queued for remote watchdog`)
      } catch (error) {
        ElMessage.error(error.message || 'Could not queue control action')
      } finally {
        this.pendingAction = ''
      }
    },
  },
}
</script>

<style scoped>
.watchdog-panel { height: 100%; min-height: 0; display: flex; flex-direction: column; color: var(--text); }
.watchdog-panel-scroll { flex: 1; min-height: 0; overflow-y: auto; padding: 2px 4px 18px 0; }
.watchdog-heading { display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; margin-bottom: 18px; }
.watchdog-eyebrow { color: #8a96a8; font-size: 10px; font-weight: 700; letter-spacing: .12em; }
.watchdog-heading h3 { font-size: 20px; margin: 3px 0 4px; font-weight: 700; }
.watchdog-heading p, .watchdog-card-head p { margin: 0; color: var(--muted); font-size: 12px; }
.watchdog-loading { padding: 18px; }
.watchdog-unavailable { padding: 28px 16px; border: 1px dashed #cbd5e1; border-radius: 12px; display: flex; flex-direction: column; gap: 10px; align-items: flex-start; }
.watchdog-unavailable span { color: var(--muted); font-size: 12px; overflow-wrap: anywhere; }
.watchdog-hero { display: flex; align-items: center; gap: 14px; padding: 18px; background: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 14px; margin-bottom: 14px; }
.watchdog-hero-off { background: #f8fafc; border-color: #e2e8f0; }
.watchdog-hero-warning { background: #fffbeb; border-color: #fde68a; }
.watchdog-state-dot { width: 11px; height: 11px; border-radius: 50%; flex: 0 0 auto; background: #16a34a; box-shadow: 0 0 0 4px rgba(22,163,74,.12); }
.watchdog-hero-off .watchdog-state-dot { background: #94a3b8; box-shadow: 0 0 0 4px rgba(148,163,184,.12); }
.watchdog-hero-warning .watchdog-state-dot { background: #d97706; box-shadow: 0 0 0 4px rgba(217,119,6,.12); }
.watchdog-hero-copy { flex: 1 1 auto; min-width: 0; display: flex; flex-direction: column; gap: 4px; }
.watchdog-hero-copy strong { font-size: 15px; }
.watchdog-hero-copy span { font-size: 12px; color: #64748b; line-height: 1.45; }
.watchdog-worker-meta { display: flex; flex-direction: column; gap: 3px; align-items: flex-end; flex: 0 0 auto; }
.watchdog-worker-meta span { font-size: 11px; color: #64748b; }
.watchdog-worker-meta strong { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 14px; }
.watchdog-modes { display: grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap: 14px; }
.watchdog-mode-card { border: 1px solid rgba(15,23,42,.08); border-radius: 14px; padding: 18px; background: #fff; min-width: 0; }
.watchdog-card-head { display: flex; justify-content: space-between; gap: 10px; min-height: 52px; }
.watchdog-card-head h4 { font-size: 14px; margin: 0 0 6px; }
.watchdog-card-head p { line-height: 1.4; }
.watchdog-state-tag { background: #f1f5f9; color: #64748b; padding: 3px 9px; border-radius: 999px; font-size: 11px; height: fit-content; white-space: nowrap; }
.watchdog-state-tag.is-on { background: #dcfce7; color: #15803d; }
.watchdog-card-stats { margin-top: 18px; display: flex; gap: 14px; border-top: 1px solid #f1f5f9; padding-top: 13px; }
.watchdog-card-stats > div { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 4px; }
.watchdog-card-stats span { color: #64748b; font-size: 11px; }
.watchdog-card-stats strong { font-size: 13px; font-weight: 600; }
.watchdog-feeder { color: #64748b; font-size: 11px; margin: 12px 0 0; overflow-wrap: anywhere; }
.watchdog-details { margin-top: 14px; border: 1px solid rgba(15,23,42,.07); border-radius: 12px; background: #f8fafc; padding: 0 16px; }
.watchdog-details-top { display: flex; justify-content: space-between; align-items: center; padding: 13px 0; font-size: 12px; color: #64748b; }
.watchdog-details-top strong { color: var(--text); font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 13px; }
.watchdog-diagnostics { --el-collapse-border-color: #e2e8f0; }
.watchdog-diagnostics :deep(.el-collapse-item__header), .watchdog-diagnostics :deep(.el-collapse-item__wrap) { background: transparent; }
.watchdog-diagnostics :deep(.el-collapse-item__header) { color: #64748b; font-size: 12px; height: 37px; }
.watchdog-path-list { display: flex; flex-direction: column; gap: 12px; padding: 2px 0 12px; }
.watchdog-path-list > div { min-width: 0; display: flex; flex-direction: column; gap: 4px; }
.watchdog-path-list span { color: #64748b; font-size: 11px; }
.watchdog-path-list code { display: block; color: var(--text); font-size: 11px; line-height: 1.5; white-space: normal; overflow-wrap: anywhere; user-select: text; }
.watchdog-toolbar { border-top: 1px solid rgba(15,23,42,.1); padding: 13px 0 2px; flex: 0 0 auto; display: flex; justify-content: space-between; align-items: center; gap: 12px; }
.watchdog-toolbar-title { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
.watchdog-toolbar-title strong { font-size: 13px; }
.watchdog-toolbar-title span, .watchdog-actions-loading, .watchdog-actions-error, .watchdog-actions-empty { font-size: 11px; color: #64748b; }
.watchdog-action-buttons { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; justify-content: flex-end; }
.watchdog-action-holder { display: inline-flex; }
.watchdog-actions-error { display: flex; align-items: center; gap: 8px; }
@media (max-width: 680px) {
  .watchdog-modes { grid-template-columns: 1fr; }
  .watchdog-toolbar { align-items: flex-start; flex-direction: column; }
  .watchdog-action-buttons { justify-content: flex-start; }
  .watchdog-hero { flex-wrap: wrap; }
}
</style>
