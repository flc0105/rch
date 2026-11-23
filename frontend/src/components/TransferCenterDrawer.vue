<template>
  <el-drawer
    v-model="visible"
    direction="rtl"
    size="430px"
    :with-header="false"
    class="transfer-center-drawer"
  >
    <div class="transfer-center-shell">
      <div class="transfer-center-header">
        <div>
          <div class="transfer-center-title">Transfers</div>
          <div class="transfer-center-subtitle">
            {{ activeTransfers.length }} active
          </div>
        </div>

        <div class="transfer-center-header-actions">
          <el-select
            class="transfer-machine-filter"
            size="small"
            :model-value="machineId"
            filterable
            clearable
            placeholder="All Machines"
            aria-label="Filter transfers by Machine ID"
            @change="$emit('filter-machine', $event || '')"
          >
            <el-option
              v-for="machine in machineOptions"
              :key="machine.machine_id"
              :value="machine.machine_id"
              :label="machine.label"
            />
          </el-select>
          <button
            class="transfer-center-close"
            type="button"
            title="Close"
            @click="visible = false"
          >
            <el-icon><Close /></el-icon>
          </button>
        </div>
      </div>

      <section v-if="activeTransfers.length" class="transfer-center-section">
        <div class="transfer-center-section-title">Active</div>

        <article
          v-for="transfer in activeTransfers"
          :key="transfer.transfer_id"
          class="transfer-card"
        >
          <div class="transfer-card-head">
            <div class="transfer-direction">{{ directionSymbol(transfer) }}</div>
            <div class="transfer-card-main">
              <div class="transfer-card-title">{{ displayName(transfer) }}</div>
              <div class="transfer-card-meta">{{ transferSubtitle(transfer) }}</div>
            </div>
            <div class="transfer-card-percent">
              {{ formatPercent(transfer.percent) }}
            </div>
          </div>

          <el-progress
            v-if="hasProgress(transfer)"
            :percentage="normalizedPercent(transfer.percent)"
            :stroke-width="6"
            :show-text="false"
          />
          <div v-else class="transfer-indeterminate" aria-hidden="true">
            <span></span>
          </div>

          <div class="transfer-card-status-row">
            <span>{{ stageLabel(transfer) }}</span>
            <span v-if="hasProgress(transfer)">
              {{ formatBytes(transfer.transferred_bytes) }} / {{ formatBytes(transfer.total_bytes) }}
            </span>
          </div>

          <div v-if="transfer.speed_bytes_per_sec > 0" class="transfer-card-detail">
            {{ formatRate(transfer.speed_bytes_per_sec) }}
            <template v-if="transfer.eta_seconds != null">
              · {{ formatEta(transfer.eta_seconds) }} left
            </template>
          </div>

          <div
            v-if="transfer.progress_supported === false && transfer.stage === 'staging'"
            class="transfer-card-detail"
          >
            Legacy HTTP mode · byte progress unavailable
          </div>

          <div class="transfer-card-actions">
            <button
              class="transfer-text-action is-danger"
              type="button"
              :disabled="transfer.cancel_supported === false || transfer.stage === 'cancelling'"
              @click="cancelActiveTransfer(transfer)"
            >
              {{ transfer.stage === 'cancelling' ? 'Cancelling…' : 'Cancel' }}
            </button>
          </div>
        </article>
      </section>

      <section v-if="recentTransfers.length" class="transfer-center-section transfer-center-recent">
        <div class="transfer-center-section-heading">
          <div class="transfer-center-section-title">Recent</div>
          <button class="transfer-text-action" type="button" @click="clearRecent">Clear Recent</button>
        </div>

        <article
          v-for="transfer in recentTransfers"
          :key="transfer.transfer_id"
          class="transfer-recent-row"
        >
          <div
            class="transfer-recent-icon"
            :class="transfer.state === 'failed' ? 'is-failed' : (['cancelled', 'interrupted'].includes(transfer.state) ? 'is-cancelled' : 'is-completed')"
          >
            <el-icon>
              <CircleCloseFilled v-if="['failed', 'cancelled', 'interrupted'].includes(transfer.state)" />
              <CircleCheckFilled v-else />
            </el-icon>
          </div>

          <div class="transfer-recent-main">
            <div class="transfer-recent-title">{{ displayName(transfer) }}</div>
            <div class="transfer-recent-meta">{{ transferSubtitle(transfer) }}</div>
          </div>

          <div class="transfer-recent-actions">
            <div class="transfer-recent-state">{{ recentStateLabel(transfer) }}</div>
            <el-dropdown trigger="click" @command="command => handleRecentAction(command, transfer)">
              <button class="transfer-more-action" type="button" title="More" aria-label="More transfer actions">
                <el-icon><MoreFilled /></el-icon>
              </button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="info">Info</el-dropdown-item>
                  <template v-if="canUseArtifact(transfer)">
                    <el-dropdown-item command="preview">Preview</el-dropdown-item>
                    <el-dropdown-item command="download">Download</el-dropdown-item>
                  </template>
                  <el-dropdown-item command="delete" divided>Delete</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>
        </article>
        <HistoryLoadMore
          v-if="remainingRecentCount > 0"
          :remaining="remainingRecentCount"
          :loading="loadingMore"
          @load-more="$emit('load-more')"
        />
      </section>

      <div v-if="!activeTransfers.length && !recentTransfers.length" class="transfer-center-empty">
        <div class="transfer-center-empty-symbol">⇅</div>
        <div class="transfer-center-empty-title">No transfers</div>
        <div class="transfer-center-empty-text">
          Active file transfers will appear here.
        </div>
      </div>
    </div>
  </el-drawer>

  <el-dialog v-model="infoVisible" title="Transfer Info" width="min(540px, 94vw)" append-to-body>
    <el-descriptions v-if="infoTransfer" :column="1" border size="small" class="transfer-info">
      <el-descriptions-item label="File">{{ displayName(infoTransfer) }}</el-descriptions-item>
      <el-descriptions-item label="Direction">{{ transferSubtitle(infoTransfer) }}</el-descriptions-item>
      <el-descriptions-item label="Status">{{ recentStateLabel(infoTransfer) }}</el-descriptions-item>
      <el-descriptions-item label="Size">{{ formatInfoBytes(infoTransfer.total_bytes) }}</el-descriptions-item>
      <el-descriptions-item label="Transferred">{{ formatInfoBytes(infoTransfer.transferred_bytes) }}</el-descriptions-item>
      <el-descriptions-item label="Started">{{ formatDate(infoTransfer.started_at) }}</el-descriptions-item>
      <el-descriptions-item label="Finished">{{ formatDate(infoTransfer.completed_at) }}</el-descriptions-item>
      <el-descriptions-item v-if="infoTransfer.source_path" label="Source Path">
        <span class="transfer-info-path">{{ infoTransfer.source_path }}</span>
      </el-descriptions-item>
      <el-descriptions-item v-if="infoTransfer.destination_path" label="Destination Path">
        <span class="transfer-info-path">{{ infoTransfer.destination_path }}</span>
      </el-descriptions-item>
      <el-descriptions-item v-if="infoTransfer.error" label="Error">{{ infoTransfer.error }}</el-descriptions-item>
      <el-descriptions-item v-if="infoTransfer.artifact_id" label="Artifact ID">{{ infoTransfer.artifact_id }}</el-descriptions-item>
    </el-descriptions>
  </el-dialog>
</template>

<script>
import { formatBytesHuman, formatDateTimeLocal } from '../utils/formatters.js'
import HistoryLoadMore from './HistoryLoadMore.vue'
import { canUseTransferArtifact, transferArtifactDownloadUrl, transferDisplayName } from '../utils/transferCenter.js'
import {
  CircleCheckFilled,
  CircleCloseFilled,
  Close,
  MoreFilled,
} from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  cancelTransfer,
  clearRecentTransfers,
  deleteRecentTransfer,
} from '../api/transferApi.js'

export default {
  components: {
    HistoryLoadMore,
    CircleCheckFilled,
    CircleCloseFilled,
    Close,
    MoreFilled,
  },

  props: {
    transfers: {
      type: Array,
      default: () => [],
    },
    tabId: { type: String, default: '' },
    machines: { type: Array, default: () => [] },
    machineAliasMap: { type: Object, default: () => ({}) },
    machineId: { type: String, default: '' },
    recentTotal: { type: Number, default: 0 },
    loadingMore: { type: Boolean, default: false },
  },

  emits: ['transfers-changed', 'preview-artifact', 'load-more', 'filter-machine'],

  data() {
    return {
      visible: false,
      infoVisible: false,
      infoTransfer: null,
    }
  },

  computed: {
    activeTransfers() {
      const active = (this.transfers || []).filter(item => item?.state === 'running')
      if (!this.machineId) return active
      const allowedIds = new Set((this.machines || [])
        .filter(device => device?.machine_id === this.machineId)
        .map(device => device.client_id))
      return active.filter(item => allowedIds.has(item.client_id))
    },

    machineOptions() {
      const machines = new Map()
      for (const item of this.machines || []) {
        const id = String(item?.machine_id || '').trim()
        if (!id) continue
        const alias = String(this.machineAliasMap?.[id] || '').trim()
        const hostname = String(item?.hostname || '').trim()
        const existing = machines.get(id)
        // Keep the best known label if multiple sessions belong to one machine.
        const label = alias || hostname || existing?.label || 'Unknown device'
        machines.set(id, { machine_id: id, label })
      }
      if (this.machineId && !machines.has(this.machineId)) {
        machines.set(this.machineId, { machine_id: this.machineId, label: 'Unknown device' })
      }
      return Array.from(machines.values()).sort((a, b) => a.label.localeCompare(b.label))
    },

    recentTransfers() {
      return (this.transfers || []).filter(item => item?.state && item.state !== 'running')
    },

    remainingRecentCount() {
      return Math.max(0, this.recentTotal - this.recentTransfers.length)
    },
  },

  methods: {
    open() {
      this.visible = true
    },

    displayName(transfer) {
      return transferDisplayName(transfer)
    },

    canUseArtifact(transfer) {
      return canUseTransferArtifact(transfer)
    },

    handleRecentAction(command, transfer) {
      if (command === 'info') {
        this.infoTransfer = transfer
        this.infoVisible = true
      } else if (command === 'delete') {
        return this.deleteRecent(transfer)
      } else if (this.canUseArtifact(transfer)) {
        if (command === 'preview') {
          this.$emit('preview-artifact', { artifact_id: transfer.artifact_id, filename: transfer.filename })
        } else if (command === 'download') {
          const link = document.createElement('a')
          link.href = transferArtifactDownloadUrl(transfer)
          link.target = '_blank'
          link.rel = 'noopener noreferrer'
          document.body.appendChild(link)
          link.click()
          link.remove()
        }
      }
    },

    formatDate(value) {
      return value ? formatDateTimeLocal(value) : '—'
    },

    formatInfoBytes(value) {
      if (value == null || value === '') return '—'
      return formatBytesHuman(value, { precision: 'adaptive', maxUnit: 'TB', invalid: '—', nonPositiveAsZero: true })
    },

    async cancelActiveTransfer(transfer) {
      const transferId = String(transfer?.transfer_id || '').trim()
      if (!transferId) return
      try {
        await cancelTransfer(transferId, this.tabId)
      } catch (e) {
        ElMessage.error(e.message || 'Failed to cancel transfer')
      }
    },

    async deleteRecent(transfer) {
      const transferId = String(transfer?.transfer_id || '').trim()
      if (!transferId) return
      try {
        await deleteRecentTransfer(transferId, this.tabId)
        this.$emit('transfers-changed')
      } catch (e) {
        ElMessage.error(e.message || 'Failed to delete transfer')
      }
    },

    async clearRecent() {
      try {
        await ElMessageBox.confirm(
          'Clear all recent transfer records?',
          'Clear Recent Transfers',
          { type: 'warning' },
        )
      } catch (_) {
        return
      }

      try {
        await clearRecentTransfers(this.tabId)
        this.$emit('transfers-changed')
      } catch (e) {
        ElMessage.error(e.message || 'Failed to clear recent transfers')
      }
    },

    recentStateLabel(transfer) {
      if (transfer?.state === 'failed') return 'Failed'
      if (transfer?.state === 'cancelled') return 'Cancelled'
      if (transfer?.state === 'interrupted') return 'Interrupted'
      return 'Completed'
    },

    hasProgress(transfer) {
      return transfer?.progress_supported !== false
        && Number.isFinite(Number(transfer?.percent))
        && Number(transfer?.total_bytes) > 0
    },

    normalizedPercent(value) {
      const number = Number(value)
      if (!Number.isFinite(number)) return 0
      return Math.max(0, Math.min(100, number))
    },

    formatPercent(value) {
      const number = Number(value)
      if (!Number.isFinite(number)) return ''
      return `${Math.round(number)}%`
    },

    directionSymbol(transfer) {
      return transfer?.direction === 'server_to_client' ? '↑' : '↓'
    },

    transferSubtitle(transfer) {
      const device = String(transfer?.hostname || transfer?.client_id || 'Device').trim() || 'Device'
      const stage = String(transfer?.stage || '').toLowerCase()
      if (stage === 'uploading_to_server') {
        return `Browser → Server · for ${device}`
      }
      if (transfer?.direction === 'server_to_client') {
        return `Server → ${device}`
      }
      return `${device} → Server`
    },

    stageLabel(transfer) {
      const stage = String(transfer?.stage || '').toLowerCase()
      if (stage === 'uploading_to_server') return 'Uploading to Server'
      if (stage === 'preparing') {
        if (transfer?.metadata?.source === 'remote_file_download_zip') return 'Preparing archive…'
        if (transfer?.metadata?.source === 'remote_file_upload') return 'Preparing for Device…'
        return 'Preparing…'
      }
      if (stage === 'staging') return 'Staging to Server'
      if (stage === 'transferring') return 'Sending to Device'
      if (stage === 'finalizing') return 'Finalizing…'
      if (stage === 'cancelling') return 'Cancelling…'
      if (stage === 'cancelled') return 'Cancelled'
      if (stage === 'failed') return 'Failed'
      if (stage === 'completed') return 'Completed'
      return 'Transferring…'
    },

    formatBytes(value) {
      return formatBytesHuman(value, { precision: 'adaptive', maxUnit: 'TB', invalid: '—', nonPositiveAsZero: false })
    },

    formatRate(value) {
      return `${this.formatBytes(value)}/s`
    },

    formatEta(value) {
      const seconds = Math.max(0, Math.round(Number(value) || 0))
      if (seconds < 60) return `${seconds}s`
      if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${seconds % 60}s`
      const hours = Math.floor(seconds / 3600)
      const minutes = Math.floor((seconds % 3600) / 60)
      return `${hours}h ${minutes}m`
    },
  },
}
</script>

<style scoped>
.transfer-center-header-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-shrink: 0;
}

/* Match the compact selector in Notification Center; no separate filter strip. */
.transfer-machine-filter {
  width: 148px;
  height: 24px;
  font-size: 11px;
}

.transfer-machine-filter :deep(.el-select__wrapper) {
  min-height: 24px;
  height: 24px;
  padding: 0 6px;
  border-radius: 6px;
  font-size: 11px;
}

@media (max-width: 380px) {
  .transfer-machine-filter { width: 124px; }
  .transfer-center-header-actions { gap: 6px; }
}
.transfer-center-shell {
  min-height: 100%;
  display: flex;
  flex-direction: column;
  color: var(--text);
}

.transfer-center-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 18px 18px 14px;
  border-bottom: 1px solid var(--line);
}

.transfer-center-title {
  font-size: 18px;
  font-weight: 700;
}

.transfer-center-subtitle {
  margin-top: 4px;
  color: var(--muted);
  font-size: 12px;
}

.transfer-center-close {
  border: 0;
  background: transparent;
  color: var(--muted);
  cursor: pointer;
  padding: 4px;
  font-size: 17px;
}

.transfer-center-section {
  padding: 16px 16px 0;
}

.transfer-center-section-title {
  margin: 0 2px 9px;
  color: var(--muted);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}


.transfer-center-section-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin: 0 2px 9px;
}

.transfer-center-section-heading .transfer-center-section-title {
  margin: 0;
}

.transfer-card-actions {
  display: flex;
  justify-content: flex-end;
  margin-top: 8px;
}

.transfer-text-action {
  border: 0;
  padding: 2px 0;
  background: transparent;
  color: var(--primary);
  font: inherit;
  font-size: 11px;
  cursor: pointer;
}

.transfer-text-action.is-danger {
  color: var(--danger);
}

.transfer-text-action:disabled {
  color: var(--muted);
  cursor: default;
  opacity: 0.65;
}

.transfer-more-action {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 30px;
  min-height: 28px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--muted);
  cursor: pointer;
}
.transfer-more-action:hover { background: var(--bg-card); color: var(--text); }
.transfer-recent-actions {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 3px;
}

.transfer-card {
  padding: 13px 14px;
  margin-bottom: 10px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--bg-card);
}

.transfer-card-head {
  display: grid;
  grid-template-columns: 24px minmax(0, 1fr) auto;
  align-items: center;
  gap: 9px;
  margin-bottom: 10px;
}

.transfer-direction {
  font-size: 18px;
  color: var(--primary);
  font-weight: 700;
}

.transfer-card-main,
.transfer-recent-main {
  min-width: 0;
}

.transfer-card-title,
.transfer-recent-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
  font-weight: 650;
}

.transfer-card-meta,
.transfer-recent-meta,
.transfer-card-detail {
  margin-top: 3px;
  color: var(--muted);
  font-size: 11px;
  overflow-wrap: anywhere;
}

.transfer-card-percent {
  min-width: 34px;
  text-align: right;
  font-size: 12px;
  font-weight: 700;
}

.transfer-card-status-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 8px;
  color: var(--muted);
  font-size: 11px;
}

.transfer-indeterminate {
  height: 6px;
  overflow: hidden;
  border-radius: 999px;
  background: rgba(148, 163, 184, 0.18);
}

.transfer-indeterminate span {
  display: block;
  width: 38%;
  height: 100%;
  border-radius: inherit;
  background: var(--primary);
  animation: transfer-slide 1.25s ease-in-out infinite;
}

@keyframes transfer-slide {
  from { transform: translateX(-110%); }
  to { transform: translateX(275%); }
}

.transfer-center-recent {
  padding-bottom: 16px;
}

.transfer-recent-row {
  display: grid;
  grid-template-columns: 22px minmax(0, 1fr) auto;
  gap: 9px;
  align-items: center;
  padding: 10px 4px;
  border-bottom: 1px solid var(--line);
}

.transfer-recent-icon {
  font-size: 15px;
}

.transfer-recent-icon.is-completed {
  color: #16a34a;
}

.transfer-recent-icon.is-failed {
  color: var(--danger);
}

.transfer-recent-icon.is-cancelled {
  color: var(--muted);
}

.transfer-recent-state {
  color: var(--muted);
  font-size: 11px;
}

.transfer-center-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 56px 24px;
  text-align: center;
}

.transfer-center-empty-symbol {
  color: var(--muted);
  font-size: 28px;
}

.transfer-center-empty-title {
  margin-top: 10px;
  font-size: 14px;
  font-weight: 700;
}

.transfer-center-empty-text {
  margin-top: 5px;
  color: var(--muted);
  font-size: 12px;
}

:deep(.el-progress-bar__outer) {
  background-color: rgba(148, 163, 184, 0.18);
}

</style>

<style>
.transfer-center-drawer .el-drawer__body {
  padding: 0;
}

@media (max-width: 640px) {
  .transfer-center-drawer.el-drawer {
    width: min(94vw, 430px) !important;
  }
}
</style>

<style>
.transfer-info .el-descriptions__content { overflow-wrap: anywhere; }
.transfer-info-path { overflow-wrap: anywhere; white-space: pre-wrap; }
</style>
