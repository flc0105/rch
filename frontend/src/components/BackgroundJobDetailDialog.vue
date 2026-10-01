<template>
  <el-dialog
    :model-value="visible"
    :title="item ? (item.display_name || item.job_name || 'Background Job') : 'Background Job Detail'"
    width="1080px"
    top="5vh"
    class="fixed-dialog background-job-detail-dialog"
    @update:model-value="$emit('update:visible', $event)"
  >
    <div
      v-if="item"
      v-loading="loading"
      class="fixed-dialog-body"
    >
      <div class="background-job-detail-head">
        <div class="background-job-detail-head-left">
          <div class="background-job-title-line">
            <div class="background-job-title">
              {{ item.display_name || item.job_name }}
            </div>

            <el-tag
              :type="buildBackgroundJobStateTagType(item.state)"
              size="small"
            >
              {{ item.state || 'unknown' }}
            </el-tag>
          </div>

          <div class="background-job-subtitle mono">
{{ item.job_key || '-' }}
          </div>
        </div>

        <div class="background-job-card-head-right">
          <el-button
            size="small"
            plain
            :loading="saveOutputLoading"
            :disabled="!safeMessages.length"
            @click="saveOutputToArtifact"
          >
            Save Output
          </el-button>

          <el-button
            size="small"
            type="danger"
            plain
            :disabled="!item.job_key || !isActive"
            @click="$emit('stop-job', item)"
          >
            Stop
          </el-button>

          <el-button
            size="small"
            type="danger"
            plain
            :disabled="isActive"
            @click="$emit('delete-job', item)"
          >
            Delete
          </el-button>
        </div>
      </div>

      <div class="background-job-stats">
        <div class="background-job-stat">
          <div class="background-job-stat-label">Duration</div>
          <div class="background-job-stat-value">
            {{ formatBackgroundJobDuration(item.duration_seconds) }}
          </div>
        </div>

        <div class="background-job-stat">
          <div class="background-job-stat-label">Messages</div>
          <div class="background-job-stat-value">
            {{ item.message_count || 0 }}
          </div>
        </div>

        <div class="background-job-stat">
          <div class="background-job-stat-label">Files</div>
          <div class="background-job-stat-value">
            {{ item.file_count || 0 }}
          </div>
        </div>

        <div class="background-job-stat">
          <div class="background-job-stat-label">Started</div>
          <div class="background-job-stat-value">
            {{ formatDateTimeStandard(item.started_at) || '-' }}
          </div>
        </div>

        <div class="background-job-stat">
          <div class="background-job-stat-label">Stopped</div>
          <div class="background-job-stat-value">
            {{ formatDateTimeStandard(item.stopped_at) || '-' }}
          </div>
        </div>

        <div class="background-job-stat">
          <div class="background-job-stat-label">Mode</div>
          <div class="background-job-stat-value mono">
            {{ item.execution_mode || 'inproc' }}
          </div>
        </div>

        <div class="background-job-stat">
          <div class="background-job-stat-label">Worker</div>
          <div class="background-job-stat-value mono">
            {{ item.thread_name || '-' }}
          </div>
        </div>
      </div>

      <div class="background-job-panels">
        <div class="background-job-panel">
          <div class="background-job-panel-title">
            Messages
          </div>

          <div class="background-job-message-list">
            <div
              v-for="(message, index) in safeMessages"
              :key="`${item.job_id || 'job'}-msg-${index}`"
              class="background-job-message-item clickable"
              @click="$emit('open-message', message)"
            >
              <div class="background-job-message-time">
                {{ formatDateTimeStandard(message.time) || '-' }}
              </div>

              <div
                class="background-job-message-text single-line"
                :class="{ 'is-error': message.status === 0, 'is-success': message.status === 1 }"
              >
                {{ formatBackgroundJobMessageText(message.text || '') }}
              </div>
            </div>

            <div
              v-if="!safeMessages.length"
              class="empty-state compact"
            >
              No messages
            </div>
          </div>
        </div>

        <div class="background-job-panel">
          <div class="background-job-panel-title">
            Files
          </div>

          <div class="background-job-file-list">
            <div
              v-for="(file, index) in safeFiles"
              :key="`${item.job_id || 'job'}-file-${index}`"
              class="background-job-file-item"
            >
              <div class="background-job-file-main">
                <div class="background-job-file-name">
                  {{ file.original_name || file.stored_name || '-' }}
                </div>

                <div class="background-job-file-meta">
                  <span>{{ formatBytes(file.size || 0) }}</span>
                  <span>{{ formatDateTimeStandard(file.time) || '-' }}</span>
                </div>
              </div>

              <div class="background-job-file-actions">
                <a
                  class="table-action-link"
                  style="cursor: pointer"
                  @click="$emit('preview-file', file)"
                >
                  Preview
                </a>

                <a
                  class="table-action-link"
                  :href="file.download_url"
                  target="_blank"
                >
                  Download
                </a>
              </div>
            </div>

            <div
              v-if="!safeFiles.length"
              class="empty-state compact"
            >
              No files
            </div>
          </div>
        </div>
      </div>
    </div>
  </el-dialog>
</template>

<script>
import { formatDateTimePreserveFraction } from '../utils/formatters.js'
import { ElMessage } from 'element-plus'

export default {
  name: 'BackgroundJobDetailDialog',

  data() {
    return {
      saveOutputLoading: false,
    }
  },

  props: {
    visible: {
      type: Boolean,
      default: false,
    },
    loading: {
      type: Boolean,
      default: false,
    },
    item: {
      type: Object,
      default: null,
    },
    currentConnection: {
      type: Object,
      default: null,
    },
    messages: {
      type: Array,
      default: () => [],
    },
    files: {
      type: Array,
      default: () => [],
    },
    buildBackgroundJobStateTagType: {
      type: Function,
      required: true,
    },
    formatBackgroundJobDuration: {
      type: Function,
      required: true,
    },
    formatDateTimeStandard: {
      type: Function,
      required: true,
    },
    formatBackgroundJobMessageText: {
      type: Function,
      required: true,
    },
    formatBytes: {
      type: Function,
      required: true,
    },
  },

  emits: [
    'update:visible',
    'stop-job',
    'delete-job',
    'open-message',
    'preview-file',
  ],

  computed: {
    safeMessages() {
      return Array.isArray(this.messages) ? this.messages : []
    },

    safeFiles() {
      return Array.isArray(this.files) ? this.files : []
    },

    isActive() {
      const state = String(this.item?.state || '').trim().toLowerCase()
      return state === 'running' || state === 'stopping'
    },
  },

  methods: {
    formatJobOutputTime(value) {
      // 与前端标准时间显示保持一致，但保留原始小数秒。
      return formatDateTimePreserveFraction(value)
    },

    async saveOutputToArtifact() {
      if (!this.item || !this.safeMessages.length || this.saveOutputLoading) return

      const records = [...this.safeMessages]
        .sort((a, b) => String(a?.time || '').localeCompare(String(b?.time || '')))
        .map(message => ({
          time: this.formatJobOutputTime(message?.time),
          message: this.formatBackgroundJobMessageText(message?.text || ''),
        }))

      const output = {
        job: {
          job_id: String(this.item.job_id || ''),
          job_name: String(this.item.job_name || ''),
          job_key: String(this.item.job_key || ''),
          display_name: String(this.item.display_name || ''),
          client_id: String(this.item.client_id || this.currentConnection?.client_id || ''),
          hostname: String(this.item.hostname || this.currentConnection?.hostname || ''),
          machine_id: String(this.item.machine_id || this.currentConnection?.machine_id || ''),
          started_at: this.formatJobOutputTime(this.item.started_at),
          stopped_at: this.formatJobOutputTime(this.item.stopped_at),
        },
        records,
      }
      const sourceCommand = String(
        this.item.display_name || this.item.job_name || this.item.job_key || 'job'
      ).trim()

      this.saveOutputLoading = true
      try {
        const res = await fetch('/api/artifacts/command-output/save', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            content: JSON.stringify(output, null, 2),
            category: 'job_output',
            client_id: String(this.item.client_id || ''),
            hostname: String(this.item.hostname || this.currentConnection?.hostname || ''),
            machine_id: String(this.item.machine_id || this.currentConnection?.machine_id || ''),
            source: 'background_job_detail',
            source_command: sourceCommand,
            job_id: String(this.item.job_id || ''),
            job_name: String(this.item.job_name || ''),
            job_key: String(this.item.job_key || ''),
            extra: {
              format: 'json',
              record_count: records.length,
            },
          }),
        })

        const json = await res.json()
        if (!res.ok || json.code !== 0) {
          throw new Error(json.message || 'Failed to save job output')
        }

        ElMessage.success('Job output saved to Command Output')
      } catch (e) {
        ElMessage.error(e.message || 'Failed to save job output')
      } finally {
        this.saveOutputLoading = false
      }
    },
  },
}
</script>

<style scoped>
.background-job-detail-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
}

.background-job-detail-head-left,
.background-job-file-main {
  min-width: 0;
}

.background-job-title-line {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.background-job-title {
  font-size: 15px;
  font-weight: 700;
  color: var(--text);
  word-break: break-word;
}

.background-job-subtitle {
  margin-top: 8px;
  color: var(--muted);
  font-size: 12px;
}

.background-job-card-head-right {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  flex-shrink: 0;
}

.background-job-stats {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.background-job-stat {
  padding: 10px 12px;
  border-radius: 12px;
  background: #f8fafc;
  border: 1px solid rgba(15, 23, 42, 0.05);
}

.background-job-stat-label {
  font-size: 11px;
  color: var(--muted-2);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.background-job-stat-value {
  margin-top: 4px;
  font-size: 13px;
  color: var(--text);
  word-break: break-word;
}

.background-job-panels {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  margin-top: 14px;
}

.background-job-panel {
  border: 1px solid rgba(15, 23, 42, 0.06);
  border-radius: 12px;
  background: #fafcff;
  overflow: hidden;
}

.background-job-panel-title {
  padding: 10px 12px;
  font-size: 13px;
  font-weight: 700;
  border-bottom: 1px solid rgba(15, 23, 42, 0.06);
  background: #f8fafc;
}

.background-job-message-list,
.background-job-file-list {
  max-height: 320px;
  overflow-y: auto;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.background-job-message-item,
.background-job-file-item {
  padding: 10px 12px;
  border-radius: 10px;
  background: #fff;
  border: 1px solid rgba(15, 23, 42, 0.05);
}

.background-job-message-item.clickable {
  cursor: pointer;
  transition: background 0.18s ease, border-color 0.18s ease;
}

.background-job-message-item.clickable:hover {
  background: #f8fafc;
  border-color: rgba(37, 99, 235, 0.16);
}

.background-job-message-time {
  font-size: 11px;
  color: var(--muted-2);
  margin-bottom: 6px;
}

.background-job-message-text {
  font-size: 13px;
  line-height: 1.6;
  color: var(--text);
  white-space: pre-wrap;
  word-break: break-word;
}

.background-job-message-text.is-error {
  color: var(--danger);
}

.background-job-message-text.is-success {
  color: #166534;
}

.background-job-message-text.single-line {
  height: 20px;
  line-height: 20px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  word-break: normal;
}

.background-job-file-name {
  font-size: 13px;
  font-weight: 700;
  color: var(--text);
  word-break: break-word;
}

.background-job-file-meta {
  margin-top: 6px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  font-size: 12px;
  color: var(--muted);
}

.background-job-file-actions {
  margin-top: 6px;
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

@media (max-width: 768px), (max-height: 720px) {
  .background-job-stats,
  .background-job-panels {
    grid-template-columns: 1fr;
  }

  .background-job-detail-head {
    flex-direction: column;
    align-items: stretch;
  }
}
</style>