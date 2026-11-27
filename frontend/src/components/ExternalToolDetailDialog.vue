<template>
  <el-dialog
    v-model="detailDialogVisible"
    :title="detailDialogTitle"
    width="780px"
    top="6vh"
    append-to-body
    modal-class="external-tool-info-overlay"
    class="external-tool-detail-dialog external-tool-info-dialog"
  >
    <div class="external-tool-detail-body">
      <div v-if="detailSubtitle" class="external-tool-detail-subtitle">
        {{ detailSubtitle }}
      </div>

      <div
        v-for="section in detailSections"
        :key="section.title"
        class="external-tool-detail-section"
      >
        <div class="external-tool-detail-section-title">
          {{ section.title }}
        </div>

        <div class="external-tool-detail-grid">
          <div
            v-for="row in section.rows"
            :key="`${section.title}:${row.label}`"
            class="external-tool-detail-row"
          >
            <div class="external-tool-detail-label">
              {{ row.label }}
            </div>
            <div
              class="external-tool-detail-value"
              :class="{ mono: row.mono, multiline: row.multiline }"
              :title="row.multiline ? '' : stringifyDetailValue(row.value)"
            >
              <pre v-if="row.multiline" class="external-tool-detail-pre">{{ formatDetailValue(row.value) }}</pre>
              <span v-else>{{ formatDetailValue(row.value) }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <template #footer>
      <el-button
        v-if="detailCopyText"
        size="small"
        plain
        @click="copyDetailText"
      >
        Copy Command
      </el-button>
      <el-button size="small" @click="detailDialogVisible = false">Close</el-button>
    </template>
  </el-dialog>
</template>

<script>
import { ElMessage } from 'element-plus'
import { copyTextFallback } from '../utils/clipboard.js'
import { stringifyDetailValue } from '../utils/externalToolPresentation.js'

export default {
  name: 'ExternalToolDetailDialog',
  data() {
    return {
      detailDialogVisible: false,
      detailDialogTitle: '',
      detailSubtitle: '',
      detailSections: [],
      detailCopyText: '',
    }
  },
  methods: {
    stringifyDetailValue,
    showDetailDialog({ title = '', subtitle = '', sections = [], copyText = '' } = {}) {
      this.detailDialogTitle = title || 'Details'
      this.detailSubtitle = subtitle || ''
      this.detailSections = (sections || []).map(section => ({
        title: section.title || 'Details',
        rows: (section.rows || []).filter(row => row && row.label),
      })).filter(section => section.rows.length)
      this.detailCopyText = copyText || ''
      this.detailDialogVisible = true
    },

    formatDetailValue(value) {
      return this.stringifyDetailValue(value)
    },

    async copyDetailText() {
      if (!this.detailCopyText) return
      try {
        if (window.isSecureContext && navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
          await navigator.clipboard.writeText(this.detailCopyText)
        } else {
          copyTextFallback(this.detailCopyText)
        }
        ElMessage.success('Copied')
      } catch (e) {
        try {
          copyTextFallback(this.detailCopyText)
          ElMessage.success('Copied')
        } catch (_) {
          ElMessage.error('Failed to copy')
        }
      }
    },
  },
}
</script>

<style scoped>
.external-tool-detail-body {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.external-tool-detail-subtitle {
  padding: 0;
  border-radius: 0;
  background: transparent;
  color: var(--muted, #64748b);
  font-size: 12px;
}

.external-tool-detail-section {
  border: 0;
  border-radius: 0;
  overflow: visible;
  background: transparent;
}

.external-tool-detail-section-title {
  padding: 0 0 8px;
  font-weight: 700;
  border-bottom: 0;
  background: transparent;
}

.external-tool-detail-grid {
  display: grid;
  grid-template-columns: 1fr;
}

.external-tool-detail-row {
  display: grid;
  grid-template-columns: 150px minmax(0, 1fr);
  gap: 12px;
  padding: 7px 0;
  border-bottom: 0;
}

.external-tool-detail-row:last-child {
  border-bottom: 0;
}

.external-tool-detail-label {
  color: var(--muted, #64748b);
  font-size: 12px;
}

.external-tool-detail-value {
  min-width: 0;
  overflow: hidden;
}

.external-tool-detail-value.multiline {
  white-space: normal;
  overflow: visible;
}

.external-tool-detail-pre {
  margin: 0;
  max-height: 260px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  padding: 10px;
  border-radius: 8px;
  background: #050505;
  border: 1px solid rgba(255,255,255,.10);
  color: #d9e2ff;
  scrollbar-color: #303544 #050505;
  scrollbar-width: thin;
}

.external-tool-detail-pre::-webkit-scrollbar {
  width: 10px;
  height: 10px;
}

.external-tool-detail-pre::-webkit-scrollbar-track {
  background: #050505;
  border-radius: 999px;
}

.external-tool-detail-pre::-webkit-scrollbar-thumb {
  background: #303544;
  border-radius: 999px;
  border: 2px solid #050505;
}

.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
}

@media (max-width: 640px) {
.external-tool-detail-row {
    grid-template-columns: 1fr;
    gap: 4px;
  }
}
</style>
