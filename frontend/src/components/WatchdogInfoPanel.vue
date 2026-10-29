<template>
  <section class="watchdog-panel">
    <div class="watchdog-panel-scroll">
      <header class="watchdog-heading">
        <div>
          <h3>Watchdog</h3>
          <p>Health and recovery controls for this connection</p>
        </div>
        <el-button :loading="loading" :disabled="!clientId" size="small" @click="loadStatus">
          Refresh
        </el-button>
      </header>

      <div v-if="!watchdogSupported" class="watchdog-policy-note">
        Watchdog is unavailable on this Client. The Client can be restarted with the watchdog capability enabled on supported platforms.
      </div>

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
            <span>{{ launchdManaged ? 'Lifecycle manager' : (status.process_recovery_watchdog.enabled && !sharedWorkerEnabled ? 'Process Recovery Watchdog supervisor' : 'Supervisor process') }}</span>
            <strong>{{ launchdManaged ? 'launchd' : ((status.process_recovery_watchdog.enabled && !sharedWorkerEnabled ? status.process_recovery_watchdog.supervisor_pid : status.remote_control_watchdog.worker_pid) ?? '—') }}</strong>
          </div>
        </div>

        <div v-if="launchdManaged" class="watchdog-policy-note">
          {{ launchdManagerLabel }} owns this Client's lifecycle. Process Recovery Watchdog, Local Heartbeat Watchdog, and Remote Control Watchdog are disabled to avoid competing supervisors.
        </div>

        <div class="watchdog-modes">
          <article class="watchdog-mode-card watchdog-process-card">
            <div class="watchdog-card-head">
              <div>
                <h4>Process Recovery Watchdog</h4>
                <p>Restarts the agent after an unexpected process exit</p>
              </div>
              <div class="watchdog-card-controls">
                <span class="watchdog-state-tag" :class="{ 'is-on': status.process_recovery_watchdog.enabled }">
                  {{ !watchdogSupported ? 'Unavailable' : launchdManaged ? `Managed by ${launchdManagerLabel}` : (status.process_recovery_watchdog.enabled ? 'Enabled' : 'Disabled') }}
                </span>
                <el-switch
                  v-if="watchdogSupported"
                  :model-value="Boolean(launchdManaged ? status.process_recovery_watchdog.configured_enabled : status.process_recovery_watchdog.enabled)"
                  :loading="togglingMode === 'process_recovery'"
                  :disabled="!canToggleMode"
                  aria-label="Toggle Process Recovery Watchdog"
                  @change="value => toggleMode('process_recovery', value)"
                />
              </div>
            </div>
            <div class="watchdog-card-stats">
              <div>
                <span>Supervisor</span>
                <strong>{{ status.process_recovery_watchdog.supervisor_alive ? 'Running' : 'Stopped' }}</strong>
              </div>
              <div>
                <span>Process PID</span>
                <strong>{{ status.process_recovery_watchdog.supervisor_pid ?? '—' }}</strong>
              </div>
            </div>
          </article>

          <article class="watchdog-mode-card">
            <div class="watchdog-card-head">
              <div>
                <h4>Remote Control Watchdog</h4>
                <p>Responds to HTTP management commands</p>
              </div>
              <div class="watchdog-card-controls">
                <span class="watchdog-state-tag" :class="{ 'is-on': status.remote_control_watchdog.enabled }">
                  {{ !watchdogSupported ? 'Unavailable' : launchdManaged ? `Managed by ${launchdManagerLabel}` : (status.remote_control_watchdog.enabled ? 'Enabled' : 'Disabled') }}
                </span>
                <el-switch
                  v-if="watchdogSupported"
                  :model-value="Boolean(launchdManaged ? status.remote_control_watchdog.configured_enabled : status.remote_control_watchdog.enabled)"
                  :loading="togglingMode === 'remote_control'"
                  :disabled="!canToggleMode"
                  aria-label="Toggle Remote Control Watchdog"
                  @change="value => toggleMode('remote_control', value)"
                />
              </div>
            </div>
            <div class="watchdog-card-stats">
              <div>
                <span>Check interval</span>
                <strong>{{ duration(status.remote_control_watchdog.interval_seconds) }}</strong>
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
                <h4>Local Heartbeat Watchdog</h4>
                <p>Monitors agent heartbeats on this device</p>
              </div>
              <div class="watchdog-card-controls">
                <span class="watchdog-state-tag" :class="{ 'is-on': status.local_heartbeat_watchdog.enabled }">
                  {{ !watchdogSupported ? 'Unavailable' : launchdManaged ? `Managed by ${launchdManagerLabel}` : (status.local_heartbeat_watchdog.enabled ? 'Enabled' : 'Disabled') }}
                </span>
                <el-switch
                  v-if="watchdogSupported"
                  :model-value="Boolean(launchdManaged ? status.local_heartbeat_watchdog.configured_enabled : status.local_heartbeat_watchdog.enabled)"
                  :loading="togglingMode === 'local_heartbeat'"
                  :disabled="!canToggleMode"
                  aria-label="Toggle Local Heartbeat Watchdog"
                  @change="value => toggleMode('local_heartbeat', value)"
                />
              </div>
            </div>
            <div class="watchdog-card-stats">
              <div>
                <span>Heartbeat</span>
                <strong>{{ duration(status.local_heartbeat_watchdog.heartbeat_interval_seconds) }}</strong>
              </div>
              <div>
                <span>Timeout</span>
                <strong>{{ duration(status.local_heartbeat_watchdog.timeout_seconds) }}</strong>
              </div>
            </div>
            <p v-if="status.local_heartbeat_watchdog.enabled" class="watchdog-feeder">
              Heartbeat sender: {{ status.local_heartbeat_watchdog.feeder_alive ? 'Active' : 'Not running' }}
              <span v-if="status.local_heartbeat_watchdog.feeder_thread_name">· {{ status.local_heartbeat_watchdog.feeder_thread_name }}</span>
            </p>
          </article>
        </div>

        <div class="watchdog-details">
          <div class="watchdog-details-top">
            <span>Agent process</span>
            <strong>{{ status.client.pid ?? '—' }}</strong>
          </div>
          <el-collapse v-model="expandedSections" class="watchdog-diagnostics">
            <el-collapse-item title="Connection & diagnostic paths" name="paths">
              <div class="watchdog-path-list">
                <div v-if="status.process_recovery_watchdog.log_path">
                  <span>Process Recovery Watchdog log</span>
                  <div class="watchdog-log-location">
                    <code>{{ status.process_recovery_watchdog.log_path }}</code>
                    <button class="watchdog-log-link" type="button" @click="openLog(status.process_recovery_watchdog.log_path, 'Process Recovery Watchdog')">View log</button>
                  </div>
                </div>
                <div v-if="status.remote_control_watchdog.control_url">
                  <span>Control endpoint (agent-side)</span>
                  <code>{{ status.remote_control_watchdog.control_url }}</code>
                </div>
                <div v-if="status.remote_control_watchdog.log_path">
                  <span>Remote Control Watchdog log</span>
                  <div class="watchdog-log-location">
                    <code>{{ status.remote_control_watchdog.log_path }}</code>
                    <button class="watchdog-log-link" type="button" @click="openLog(status.remote_control_watchdog.log_path, 'Remote Control Watchdog')">View log</button>
                  </div>
                </div>
                <div v-if="status.local_heartbeat_watchdog.heartbeat_file_path">
                  <span>Local heartbeat file</span>
                  <code>{{ status.local_heartbeat_watchdog.heartbeat_file_path }}</code>
                </div>
                <div v-if="status.local_heartbeat_watchdog.log_path">
                  <span>Local Heartbeat Watchdog log</span>
                  <div class="watchdog-log-location">
                    <code>{{ status.local_heartbeat_watchdog.log_path }}</code>
                    <button class="watchdog-log-link" type="button" @click="openLog(status.local_heartbeat_watchdog.log_path, 'Local Heartbeat Watchdog')">View log</button>
                  </div>
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
      <div v-if="actions.length" class="watchdog-action-buttons">
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
      <div v-if="actionsError" class="watchdog-actions-error">
        {{ actionsError }}
        <el-button link type="primary" size="small" @click="loadActions">Retry</el-button>
      </div>
    </footer>
  </section>
</template>

<script>
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  getWatchdogStatus,
  getHttpControlActions,
  queueHttpControlAction,
  updateRuntimeConfig,
} from '../api/connectionsApi.js'

const RECOVERY_ACTIONS = [
  { action: 'kill', label: 'Kill', description: 'Terminate the current agent process via Remote Control Watchdog.' },
  { action: 'relaunch', label: 'Relaunch', description: 'Launch a replacement agent, then terminate the current agent process.' },
  { action: 'clone', label: 'Clone', description: 'Launch another agent instance without stopping the current one.' },
]

export default {
  name: 'WatchdogInfoPanel',
  emits: ['open-log-viewer'],
  props: {
    clientId: { type: [String, Number], default: '' },
    currentConnection: { type: Object, default: null },
  },
  data() {
    return {
      status: null,
      loading: false,
      error: '',
      actions: RECOVERY_ACTIONS.map(action => ({ ...action })),
      actionsLoading: false,
      actionsError: '',
      pendingAction: '',
      togglingMode: '',
      expandedSections: [],
    }
  },
  computed: {
    watchdogSupported() {
      const reported = this.currentConnection?.feature_manifest?.watchdog
      if (typeof reported === 'boolean') return reported
      return this.status?.client?.watchdog_supported !== false
    },
    launchdManaged() {
      return Boolean(this.status?.client?.watchdogs_suppressed && this.status?.client?.lifecycle_manager === 'launchd')
    },
    launchdManagerLabel() {
      const source = String(this.currentConnection?.launch_source || '').toLowerCase()
      if (source === 'launchagent') return 'LaunchAgent'
      if (source === 'launchdaemon') return 'LaunchDaemon'
      return 'launchd'
    },
    sharedWorkerEnabled() {
      return Boolean(this.status?.remote_control_watchdog?.enabled || this.status?.local_heartbeat_watchdog?.enabled)
    },
    enabled() {
      return Boolean(this.sharedWorkerEnabled || this.status?.process_recovery_watchdog?.enabled)
    },
    workerStatus() {
      return this.status?.remote_control_watchdog?.worker_alive ? 'Running' : 'Stopped'
    },
    healthTone() {
      if (!this.watchdogSupported || this.launchdManaged) return 'off'
      if (!this.enabled) return 'off'
      if ((this.sharedWorkerEnabled && !this.status?.remote_control_watchdog?.worker_alive) ||
          (this.status?.process_recovery_watchdog?.enabled && !this.status?.process_recovery_watchdog?.supervisor_alive)) return 'warning'
      return 'healthy'
    },
    healthTitle() {
      if (!this.watchdogSupported) return 'Watchdog is unavailable'
      if (this.launchdManaged) return `Lifecycle managed by ${this.launchdManagerLabel}`
      if (!this.enabled) return 'Watchdog is disabled'
      return this.healthTone === 'healthy' ? 'Supervisor is running' : 'Supervisor is not running'
    },
    healthSubtitle() {
      if (this.launchdManaged) return `Client-side watchdogs stay off so ${this.launchdManagerLabel} remains the single lifecycle supervisor.`
      if (!this.enabled) return 'All watchdog modes are turned off.'
      if (this.healthTone === 'warning') return 'A watchdog mode is enabled, but its supervisor process is unavailable.'
      if (this.status.process_recovery_watchdog.enabled) {
        const modes = ['Process Recovery Watchdog']
        if (this.status.remote_control_watchdog.enabled) modes.push('Remote Control Watchdog')
        if (this.status.local_heartbeat_watchdog.enabled) modes.push('Local Heartbeat Watchdog')
        return `${modes.join(', ')} ${modes.length === 1 ? 'is' : 'are'} enabled.`
      }
      if (this.status.remote_control_watchdog.enabled && this.status.local_heartbeat_watchdog.enabled) return 'Remote Control Watchdog and Local Heartbeat Watchdog are enabled.'
      return this.status.remote_control_watchdog.enabled ? 'Remote Control Watchdog is enabled.' : 'Local Heartbeat Watchdog is enabled.'
    },
    connectionOffline() {
      return this.currentConnection?.connection_state === 'offline' || Boolean(this.currentConnection?.disconnected_at)
    },
    canToggleMode() {
      return this.watchdogSupported && !this.connectionOffline && !this.loading && !this.error &&
        Boolean(this.status) && !this.togglingMode && !this.pendingAction
    },
    canControl() {
      // Recovery controls must not rely on the health/status request or the
      // agent's online/busy state; launchd-managed Clients intentionally disable Remote Control Watchdog.
      return Boolean(this.clientId) && this.watchdogSupported && !this.launchdManaged && !this.pendingAction
    },
    actionHint() {
      if (!this.watchdogSupported) return 'This Client does not support Remote Control Watchdog control'
      if (this.launchdManaged) return `Remote Control Watchdog control is disabled while ${this.launchdManagerLabel} manages this Client`
      if (this.connectionOffline) return 'Agent is offline; command can be queued for its next poll'
      if (!this.status || this.error) return 'Status unavailable; recovery commands can still be queued'
      if (!this.status.remote_control_watchdog.enabled || !this.status.remote_control_watchdog.worker_alive) return 'Recovery commands can be queued; delivery requires an active Remote Control Watchdog'
      return 'Commands are queued through the Remote Control Watchdog'
    },
  },
  mounted() {
    void this.loadStatus()
    void this.loadActions()
  },
  methods: {
    openLog(path, title) {
      if (!path || !this.clientId) return
      this.$emit('open-log-viewer', { clientId: this.clientId, path, title })
    },
    duration(value) {
      return value == null || !Number.isFinite(Number(value)) ? '—' : `${value} s`
    },
    async toggleMode(mode, enabled) {
      const modes = {
        remote_control: { key: 'REMOTE_CONTROL_WATCHDOG_ENABLED', statusKey: 'remote_control_watchdog', label: 'Remote Control Watchdog' },
        local_heartbeat: { key: 'LOCAL_HEARTBEAT_WATCHDOG_ENABLED', statusKey: 'local_heartbeat_watchdog', label: 'Local Heartbeat Watchdog' },
        process_recovery: { key: 'PROCESS_RECOVERY_WATCHDOG_ENABLED', statusKey: 'process_recovery_watchdog', label: 'Process Recovery Watchdog' },
      }
      const selected = modes[mode]
      if (!this.canToggleMode || !selected || typeof enabled !== 'boolean') return
      const clientId = this.clientId
      const { key, statusKey, label } = selected
      if (Boolean(this.launchdManaged ? this.status[statusKey].configured_enabled : this.status[statusKey].enabled) === enabled) return

      this.togglingMode = mode
      try {
        // Reuse the Configuration UI endpoint; the backend executes the existing set command.
        await updateRuntimeConfig(clientId, key, enabled)
        if (clientId !== this.clientId) return
        await this.loadStatus()
        if (this.error || !this.status) {
          ElMessage.warning(`${label} updated, but status could not be refreshed`)
        } else if (this.launchdManaged) {
          ElMessage.warning(`${label} setting saved; ${this.launchdManagerLabel} manages the Client lifecycle`)
        } else if (this.status[statusKey].enabled !== enabled) {
          ElMessage.warning(`${label} setting saved; refresh to verify its runtime state`)
        } else {
          ElMessage.success(`${label} ${enabled ? 'enabled' : 'disabled'}`)
        }
      } catch (error) {
        if (clientId === this.clientId) {
          ElMessage.error(error.message || `Failed to update ${label.toLowerCase()}`)
        }
      } finally {
        this.togglingMode = ''
      }
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
        if (!data || typeof data !== 'object' || Array.isArray(data) ||
            !data.client || !data.remote_control_watchdog || !data.local_heartbeat_watchdog || !data.process_recovery_watchdog ||
            typeof data.client !== 'object' || typeof data.remote_control_watchdog !== 'object' ||
            typeof data.local_heartbeat_watchdog !== 'object' || typeof data.process_recovery_watchdog !== 'object' ||
            !('worker_alive' in data.remote_control_watchdog) || !('supervisor_alive' in data.process_recovery_watchdog)) {
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
        const available = new Map(data.filter(item => item && typeof item.action === 'string').map(item => [item.action, item]))
        this.actions = RECOVERY_ACTIONS.map(action => ({ ...action, ...(available.get(action.action) || {}), action: action.action }))
      } catch (error) {
        // Keep known recovery controls available if action discovery fails.
        this.actions = RECOVERY_ACTIONS.map(action => ({ ...action }))
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
        ElMessage.success(`${action.label || action.action} queued for Remote Control Watchdog`)
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
.watchdog-heading h3 { font-size: 20px; margin: 0 0 4px; font-weight: 700; }
.watchdog-heading p, .watchdog-card-head p { margin: 0; color: var(--muted); font-size: 12px; }
.watchdog-loading { padding: 18px; }
.watchdog-unavailable { padding: 28px 16px; border: 1px dashed #cbd5e1; border-radius: 12px; display: flex; flex-direction: column; gap: 10px; align-items: flex-start; }
.watchdog-unavailable span { color: var(--muted); font-size: 12px; overflow-wrap: anywhere; }
.watchdog-hero { display: flex; align-items: center; gap: 14px; padding: 18px; background: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 14px; margin-bottom: 14px; }
.watchdog-hero-off { background: #f8fafc; border-color: #e2e8f0; }
.watchdog-hero-warning { background: #fffbeb; border-color: #fde68a; }
.watchdog-policy-note { margin: -2px 0 14px; padding: 11px 13px; border-radius: 10px; background: #f8fafc; border: 1px solid #e2e8f0; color: #475569; font-size: 12px; line-height: 1.5; }
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
.watchdog-process-card { grid-column: 1 / -1; }
.watchdog-mode-card { border: 1px solid rgba(15,23,42,.08); border-radius: 14px; padding: 18px; background: #fff; min-width: 0; }
.watchdog-card-head { display: flex; justify-content: space-between; gap: 10px; min-height: 52px; }
.watchdog-card-head h4 { font-size: 14px; margin: 0 0 6px; }
.watchdog-card-controls { display: flex; align-items: center; gap: 10px; flex: 0 0 auto; }
.watchdog-card-head p { line-height: 1.4; }
.watchdog-state-tag { background: #f1f5f9; color: #64748b; padding: 3px 9px; border-radius: 999px; font-size: 11px; height: fit-content; white-space: nowrap; }
.watchdog-state-tag.is-on { background: #dcfce7; color: #15803d; }
.watchdog-card-stats { margin-top: 18px; display: flex; gap: 14px; border-top: 1px solid #f1f5f9; padding-top: 13px; }
.watchdog-card-stats > div { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 4px; }
.watchdog-card-stats span { color: #64748b; font-size: 11px; }
.watchdog-card-stats strong { font-size: 13px; font-weight: 600; }
.watchdog-feeder { color: #64748b; font-size: 11px; margin: 12px 0 0; overflow-wrap: anywhere; }
.watchdog-details { margin-top: 14px; border: 1px solid rgba(15,23,42,.07); border-radius: 12px; background: #f8fafc; padding: 0 16px; }
.watchdog-details-top { display: flex; justify-content: space-between; align-items: center; padding: 13px 0; border-bottom: 1px solid #e2e8f0; font-size: 12px; color: #64748b; }
.watchdog-details-top strong { color: var(--text); font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 13px; }
.watchdog-diagnostics { border: none; --el-collapse-border-color: transparent; }
.watchdog-diagnostics :deep(.el-collapse-item__header), .watchdog-diagnostics :deep(.el-collapse-item__wrap) { background: transparent; }
.watchdog-diagnostics :deep(.el-collapse-item__header) { color: #64748b; font-size: 12px; height: 37px; border-bottom: none; }
.watchdog-diagnostics :deep(.el-collapse-item__wrap) { border-bottom: none; }
.watchdog-path-list { display: flex; flex-direction: column; gap: 12px; padding: 2px 0 12px; }
.watchdog-path-list > div { min-width: 0; display: flex; flex-direction: column; gap: 4px; }
.watchdog-path-list span { color: #64748b; font-size: 11px; }
.watchdog-log-location { display: block; min-width: 0; }
.watchdog-log-link { display: inline; margin-left: 6px; border: none; background: none; padding: 0; font-size: 11px; color: var(--el-color-primary); cursor: pointer; white-space: nowrap; }
.watchdog-log-link:hover { text-decoration: underline; }
.watchdog-path-list code { display: block; color: var(--text); font-size: 11px; line-height: 1.5; white-space: normal; overflow-wrap: anywhere; user-select: text; }
.watchdog-log-location code { display: inline; }
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
