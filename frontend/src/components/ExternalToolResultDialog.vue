<template>
  <el-dialog
    v-model="oneshotDialogVisible"
    :title="oneshotDialogTitle"
    width="940px"
    top="6vh"
    append-to-body
    modal-class="external-tool-info-overlay"
    class="external-tool-detail-dialog external-tool-info-dialog"
  >
    <div class="external-tool-oneshot-body">
      <div class="external-tool-detail-subtitle">
        {{ formatOneshotSummary(oneshotResult) }}
      </div>

      <div class="external-tool-detail-section">
        <div class="external-tool-detail-section-title">Stdout</div>
        <pre class="external-tool-log-content external-tool-oneshot-output">{{ oneshotResult?.stdout || 'No stdout.' }}</pre>
      </div>

      <div class="external-tool-detail-section">
        <div class="external-tool-detail-section-title">Stderr</div>
        <pre class="external-tool-log-content external-tool-oneshot-output">{{ oneshotResult?.stderr || 'No stderr.' }}</pre>
      </div>

  <!--      <div class="external-tool-detail-section">-->
  <!--        <div class="external-tool-detail-section-title">Result</div>-->
  <!--        <pre class="external-tool-detail-pre">{{ stringifyDetailValue(oneshotResult || {}) }}</pre>-->
  <!--      </div>-->
    </div>

    <template #footer>
      <el-button size="small" plain @click="copyOneshotResult">Copy Result</el-button>
      <el-button size="small" @click="oneshotDialogVisible = false">Close</el-button>
    </template>
  </el-dialog>
</template>

<script>
import { ElMessage } from 'element-plus'
import { copyTextFallback } from '../utils/clipboard.js'
import { stringifyDetailValue } from '../utils/externalToolPresentation.js'

export default {
  name: 'ExternalToolResultDialog',
  data() {
    return {
      oneshotDialogVisible: false,
      oneshotDialogTitle: 'External Tool Result',
      oneshotResult: null,
    }
  },
  methods: {
    stringifyDetailValue,
    openOneshotResultDialog(item, result) {
      this.oneshotResult = result || {}
      this.oneshotDialogTitle = `${item?.display_name || item?.id || 'External Tool'} Result`
      this.oneshotDialogVisible = true
      if (result?.success) {
        ElMessage.success(result.message || 'External tool completed')
      } else {
        ElMessage.error(result?.message || 'External tool failed')
      }
    },

    formatOneshotSummary(result) {
      if (!result) return ''
      const pieces = [
        result.side || '',
        result.status || '',
        `exit=${result.returncode ?? '-'}`,
        result.duration_sec !== undefined && result.duration_sec !== null ? `${result.duration_sec}s` : '',
        result.run_id || '',
      ].filter(Boolean)
      return pieces.join(' / ')
    },

    async copyOneshotResult() {
      const text = this.stringifyDetailValue(this.oneshotResult || {})
      try {
        if (window.isSecureContext && navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
          await navigator.clipboard.writeText(text)
        } else {
          copyTextFallback(text)
        }
        ElMessage.success('Copied')
      } catch (_) {
        ElMessage.error('Failed to copy')
      }
    },
  },
}
</script>

<style scoped>
.external-tool-oneshot-body {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.external-tool-oneshot-output {
  min-height: 140px;
  max-height: 260px;
}

.external-tool-log-content {
  max-height: 560px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  padding: 12px;
  border-radius: 10px;
  background: #050505;
  color: #d9e2ff;
  border: 1px solid rgba(255,255,255,.12);
  scrollbar-color: #303544 #050505;
  scrollbar-width: thin;
}

.external-tool-log-content::-webkit-scrollbar {
  width: 10px;
  height: 10px;
}

.external-tool-log-content::-webkit-scrollbar-track {
  background: #050505;
  border-radius: 999px;
}

.external-tool-log-content::-webkit-scrollbar-thumb {
  background: #303544;
  border-radius: 999px;
  border: 2px solid #050505;
}

.external-tool-log-content::-webkit-scrollbar-thumb:hover {
  background: #495064;
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

@media (max-width: 640px) {
.external-tool-oneshot-body {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.external-tool-oneshot-output {
  min-height: 140px;
  max-height: 260px;
}
}
</style>
