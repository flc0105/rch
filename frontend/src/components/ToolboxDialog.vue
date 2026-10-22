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
            :title="action.disabled && action.shortcut ? `Unavailable: ${action.label}` : action.label"
            @click="action.disabled ? null : (action.shortcut ? $emit('launch-pin', action.shortcut) : $emit('launch', action.id))"
          >
            <span class="toolbox-icon" :class="{ 'toolbox-icon-accent': action.accent }">
              <component :is="iconComponents[action.icon]" :size="27" :stroke-width="1.75" aria-hidden="true" />
            </span>
            <span class="toolbox-label">{{ action.label }}</span>
            <span v-if="action.shortcut && action.unavailable" class="toolbox-shortcut-unavailable">Unavailable</span>
          </button>
        </div>
        <div v-if="!query.trim()" class="toolbox-grid-entry">
          <button class="toolbox-item" type="button" title="Add shortcut" aria-label="Add shortcut" @click="openShortcutPicker">
            <span class="toolbox-icon toolbox-icon-add"><Plus :size="27" :stroke-width="1.75" /></span>
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
        v-if="contextMenuAction.shortcut?.kind === 'quick_action' && !contextMenuAction.disabled"
        type="button" role="menuitem" class="toolbox-context-menu-item"
        @click="handleContextCommand(contextMenuAction, 'terminal')">Run in Terminal</button>
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

  <el-dialog v-model="shortcutPickerVisible" title="Add to Toolbox" width="520px" class="toolbox-add-dialog" append-to-body>
    <el-form label-position="top">
      <el-form-item label="Type">
        <el-radio-group v-model="shortcutKind" class="toolbox-shortcut-type"><el-radio-button value="script">Script</el-radio-button><el-radio-button value="quick_action">Quick Action</el-radio-button></el-radio-group>
      </el-form-item>
      <el-form-item label="Resource">
        <el-select v-model="shortcutResource" filterable placeholder="Select a resource" style="width: 100%" :loading="pinLoading">
          <el-option v-for="item in pickerResources" :key="item.key" :label="item.label" :value="item.key" :disabled="item.pinned" />
        </el-select>
      </el-form-item>
      <el-form-item label="Display Name">
        <el-input v-model="shortcutLabel" maxlength="64" show-word-limit placeholder="Optional custom name" />
      </el-form-item>
      <el-form-item label="Icon">
        <button type="button" class="toolbox-icon-select" @click="iconPickerVisible = true">
          <component :is="iconComponents[shortcutIcon]" :size="21" aria-hidden="true" />
          <span>{{ shortcutIcon }}</span>
          <span class="toolbox-icon-select-change">Choose icon</span>
        </button>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="shortcutPickerVisible = false">Cancel</el-button>
      <el-button type="primary" :disabled="!shortcutResource || pinLoading" @click="addShortcut">Add</el-button>
    </template>
  </el-dialog>
  <IconPickerDialog
    v-model:visible="iconPickerVisible"
    :model-value="shortcutIcon"
    :icons="shortcutIconChoices"
    :icon-components="iconComponents"
    @select="selectShortcutIcon"
  />
</template>

<script>
import {
  Activity, Archive, BookOpen, Bot, CalendarClock, Clipboard, Code2,
  FileCode, FolderOpen, History, KeyRound, Monitor, MonitorPlay,
  Search, Settings2, Terminal, Wrench, Zap, ScrollText,
  Plus, Rocket, Play, ShieldCheck,
  Star, Heart, CheckCircle, CircleAlert, Bell, Bookmark, Flag, Folder, FolderCode,
  FileText, FileJson, Files, Braces, Bug, GitBranch, GitMerge, GitPullRequest, GitCommit,
  Box, Boxes, Cpu, HardDrive, Cloud, CloudUpload, CloudDownload, Download, Upload,
  Settings, SlidersHorizontal, DatabaseBackup, Shield, Lock, RefreshCcw, Repeat,
  Timer, Clock, Calendar, ListChecks, ListTodo, ChartNoAxesColumn, ChartLine, Eye,
  Filter, Link, Globe2, Network, Wifi, Send, Mail, MessageSquare, Image, Camera,
  Video, Music, Headphones, Pencil, PenLine, Trash2, Copy, Scissors, Save, Printer,
  Power, Plug, Lightbulb, Sun, Moon,
} from '@lucide/vue'
import { Close } from '@element-plus/icons-vue'
import IconPickerDialog from './IconPickerDialog.vue'
import { TOOLBOX_SHORTCUT_ICONS, isScriptSupportedOnPlatform, isQuickActionSupportedOnPlatform } from '../data/toolbarPreferences.js'

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
  zap: Zap, search: Search,
  rocket: Rocket, play: Play, 'shield-check': ShieldCheck,
  star: Star, heart: Heart, 'check-circle': CheckCircle, 'circle-alert': CircleAlert,
  bell: Bell, bookmark: Bookmark, flag: Flag, folder: Folder, 'folder-code': FolderCode,
  'file-text': FileText, 'file-json': FileJson, files: Files, braces: Braces, bug: Bug,
  'git-branch': GitBranch, 'git-merge': GitMerge, 'git-pull-request': GitPullRequest,
  'git-commit': GitCommit, box: Box, boxes: Boxes, cpu: Cpu, 'hard-drive': HardDrive,
  cloud: Cloud, 'cloud-upload': CloudUpload, 'cloud-download': CloudDownload,
  download: Download, upload: Upload, settings: Settings, 'sliders-horizontal': SlidersHorizontal,
  'database-backup': DatabaseBackup, shield: Shield, lock: Lock,
  'refresh-ccw': RefreshCcw, repeat: Repeat, timer: Timer, clock: Clock,
  calendar: Calendar, 'list-checks': ListChecks, 'list-todo': ListTodo,
  'chart-no-axes-column': ChartNoAxesColumn, 'chart-line': ChartLine, eye: Eye,
  filter: Filter, link: Link, 'globe-2': Globe2, network: Network, wifi: Wifi,
  send: Send, mail: Mail, 'message-square': MessageSquare, image: Image,
  camera: Camera, video: Video, music: Music, headphones: Headphones,
  pencil: Pencil, 'pen-line': PenLine, 'trash-2': Trash2, copy: Copy,
  scissors: Scissors, save: Save, printer: Printer, power: Power, plug: Plug,
  lightbulb: Lightbulb, sun: Sun, moon: Moon,
})

export default {
  name: 'ToolboxDialog',
  components: { Search, Settings2, Close, Plus, IconPickerDialog },
  props: {
    visible: { type: Boolean, default: false },
    actions: { type: Array, default: () => [] },
    shortcuts: { type: Array, default: () => [] },
    scripts: { type: Array, default: () => [] },
    quickActions: { type: Array, default: () => [] },
    pinLoading: { type: Boolean, default: false },
    currentPlatform: { type: String, default: '' },
  },
  emits: ['update:visible', 'launch', 'load-pin-options', 'add-pin', 'remove-pin', 'launch-pin'],
  data() {
    return { query: '', contextMenuAction: null, contextMenuX: 0, contextMenuY: 0, contextMenuSerial: 0,
      shortcutPickerVisible: false, iconPickerVisible: false, shortcutKind: 'script', shortcutResource: '', shortcutIcon: 'file-code', shortcutLabel: '' }
  },
  computed: {
    iconComponents() { return icons },
    shortcutIconChoices() { return TOOLBOX_SHORTCUT_ICONS },
    pickerResources() {
      const isScript = this.shortcutKind === 'script'
      const items = isScript
        ? this.scripts.filter(item => item.script_name && isScriptSupportedOnPlatform(item, this.currentPlatform)).map(item => ({ key: item.script_name, label: item.display_name || item.script_name, pin: { kind: 'script', script_name: item.script_name } }))
        : this.quickActions.filter(item => item.in_current_scope === true && item.platform && item.alias && isQuickActionSupportedOnPlatform(item.platform, this.currentPlatform)).map(item => ({
          key: JSON.stringify([item.platform, item.alias]), label: `${item.alias} · ${item.platform}`,
          pin: { kind: 'quick_action', platform: item.platform, alias: item.alias },
        }))
      return items.map(item => ({ ...item, pinned: this.shortcuts.some(pin =>
        pin.kind === item.pin.kind && (isScript ? pin.script_name === item.pin.script_name
          : pin.platform === item.pin.platform && pin.alias === item.pin.alias)) }))
        .sort((a, b) => a.label.localeCompare(b.label, 'en', { sensitivity: 'base' }) || a.key.localeCompare(b.key))
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
      this.shortcutLabel = ''
      this.iconPickerVisible = false
      this.shortcutPickerVisible = true
      this.$emit('load-pin-options')
    },
    selectShortcutIcon(name) {
      if (this.shortcutIconChoices.includes(name)) this.shortcutIcon = name
    },
    addShortcut() {
      const choice = this.pickerResources.find(item => item.key === this.shortcutResource && !item.pinned)
      if (!choice) return
      this.$emit('add-pin', { ...choice.pin, icon: this.shortcutIcon, ...(this.shortcutLabel.trim() ? { label: this.shortcutLabel.trim().slice(0, 64) } : {}) })
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
        if (option === 'unpin') this.$emit('remove-pin', action.shortcut)
        else this.$emit('launch-pin', action.shortcut, option === 'terminal' ? 'terminal' : 'dialog')
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
      this.iconPickerVisible = false
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
.toolbox-list { overflow-y: auto; min-height: 0; padding: 2px 4px 8px; }
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
.toolbox-icon-add { border-style: dashed; }
.toolbox-icon-accent { color: var(--el-color-primary); background: var(--el-color-primary-light-9); border-color: var(--el-color-primary-light-7); }
.toolbox-label { max-width: 100%; overflow-wrap: anywhere; font-size: 12px; font-weight: 500; line-height: 1.25; text-align: center; }
.toolbox-icon-select { display: flex; align-items: center; gap: 12px; width: 100%; min-width: 0; padding: 10px 12px; border: 1px solid var(--el-border-color); border-radius: 8px; background: var(--el-fill-color-light); color: var(--el-text-color-primary); font: inherit; cursor: pointer; }
.toolbox-icon-select-change { margin-left: auto; color: var(--el-color-primary); font-size: 13px; }
/* Element Plus draws the radio buttons' outlines; leave room for the first outline near a scroll container edge. */
.toolbox-shortcut-type { margin-inline-start: 1px; }
.toolbox-item-disabled { opacity: 0.38; cursor: not-allowed; }
.toolbox-shortcut-unavailable { font-size: 11px; color: var(--el-color-danger); }
@media (max-width: 780px) { .toolbox-grid { grid-template-columns: repeat(4, minmax(0, 1fr)); } }
@media (max-width: 550px) { .toolbox-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); } .toolbox-icon { width: 52px; height: 52px; border-radius: 15px; } }
@media (max-width: 390px) { .toolbox-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
</style>

<style>
.toolbox-dialog.el-dialog { max-width: calc(100vw - 24px); height: min(70vh, calc(100dvh - 24px)); display: flex; flex-direction: column; }
.toolbox-dialog .el-dialog__header { flex: 0 0 auto; }
.toolbox-dialog .el-dialog__body { flex: 1 1 auto; min-height: 0; display: flex; flex-direction: column; overflow: hidden; }
.toolbox-dialog .toolbox-list { flex: 1 1 auto; }
</style>

<style>
.toolbox-add-dialog.el-dialog { max-width: calc(100vw - 24px); height: min(58vh, calc(100dvh - 24px)); display: flex; flex-direction: column; }
.toolbox-add-dialog .el-dialog__header, .toolbox-add-dialog .el-dialog__footer { flex: 0 0 auto; }
.toolbox-add-dialog .el-dialog__body { flex: 1 1 auto; min-height: 0; overflow-y: auto; }
</style>
