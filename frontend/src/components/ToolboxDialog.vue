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
        <div
          v-for="action in filteredActions"
          :key="action.id"
          class="toolbox-grid-entry"
          @contextmenu.prevent.stop="openContextMenu($event, action)"
        >
          <button
            class="toolbox-item"
            :class="{ 'toolbox-item-disabled': action.disabled }"
            type="button"
            :disabled="action.disabled && !action.shortcut"
            :title="action.label"
            @click="action.disabled ? null : (action.shortcut ? $emit('launch-pin', action.shortcut) : $emit('launch', action.id))"
          >
            <span class="toolbox-icon" :class="{ 'toolbox-icon-accent': action.accent }">
              <component :is="iconComponents[action.icon]" :size="27" :stroke-width="1.75" aria-hidden="true" />
            </span>
            <span class="toolbox-label">{{ action.label }}</span>
          </button>
        </div>
        <div v-if="!query.trim()" class="toolbox-grid-entry">
          <button class="toolbox-item" type="button" title="Add shortcut" aria-label="Add shortcut" @click="openShortcutPicker">
            <span class="toolbox-icon"><Plus :size="27" :stroke-width="1.75" /></span>
            <span class="toolbox-label">Add</span>
          </button>
        </div>
      </div>
      <el-empty v-else description="No tools found" :image-size="72" />
    </div>
  </el-dialog>

  <!-- One context menu for the entire Toolbox: anchor it to the pointer, not the icon. -->
  <teleport to="body">
    <div
      v-if="contextMenuAction"
      ref="contextMenu"
      class="toolbox-context-menu"
      role="menu"
      :style="{ left: `${contextMenuX}px`, top: `${contextMenuY}px` }"
      @pointerdown.stop
      @click.stop
      @contextmenu.prevent.stop
      @keydown.esc.stop.prevent="closeContextMenu"
    >
      <button type="button" role="menuitem" class="toolbox-context-menu-item" :disabled="contextMenuAction.disabled" @click="handleContextCommand(contextMenuAction, 'open')">Open</button>
      <button
        v-if="contextMenuAction.shortcut"
        type="button" role="menuitem" class="toolbox-context-menu-item"
        @click="handleContextCommand(contextMenuAction, 'unpin')">Unpin</button>
      <button
        v-for="option in contextMenuAction.menuOptions || []"
        :key="option.id"
        type="button"
        role="menuitem"
        class="toolbox-context-menu-item"
        @click="handleContextCommand(contextMenuAction, option.id)"
      >{{ option.label }}</button>
    </div>
  </teleport>

  <el-dialog v-model="shortcutPickerVisible" title="Add to Toolbox" width="520px" append-to-body>
    <el-form label-position="top">
      <el-form-item label="Type">
        <el-radio-group v-model="shortcutKind"><el-radio-button value="script">Script</el-radio-button><el-radio-button value="quick_action">Quick Action</el-radio-button></el-radio-group>
      </el-form-item>
      <el-form-item label="Resource">
        <el-select v-model="shortcutResource" filterable placeholder="Select a resource" style="width: 100%" :loading="pinLoading">
          <el-option v-for="item in pickerResources" :key="item.key" :label="item.label" :value="item.key" :disabled="item.pinned" />
        </el-select>
      </el-form-item>
      <el-form-item label="Icon">
        <div class="toolbox-icon-picker">
          <button v-for="name in shortcutIconChoices" :key="name" type="button"
            class="toolbox-icon-choice" :class="{ 'is-selected': shortcutIcon === name }"
            :title="name" :aria-label="name" @click="shortcutIcon = name">
            <component :is="iconComponents[name]" :size="21" />
          </button>
        </div>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="shortcutPickerVisible = false">Cancel</el-button>
      <el-button type="primary" :disabled="!shortcutResource || pinLoading" @click="addShortcut">Add</el-button>
    </template>
  </el-dialog>
</template>

<script>
import {
  Activity, Archive, BookOpen, Bot, CalendarClock, Clipboard, Code2,
  FileCode, FolderOpen, History, KeyRound, Monitor, MonitorPlay,
  Search, Settings2, Terminal, Wrench, Zap, ScrollText,
  Plus, Rocket, Play, ShieldCheck,
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
  rocket: Rocket, play: Play, 'shield-check': ShieldCheck,
})

export default {
  name: 'ToolboxDialog',
  components: { Search, Settings2, Close, Plus },
  props: {
    visible: { type: Boolean, default: false },
    actions: { type: Array, default: () => [] },
    shortcuts: { type: Array, default: () => [] },
    scripts: { type: Array, default: () => [] },
    quickActions: { type: Array, default: () => [] },
    pinLoading: { type: Boolean, default: false },
  },
  emits: ['update:visible', 'launch', 'load-pin-options', 'add-pin', 'remove-pin', 'launch-pin'],
  data() {
    return { query: '', contextMenuAction: null, contextMenuX: 0, contextMenuY: 0, contextMenuSerial: 0,
      shortcutPickerVisible: false, shortcutKind: 'script', shortcutResource: '', shortcutIcon: 'file-code' }
  },
  computed: {
    iconComponents() { return icons },
    shortcutIconChoices() {
      return ['file-code', 'terminal', 'zap', 'rocket', 'play', 'activity', 'shield-check', 'folder-open',
        'monitor', 'wrench', 'calendar-clock', 'book-open', 'code-2', 'archive', 'clipboard', 'scroll-text']
    },
    pickerResources() {
      const isScript = this.shortcutKind === 'script'
      const items = isScript
        ? this.scripts.filter(item => item.script_name).map(item => ({ key: item.script_name, label: item.display_name || item.script_name, pin: { kind: 'script', script_name: item.script_name } }))
        : this.quickActions.filter(item => item.in_current_scope === true && item.platform && item.alias).map(item => ({
          key: JSON.stringify([item.platform, item.alias]), label: `${item.alias} · ${item.platform}`,
          pin: { kind: 'quick_action', platform: item.platform, alias: item.alias },
        }))
      return items.map(item => ({ ...item, pinned: this.shortcuts.some(pin =>
        pin.kind === item.pin.kind && (isScript ? pin.script_name === item.pin.script_name
          : pin.platform === item.pin.platform && pin.alias === item.pin.alias)) }))
    },
    filteredActions() {
      const term = this.query.trim().toLocaleLowerCase()
      if (!term) return this.actions
      return this.actions.filter((action) => action.label.toLocaleLowerCase().includes(term))
    },
  },
  mounted() {
    document.addEventListener('pointerdown', this.onOutsidePointerDown, true)
    document.addEventListener('scroll', this.onViewportScroll, true)
    window.addEventListener('keydown', this.onGlobalKeydown, true)
    window.addEventListener('resize', this.closeContextMenu)
  },
  beforeUnmount() {
    document.removeEventListener('pointerdown', this.onOutsidePointerDown, true)
    document.removeEventListener('scroll', this.onViewportScroll, true)
    window.removeEventListener('keydown', this.onGlobalKeydown, true)
    window.removeEventListener('resize', this.closeContextMenu)
  },
  methods: {
    openShortcutPicker() {
      this.closeContextMenu()
      this.shortcutKind = 'script'
      this.shortcutResource = ''
      this.shortcutIcon = 'file-code'
      this.shortcutPickerVisible = true
      this.$emit('load-pin-options')
    },
    addShortcut() {
      const choice = this.pickerResources.find(item => item.key === this.shortcutResource && !item.pinned)
      if (!choice) return
      this.$emit('add-pin', { ...choice.pin, icon: this.shortcutIcon })
      this.shortcutPickerVisible = false
    },
    openContextMenu(event, action) {
      if (action.disabled && !action.shortcut) { this.closeContextMenu(); return }
      const serial = ++this.contextMenuSerial
      this.contextMenuAction = action
      this.contextMenuX = event.clientX
      this.contextMenuY = event.clientY
      // Read the actual menu size so the menu stays inside the viewport.
      this.$nextTick(() => {
        if (serial !== this.contextMenuSerial) return
        const rect = this.$refs.contextMenu?.getBoundingClientRect?.()
        if (!rect) return
        const margin = 8
        this.contextMenuX = Math.max(margin, Math.min(event.clientX, window.innerWidth - rect.width - margin))
        this.contextMenuY = Math.max(margin, Math.min(event.clientY, window.innerHeight - rect.height - margin))
      })
    },
    closeContextMenu() {
      this.contextMenuSerial++
      this.contextMenuAction = null
    },
    onOutsidePointerDown(event) {
      if (this.contextMenuAction && !this.$refs.contextMenu?.contains(event.target)) this.closeContextMenu()
    },
    onGlobalKeydown(event) {
      if (!this.contextMenuAction || event.key !== 'Escape') return
      event.preventDefault()
      event.stopPropagation()
      this.closeContextMenu()
    },
    onViewportScroll(event) {
      if (this.contextMenuAction && !this.$refs.contextMenu?.contains(event.target)) this.closeContextMenu()
    },
    handleContextCommand(action, option) {
      if (action.disabled && option !== 'unpin') return
      this.closeContextMenu()
      if (action.shortcut) {
        this.$emit(option === 'unpin' ? 'remove-pin' : 'launch-pin', action.shortcut)
      } else this.$emit('launch', action.id, option)
    },
  },
  watch: {
    query() { this.closeContextMenu() },
    shortcutKind() { this.shortcutResource = '' },
    visible(isVisible) {
      this.closeContextMenu()
      if (!isVisible) return
      this.query = ''
      this.shortcutPickerVisible = false
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
.toolbox-grid-entry { display: block; min-width: 0; }
.toolbox-context-menu {
  position: fixed;
  z-index: 4000;
  min-width: 150px;
  max-width: calc(100vw - 16px);
  max-height: calc(100dvh - 16px);
  overflow-y: auto;
  padding: 5px;
  border: 1px solid var(--el-border-color-light);
  border-radius: var(--el-border-radius-base);
  background: var(--el-bg-color-overlay);
  box-shadow: var(--el-box-shadow-light);
}
.toolbox-context-menu-item {
  display: block;
  width: 100%;
  padding: 8px 12px;
  border: 0;
  border-radius: 4px;
  background: transparent;
  color: var(--el-text-color-regular);
  font: inherit;
  font-size: 14px;
  line-height: 1.5;
  text-align: left;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  cursor: pointer;
}
.toolbox-context-menu-item:hover,
.toolbox-context-menu-item:focus-visible {
  color: var(--el-color-primary);
  background: var(--el-fill-color-light);
  outline: none;
}
.toolbox-item { width: 100%; display: flex; flex-direction: column; align-items: center; gap: 9px; min-width: 0; padding: 10px 4px; border: 1px solid transparent; border-radius: 15px; background: transparent; color: var(--el-text-color-primary); font: inherit; cursor: pointer; }
.toolbox-item:not(:disabled):hover { background: var(--el-fill-color-light); border-color: var(--el-border-color-lighter); }
.toolbox-item:focus-visible { outline: 2px solid var(--el-color-primary); outline-offset: -2px; }
.toolbox-icon { display: inline-flex; align-items: center; justify-content: center; width: 60px; height: 60px; max-width: 100%; border: 1px solid var(--el-border-color); border-radius: 18px; color: var(--el-text-color-primary); background: var(--el-fill-color-light); }
.toolbox-icon-accent { color: var(--el-color-primary); background: var(--el-color-primary-light-9); border-color: var(--el-color-primary-light-7); }
.toolbox-label { max-width: 100%; overflow-wrap: anywhere; font-size: 12px; font-weight: 500; line-height: 1.25; text-align: center; }
.toolbox-icon-picker { display: grid; grid-template-columns: repeat(8, minmax(0, 1fr)); gap: 8px; width: 100%; }
.toolbox-icon-choice { display: grid; place-items: center; min-width: 0; height: 40px; border: 1px solid var(--el-border-color); border-radius: 8px; background: var(--el-fill-color-light); color: var(--el-text-color-primary); cursor: pointer; }
.toolbox-icon-choice.is-selected { border-color: var(--el-color-primary); color: var(--el-color-primary); background: var(--el-color-primary-light-9); }
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
