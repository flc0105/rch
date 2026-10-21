<template>
  <el-dialog
    :model-value="visible"
    title="Toolbox"
    width="860px"
    top="7vh"
    class="toolbox-dialog"
    :show-close="false"
    append-to-body
    :destroy-on-close="false"
    @update:model-value="$emit('update:visible', $event)"
  >
    <template #header>
      <div class="toolbox-header">
        <strong>Toolbox</strong>
        <div class="toolbox-header-actions">
          <el-tooltip content="Settings" placement="bottom">
            <button class="toolbox-header-action" type="button" aria-label="Settings" @click="$emit('launch', 'settings')">
              <Settings2 :size="18" :stroke-width="1.8" />
            </button>
          </el-tooltip>
          <button
            type="button"
            class="toolbox-header-action"
            aria-label="Close"
            title="Close"
            @click="$emit('update:visible', false)"
          >
            <el-icon><Close /></el-icon>
          </button>
        </div>
      </div>
    </template>

    <el-input
      ref="searchInput"
      v-model="query"
      class="toolbox-search"
      clearable
      placeholder="Search tools..."
      aria-label="Search tools"
    >
      <template #prefix><Search :size="17" :stroke-width="1.8" /></template>
    </el-input>

    <div class="toolbox-list">
      <div v-if="filteredActions.length" class="toolbox-grid">
        <button
          v-for="action in filteredActions"
          :key="action.id"
          class="toolbox-item"
          :class="{ 'toolbox-item-disabled': action.disabled }"
          type="button"
          :disabled="action.disabled"
          :title="action.label"
          @click="$emit('launch', action.id)"
        >
          <span class="toolbox-icon" :class="{ 'toolbox-icon-accent': action.accent }">
            <component :is="iconComponents[action.icon]" :size="27" :stroke-width="1.75" aria-hidden="true" />
          </span>
          <span class="toolbox-label">{{ action.label }}</span>
        </button>
      </div>
      <el-empty v-else description="No tools found" :image-size="72" />
    </div>
  </el-dialog>
</template>

<script>
import {
  Activity, Archive, BookOpen, Bot, CalendarClock, Clipboard, Code2,
  FileCode, FolderOpen, History, KeyRound, Monitor, MonitorPlay,
  Search, Settings2, Terminal, Wrench, Zap, ScrollText,
} from '@lucide/vue'
import { Close } from '@element-plus/icons-vue'

// Icons are presentation only; tool identity and launch behavior come from the shared catalog.
const icons = Object.freeze({
  'folder-open': FolderOpen,
  archive: Archive,
  monitor: Monitor,
  'file-code': FileCode,
  history: History,
  terminal: Terminal,
  'monitor-play': MonitorPlay,
  clipboard: Clipboard,
  wrench: Wrench,
  'scroll-text': ScrollText,
  'calendar-clock': CalendarClock,
  bot: Bot,
  activity: Activity,
  'key-round': KeyRound,
  'book-open': BookOpen,
  'code-2': Code2,
  zap: Zap,
})

export default {
  name: 'ToolboxDialog',
  components: { Search, Settings2, Close },
  props: {
    visible: { type: Boolean, default: false },
    actions: { type: Array, default: () => [] },
  },
  emits: ['update:visible', 'launch'],
  data() {
    return { query: '' }
  },
  computed: {
    iconComponents() { return icons },
    filteredActions() {
      const term = this.query.trim().toLocaleLowerCase()
      if (!term) return this.actions
      return this.actions.filter((action) => action.label.toLocaleLowerCase().includes(term))
    },
  },
  watch: {
    visible(isVisible) {
      if (!isVisible) return
      this.query = ''
      this.$nextTick(() => this.$refs.searchInput?.focus?.())
    },
  },
}
</script>

<style scoped>
.toolbox-header { width: 100%; display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.toolbox-header strong { font-size: 17px; font-weight: 650; }
.toolbox-header-actions { flex: 0 0 auto; display: flex; align-items: center; gap: 10px; }
.toolbox-header-action {
  width: 32px;
  height: 32px;
  padding: 0;
  border: 0;
  border-radius: 4px;
  background: transparent;
  color: var(--el-color-info);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  line-height: 1;
  cursor: pointer;
  transition: color 0.15s ease, background-color 0.15s ease;
}
.toolbox-header-action:hover,
.toolbox-header-action:focus-visible {
  color: var(--el-color-primary);
  background: var(--el-fill-color-light);
  outline: none;
}
.toolbox-header-action .el-icon { width: 18px; height: 18px; }
.toolbox-search { margin-bottom: 18px; }
.toolbox-list { overflow-y: auto; max-height: min(62vh, 610px); min-height: 165px; padding: 2px 4px 8px; }
.toolbox-grid { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 12px 8px; }
.toolbox-item { display: flex; flex-direction: column; align-items: center; gap: 9px; min-width: 0; padding: 10px 4px; border: 1px solid transparent; border-radius: 15px; background: transparent; color: var(--el-text-color-primary); font: inherit; cursor: pointer; }
.toolbox-item:not(:disabled):hover { background: var(--el-fill-color-light); border-color: var(--el-border-color-lighter); }
.toolbox-item:focus-visible { outline: 2px solid var(--el-color-primary); outline-offset: -2px; }
.toolbox-icon { display: inline-flex; align-items: center; justify-content: center; width: 60px; height: 60px; max-width: 100%; border: 1px solid var(--el-border-color); border-radius: 18px; color: var(--el-text-color-primary); background: var(--el-fill-color-light); }
.toolbox-icon-accent { color: var(--el-color-primary); background: var(--el-color-primary-light-9); border-color: var(--el-color-primary-light-7); }
.toolbox-label { max-width: 100%; overflow-wrap: anywhere; font-size: 12px; font-weight: 500; line-height: 1.25; text-align: center; }
.toolbox-item-disabled { opacity: 0.38; cursor: not-allowed; }
@media (max-width: 780px) { .toolbox-grid { grid-template-columns: repeat(4, minmax(0, 1fr)); } }
@media (max-width: 550px) { .toolbox-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); } .toolbox-icon { width: 52px; height: 52px; border-radius: 15px; } }
@media (max-width: 390px) { .toolbox-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
</style>

<style>
.toolbox-dialog.el-dialog { max-width: calc(100vw - 24px); max-height: calc(100dvh - 20px); display: flex; flex-direction: column; }
.toolbox-dialog .el-dialog__header { flex: 0 0 auto; }
.toolbox-dialog .el-dialog__body { flex: 1 1 auto; min-height: 0; display: flex; flex-direction: column; overflow: hidden; }
.toolbox-dialog .toolbox-list { flex: 1 1 auto; }
</style>
