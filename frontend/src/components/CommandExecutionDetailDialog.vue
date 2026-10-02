<template>
  <el-dialog
    :model-value="visible"
    :title="entry ? (entry.command || 'Execution Detail') : 'Execution Detail'"
    width="1000px"
    top="5vh"
    class="fixed-dialog command-execution-detail-dialog"
    @update:model-value="$emit('update:visible', $event)"
  >
    <div
      v-if="entry"
      class="fixed-dialog-body"
    >
      <div class="background-job-stats">
        <div class="background-job-stat">
          <div class="background-job-stat-label">Status</div>
          <div class="background-job-stat-value">
            <el-tag
              :type="buildCommandExecutionStatusTagType(entry.status)"
              size="small"
            >
              {{ entry.status || 'unknown' }}
            </el-tag>
          </div>
        </div>

        <div class="background-job-stat">
          <div class="background-job-stat-label">Source</div>
          <div class="background-job-stat-value">
            {{ entry.source || '-' }}
          </div>
        </div>

        <div class="background-job-stat">
          <div class="background-job-stat-label">Duration</div>
          <div class="background-job-stat-value">
            {{ formatCommandExecutionDuration(entry) }}
          </div>
        </div>

        <div class="background-job-stat">
          <div class="background-job-stat-label">Started</div>
          <div class="background-job-stat-value">
            {{ formatDateTimeStandard(entry.started_at) || '-' }}
          </div>
        </div>

        <div class="background-job-stat">
          <div class="background-job-stat-label">Finished</div>
          <div class="background-job-stat-value">
            {{ formatDateTimeStandard(entry.finished_at) || '-' }}
          </div>
        </div>

        <div class="background-job-stat">
          <div class="background-job-stat-label">Files</div>
          <div class="background-job-stat-value">
            {{ (entry.files || []).length }}
          </div>
        </div>
      </div>

      <div class="command-execution-detail-section">
        <div class="command-execution-detail-label">Summary</div>
        <div class="command-execution-detail-summary">
          {{ buildCommandExecutionSummary(entry) }}
        </div>
      </div>

      <div class="command-execution-detail-panels">
        <div class="background-job-panel">
          <div class="background-job-panel-title command-output-panel-title">
            <span>Output Records</span>

            <el-button
              size="small"
              plain
              @click="$emit('toggle-output-sort')"
            >
              {{ outputSortOrder === 'desc' ? 'Oldest first' : 'Newest first' }}
            </el-button>
          </div>

          <div class="background-job-message-list">
            <div
              v-for="(record, index) in outputRecords"
              :key="`${entry.entry_id}-output-${index}`"
              class="background-job-message-item"
            >
              <div class="background-job-message-time">
                {{ formatDateTimeStandard(record.created_at) || '-' }}
              </div>

              <div
                class="background-job-message-text"
                :class="{
                  'is-error': record.status === 0,
                  'is-success': record.status === 1,
                }"
              >
                {{ formatCommandExecutionRecordText(record.text || '') }}
              </div>
            </div>

            <div
              v-if="entry.output_truncated"
              class="empty-state compact"
            >
              Output was truncated for storage safety
            </div>

            <div
              v-if="!entry.output_records || !entry.output_records.length"
              class="empty-state compact"
            >
              No output records
            </div>
          </div>
        </div>

        <div class="background-job-panel">
          <div class="background-job-panel-title">Produced Files</div>

          <div class="background-job-file-list">
            <div
              v-for="(file, index) in entry.files"
              :key="`${entry.entry_id}-file-${index}`"
              class="background-job-file-item"
            >
              <div class="background-job-file-main">
                <div class="background-job-file-name">
                  {{ file.original_name || file.stored_name || '-' }}
                </div>

                <div class="background-job-file-meta">
                  <span>{{ formatBytes(file.size || 0) }}</span>
                  <span>{{ formatDateTimeStandard(file.created_at) || '-' }}</span>
                  <span v-if="getCommandExecutionFileStatusText(file)">
                    [{{ getCommandExecutionFileStatusText(file) }}]
                  </span>
                </div>
              </div>

              <div class="background-job-file-actions">
                <a
                  v-if="file.download_url && file.is_available"
                  style="cursor:pointer"
                  class="table-action-link"
                  @click="$emit('preview-file', file)"
                >
                  Preview
                </a>

                <a
                  v-if="file.download_url && file.is_available"
                  class="table-action-link"
                  :href="file.download_url"
                  target="_blank"
                >
                  Download
                </a>
              </div>
            </div>

            <div
              v-if="!entry.files || !entry.files.length"
              class="empty-state compact"
            >
              No files produced
            </div>
          </div>
        </div>
      </div>
    </div>
  </el-dialog>
</template>

<script>
export default {
  name: 'CommandExecutionDetailDialog',

  props: {
    visible: {
      type: Boolean,
      default: false,
    },

    entry: {
      type: Object,
      default: null,
    },

    outputRecords: {
      type: Array,
      default: () => [],
    },

    outputSortOrder: {
      type: String,
      default: 'desc',
    },

    buildCommandExecutionStatusTagType: {
      type: Function,
      required: true,
    },

    formatCommandExecutionDuration: {
      type: Function,
      required: true,
    },

    formatDateTimeStandard: {
      type: Function,
      required: true,
    },

    buildCommandExecutionSummary: {
      type: Function,
      required: true,
    },

    formatCommandExecutionRecordText: {
      type: Function,
      required: true,
    },

    getCommandExecutionFileStatusText: {
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
    'toggle-output-sort',
    'preview-file',
  ],
}
</script>

<style scoped>
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

.background-job-stat-label,
.command-execution-detail-label {
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

.command-execution-detail-section {
  margin-top: 14px;
}

.command-execution-detail-label {
  display: block;
  margin-bottom: 6px;
}

.command-execution-detail-summary {
  font-size: 13px;
  line-height: 1.6;
  color: var(--text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.command-execution-detail-panels {
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

.command-output-panel-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
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

.background-job-file-main {
  min-width: 0;
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
  .command-execution-detail-panels {
    grid-template-columns: 1fr;
  }

  .command-output-panel-title {
    flex-direction: column;
    align-items: stretch;
  }
}
</style>

