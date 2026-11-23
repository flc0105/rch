<template>
  <div class="history-load-more">
    <button
      type="button"
      class="history-load-more-action"
      :disabled="loading"
      :aria-label="`Load more, ${remaining} remaining`"
      @click="$emit('load-more')"
    >
      <el-icon v-if="loading" class="is-loading"><Loading /></el-icon>
      <el-icon v-else><ArrowDown /></el-icon>
      <span>Load more</span>
      <span class="history-load-more-count">{{ remaining }} remaining</span>
    </button>
  </div>
</template>

<script>
import { ArrowDown, Loading } from '@element-plus/icons-vue'

export default {
  name: 'HistoryLoadMore',
  components: { ArrowDown, Loading },
  props: {
    remaining: { type: Number, required: true },
    loading: { type: Boolean, default: false },
  },
  emits: ['load-more'],
}
</script>

<style scoped>
.history-load-more {
  display: flex;
  justify-content: center;
  margin: 10px 16px 16px;
  padding-top: 10px;
  border-top: 1px solid var(--el-border-color-lighter, #e9edf2);
}
.history-load-more-action {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  border: 0;
  border-radius: 7px;
  background: transparent;
  color: var(--el-text-color-regular, #475569);
  font: inherit;
  font-size: 12px;
  line-height: 18px;
  cursor: pointer;
  transition: background 0.15s, color 0.15s;
}
.history-load-more-action:hover:not(:disabled) {
  color: var(--el-color-primary, #409eff);
  background: var(--el-fill-color-light, #f5f7fa);
}
.history-load-more-action:focus-visible {
  outline: 2px solid var(--el-color-primary, #409eff);
  outline-offset: 2px;
}
.history-load-more-action:disabled { opacity: 0.6; cursor: wait; }
.history-load-more-count { color: var(--el-text-color-placeholder, #94a3b8); }
.history-load-more-action .el-icon { font-size: 12px; }
</style>
