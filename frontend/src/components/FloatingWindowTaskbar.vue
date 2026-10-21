<template>
  <div v-if="windows.length" v-show="!modalOpen" class="rch-floating-taskbar" :style="taskbarPosition">
    <div class="rch-window-taskbar-grip" title="Drag taskbar" @pointerdown="startDrag">
      <span class="rch-taskbar-grip-dots">⋮⋮</span>
      <span class="rch-taskbar-device">{{ deviceLabel || 'Windows' }}</span>
      <span class="rch-taskbar-count">{{ windows.length }}</span>
    </div>
    <div class="rch-taskbar-items">
      <button
        v-for="item in windows"
        :key="item.id"
        class="rch-taskbar-item"
        :class="{ 'rch-taskbar-item-active': activeId === item.id && !item.minimized, 'rch-taskbar-item-minimized': item.minimized }"
        type="button"
        :title="item.title"
        @click="toggleTask(item.id)"
        @contextmenu.prevent.stop="openMenu($event, item.id)"
      >
        <span class="rch-taskbar-item-icon">{{ item.icon }}</span>
        <span class="rch-taskbar-item-title">{{ item.title }}</span>
        <span v-if="item.minimized" class="rch-taskbar-item-min-mark">−</span>
      </button>
    </div>
    <div v-if="menuId" class="rch-window-context-menu" :style="menuPosition" @pointerdown.stop>
      <button type="button" @click="activate(menuId); menuId = ''">Restore / Bring to Front</button>
      <button type="button" @click="minimize(menuId); menuId = ''">Minimize</button>
      <button type="button" class="rch-window-context-close" @click="requestClose(menuId); menuId = ''">Close</button>
    </div>
  </div>
</template>

<script>
// Dialogs stay mounted while minimized. Only their DOM overlay is hidden: never
// toggle the component's v-model here, as @close destroys remote sessions.
const GLOBAL_TOOLS = new Set(['agents', 'one-liners', 'settings', 'builder', 'groups', 'documents'])
const TOOLS = {
  log: ['Log Viewer', '▤'], screen: ['Screen View', '▣'], pty: ['Remote PTY', '⌘'],
  files: ['Remote Files', '▦'], process: ['Process Manager', '▥'], info: ['Connection Info', 'ⓘ'],
  external: ['External Tools', '⚙'], scripts: ['Script Library', '≡'], jobs: ['Background Jobs', '◷'],
  artifacts: ['Artifacts', '▧'], history: ['Command History', '↺'], clipboard: ['Clipboard', '▤'],
  keychains: ['Keychains', '⚿'], 'quick-actions': ['Quick Actions', '⚡'],
  'one-liners': ['One-Liners', '≡'], agents: ['Agent Outputs', '◇'],
  settings: ['Settings', '⚙'], builder: ['Build Agent', '◇'],
  groups: ['Device Groups', '▣'], documents: ['Documents', '▤'],
}

export default {
  name: 'FloatingWindowTaskbar',
  props: { deviceLabel: { type: String, default: '' } },
  emits: ['close-window'],
  data() {
    return {
      windows: [], activeId: '', menuId: '', menuX: 0, menuY: 0, modalOpen: false,
      posX: null, posY: null,
    }
  },
  computed: {
    taskbarPosition() {
      return this.posX === null ? {} : { left: `${this.posX}px`, top: `${this.posY}px`, right: 'auto', bottom: 'auto' }
    },
    menuPosition() {
      return { left: `${this.menuX}px`, top: `${this.menuY}px` }
    },
  },
  mounted() {
    this._entries = new Map()
    this._scanScheduled = false
    this._observer = new MutationObserver(() => this.queueScan())
    this._observer.observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ['style', 'class'] })
    this._onPointerDown = event => {
      if (!event.target.closest?.('.rch-floating-taskbar')) this.menuId = ''
      const dialog = event.target.closest?.('.el-dialog.rch-managed-window')
      if (dialog) {
        const entry = [...this._entries.values()].find(item => item.dialog === dialog)
        if (entry) this.bringForward(entry.id)
      }
    }
    document.addEventListener('pointerdown', this._onPointerDown, true)
    this.queueScan()
  },
  beforeUnmount() {
    this._observer?.disconnect()
    document.removeEventListener('pointerdown', this._onPointerDown, true)
    this.finishDrag()
    for (const entry of this._entries?.values() || []) {
      if (entry.minimized && entry.host?.isConnected) entry.host.style.display = ''
    }
  },
  methods: {
    queueScan() {
      if (this._scanScheduled) return
      this._scanScheduled = true
      this.$nextTick(() => { this._scanScheduled = false; this.scanWindows() })
    },
    scanWindows() {
      const seen = new Set()
      for (const dialog of document.querySelectorAll('.el-dialog.rch-managed-window')) {
        const id = Object.keys(TOOLS).find(key => dialog.classList.contains(`rch-window-${key}`))
        if (!id) continue
        const host = dialog.closest('.el-overlay') || dialog.closest('.el-overlay-dialog') || dialog
        const previous = this._entries.get(id)
        // Element Plus can hide the dialog (or an inner overlay wrapper)
        // without hiding the outer overlay node. Checking the host alone
        // leaves a dead taskbar entry after a backdrop/ESC/titlebar close.
        // A window minimized by us is intentionally hidden and stays listed.
        const rendered = dialog.isConnected !== false &&
          host.style.display !== 'none' &&
          (typeof dialog.getClientRects !== 'function' || dialog.getClientRects().length > 0)
        if (!rendered && !previous?.minimized) continue
        seen.add(id)
        const [shortTitle, icon] = TOOLS[id]
        const title = (dialog.querySelector?.('.el-dialog__title, .screen-view-dialog-title')?.textContent || shortTitle).trim() || shortTitle
        if (previous?.dialog === dialog) {
          previous.title = title
          this.attachMinimizeControl(previous)
          continue
        }
        const entry = { id, dialog, host, title, shortTitle, icon, minimized: false }
        this._entries.set(id, entry)
        this.attachMinimizeControl(entry)
        this.bringForward(id)
      }
      for (const id of [...this._entries.keys()]) {
        if (!seen.has(id)) this._entries.delete(id)
      }
      if (!this._entries.has(this.activeId)) this.activeId = [...this._entries.keys()].at(-1) || ''
      if (this.menuId && !this._entries.has(this.menuId)) this.menuId = ''
      this.windows = [...this._entries.values()].map(({ id, title, shortTitle, icon, minimized }) => ({ id, title, shortTitle, icon, minimized }))
      // Confirmation and nested dialogs keep their normal modal behavior.
      // Keep the floating taskbar below their interaction layer.
      this.modalOpen = [...document.querySelectorAll('.el-dialog:not(.rch-managed-window), .el-message-box')]
        .some(node => typeof node.getClientRects === 'function' && node.getClientRects().length > 0)
    },
    attachMinimizeControl(entry) {
      const header = entry.dialog.querySelector('.el-dialog__header')
      if (!header || header.querySelector('.rch-managed-minimize-button')) return
      const button = document.createElement('button')
      button.type = 'button'
      button.className = 'rch-managed-minimize-button'
      button.textContent = '−'
      button.title = 'Minimize'
      button.setAttribute('aria-label', 'Minimize')
      button.addEventListener('pointerdown', event => event.stopPropagation())
      button.addEventListener('mousedown', event => event.stopPropagation())
      button.addEventListener('click', event => {
        event.stopPropagation()
        this.minimize(entry.id)
      })
      const customActions = header.querySelector('.screen-view-header-actions, .documents-header-actions')
      if (customActions) {
        button.classList.add('rch-managed-minimize-custom')
        customActions.insertBefore(button, customActions.lastElementChild)
      } else {
        header.appendChild(button)
      }
    },
    bringForward(id) {
      const entry = this._entries.get(id)
      if (!entry) return
      // Keep managed windows at one stacking level; DOM order determines
      // which is frontmost. Element Plus modals and dropdowns then retain
      // their own higher z-indices instead of being obscured by our windows.
      entry.host.style.zIndex = '2000'
      const parent = entry.host.parentElement
      if (parent && parent.lastElementChild !== entry.host) parent.appendChild(entry.host)
      this.activeId = id
    },
    toggleTask(id) {
      const entry = this._entries.get(id)
      if (!entry) return
      if (this.activeId === id && !entry.minimized) this.minimize(id)
      else this.activate(id)
    },
    activate(id) {
      const entry = this._entries.get(id)
      if (!entry) return false
      if (entry.minimized) {
        entry.host.style.display = ''
        entry.minimized = false
        window.dispatchEvent(new Event('resize'))
      }
      this.bringForward(id)
      this.scanWindows()
      return true
    },
    minimize(id) {
      const entry = this._entries.get(id)
      if (!entry || entry.minimized) return false
      entry.minimized = true
      entry.host.style.display = 'none'
      if (this.activeId === id) {
        const next = [...this._entries.values()].reverse().find(item => !item.minimized)
        this.activeId = next?.id || ''
      }
      this.scanWindows()
      return true
    },
    prepareClose(id) {
      const entry = this._entries.get(id)
      if (!entry) return
      // Let Element Plus run its normal close transition and cleanup even
      // when the user closes a minimized window from the taskbar.
      entry.minimized = false
      entry.host.style.display = ''
    },
    requestClose(id) {
      if (!this._entries.has(id)) return
      this.$emit('close-window', id)
    },
    getDeviceWindowIds() {
      return [...this._entries.keys()].filter(id => !GLOBAL_TOOLS.has(id))
    },
    hasDeviceWindows() {
      return this.getDeviceWindowIds().length > 0
    },
    async waitForDeviceWindowsToClose(timeoutMs = 2000) {
      const deadline = Date.now() + timeoutMs
      while (Date.now() < deadline) {
        this.scanWindows()
        if (!this.hasDeviceWindows()) return true
        await new Promise(resolve => window.setTimeout(resolve, 40))
      }
      this.scanWindows()
      return !this.hasDeviceWindows()
    },
    restoreAll() {
      for (const entry of this._entries.values()) {
        if (entry.minimized) { entry.host.style.display = ''; entry.minimized = false }
      }
      this.scanWindows()
    },
    openMenu(event, id) {
      this.menuId = id
      this.menuX = Math.min(event.clientX, window.innerWidth - 210)
      this.menuY = Math.min(event.clientY, window.innerHeight - 125)
    },
    startDrag(event) {
      if (event.button !== 0) return
      const rect = this.$el.getBoundingClientRect()
      this._drag = { x: event.clientX - rect.left, y: event.clientY - rect.top }
      this.posX = rect.left
      this.posY = rect.top
      this._onDragMove = e => {
        this.posX = Math.max(0, Math.min(e.clientX - this._drag.x, window.innerWidth - this.$el.offsetWidth))
        this.posY = Math.max(0, Math.min(e.clientY - this._drag.y, window.innerHeight - this.$el.offsetHeight))
      }
      this._onDragEnd = () => this.finishDrag()
      window.addEventListener('pointermove', this._onDragMove)
      window.addEventListener('pointerup', this._onDragEnd, { once: true })
      event.preventDefault()
    },
    finishDrag() {
      if (this._onDragMove) window.removeEventListener('pointermove', this._onDragMove)
      if (this._onDragEnd) window.removeEventListener('pointerup', this._onDragEnd)
      this._onDragMove = null
      this._onDragEnd = null
      this._drag = null
    },
  },
}
</script>

<style scoped>
.rch-floating-taskbar { position: fixed; right: 18px; bottom: 18px; z-index: 10000; max-width: min(670px, calc(100vw - 24px)); min-width: 210px; padding: 8px; background: var(--el-bg-color-overlay, #fff); color: var(--el-text-color-primary); border: 1px solid var(--el-border-color); border-radius: 10px; box-shadow: var(--el-box-shadow-dark); }
.rch-window-taskbar-grip { display: flex; align-items: center; gap: 7px; cursor: grab; user-select: none; padding: 2px 4px 8px; font-size: 12px; }
.rch-window-taskbar-grip:active { cursor: grabbing; }
.rch-taskbar-grip-dots { color: var(--el-text-color-secondary); letter-spacing: -3px; }
.rch-taskbar-device { font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.rch-taskbar-count { margin-left: auto; color: var(--el-text-color-secondary); }
.rch-taskbar-items { display: flex; align-items: center; gap: 5px; overflow-x: auto; max-height: 88px; flex-wrap: wrap; }
.rch-taskbar-item { border: 1px solid var(--el-border-color); border-radius: 6px; padding: 6px 9px; display: inline-flex; align-items: center; gap: 6px; background: var(--el-fill-color-blank); color: inherit; cursor: pointer; font: inherit; font-size: 12px; max-width: 168px; }
.rch-taskbar-item:hover, .rch-taskbar-item-active { border-color: var(--el-color-primary); background: var(--el-color-primary-light-9); }
.rch-taskbar-item-minimized { opacity: .65; }
.rch-taskbar-item-title { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.rch-taskbar-item-min-mark { font-weight: 700; }
.rch-window-context-menu { position: fixed; width: 200px; display: grid; gap: 1px; z-index: 10001; background: var(--el-bg-color-overlay, #fff); border: 1px solid var(--el-border-color); box-shadow: var(--el-box-shadow); border-radius: 8px; padding: 5px; }
.rch-window-context-menu button { text-align: left; border: none; background: transparent; color: inherit; padding: 8px; border-radius: 5px; cursor: pointer; }
.rch-window-context-menu button:hover { background: var(--el-fill-color-light); }
.rch-window-context-close { color: var(--el-color-danger) !important; }
</style>

<style>
.el-dialog.rch-managed-window .el-dialog__header { position: relative; }
.el-dialog.rch-managed-window .rch-managed-minimize-button { position: absolute; top: 10px; right: 48px; width: 25px; height: 25px; border: 0; background: transparent; color: var(--el-text-color-secondary); border-radius: 4px; cursor: pointer; font-size: 20px; line-height: 23px; }
.el-dialog.rch-managed-window .rch-managed-minimize-button:hover { background: var(--el-fill-color-light); color: var(--el-text-color-primary); }
.el-dialog.rch-managed-window .rch-managed-minimize-custom { position: static; display: inline-flex; align-items: center; justify-content: center; margin-right: 6px; }
</style>
