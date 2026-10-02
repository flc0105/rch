<template>
  <el-dialog
    :model-value="visible"
    title="Message"
    width="760px"
    top="8vh"
    class="fixed-dialog background-job-message-dialog"
    @update:model-value="$emit('update:visible', $event)"
  >
    <div class="fixed-dialog-body">
      <div class="background-job-full-message-time">
        {{ formatDateTimeStandard(safeMessage.created_at) || '-' }}
      </div>

      <pre
        class="background-job-full-message-text"
        :class="{ 'is-error': safeMessage.status === 0, 'is-success': safeMessage.status === 1 }"
      >{{ formatBackgroundJobMessageText(safeMessage.text || '') }}</pre>
    </div>
  </el-dialog>
</template>

<script>
export default {
  name: 'BackgroundJobMessageDialog',

  props: {
    visible: {
      type: Boolean,
      default: false,
    },
    message: {
      type: Object,
      default: () => ({}),
    },
    formatDateTimeStandard: {
      type: Function,
      required: true,
    },
    formatBackgroundJobMessageText: {
      type: Function,
      required: true,
    },
  },

  emits: ['update:visible'],

  computed: {
    safeMessage() {
      return this.message || {}
    },
  },
}
</script>


<style scoped>
.background-job-full-message-time {
  font-size: 12px;
  color: var(--muted);
  margin-bottom: 10px;
}

.background-job-full-message-text {
  margin: 0;
  padding: 14px;
  min-height: 280px;
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

.background-job-full-message-text.is-error {
  color: var(--danger);
}

.background-job-full-message-text.is-success {
  color: #166534;
}
</style>