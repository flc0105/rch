<template>
  <el-dialog
    v-model="visible"
    :title="dialogTitle"
    width="1180px"
    top="5vh"
    class="machine-connection-history-dialog"
    modal-class="machine-connection-history-overlay"
    destroy-on-close
  >
    <div class="machine-history-body" v-loading="loading">
      <div class="machine-history-toolbar">
        <div class="machine-history-identity">
          <div class="machine-history-device-name">{{ deviceName || 'Unknown device' }}</div>
          <div class="machine-history-machine-id">machine_id: {{ shortenMachineId(machineId) }}</div>
        </div>

        <el-button size="small" @click="loadHistory">
          Refresh
        </el-button>
      </div>

      <div class="machine-history-stats">
        <div class="machine-history-stat">
          <div class="machine-history-stat-label">All Connections</div>
          <div class="machine-history-stat-value">{{ history.connection_count || 0 }}</div>
        </div>
        <div class="machine-history-stat">
          <div class="machine-history-stat-label">Online Now</div>
          <div class="machine-history-stat-value">{{ history.online_connection_count || 0 }}</div>
        </div>
        <div class="machine-history-stat">
          <div class="machine-history-stat-label">Total Activities</div>
          <div class="machine-history-stat-value">{{ history.command_count || 0 }}</div>
        </div>
        <div class="machine-history-stat">
          <div class="machine-history-stat-label">Total Online Time</div>
          <div class="machine-history-stat-value">{{ formatDuration(history.total_online_duration_ms) }}</div>
        </div>
      </div>

      <el-alert
        v-if="history.unassigned_command_count"
        class="machine-history-alert"
        type="warning"
        :closable="false"
        show-icon
        :title="`${history.unassigned_command_count} activity record(s) have no client_id and cannot be assigned to a session.`"
      />

      <div v-if="sessions.length" class="machine-history-mobile-list">
        <article
          v-for="(row, index) in sessions"
          :key="`mobile-${row.client_id}`"
          class="machine-history-mobile-card"
        >
          <div class="machine-history-mobile-card-head">
            <div class="machine-history-mobile-card-state">
              <span class="machine-history-mobile-index">#{{ index + 1 }}</span>
              <el-tag size="small" :type="sessionStatusTagType(row)">
                {{ sessionStatusText(row) }}
              </el-tag>
            </div>
            <code class="machine-session-client-id machine-history-mobile-client-id">{{ row.client_id || '-' }}</code>
          </div>

          <div class="machine-history-mobile-summary">
            <div class="machine-history-mobile-field">
              <span>Online</span>
              <strong>{{ formatDateTime(row.connected_at) }}</strong>
            </div>
            <div class="machine-history-mobile-field">
              <span>Offline</span>
              <strong>{{ row.connection_state === 'online' ? 'online' : formatDateTime(row.disconnected_at) }}</strong>
            </div>
            <div class="machine-history-mobile-field">
              <span>Duration</span>
              <strong>{{ formatDuration(row.duration_ms) }}</strong>
            </div>
            <div class="machine-history-mobile-field">
              <span>Activities</span>
              <strong>{{ row.command_count || 0 }}</strong>
            </div>
          </div>

          <el-button
            class="machine-history-mobile-details-toggle"
            size="small"
            text
            @click="toggleMobileSessionDetails(row)"
          >
            {{ isMobileSessionExpanded(row) ? 'Hide details' : 'Details' }}
          </el-button>

          <div v-if="isMobileSessionExpanded(row)" class="machine-history-mobile-details">
            <div class="machine-session-meta-grid">
              <div class="machine-session-meta-item">
                <span class="label">Hostname</span>
                <span class="value">{{ row.hostname || '-' }}</span>
              </div>
              <div class="machine-session-meta-item">
                <span class="label">Address</span>
                <span class="value">{{ row.addr || '-' }}</span>
              </div>
              <div class="machine-session-meta-item">
                <span class="label">OS</span>
                <span class="value">{{ formatOs(row) }}</span>
              </div>
              <div class="machine-session-meta-item">
                <span class="label">User</span>
                <span class="value">{{ row.username || '-' }}</span>
              </div>
              <div class="machine-session-meta-item">
                <span class="label">Integrity</span>
                <span class="value">{{ row.integrity || '-' }}</span>
              </div>
              <div class="machine-session-meta-item">
                <span class="label">Process</span>
                <span class="value">{{ formatProcess(row) }}</span>
              </div>
              <div class="machine-session-meta-item">
                <span class="label">Launch mode</span>
                <span class="value">{{ formatLaunchModeValue(row) }}</span>
              </div>
              <div class="machine-session-meta-item">
                <span class="label">Build</span>
                <span class="value">{{ row.build_version || '-' }}</span>
              </div>
              <div class="machine-session-meta-item">
                <span class="label">Last seen</span>
                <span class="value">{{ formatDateTime(row.last_seen_at) }}</span>
              </div>
              <div v-if="row.termination_reason || hasTerminationDetail(row)" class="machine-session-meta-item machine-session-meta-wide">
                <span class="label">Termination</span>
                <div class="value machine-session-termination-value">
                  {{ formatEndReason(row.termination_reason) }}<span v-if="terminationDetailText(row)"> ({{ terminationDetailText(row) }})</span>
                  <pre v-if="row.termination_detail?.traceback">{{ row.termination_detail.traceback }}</pre>
                </div>
              </div>
              <div class="machine-session-meta-item machine-session-meta-wide">
                <span class="label">cwd</span>
                <span class="value">{{ row.cwd || '-' }}</span>
              </div>
            </div>

            <div class="machine-session-command-header">
              <span>Activities ({{ row.command_count || 0 }})</span>
            </div>
            <div class="machine-session-command-section" v-loading="row.command_loading">
              <div
                v-for="(activity, activityIndex) in (row.commands || [])"
                :key="activity.activity_id || `${row.client_id}-${activity.started_at || activity.created_at || activityIndex}-${activityIndex}`"
                class="machine-history-mobile-activity"
              >
                <div class="machine-history-mobile-activity-head">
                  <span>{{ formatDateTime(activity.started_at || activity.created_at) }}</span>
                  <el-tag size="small" :type="commandStatusTagType(activity.status)">
                    {{ activity.status || 'unknown' }}
                  </el-tag>
                </div>
                <div class="machine-history-mobile-activity-summary">
                  <span class="machine-session-activity-kind">{{ activityKindLabel(activity.kind) }}</span>
                  <span class="machine-session-activity-separator">·</span>
                  <span>{{ activity.summary || '-' }}</span>
                </div>
                <div class="machine-history-mobile-activity-duration">
                  Duration · {{ formatDuration(commandDurationMs(activity)) }}
                </div>
              </div>

              <div
                v-if="!row.commands?.length && !row.command_loading && (row.command_loaded || !Number(row.command_count || 0))"
                class="empty-state compact"
              >
                No activities
              </div>

              <div v-if="row.command_has_more" class="machine-session-command-load-more">
                <el-button
                  size="small"
                  plain
                  :loading="row.command_loading"
                  @click="loadSessionCommands(row, true)"
                >
                  Load More
                </el-button>
              </div>
            </div>
          </div>
        </article>
      </div>

      <el-table
        v-if="sessions.length"
        :data="sessions"
        row-key="client_id"
        :expand-row-keys="expandedSessionIds"
        border
        stripe
        class="machine-history-table"
        @expand-change="handleSessionExpand"
      >
        <el-table-column type="expand" width="40">
          <template #default="scope">
            <div class="machine-session-detail">
              <div class="machine-session-meta-grid">
                <div class="machine-session-meta-item">
                  <span class="label">Hostname</span>
                  <span class="value">{{ scope.row.hostname || '-' }}</span>
                </div>
                <div class="machine-session-meta-item">
                  <span class="label">Address</span>
                  <span class="value">{{ scope.row.addr || '-' }}</span>
                </div>
                <div class="machine-session-meta-item">
                  <span class="label">OS</span>
                  <span class="value">{{ formatOs(scope.row) }}</span>
                </div>
                <div class="machine-session-meta-item">
                  <span class="label">User</span>
                  <span class="value">{{ scope.row.username || '-' }}</span>
                </div>
                <div class="machine-session-meta-item">
                  <span class="label">Integrity</span>
                  <span class="value">{{ scope.row.integrity || '-' }}</span>
                </div>
                <div class="machine-session-meta-item">
                  <span class="label">Process</span>
                  <span class="value">{{ formatProcess(scope.row) }}</span>
                </div>
                <div class="machine-session-meta-item">
                  <span class="label">Launch mode</span>
                  <span class="value">{{ formatLaunchModeValue(scope.row) }}</span>
                </div>
                <div class="machine-session-meta-item">
                  <span class="label">Build</span>
                  <span class="value">{{ scope.row.build_version || '-' }}</span>
                </div>
                <div class="machine-session-meta-item">
                  <span class="label">Last seen</span>
                  <span class="value">{{ formatDateTime(scope.row.last_seen_at) }}</span>
                </div>
                <div v-if="scope.row.termination_reason || hasTerminationDetail(scope.row)" class="machine-session-meta-item machine-session-meta-wide">
                  <span class="label">Termination</span>
                  <div class="value machine-session-termination-value">
                    {{ formatEndReason(scope.row.termination_reason) }}<span v-if="terminationDetailText(scope.row)"> ({{ terminationDetailText(scope.row) }})</span>
                    <pre v-if="scope.row.termination_detail?.traceback">{{ scope.row.termination_detail.traceback }}</pre>
                  </div>
                </div>
                <div class="machine-session-meta-item machine-session-meta-wide">
                  <span class="label">cwd</span>
                  <span class="value">{{ scope.row.cwd || '-' }}</span>
                </div>
              </div>

              <div class="machine-session-command-header">
                <span>Activities ({{ scope.row.command_count || 0 }})</span>
              </div>

              <div
                class="machine-session-command-section"
                v-loading="scope.row.command_loading"
              >
                <el-table
                  v-if="scope.row.commands && scope.row.commands.length"
                  :data="scope.row.commands"
                  size="small"
                  border
                  max-height="320"
                  class="machine-session-command-table"
                  table-layout="fixed"
                >
                  <el-table-column label="Time" width="160">
                    <template #default="commandScope">
                      {{ formatDateTime(commandScope.row.started_at || commandScope.row.created_at) }}
                    </template>
                  </el-table-column>
                  <el-table-column label="Status" width="90">
                    <template #default="commandScope">
                      <el-tag
                        size="small"
                        :type="commandStatusTagType(commandScope.row.status)"
                      >
                        {{ commandScope.row.status || 'unknown' }}
                      </el-tag>
                    </template>
                  </el-table-column>
                  <el-table-column label="Activity" min-width="360" show-overflow-tooltip>
                    <template #default="commandScope">
                      <div class="machine-session-activity-text">
                        <span class="machine-session-activity-kind">{{ activityKindLabel(commandScope.row.kind) }}</span>
                        <span class="machine-session-activity-separator">·</span>
                        <span class="machine-session-command-text">{{ commandScope.row.summary || '-' }}</span>
                      </div>
                    </template>
                  </el-table-column>
                  <el-table-column label="Duration" width="105">
                    <template #default="commandScope">
                      {{ formatDuration(commandDurationMs(commandScope.row)) }}
                    </template>
                  </el-table-column>
                </el-table>

                <div
                  v-else-if="!scope.row.command_loading && (scope.row.command_loaded || !Number(scope.row.command_count || 0))"
                  class="empty-state compact"
                >
                  No activities
                </div>

                <div
                  v-if="scope.row.command_has_more"
                  class="machine-session-command-load-more"
                >
                  <el-button
                    size="small"
                    plain
                    :loading="scope.row.command_loading"
                    @click="loadSessionCommands(scope.row, true)"
                  >
                    Load More
                  </el-button>
                </div>
              </div>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="#" width="60" class-name="machine-history-index-column">
          <template #default="scope">
            {{ scope.$index + 1 }}
          </template>
        </el-table-column>

        <el-table-column label="State" width="110">
          <template #default="scope">
            <el-tag
              size="small"
              :type="sessionStatusTagType(scope.row)"
            >
              {{ sessionStatusText(scope.row) }}
            </el-tag>
          </template>
        </el-table-column>

        <el-table-column label="Client" min-width="136" show-overflow-tooltip>
          <template #default="scope">
            <code class="machine-session-client-id">{{ scope.row.client_id || '-' }}</code>
          </template>
        </el-table-column>

        <el-table-column label="Online" min-width="80" class-name="machine-history-time-column" show-overflow-tooltip>
          <template #default="scope">
            {{ formatDateTime(scope.row.connected_at) }}
          </template>
        </el-table-column>

        <el-table-column label="Offline" min-width="80" class-name="machine-history-time-column" show-overflow-tooltip>
          <template #default="scope">
            {{ scope.row.connection_state === 'online' ? 'online' : formatDateTime(scope.row.disconnected_at) }}
          </template>
        </el-table-column>

        <el-table-column label="Duration" width="100" show-overflow-tooltip>
          <template #default="scope">
            {{ formatDuration(scope.row.duration_ms) }}
          </template>
        </el-table-column>

        <el-table-column label="Activities" width="90" align="right">
          <template #default="scope">
            {{ scope.row.command_count || 0 }}
          </template>
        </el-table-column>
      </el-table>

      <div v-else-if="!loading" class="empty-state machine-history-empty">
        No connection history for this machine yet
      </div>

      <div v-if="history.tracking_started_at" class="machine-history-footer-note">
        Connection lifecycle and activity records are stored in rch.db. Activity summaries are loaded for each client session.
      </div>
    </div>
  </el-dialog>
</template>

<script>
import { diffDateTimeMs, formatDateTimeStandard, formatLaunchMode } from '../utils/formatters.js'
import { ElMessage } from 'element-plus'
import { getMachineConnectionCommands, getMachineConnectionHistory } from '../api/connectionsApi.js'

export default {
  name: 'MachineConnectionHistoryDialog',

  data() {
    return {
      visible: false,
      loading: false,
      machineId: '',
      deviceName: '',
      history: {
        sessions: [],
      },
      mobileExpandedSessionIds: [],
      expandedSessionIds: [],
    }
  },


  computed: {
    dialogTitle() {
      return this.deviceName ? `Connection History · ${this.deviceName}` : 'Connection History'
    },

    sessions() {
      return Array.isArray(this.history.sessions) ? this.history.sessions : []
    },
  },

  methods: {
    open(item = {}) {
      this.machineId = String(item.machine_id || '').trim()
      this.deviceName = String(
        item.device_display_name || item.display_hostname || item.device_alias || item.hostname || '',
      ).trim()
      this.visible = true
      this.expandedSessionIds = []
      this.mobileExpandedSessionIds = []
      return this.loadHistory()
    },

    async loadHistory() {
      if (!this.machineId) {
        this.history = { sessions: [] }
        return
      }

      this.loading = true
      try {
        const payload = await getMachineConnectionHistory(this.machineId)
        const previous = new Map(this.sessions.map(row => [row.client_id, row]))
        this.history = {
          ...(payload || {}),
          sessions: (Array.isArray(payload?.sessions) ? payload.sessions : []).map(session => {
            const old = previous.get(session.client_id)
            return {
              ...session,
              commands: old?.commands || [],
              command_loaded: old?.command_loaded || false,
              command_loading: old?.command_loading || false,
              command_has_more: old?.command_has_more || false,
              command_next_cursor: old?.command_next_cursor || '',
            }
          }),
        }
        const available = new Set(this.sessions.map(row => row.client_id))
        this.expandedSessionIds = this.expandedSessionIds.filter(id => available.has(id))
        this.mobileExpandedSessionIds = this.mobileExpandedSessionIds.filter(id => available.has(id))
        const expanded = new Set([...this.expandedSessionIds, ...this.mobileExpandedSessionIds])
        for (const row of this.sessions) {
          if (expanded.has(row.client_id) && Number(row.command_count || 0) && !row.command_loading) {
            this.loadSessionCommands(row)
          }
        }
      } catch (e) {
        ElMessage.error(e.message || 'Failed to load connection history')
      } finally {
        this.loading = false
      }
    },

    handleSessionExpand(row, expandedRows) {
      this.expandedSessionIds = Array.isArray(expandedRows)
        ? expandedRows.map(item => item?.client_id).filter(Boolean)
        : []
      const expanded = this.expandedSessionIds.includes(row?.client_id)
      if (!expanded) return
      if (row?.command_loaded || row?.command_loading || !Number(row?.command_count || 0)) return
      this.loadSessionCommands(row)
    },

    isMobileSessionExpanded(row) {
      const clientId = String(row?.client_id || '')
      return !!clientId && this.mobileExpandedSessionIds.includes(clientId)
    },

    toggleMobileSessionDetails(row) {
      const clientId = String(row?.client_id || '')
      if (!clientId) return

      if (this.mobileExpandedSessionIds.includes(clientId)) {
        this.mobileExpandedSessionIds = this.mobileExpandedSessionIds.filter(id => id !== clientId)
        return
      }

      this.mobileExpandedSessionIds = [...this.mobileExpandedSessionIds, clientId]
      if (!row.command_loaded && !row.command_loading && Number(row.command_count || 0)) {
        return this.loadSessionCommands(row)
      }
    },

    async loadSessionCommands(row, append = false) {
      if (!this.machineId || !row?.client_id || row.command_loading) return

      row.command_loading = true
      try {
        const data = await getMachineConnectionCommands(this.machineId, row.client_id, {
          limit: 50,
          cursor: append ? row.command_next_cursor : '',
        })

        const current = this.sessions.find(item => item.client_id === row.client_id)
        if (!current) return

        const items = Array.isArray(data?.items) ? data.items : []
        current.commands = append ? [...(current.commands || []), ...items] : items
        current.command_next_cursor = String(data?.next_cursor || '')
        current.command_has_more = data?.has_more === true
        current.command_loaded = true
      } catch (e) {
        ElMessage.error(e.message || 'Failed to load connection activities')
      } finally {
        const current = this.sessions.find(item => item.client_id === row.client_id)
        if (current) current.command_loading = false
      }
    },


    activityKindLabel(kind) {
      return ({
        command: 'Command', alias: 'Alias', script: 'Script',
        remote_files: 'Remote Files', transfer: 'Transfer', external_tool: 'External Tool',
      })[kind] || 'Activity'
    },

    shortenMachineId(machineId) {
      const value = String(machineId || '').trim()
      if (!value) return '-'
      return value.length > 12 ? value.slice(0, 12) : value
    },

    formatDateTime(value) {
      return formatDateTimeStandard(value)
    },

    commandDurationMs(row) {
      return diffDateTimeMs(row?.started_at || row?.created_at, row?.finished_at)
    },

    formatDuration(durationMs) {
      const totalSeconds = Math.max(Math.floor(Number(durationMs || 0) / 1000), 0)
      if (!totalSeconds) return '0s'

      const days = Math.floor(totalSeconds / 86400)
      const hours = Math.floor((totalSeconds % 86400) / 3600)
      const minutes = Math.floor((totalSeconds % 3600) / 60)
      const seconds = totalSeconds % 60
      const parts = []

      if (days) parts.push(`${days}d`)
      if (hours) parts.push(`${hours}h`)
      if (minutes) parts.push(`${minutes}m`)
      if (seconds || !parts.length) parts.push(`${seconds}s`)

      return parts.slice(0, 3).join(' ')
    },

    formatOs(row) {
      const type = String(row?.os_type || row?.os_name || '').trim()
      const version = String(row?.os_ver || '').trim()
      return [type, version].filter(Boolean).join(' ') || '-'
    },

    formatProcess(row) {
      const processName = String(row?.process_name || '').trim()
      const processId = String(row?.process_id || '').trim()
      if (processName && processId) return `${processName} (${processId})`
      return processName || processId || '-'
    },


    formatLaunchModeValue(row) {
      return formatLaunchMode(row?.launch_mode, row?.launch_source)
    },

    terminationDetailText(row) {
      const details = row?.termination_detail || {}
      return [details.command ? `Command: ${details.command}` : '', details.summary || ''].filter(Boolean).join('; ')
    },

    hasTerminationDetail(row) {
      const details = row?.termination_detail
      return Boolean(details?.command || details?.summary || details?.traceback)
    },

    formatEndReason(value) {
      const names = {
        server_requested_disconnect: 'Server requested disconnect',
        client_exit: 'Client exit',
        client_restart: 'Client restart',
        client_update: 'Client update',
        connection_lost: 'Connection lost',
        transport_error: 'Transport error',
        timeout: 'Timeout',
        unexpected_disconnect: 'Unexpected disconnect',
        client_error: 'Client error',
      }
      return names[value] || value
    },

    sessionStatusText(row) {
      if (row?.connection_state === 'online') return 'online'
      if (row?.connection_state === 'interrupted') return 'interrupted'
      return 'offline'
    },

    sessionStatusTagType(row) {
      if (row?.connection_state === 'online') return 'success'
      if (row?.connection_state === 'interrupted') return 'warning'
      return 'info'
    },

    commandStatusTagType(status) {
      if (status === 'success') return 'success'
      if (status === 'error') return 'danger'
      if (status === 'running') return 'warning'
      return 'info'
    },
  },
}
</script>

<style scoped>
.machine-history-body {
  height: 100%;
  min-height: 0;
  overflow: auto;
}

.machine-history-toolbar {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 14px;
}

.machine-history-identity {
  min-width: 0;
}

.machine-history-device-name {
  font-size: 15px;
  font-weight: 700;
  color: var(--el-text-color-primary);
}

.machine-history-machine-id {
  margin-top: 4px;
  color: var(--el-text-color-secondary);
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 12px;
  overflow-wrap: anywhere;
}

.machine-history-stats {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  margin-bottom: 14px;
}

.machine-history-stat {
  padding: 12px 14px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: var(--el-fill-color-extra-light);
}

.machine-history-stat-label {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.machine-history-stat-value {
  margin-top: 5px;
  color: var(--el-text-color-primary);
  font-size: 17px;
  font-weight: 700;
}

.machine-history-alert {
  margin-bottom: 12px;
}

.machine-history-table {
  width: 100%;
}

.machine-history-mobile-list {
  display: none;
}

.machine-history-mobile-card {
  min-width: 0;
  padding: 12px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 12px;
  background: var(--el-bg-color);
  box-shadow: 0 3px 10px rgba(15, 23, 42, 0.04);
}

.machine-history-mobile-card-head {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 8px;
  min-width: 0;
}

.machine-history-mobile-card-state {
  display: flex;
  align-items: center;
  gap: 8px;
}

.machine-history-mobile-index {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  font-weight: 700;
}

.machine-history-mobile-client-id {
  max-width: 100%;
  overflow-wrap: anywhere;
  font-size: 12px;
}

.machine-history-mobile-summary {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px 10px;
  margin-top: 14px;
}

.machine-history-mobile-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.machine-history-mobile-field > span {
  color: var(--el-text-color-secondary);
  font-size: 11px;
}

.machine-history-mobile-field > strong {
  min-width: 0;
  color: var(--el-text-color-primary);
  font-size: 12px;
  font-weight: 600;
  line-height: 1.4;
  overflow-wrap: anywhere;
}

.machine-history-mobile-details-toggle {
  margin-top: 10px;
}

.machine-history-mobile-details {
  margin-top: 8px;
  padding-top: 12px;
  border-top: 1px solid var(--el-border-color-lighter);
}

.machine-history-mobile-details .machine-session-meta-grid {
  grid-template-columns: minmax(0, 1fr);
  gap: 10px;
}

.machine-history-mobile-details .machine-session-meta-item {
  flex-direction: column;
  align-items: flex-start;
  gap: 3px;
}

.machine-history-mobile-details .machine-session-meta-wide {
  grid-column: span 1;
}

.machine-history-mobile-activity {
  min-width: 0;
  padding: 10px 0;
  border-top: 1px solid var(--el-border-color-lighter);
}

.machine-history-mobile-activity-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
  color: var(--el-text-color-secondary);
  font-size: 11px;
}

.machine-history-mobile-activity-summary {
  display: flex;
  align-items: baseline;
  gap: 5px;
  min-width: 0;
  margin-top: 7px;
  color: var(--el-text-color-primary);
  font-size: 12px;
  line-height: 1.45;
  overflow-wrap: anywhere;
}

.machine-history-mobile-activity-duration {
  margin-top: 6px;
  color: var(--el-text-color-secondary);
  font-size: 11px;
}

.machine-session-detail {
  padding: 12px 18px 18px 62px;
  background: var(--el-fill-color-extra-light);
}

.machine-session-meta-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px 18px;
  margin-bottom: 16px;
}

.machine-session-meta-item {
  display: flex;
  min-width: 0;
  gap: 8px;
  font-size: 12px;
}

.machine-session-meta-item .label {
  flex: 0 0 auto;
  color: var(--el-text-color-secondary);
}

.machine-session-meta-item .value {
  min-width: 0;
  color: var(--el-text-color-regular);
  overflow-wrap: anywhere;
}

.machine-session-meta-wide {
  grid-column: span 2;
}



.machine-session-command-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin: 2px 0 8px;
  font-size: 13px;
  font-weight: 700;
  color: var(--el-text-color-primary);
}

.machine-session-command-section {
  min-height: 44px;
}

.machine-session-command-load-more {
  display: flex;
  justify-content: center;
  margin-top: 10px;
}

.machine-session-command-text,
.machine-session-client-id {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}

.machine-session-activity-text {
  display: flex;
  align-items: center;
  min-width: 0;
  gap: 5px;
}

.machine-session-activity-kind {
  color: var(--el-text-color-secondary);
  flex: 0 0 auto;
  white-space: nowrap;
}

.machine-session-activity-separator {
  color: var(--el-text-color-placeholder);
}

.machine-session-command-text {
  display: block;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* Keep every session column visible; long values truncate instead of widening the table. */
:deep(.machine-history-table .cell) {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

:deep(.machine-history-table .el-table__header .cell),
:deep(.machine-session-command-table .el-table__header .cell) {
  white-space: nowrap;
}

.machine-history-empty {
  padding: 56px 0;
}

.machine-history-footer-note {
  margin-top: 12px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.6;
}

@media (max-width: 768px) {
  .machine-history-body {
    overscroll-behavior: contain;
    -webkit-overflow-scrolling: touch;
  }
}

@media (max-width: 900px) {
  .machine-history-stats {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .machine-session-meta-grid {
    grid-template-columns: 1fr;
  }

  .machine-session-meta-wide {
    grid-column: span 1;
  }

  .machine-session-detail {
    padding-left: 12px;
  }
}
.machine-session-end-details { min-width: 0; overflow-wrap: anywhere; white-space: pre-wrap; font-size: 12px; }
.machine-session-end-details pre { margin: 6px 0 0; max-height: 240px; overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere; font-size: inherit; }
</style>

<style>
.machine-connection-history-overlay .el-overlay-dialog {
  overflow: hidden;
}

.machine-connection-history-overlay .el-dialog {
  height: 78vh;
  max-height: 78vh;
  margin-top: 5vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.machine-connection-history-overlay .el-dialog__header {
  flex: 0 0 auto;
}

.machine-connection-history-overlay .el-dialog__body {
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
  padding-top: 12px;
  padding-bottom: 12px;
}

@media (max-width: 768px) {
  .machine-history-table {
    display: none !important;
  }

  .machine-history-mobile-list {
    display: flex !important;
    flex-direction: column;
    gap: 10px;
  }

  .machine-connection-history-overlay .el-dialog__body {
    overflow: hidden;
  }

  .machine-history-body {
    overflow-y: auto;
    overscroll-behavior: contain;
    -webkit-overflow-scrolling: touch;
  }
}

@media (max-width: 768px), (max-height: 720px) {
  .machine-connection-history-overlay .el-dialog {
    width: 100vw !important;
    max-width: 100vw !important;
    height: 100dvh;
    max-height: 100dvh;
    margin: 0;
    border-radius: 0;
  }
}
</style>
