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

        <button
          class="transfer-center-close"
          type="button"
          title="Close"
          @click="visible = false"
        >
          <el-icon><Close /></el-icon>
        </button>
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
              <div class="transfer-card-title">{{ transfer.filename || 'File transfer' }}</div>
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
            :class="transfer.state === 'failed' ? 'is-failed' : (transfer.state === 'cancelled' ? 'is-cancelled' : 'is-completed')"
          >
            <el-icon>
              <CircleCloseFilled v-if="transfer.state === 'failed' || transfer.state === 'cancelled'" />
              <CircleCheckFilled v-else />
            </el-icon>
          </div>

          <div class="transfer-recent-main">
            <div class="transfer-recent-title">{{ transfer.filename || 'File transfer' }}</div>
            <div class="transfer-recent-meta">
              {{ transfer.state === 'failed' ? (transfer.error || 'Transfer failed') : transferSubtitle(transfer) }}
            </div>
          </div>

          <div class="transfer-recent-actions">
            <div class="transfer-recent-state">{{ recentStateLabel(transfer) }}</div>
            <button
              class="transfer-text-action"
              type="button"
              title="Delete transfer record"
              @click="deleteRecent(transfer)"
            >
              Delete
            </button>
          </div>
        </article>
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
</template>

<script>
import { formatBytesHuman } from '../utils/formatters.js'
import {
  CircleCheckFilled,
  CircleCloseFilled,
  Close,
} from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  cancelTransfer,
  clearRecentTransfers,
  deleteRecentTransfer,
} from '../api/transferApi.js'

export default {
  components: {
    CircleCheckFilled,
    CircleCloseFilled,
    Close,
  },

  props: {
    transfers: {
      type: Array,
      default: () => [],
    },
    tabId: {
      type: String,
      default: '',
    },
  },

  emits: ['transfers-changed'],

  data() {
    return {
      visible: false,
    }
  },

  computed: {
    activeTransfers() {
      return (this.transfers || []).filter(item => item?.state === 'running')
    },

    recentTransfers() {
      return (this.transfers || [])
        .filter(item => item?.state && item.state !== 'running')
        .slice(0, 50)
    },
  },

  methods: {
    open() {
      this.visible = true
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
        return transfer.destination_path
          ? `Server → ${device} · ${transfer.destination_path}`
          : `Server → ${device}`
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
.transfer-center-shell {
  min-height: 100%;
  display: flex;
  flex-direction: column;
  color: var(--text);
}

.transfer-center-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
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
