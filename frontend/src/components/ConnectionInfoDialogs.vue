<template>
  <el-dialog
    v-model="infoVisible"
    title="Connection Info"
    width="980px"
    top="6vh"
    class="fixed-dialog connection-info-dialog"
    modal-class="connection-info-overlay"
  >
    <div
      class="fixed-dialog-body connection-info-body"
      v-loading="loading"
    >
      <el-tabs
        v-model="activeTab"
        class="connection-info-tabs"
      >
        <el-tab-pane
          label="Basic Info"
          name="basic"
          class="connection-info-tab-pane"
        >
          <div class="connection-info-tab-scroll">
            <div class="connection-info-stats-grid">
              <div
                v-for="item in connectionInfoCards"
                :key="item.label"
                class="connection-info-stat connection-info-stat-expandable"
                @click="openConnectionInfoValueDialog(item)"
              >
                <div class="connection-info-stat-label">
                  {{ item.label }}
                </div>

                <div
                  class="connection-info-stat-value"
                  :class="{ mono: item.mono }"
                >
                  {{ item.fullValue }}
                </div>
              </div>
            </div>
          </div>
        </el-tab-pane>

        <el-tab-pane
          label="Dashboard"
          name="dashboard"
          class="connection-info-tab-pane"
        >
          <div class="connection-info-tab-scroll monitor-dashboard-scroll">
            <div class="monitor-dashboard-head">
              <div>
                <div class="monitor-dashboard-title">Device Dashboard</div>
                <div class="monitor-dashboard-subtitle">
                  {{ currentConnection?.hostname || selectedId || 'Device' }}
                </div>
              </div>

              <div class="monitor-live-block">
                <div
                  class="monitor-live-badge"
                  :class="`monitor-live-${monitorDisplayState}`"
                >
                  <span class="monitor-live-dot"></span>
                  {{ monitorDisplayLabel }}
                </div>
                <div class="monitor-updated-text">
                  {{ monitorUpdatedText }}
                </div>
              </div>
            </div>

            <div
              v-if="monitorError"
              class="monitor-dashboard-error"
            >
              {{ monitorError }}
            </div>

            <div class="monitor-overview-grid">
              <div class="monitor-overview-card">
                <div class="monitor-card-label">CPU</div>
                <div class="monitor-card-value">{{ formatPercent(monitorSystem.cpu_percent) }}</div>
                <el-progress
                  :percentage="normalizePercent(monitorSystem.cpu_percent)"
                  :color="monitorUsageProgressColor(monitorSystem.cpu_percent)"
                  :show-text="false"
                  :stroke-width="6"
                />
                <div class="monitor-card-meta">
                  {{ Number(monitorSystem.cpu_count || 0) || '-' }} cores
                </div>
              </div>

              <div class="monitor-overview-card">
                <div class="monitor-card-label">Memory</div>
                <div class="monitor-card-value">{{ formatPercent(monitorSystem.memory?.percent) }}</div>
                <el-progress
                  :percentage="normalizePercent(monitorSystem.memory?.percent)"
                  :color="monitorUsageProgressColor(monitorSystem.memory?.percent)"
                  :show-text="false"
                  :stroke-width="6"
                />
                <div class="monitor-card-meta">
                  {{ formatUsagePair(monitorSystem.memory?.used, monitorSystem.memory?.total) }}
                </div>
                <div class="monitor-card-meta monitor-card-meta-secondary">
                  Swap {{ formatUsagePair(monitorSystem.swap?.used, monitorSystem.swap?.total) }}
                </div>
              </div>

              <div class="monitor-overview-card">
                <div class="monitor-card-label">Battery</div>
                <template v-if="monitorBattery.available">
                  <div class="monitor-card-value">{{ formatPercent(monitorBattery.percent) }}</div>
                  <el-progress
                    :percentage="normalizePercent(monitorBattery.percent)"
                    :show-text="false"
                    :stroke-width="6"
                  />
                  <div class="monitor-card-meta">
                    {{ monitorBattery.plugged ? 'Charging / AC Power' : 'On Battery' }}
                  </div>
                </template>
                <template v-else>
                  <div class="monitor-card-value monitor-card-value-muted">—</div>
                  <div class="monitor-card-empty-line"></div>
                  <div class="monitor-card-meta">No battery</div>
                </template>
              </div>

              <div class="monitor-overview-card">
                <div class="monitor-card-label">Runtime</div>
                <div class="monitor-card-value monitor-runtime-value">
                  {{ formatUptime(monitorSystem.uptime_seconds) }}
                </div>
                <div class="monitor-runtime-row">
                  <span>Processes</span>
                  <strong>{{ Number(monitorSystem.process_count || 0) || '-' }}</strong>
                </div>
                <div class="monitor-runtime-row">
                  <span>Sample</span>
                  <strong>500 ms</strong>
                </div>
              </div>
            </div>

            <div class="monitor-section">
              <div class="monitor-section-head">
                <div>
                  <div class="monitor-section-title">Network</div>
                  <div class="monitor-section-subtitle">
                    {{ monitorNetworkInterfaceText }}
                  </div>
                </div>
              </div>

              <div class="monitor-network-grid">
                <div class="monitor-network-item">
                  <span class="monitor-network-arrow">↓</span>
                  <div>
                    <div class="monitor-network-label">Download</div>
                    <div class="monitor-network-value">
                      {{ formatRate(monitorNetwork.rx_bytes_per_sec) }}
                    </div>
                  </div>
                </div>

                <div class="monitor-network-item">
                  <span class="monitor-network-arrow">↑</span>
                  <div>
                    <div class="monitor-network-label">Upload</div>
                    <div class="monitor-network-value">
                      {{ formatRate(monitorNetwork.tx_bytes_per_sec) }}
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <div class="monitor-section monitor-storage-section">
              <div class="monitor-section-head">
                <div>
                  <div class="monitor-section-title">Storage</div>
                  <div class="monitor-section-subtitle">Mounted user-visible volumes</div>
                </div>
                <span class="monitor-volume-count">
                  {{ monitorVolumes.length }} {{ monitorVolumes.length === 1 ? 'volume' : 'volumes' }}
                </span>
              </div>

              <div
                v-if="monitorVolumes.length"
                class="monitor-storage-grid"
              >
                <div
                  v-for="volume in monitorVolumes"
                  :key="`${volume.device}-${volume.mountpoint}`"
                  class="monitor-storage-card"
                >
                  <div class="monitor-storage-title-row">
                    <div class="monitor-storage-title-wrap">
                      <strong>{{ volume.name || volume.mountpoint || 'Volume' }}</strong>
                      <span
                        v-if="volume.system"
                        class="monitor-storage-system-badge"
                      >System</span>
                    </div>
                    <span>{{ formatPercent(volume.percent) }}</span>
                  </div>

                  <el-progress
                    :percentage="normalizePercent(volume.percent)"
                    :color="monitorUsageProgressColor(volume.percent)"
                    :show-text="false"
                    :stroke-width="7"
                  />

                  <div class="monitor-storage-usage">
                    {{ formatBytes(volume.used) }} used · {{ formatBytes(volume.free) }} free · {{ formatBytes(volume.total) }} total
                  </div>
                  <div class="monitor-storage-meta">
                    <span>{{ volume.mountpoint || '-' }}</span>
                    <span>{{ formatVolumeMeta(volume) }}</span>
                  </div>
                </div>
              </div>

              <div
                v-else
                class="empty-state compact monitor-storage-empty"
              >
                {{ monitorStatus === 'opening' ? 'Waiting for storage data…' : 'No volumes available' }}
              </div>
            </div>
          </div>
        </el-tab-pane>

        <el-tab-pane
          label="Commands"
          name="commands"
          class="connection-info-tab-pane connection-info-command-tab"
        >
          <div class="connection-command-panel">
            <div class="connection-command-panel-title">
              Command List
            </div>

            <div class="connection-command-list">
              <div
                v-for="(item, index) in connectionInfoClientCommands"
                :key="`${item.template}-${index}`"
                class="connection-command-item"
              >
                <div class="connection-command-group">
                  <span v-if="item.group">{{ item.group }}</span>
                </div>

                <div class="connection-command-text">
                  <span class="mono">{{ item.name || item.template }}</span>
                  <span v-if="item.help"> — {{ item.help }}</span>
                </div>
              </div>

              <div
                v-if="!connectionInfoClientCommands.length"
                class="empty-state compact"
              >
                No commands available
              </div>
            </div>
          </div>
        </el-tab-pane>

        <el-tab-pane
          label="Configuration"
          name="configuration"
          class="connection-info-tab-pane"
        >
          <div
            class="connection-info-tab-scroll"
            v-loading="runtimeConfigLoading"
          >
            <div
              v-if="runtimeConfigError"
              class="empty-state compact"
            >
              {{ runtimeConfigError }}
            </div>

            <div
              v-else-if="runtimeConfigItems.length"
              class="connection-info-stats-grid"
            >
              <div
                v-for="item in runtimeConfigItems"
                :key="item.key"
                class="connection-info-stat connection-config-stat"
                :class="{ 'connection-config-stat-editable': item.editable !== false }"
                :title="item.editable !== false ? 'Double-click to edit' : ''"
                @dblclick="openRuntimeConfigEditor(item)"
              >
                <div class="connection-config-stat-head">
                  <div class="connection-info-stat-label">
                    {{ item.key }}
                  </div>
                  <span
                    v-if="item.source === 'override'"
                    class="connection-config-override-badge"
                  >
                    override
                  </span>
                </div>

                <div class="connection-info-stat-value">
                  {{ formatRuntimeConfigValue(item.value) }}
                </div>
              </div>
            </div>

            <div
              v-else-if="!runtimeConfigLoading"
              class="empty-state compact"
            >
              No runtime configuration available
            </div>
          </div>
        </el-tab-pane>

        <el-tab-pane
          label="Variables"
          name="variables"
          class="connection-info-tab-pane"
        >
          <div class="connection-info-tab-scroll">
            <div
              v-if="variableManifestItems.length"
              class="connection-info-stats-grid"
            >
              <div
                v-for="item in variableManifestItems"
                :key="item.template"
                class="connection-info-stat"
              >
                <div class="connection-info-stat-label connection-variable-template mono">
                  {{ item.template }}
                </div>

                <div class="connection-info-stat-value connection-variable-description">
                  {{ item.description || '-' }}
                </div>
              </div>
            </div>

            <div
              v-else
              class="empty-state compact"
            >
              No command variables available
            </div>
          </div>
        </el-tab-pane>
      </el-tabs>
    </div>
  </el-dialog>

  <el-dialog
    v-model="valueVisible"
    :title="valueTitle || 'Details'"
    width="760px"
    top="12vh"
    class="fixed-dialog connection-info-value-dialog"
    modal-class="connection-info-value-overlay"
  >
    <div class="fixed-dialog-body connection-info-value-body">
      <pre class="connection-info-full-value">{{ valueValue || '-' }}</pre>
    </div>
  </el-dialog>

  <el-dialog
    v-model="runtimeConfigEditorVisible"
    title="Edit Configuration"
    width="560px"
    top="14vh"
    class="connection-config-editor-dialog"
    modal-class="connection-config-editor-overlay"
    :close-on-click-modal="true"
  >
    <div
      v-if="runtimeConfigEditorItem"
      class="connection-config-editor"
    >
      <div class="connection-config-editor-key-row">
        <span class="connection-config-editor-key">
          {{ runtimeConfigEditorItem.key }}
        </span>
        <span
          v-if="runtimeConfigEditorItem.source === 'override'"
          class="connection-config-override-badge"
        >
          override
        </span>
      </div>

      <div
        v-if="runtimeConfigEditorItem.desc"
        class="connection-config-editor-desc"
      >
        {{ runtimeConfigEditorItem.desc }}
      </div>

      <div class="connection-config-editor-meta">
        <div>
          <span>Current</span>
          <strong>{{ formatRuntimeConfigValue(runtimeConfigEditorItem.value) }}</strong>
        </div>
        <div>
          <span>Default</span>
          <strong>{{ formatRuntimeConfigValue(runtimeConfigEditorItem.default_value) }}</strong>
        </div>
      </div>

      <div class="connection-config-editor-control">
        <el-select
          v-if="runtimeConfigEditorChoices.length"
          v-model="runtimeConfigEditorValue"
          style="width: 100%"
        >
          <el-option
            v-for="choice in runtimeConfigEditorChoices"
            :key="`${runtimeConfigEditorItem.key}:${choice.value}`"
            :label="choice.label"
            :value="choice.value"
          />
        </el-select>

        <el-switch
          v-else-if="runtimeConfigEditorItem.value_type === 'boolean'"
          v-model="runtimeConfigEditorValue"
        />

        <el-input-number
          v-else-if="runtimeConfigEditorItem.value_type === 'integer'"
          v-model="runtimeConfigEditorValue"
          :min="runtimeConfigEditorNumberMin"
          :max="runtimeConfigEditorNumberMax"
          :step="runtimeConfigEditorNumberStep ?? 1"
          controls-position="right"
          style="width: 100%"
        />

        <el-input-number
          v-else-if="runtimeConfigEditorItem.value_type === 'float'"
          v-model="runtimeConfigEditorValue"
          :min="runtimeConfigEditorNumberMin"
          :max="runtimeConfigEditorNumberMax"
          :step="runtimeConfigEditorNumberStep"
          controls-position="right"
          style="width: 100%"
        />

        <el-input
          v-else
          v-model="runtimeConfigEditorValue"
        />
      </div>
    </div>

    <template #footer>
      <div class="connection-config-editor-footer">
        <el-button
          :disabled="runtimeConfigSaving || runtimeConfigEditorItem?.source !== 'override'"
          @click="resetRuntimeConfigEditorItem"
        >
          Reset Default
        </el-button>

        <div class="connection-config-editor-footer-right">
          <el-button
            :disabled="runtimeConfigSaving"
            @click="runtimeConfigEditorVisible = false"
          >
            Cancel
          </el-button>
          <el-button
            type="primary"
            :loading="runtimeConfigSaving"
            @click="saveRuntimeConfigEditorItem"
          >
            Save
          </el-button>
        </div>
      </div>
    </template>
  </el-dialog>
</template>

<script>
import { formatBytesHuman, formatDateTimeStandard as formatDateTimeStandardValue } from '../utils/formatters.js'
import { ElMessage } from 'element-plus'

export default {
  name: 'ConnectionInfoDialogs',

  props: {
    selectedId: {
      type: [String, Number],
      default: '',
    },

    currentConnection: {
      type: Object,
      default: null,
    },

    statusNowTick: {
      type: Number,
      default: () => Date.now(),
    },

    tabId: {
      type: String,
      default: '',
    },
  },

  data() {
    return {
      infoVisible: false,
      valueVisible: false,
      loading: false,
      jobCount: 0,
      valueTitle: '',
      valueValue: '',
      connectionInfoClientCommands: [],
      activeTab: 'basic',
      runtimeConfigItems: [],
      runtimeConfigStorePath: '',
      runtimeConfigLoading: false,
      runtimeConfigLoaded: false,
      runtimeConfigError: '',
      runtimeConfigEditorVisible: false,
      runtimeConfigEditorItem: null,
      runtimeConfigEditorValue: '',
      runtimeConfigSaving: false,
      monitorSessionId: '',
      monitorStatus: 'idle',
      monitorError: '',
      monitorLastUpdatedAt: 0,
      monitorStarting: false,
      monitorChannels: {
        system: {},
        storage: { volumes: [] },
        network: {},
        battery: { available: false },
      },
    }
  },

  computed: {
    connectionInfoCards() {
      const conn = this.currentConnection || {}
      const items = [
        { label: 'Status', value: this.formatStatusText(conn) },
        { label: 'Hostname', value: conn.hostname || '-' },
        { label: 'Address', value: conn.addr || '-', mono: true },
        { label: 'Client ID', value: conn.client_id || '-', mono: true },
        { label: 'OS Type', value: conn.os_type },
        { label: 'Platform', value: conn.os_full || '-' },
        { label: 'OS Name', value: conn.os_name },
        { label: 'OS Version', value: conn.os_ver },
        { label: 'OS Alias', value: conn.os_alias },
        { label: 'Arch', value: conn.arch },
        { label: 'Manufacturer', value: conn.manufacturer },
        { label: 'Model', value: conn.model },
        { label: 'Integrity', value: conn.integrity || '-' },
        { label: 'Build Version', value: conn.build_version || '-' },
        { label: 'Client Revision', value: conn.client_revision || '-', mono: true },
        { label: 'Machine ID', value: conn.machine_id || '-', mono: true },
        { label: 'Fingerprint Basis', value: conn.machine_fingerprint_basis || '-', mono: true },
        { label: 'Last Seen', value: this.formatLastSeenText(conn) },
        { label: 'Connected At', value: this.formatDateTimeStandard(conn.connected_at) || '-' },
        { label: 'Disconnected At', value: this.formatDateTimeStandard(conn.disconnected_at) || '-' },
        { label: 'RTT', value: this.formatRttText(conn) },
        { label: 'Working Directory', value: conn.cwd || '-', mono: true },
        { label: 'PID', value: conn.process_id || '-' },
        { label: 'Process Name', value: conn.process_name || '-' },
        { label: 'Launch Command', value: conn.launch_command || '-' },
        { label: 'Username', value: conn.username || '-' },
        { label: 'Python Version', value: conn.python_ver || '-' },
        { label: 'Reported Jobs', value: this.jobCount },
        { label: 'Command Count', value: this.connectionInfoClientCommands.length },
      ]

      return items.map(item => {
        const fullValue = this.normalizeConnectionInfoValue(item.value)
        return {
          ...item,
          fullValue,
          expandable: this.isConnectionInfoValueExpandable(fullValue),
        }
      })
    },

    monitorSystem() {
      return this.monitorChannels.system || {}
    },

    monitorNetwork() {
      return this.monitorChannels.network || {}
    },

    monitorBattery() {
      return this.monitorChannels.battery || { available: false }
    },

    monitorVolumes() {
      const volumes = this.monitorChannels.storage?.volumes
      return Array.isArray(volumes) ? volumes : []
    },

    monitorDisplayState() {
      if (this.monitorError || this.monitorStatus === 'error') return 'error'
      if (this.monitorStatus === 'open' || this.monitorStatus === 'live') return 'live'
      if (this.monitorStatus === 'opening') return 'opening'
      if (this.getConnectionDisplayState(this.currentConnection || {}) === 'offline') return 'offline'
      return 'idle'
    },

    monitorDisplayLabel() {
      const labels = {
        live: 'LIVE · 500 ms',
        opening: 'CONNECTING',
        offline: 'OFFLINE',
        error: 'ERROR',
        idle: 'IDLE',
      }
      return labels[this.monitorDisplayState] || 'IDLE'
    },

    monitorUpdatedText() {
      if (!this.monitorLastUpdatedAt) {
        if (this.monitorStatus === 'opening') return 'Waiting for metrics…'
        return 'No live data'
      }

      const ageMs = Math.max(Number(this.statusNowTick || Date.now()) - this.monitorLastUpdatedAt, 0)
      if (ageMs < 1000) return 'Updated <1s ago'
      if (ageMs < 60000) return `Updated ${Math.floor(ageMs / 1000)}s ago`
      return `Updated ${Math.floor(ageMs / 60000)}m ago`
    },

    monitorNetworkInterfaceText() {
      const name = String(this.monitorNetwork.interface || '').trim()
      const ipv4 = String(this.monitorNetwork.ipv4 || '').trim()
      if (name && ipv4) return `${name} · ${ipv4}`
      return name || ipv4 || 'Active interface unavailable'
    },

    runtimeConfigEditorNumberMin() {
      const value = Number(this.runtimeConfigEditorItem?.min_value)
      return Number.isFinite(value) ? value : undefined
    },

    runtimeConfigEditorNumberMax() {
      const value = Number(this.runtimeConfigEditorItem?.max_value)
      return Number.isFinite(value) ? value : undefined
    },

    runtimeConfigEditorNumberStep() {
      const value = Number(this.runtimeConfigEditorItem?.step)
      return Number.isFinite(value) && value > 0 ? value : undefined
    },

    runtimeConfigEditorChoices() {
      const choices = this.runtimeConfigEditorItem?.choices
      if (!Array.isArray(choices)) return []

      return choices.map(choice => {
        const value = this.normalizeRuntimeConfigSelectValue(choice)
        return {
          label: String(choice),
          value,
        }
      })
    },

    variableManifestItems() {
      const manifest = this.currentConnection?.variable_manifest
      if (!Array.isArray(manifest)) return []

      return manifest
        .filter(item => item && item.template)
        .map(item => ({
          ...item,
          template: String(item.template || '').trim(),
          description: String(item.description || '').trim(),
          namespace: String(item.namespace || '').trim(),
          name: String(item.name || '').trim(),
        }))
    },
  },

  watch: {
    activeTab(value, previousValue) {
      if (value === 'configuration' && this.infoVisible && !this.runtimeConfigLoaded) {
        this.loadRuntimeConfig(this.selectedId)
      }

      if (value === 'dashboard' && this.infoVisible) {
        void this.startDeviceMonitor()
      } else if (previousValue === 'dashboard') {
        void this.stopDeviceMonitor()
      }
    },

    infoVisible(value) {
      if (!value) {
        void this.stopDeviceMonitor()
      }
    },
  },

  mounted() {
    window.addEventListener('pagehide', this.handleDeviceMonitorPageHide)
  },

  beforeUnmount() {
    window.removeEventListener('pagehide', this.handleDeviceMonitorPageHide)
    void this.stopDeviceMonitor()
  },

  methods: {
    async open() {
      if (!this.selectedId) {
        ElMessage.warning('Please select a device')
        return
      }

      this.infoVisible = true
      this.loading = true
      this.jobCount = 0
      this.valueVisible = false
      this.valueTitle = ''
      this.valueValue = ''
      this.connectionInfoClientCommands = []
      this.activeTab = 'basic'
      this.runtimeConfigItems = []
      this.runtimeConfigStorePath = ''
      this.runtimeConfigLoaded = false
      this.runtimeConfigError = ''
      this.runtimeConfigEditorVisible = false
      this.runtimeConfigEditorItem = null
      this.resetDeviceMonitorState()

      try {
        await Promise.all([
          this.loadConnectionInfoClientCommands(this.selectedId),
          this.loadConnectionInfoJobCount(this.selectedId),
        ])
      } catch (e) {
      } finally {
        this.loading = false
      }
    },

    resetDeviceMonitorState() {
      this.monitorSessionId = ''
      this.monitorStatus = 'idle'
      this.monitorError = ''
      this.monitorLastUpdatedAt = 0
      this.monitorStarting = false
      this.monitorChannels = {
        system: {},
        storage: { volumes: [] },
        network: {},
        battery: { available: false },
      }
    },

    async startDeviceMonitor() {
      if (!this.infoVisible || this.activeTab !== 'dashboard' || !this.selectedId) return
      if (this.monitorSessionId || this.monitorStarting) return

      this.monitorStarting = true
      this.monitorStatus = 'opening'
      this.monitorError = ''
      this.monitorLastUpdatedAt = 0
      this.monitorChannels = {
        system: {},
        storage: { volumes: [] },
        network: {},
        battery: { available: false },
      }

      try {
        const headers = { 'Content-Type': 'application/json' }
        if (this.tabId) headers['X-Tab-Id'] = this.tabId

        const res = await fetch(
          `/api/connections/${encodeURIComponent(this.selectedId)}/device-monitor/open`,
          {
            method: 'POST',
            headers,
            body: JSON.stringify({
              channels: ['system', 'storage', 'network', 'battery'],
              intervals: {
                system: 0.5,
                network: 0.5,
                storage: 5,
                battery: 5,
              },
            }),
          },
        )
        const json = await res.json()
        if (!res.ok || json.code !== 0) {
          throw new Error(json.message || 'Failed to open device monitor')
        }

        const sessionId = String(json.data?.monitor_session_id || '').trim()
        if (!sessionId) {
          throw new Error('Device monitor did not return a session id')
        }

        this.monitorSessionId = sessionId
        this.monitorStatus = String(json.data?.status || 'opening')

        if (!this.infoVisible || this.activeTab !== 'dashboard') {
          await this.stopDeviceMonitor()
        }
      } catch (e) {
        this.monitorStatus = 'error'
        this.monitorError = e?.message || 'Failed to open device monitor'
      } finally {
        this.monitorStarting = false
      }
    },

    async stopDeviceMonitor(keepalive = false) {
      const sessionId = String(this.monitorSessionId || '').trim()
      this.monitorSessionId = ''
      if (this.monitorStatus !== 'error') this.monitorStatus = 'idle'
      if (!sessionId) return

      try {
        const headers = {}
        if (this.tabId) headers['X-Tab-Id'] = this.tabId
        await fetch(`/api/device-monitor/${encodeURIComponent(sessionId)}/close`, {
          method: 'POST',
          headers,
          keepalive: Boolean(keepalive),
        })
      } catch (_e) {
      }
    },

    handleDeviceMonitorPageHide() {
      if (!this.monitorSessionId) return
      void this.stopDeviceMonitor(true)
    },

    handleDeviceMonitorSnapshot(payload = {}) {
      if (!this.infoVisible || this.activeTab !== 'dashboard') return
      if (String(payload.monitor_session_id || '') !== String(this.monitorSessionId || '')) return
      if (String(payload.client_id || '') !== String(this.selectedId || '')) return

      const channel = String(payload.channel || '').trim().toLowerCase()
      if (!['system', 'storage', 'network', 'battery'].includes(channel)) return

      this.monitorChannels = {
        ...this.monitorChannels,
        [channel]: payload.data && typeof payload.data === 'object' ? payload.data : {},
      }
      this.monitorStatus = 'live'
      this.monitorError = ''

      const collectedAt = Number(payload.collected_at || 0)
      this.monitorLastUpdatedAt = collectedAt > 0
        ? collectedAt * 1000
        : Date.now()
    },

    handleDeviceMonitorStatus(payload = {}) {
      if (String(payload.monitor_session_id || '') !== String(this.monitorSessionId || '')) return
      const state = String(payload.state || payload.status || '').trim().toLowerCase()

      if (state === 'open') {
        this.monitorStatus = 'open'
        this.monitorError = ''
        return
      }

      if (state === 'error') {
        this.monitorStatus = 'error'
        this.monitorError = String(payload.error || 'Device monitor failed')
        return
      }

      if (state === 'closed') {
        this.monitorStatus = 'idle'
      }
    },

    normalizePercent(value) {
      const numeric = Number(value)
      if (!Number.isFinite(numeric)) return 0
      return Math.max(0, Math.min(100, numeric))
    },

    monitorUsageProgressColor(value) {
      const percent = this.normalizePercent(value)
      if (percent >= 95) return '#f56c6c'
      if (percent >= 85) return '#e6a23c'
      if (percent >= 70) return '#d6b93f'
      return '#409eff'
    },

    formatPercent(value) {
      const numeric = Number(value)
      if (!Number.isFinite(numeric)) return '—'
      return `${Math.round(numeric * 10) / 10}%`
    },

    formatBytes(value) {
      return formatBytesHuman(value, { precision: 'adaptive', maxUnit: 'PB', invalid: '—', nonPositiveAsZero: false })
    },

    formatUsagePair(used, total) {
      const usedNumber = Number(used)
      const totalNumber = Number(total)
      if (!Number.isFinite(usedNumber) || !Number.isFinite(totalNumber) || totalNumber <= 0) return '—'
      return `${this.formatBytes(usedNumber)} / ${this.formatBytes(totalNumber)}`
    },

    formatRate(value) {
      const text = this.formatBytes(value)
      return text === '—' ? '—' : `${text}/s`
    },

    formatUptime(value) {
      const seconds = Number(value)
      if (!Number.isFinite(seconds) || seconds < 0) return '—'
      const totalMinutes = Math.floor(seconds / 60)
      const days = Math.floor(totalMinutes / 1440)
      const hours = Math.floor((totalMinutes % 1440) / 60)
      const minutes = totalMinutes % 60

      if (days > 0) return `${days}d ${hours}h`
      if (hours > 0) return `${hours}h ${minutes}m`
      return `${minutes}m`
    },

    formatVolumeMeta(volume) {
      const fstype = String(volume?.fstype || '').trim()
      const kind = String(volume?.kind || '').trim()
      const parts = []
      if (fstype) parts.push(fstype.toUpperCase())
      if (kind) parts.push(kind.charAt(0).toUpperCase() + kind.slice(1))
      return parts.join(' · ') || 'Volume'
    },

    async loadConnectionInfoClientCommands(clientId) {
      const res = await fetch(`/api/connections/${encodeURIComponent(clientId)}/command-candidates`)
      const json = await res.json()

      if (!res.ok || json.code !== 0) {
        throw new Error(json.message || 'Failed to load command candidates')
      }

      this.connectionInfoClientCommands = (Array.isArray(json.data) ? json.data : [])
        .filter(item => item && item.source === 'client' && item.suggest !== false)
        .map(item => this.normalizeConnectionInfoCommand(item))
    },

    async loadConnectionInfoJobCount(clientId) {
      const res = await fetch(`/api/connections/${encodeURIComponent(clientId)}/background-jobs`)
      const json = await res.json()

      if (res.ok && json.code === 0 && Array.isArray(json.data)) {
        this.jobCount = json.data.length
      }
    },

    async loadRuntimeConfig(clientId) {
      if (!clientId || this.runtimeConfigLoading) return

      this.runtimeConfigLoading = true
      this.runtimeConfigError = ''

      try {
        const res = await fetch(`/api/connections/${encodeURIComponent(clientId)}/runtime-config`)
        const json = await res.json()

        if (!res.ok || json.code !== 0) {
          throw new Error(json.message || 'Failed to load runtime configuration')
        }

        this.applyRuntimeConfigPayload(json.data)
        this.runtimeConfigLoaded = true
      } catch (e) {
        this.runtimeConfigItems = []
        this.runtimeConfigLoaded = false
        this.runtimeConfigError = e?.message || 'Failed to load runtime configuration'
      } finally {
        this.runtimeConfigLoading = false
      }
    },

    applyRuntimeConfigPayload(payload) {
      const data = payload && typeof payload === 'object' ? payload : {}
      this.runtimeConfigStorePath = String(data.store_path || '')
      this.runtimeConfigItems = Array.isArray(data.items)
        ? data.items.filter(item => item && item.key)
        : []
    },

    normalizeConnectionInfoCommand(item) {
      const template = String(item.template || '').trim()
      const name = String(item.name || template || '').trim()
      const help = String(item.help || '').trim()
      const group = String(item.group || '').trim()
      const source = String(item.source || '').trim()

      return {
        ...item,
        value: template,
        name,
        template,
        help,
        group,
        source,
      }
    },

    // 连接状态展示逻辑放在组件内，避免继续依赖 legacy connection formatter。
    getConnectionDisplayState(conn) {
      const state = String((conn && conn.connection_state) || '').trim()
      if (state === 'offline') return 'offline'

      if (conn && conn.is_transfer_active) {
        return 'online'
      }

      const disconnectedAt = String((conn && conn.disconnected_at) || '').trim()
      if (disconnectedAt) return 'offline'

      const lastSeenAt = String((conn && conn.last_seen_at) || '').trim()
      if (!lastSeenAt) return state || 'online'

      const staleAfterSeconds = Number((conn && conn.stale_after_seconds) || 45)
      const seenMs = Date.parse(lastSeenAt)
      if (!Number.isFinite(seenMs)) return state || 'online'

      const ageMs = Math.max(this.statusNowTick - seenMs, 0)
      if (ageMs > staleAfterSeconds * 1000) return 'stale'

      return 'online'
    },

    formatStatusText(conn) {
      const state = this.getConnectionDisplayState(conn)
      if (state === 'online') return 'online'
      if (state === 'stale') return 'stale'
      return 'offline'
    },

    formatLastSeenText(conn) {
      if (!conn) return '-'

      const state = this.getConnectionDisplayState(conn)
      if (state === 'offline') {
        return this.formatDateTimeStandard(conn.disconnected_at) || '-'
      }

      return this.formatDateTimeStandard(conn.last_seen_at) || '-'
    },

    formatDateTimeStandard(value) {
      return formatDateTimeStandardValue(value)
    },

    formatRttText(conn) {
      const value = conn && conn.last_rtt_ms
      if (value === null || value === undefined || value === '') return '-'
      return `${value} ms`
    },

    normalizeConnectionInfoValue(value) {
      if (value === null || value === undefined || value === '') return '-'
      if (typeof value === 'boolean') return value ? 'true' : 'false'
      if (Array.isArray(value)) {
        return value.length ? value.join(', ') : '-'
      }
      if (typeof value === 'object') {
        try {
          return JSON.stringify(value, null, 2)
        } catch (_error) {
          return String(value)
        }
      }
      return String(value)
    },

    isConnectionInfoValueExpandable(value) {
      const text = this.normalizeConnectionInfoValue(value)
      if (!text || text === '-') return false
      return text.length > 42 || text.includes('\n')
    },

    openConnectionInfoValueDialog(item) {
      if (!item) return
      this.valueTitle = item.label || 'Details'
      this.valueValue = item.fullValue || '-'
      this.valueVisible = true
    },

    formatRuntimeConfigValue(value) {
      if (value === null || value === undefined) return 'None'
      if (typeof value === 'boolean') return value ? 'true' : 'false'
      return String(value)
    },

    openRuntimeConfigEditor(item) {
      if (!item || item.editable === false) return

      this.runtimeConfigEditorItem = item
      this.runtimeConfigEditorValue = this.normalizeRuntimeConfigEditorValue(item)
      this.runtimeConfigEditorVisible = true
    },

    normalizeRuntimeConfigEditorValue(item) {
      const choices = Array.isArray(item?.choices) ? item.choices : []
      if (choices.length) {
        const currentValue = this.normalizeRuntimeConfigSelectValue(item?.value)
        const matchedChoice = choices
          .map(choice => this.normalizeRuntimeConfigSelectValue(choice))
          .find(choice => choice === currentValue)
        return matchedChoice !== undefined ? matchedChoice : currentValue
      }

      const valueType = String(item?.value_type || '')
      const value = item?.value
      if (valueType === 'boolean') return Boolean(value)
      if (valueType === 'integer' || valueType === 'float') {
        const numeric = Number(value)
        return Number.isFinite(numeric) ? numeric : 0
      }
      if (value === null || value === undefined) return ''
      return String(value)
    },

    normalizeRuntimeConfigSelectValue(value) {
      if (value === null || value === undefined) return ''
      return String(value).trim()
    },

    async saveRuntimeConfigEditorItem() {
      const item = this.runtimeConfigEditorItem
      if (!item || !this.selectedId || this.runtimeConfigSaving) return

      this.runtimeConfigSaving = true

      try {
        const res = await fetch(
          `/api/connections/${encodeURIComponent(this.selectedId)}/runtime-config/${encodeURIComponent(item.key)}`,
          {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ value: this.runtimeConfigEditorValue }),
          },
        )
        const json = await res.json()

        if (!res.ok || json.code !== 0) {
          throw new Error(json.message || 'Failed to update runtime configuration')
        }

        this.applyRuntimeConfigPayload(json.data)
        this.runtimeConfigLoaded = true
        this.runtimeConfigEditorVisible = false
        ElMessage.success(`${item.key} updated`)
      } catch (e) {
        ElMessage.error(e?.message || 'Failed to update runtime configuration')
      } finally {
        this.runtimeConfigSaving = false
      }
    },

    async resetRuntimeConfigEditorItem() {
      const item = this.runtimeConfigEditorItem
      if (!item || !this.selectedId || item.source !== 'override' || this.runtimeConfigSaving) return

      this.runtimeConfigSaving = true

      try {
        const res = await fetch(
          `/api/connections/${encodeURIComponent(this.selectedId)}/runtime-config/${encodeURIComponent(item.key)}`,
          { method: 'DELETE' },
        )
        const json = await res.json()

        if (!res.ok || json.code !== 0) {
          throw new Error(json.message || 'Failed to reset runtime configuration')
        }

        this.applyRuntimeConfigPayload(json.data)
        this.runtimeConfigLoaded = true
        this.runtimeConfigEditorVisible = false
        ElMessage.success(`${item.key} reset to default`)
      } catch (e) {
        ElMessage.error(e?.message || 'Failed to reset runtime configuration')
      } finally {
        this.runtimeConfigSaving = false
      }
    },
  },
}
</script>

<style scoped>
.connection-info-body {
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.connection-info-tabs {
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.connection-info-tabs :deep(.el-tabs__header) {
  flex: 0 0 auto;
  margin-bottom: 12px;
}

.connection-info-tabs :deep(.el-tabs__content) {
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
}

.connection-info-tabs :deep(.el-tab-pane) {
  height: 100%;
  min-height: 0;
}

.connection-info-tab-pane {
  height: 100%;
  min-height: 0;
}

.connection-info-tab-scroll {
  height: 100%;
  min-height: 0;
  overflow-y: auto;
  padding-right: 2px;
}

.connection-info-stats-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.connection-info-stat {
  display: flex;
  flex-direction: column;
  justify-content: flex-start;
  overflow: hidden;
  min-width: 0;
  padding: 12px 14px;
  border-radius: 12px;
  background: #f8fafc;
  border: 1px solid rgba(15, 23, 42, 0.05);
}

.connection-info-stat-label {
  font-size: 12px;
  line-height: 16px;
  font-weight: 400;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  overflow: hidden;
  word-break: break-word;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  min-height: 16px;
  font-family: inherit;
}

.connection-info-stat-value {
  margin-top: 4px;
  font-size: 13px;
  line-height: 18px;
  font-weight: 400;
  color: var(--text);
  overflow: hidden;
  word-break: break-word;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  min-height: 36px;
  font-family: inherit;
}

.connection-info-stat .mono {
  font-family: inherit !important;
  font-size: 13px;
  line-height: 18px;
  font-weight: 400;
}

.connection-info-stat-expandable {
  cursor: pointer;
  transition: border-color 0.18s ease, background 0.18s ease, box-shadow 0.18s ease;
}

.connection-info-stat-expandable:hover,
.connection-config-stat-editable:hover {
  background: #f3f7ff;
  border-color: rgba(37, 99, 235, 0.18);
  box-shadow: 0 0 0 1px rgba(37, 99, 235, 0.05);
}

.connection-variable-template {
  text-transform: none;
  letter-spacing: 0;
}

.connection-variable-description {
  white-space: normal;
  word-break: break-word;
}

.connection-config-stat-editable {
  cursor: pointer;
  transition: border-color 0.18s ease, background 0.18s ease, box-shadow 0.18s ease;
}

.connection-config-stat-head {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  min-width: 0;
}

.connection-config-stat-head .connection-info-stat-label {
  flex: 1 1 auto;
  min-width: 0;
}

.connection-config-override-badge {
  flex: 0 0 auto;
  padding: 1px 6px;
  border-radius: 999px;
  background: #fff7ed;
  border: 1px solid #fed7aa;
  color: #c2410c;
  font-size: 10px;
  line-height: 16px;
  font-weight: 400;
  text-transform: none;
  letter-spacing: 0;
}

.connection-info-command-tab {
  display: flex;
  flex-direction: column;
}

.connection-command-panel {
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  border: 1px solid rgba(15, 23, 42, 0.06);
  border-radius: 12px;
  background: #fafcff;
  overflow: hidden;
}

.connection-command-panel-title {
  flex: 0 0 auto;
  padding: 10px 12px;
  font-size: 13px;
  font-weight: 700;
  border-bottom: 1px solid rgba(15, 23, 42, 0.06);
  background: #f8fafc;
}

.connection-command-list {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.connection-command-item {
  padding: 10px 12px;
  border-radius: 10px;
  background: #fff;
  border: 1px solid rgba(15, 23, 42, 0.05);
}

.connection-command-group {
  min-height: 13px;
  font-size: 11px;
  color: var(--muted-2);
  margin-bottom: 6px;
}

.connection-command-text {
  font-size: 13px;
  line-height: 1.6;
  color: var(--text);
  white-space: pre-wrap;
  word-break: break-word;
}

.connection-info-full-value {
  margin: 0;
  padding: 14px;
  min-height: 220px;
  max-height: 62vh;
  overflow: auto;
  border-radius: 14px;
  background: #f8fafc;
  border: 1px solid rgba(15, 23, 42, 0.06);
  color: var(--text);
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.65;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 13px;
}

.connection-config-editor {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.connection-config-editor-key-row {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.connection-config-editor-key {
  min-width: 0;
  overflow-wrap: anywhere;
  color: var(--text);
  font-size: 14px;
  font-weight: 700;
}

.connection-config-editor-desc {
  color: var(--muted);
  font-size: 13px;
  line-height: 1.6;
}

.connection-config-editor-meta {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.connection-config-editor-meta > div {
  min-width: 0;
  padding: 10px 12px;
  border-radius: 10px;
  background: #f8fafc;
  border: 1px solid rgba(15, 23, 42, 0.06);
}

.connection-config-editor-meta span,
.connection-config-editor-meta strong {
  display: block;
}

.connection-config-editor-meta span {
  color: var(--muted);
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.connection-config-editor-meta strong {
  margin-top: 4px;
  color: var(--text);
  font-size: 13px;
  font-weight: 500;
  overflow-wrap: anywhere;
}

.connection-config-editor-control {
  min-height: 40px;
  display: flex;
  align-items: center;
}

.connection-config-editor-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.connection-config-editor-footer-right {
  display: flex;
  gap: 10px;
}


.monitor-dashboard-scroll {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.monitor-dashboard-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 2px 2px 0;
}

.monitor-dashboard-title {
  color: var(--text);
  font-size: 15px;
  line-height: 22px;
  font-weight: 700;
}

.monitor-dashboard-subtitle,
.monitor-updated-text,
.monitor-section-subtitle {
  margin-top: 2px;
  color: var(--muted);
  font-size: 12px;
  line-height: 18px;
}

.monitor-live-block {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 3px;
}

.monitor-live-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 24px;
  padding: 2px 8px;
  border-radius: 999px;
  background: #f8fafc;
  border: 1px solid rgba(15, 23, 42, 0.08);
  color: var(--muted);
  font-size: 11px;
  line-height: 18px;
  font-weight: 600;
  letter-spacing: 0.02em;
}

.monitor-live-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #94a3b8;
}

.monitor-live-live {
  color: #15803d;
  background: #f0fdf4;
  border-color: #bbf7d0;
}

.monitor-live-live .monitor-live-dot {
  background: #22c55e;
}

.monitor-live-opening {
  color: #1d4ed8;
  background: #eff6ff;
  border-color: #bfdbfe;
}

.monitor-live-opening .monitor-live-dot {
  background: #3b82f6;
}

.monitor-live-error,
.monitor-live-offline {
  color: #b91c1c;
  background: #fef2f2;
  border-color: #fecaca;
}

.monitor-live-error .monitor-live-dot,
.monitor-live-offline .monitor-live-dot {
  background: #ef4444;
}

.monitor-dashboard-error {
  padding: 9px 11px;
  border-radius: 10px;
  border: 1px solid #fecaca;
  background: #fef2f2;
  color: #b91c1c;
  font-size: 12px;
  line-height: 18px;
  overflow-wrap: anywhere;
}

.monitor-overview-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.monitor-overview-card,
.monitor-section,
.monitor-storage-card {
  min-width: 0;
  border-radius: 12px;
  border: 1px solid rgba(15, 23, 42, 0.06);
  background: #f8fafc;
}

.monitor-overview-card {
  min-height: 138px;
  padding: 13px 14px;
}

.monitor-card-label,
.monitor-network-label {
  color: var(--muted);
  font-size: 11px;
  line-height: 16px;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.monitor-card-value {
  margin: 7px 0 9px;
  color: var(--text);
  font-size: 25px;
  line-height: 30px;
  font-weight: 700;
  letter-spacing: -0.02em;
}

.monitor-card-value-muted {
  color: var(--muted);
}

.monitor-card-empty-line {
  height: 6px;
  margin-bottom: 14px;
  border-radius: 999px;
  background: #e5e7eb;
}

.monitor-card-meta {
  margin-top: 8px;
  color: var(--muted);
  font-size: 11px;
  line-height: 16px;
  overflow-wrap: anywhere;
}

.monitor-card-meta-secondary {
  margin-top: 2px;
  color: var(--muted-2);
}

.monitor-runtime-value {
  font-size: 22px;
}

.monitor-runtime-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-top: 6px;
  color: var(--muted);
  font-size: 11px;
  line-height: 17px;
}

.monitor-runtime-row strong {
  color: var(--text);
  font-size: 12px;
  font-weight: 600;
}

.monitor-section {
  padding: 13px 14px;
}

.monitor-section-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.monitor-section-title {
  color: var(--text);
  font-size: 13px;
  line-height: 19px;
  font-weight: 700;
}

.monitor-network-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.monitor-network-item {
  display: flex;
  align-items: center;
  min-width: 0;
  gap: 12px;
  padding: 10px 12px;
  border-radius: 10px;
  background: #fff;
  border: 1px solid rgba(15, 23, 42, 0.05);
}

.monitor-network-arrow {
  flex: 0 0 auto;
  width: 28px;
  height: 28px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: #eff6ff;
  color: #2563eb;
  font-size: 16px;
  font-weight: 700;
}

.monitor-network-value {
  margin-top: 2px;
  color: var(--text);
  font-size: 16px;
  line-height: 22px;
  font-weight: 700;
}

.monitor-storage-section {
  margin-bottom: 2px;
}

.monitor-volume-count {
  flex: 0 0 auto;
  padding: 2px 7px;
  border-radius: 999px;
  background: #eef2ff;
  color: #4338ca;
  font-size: 10px;
  line-height: 16px;
  font-weight: 600;
}

.monitor-storage-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.monitor-storage-card {
  padding: 11px 12px;
  background: #fff;
}

.monitor-storage-title-row,
.monitor-storage-title-wrap,
.monitor-storage-meta {
  display: flex;
  align-items: center;
  min-width: 0;
}

.monitor-storage-title-row {
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 8px;
  color: var(--text);
  font-size: 12px;
}

.monitor-storage-title-wrap {
  gap: 6px;
  overflow: hidden;
}

.monitor-storage-title-wrap strong {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 700;
}

.monitor-storage-system-badge {
  flex: 0 0 auto;
  padding: 0 5px;
  border-radius: 999px;
  background: #f1f5f9;
  color: #475569;
  font-size: 9px;
  line-height: 15px;
  font-weight: 600;
}

.monitor-storage-usage {
  margin-top: 8px;
  color: var(--text);
  font-size: 11px;
  line-height: 17px;
}

.monitor-storage-meta {
  justify-content: space-between;
  gap: 8px;
  margin-top: 3px;
  color: var(--muted);
  font-size: 10px;
  line-height: 16px;
}

.monitor-storage-meta span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.monitor-storage-empty {
  padding: 16px 0 6px;
}

.monitor-overview-card :deep(.el-progress-bar__outer),
.monitor-storage-card :deep(.el-progress-bar__outer) {
  background: #e5e7eb;
}

@media (max-width: 900px) {
  .monitor-overview-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 620px) {
  .monitor-dashboard-head,
  .monitor-section-head {
    align-items: stretch;
    flex-direction: column;
  }

  .monitor-live-block {
    align-items: flex-start;
  }

  .monitor-overview-grid,
  .monitor-network-grid,
  .monitor-storage-grid {
    grid-template-columns: repeat(1, minmax(0, 1fr));
  }
}

@media (max-width: 1200px) {
  .connection-info-stats-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

@media (max-width: 860px) {
  .connection-info-stats-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 480px) {
  .connection-info-stats-grid,
  .connection-config-editor-meta {
    grid-template-columns: repeat(1, minmax(0, 1fr));
  }

  .connection-config-editor-footer {
    align-items: stretch;
    flex-direction: column;
  }

  .connection-config-editor-footer-right {
    justify-content: flex-end;
  }
}
</style>

<style>
/* ConnectionInfoDialogs: 主对话框固定高度，Tab 内容只在内部滚动。 */
.connection-info-overlay .el-dialog {
  height: 680px;
  max-height: 88vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.connection-info-overlay .el-dialog__header {
  flex: 0 0 auto;
}

.connection-info-overlay .el-dialog__body {
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden !important;
}

.connection-info-value-overlay .el-dialog__body {
  overflow: hidden !important;
}
</style>
