<template>
  <aside class="sidebar panel">
    <div class="panel-header">
      <el-dropdown
        class="device-group-switcher"
        trigger="click"
        placement="bottom-start"
        @command="handleGroupFilterCommand"
      >
<!--        <button-->
<!--          type="button"-->
<!--          class="device-group-switcher-trigger"-->
<!--          aria-label="Device group filter"-->
<!--          @click="closeDeviceContextMenu"-->
<!--        >-->
<!--          <span class="device-group-switcher-name">{{ selectedGroupLabel }}</span>-->
<!--          <span class="device-group-switcher-count">{{ selectedGroupMachineCount }}</span>-->
<!--          <span class="device-group-switcher-chevron" aria-hidden="true"></span>-->
<!--        </button>-->

        <button
  type="button"
  class="device-group-switcher-trigger"
  aria-label="Device group filter"
  @click="closeDeviceContextMenu"
>
  <span class="device-group-switcher-name">{{ selectedGroupLabel }}</span>
  <span class="device-group-switcher-chevron" aria-hidden="true"></span>
</button>

        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item command="__all_devices__">
              <span class="device-group-dropdown-item">
                <span
                  class="device-group-dropdown-check"
                  :class="{ visible: !selectedGroupId }"
                >✓</span>
                <span class="device-group-dropdown-name">All Devices</span>
                <span class="device-group-dropdown-count">{{ getDeviceGroupCount('') }}</span>
              </span>
            </el-dropdown-item>

            <el-dropdown-item
              v-for="group in deviceGroups"
              :key="group.group_id"
              :command="group.group_id"
            >
              <span class="device-group-dropdown-item">
                <span
                  class="device-group-dropdown-check"
                  :class="{ visible: selectedGroupId === group.group_id }"
                >✓</span>
                <span class="device-group-dropdown-name">{{ group.name }}</span>
                <span class="device-group-dropdown-count">{{ getDeviceGroupCount(group.group_id) }}</span>
              </span>
            </el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>

      <el-dropdown
        trigger="click"
        placement="bottom-end"
        @command="handleToolbarCommand"
      >
        <el-button
          class="device-toolbar-more-btn"
          text
          title="Device actions"
          aria-label="Device actions"
          @click="closeDeviceContextMenu"
        >
          <span class="device-toolbar-more-icon">⋮</span>
        </el-button>

        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item command="refresh">
              Refresh
            </el-dropdown-item>

            <el-dropdown-item command="toggle-hidden">
              {{ showHiddenDevices ? 'Hide hidden devices' : 'Show hidden devices' }}
            </el-dropdown-item>

            <el-dropdown-item divided command="manage-groups">
              Manage groups
            </el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </div>

    <div class="sidebar-body">
      <div v-if="connections.length === 0" class="empty-state">
        No visible devices
      </div>

      <div
        v-for="item in connections"
        :key="item.client_id"
        class="device-item"
        :class="{
          active: selectedId === item.client_id,
          'device-item-hidden': item.device_hidden,
          'context-active': contextMenuClientId === item.client_id,
        }"
        @click="handleDeviceClick(item, $event)"
        @contextmenu.prevent.stop="openDeviceContextMenu($event, item)"
        @touchstart="handleDeviceTouchStart($event, item)"
        @touchmove="handleDeviceTouchMove"
        @touchend="handleDeviceTouchEnd"
        @touchcancel="handleDeviceTouchEnd"
      >
        <div class="device-item-top">
          <div class="device-text">
            <div class="device-name-row">
              <div class="device-name">
                {{ formatDeviceName(item) }}
              </div>
              <el-icon
                v-if="getConnectionDisplayState(item) === 'online' && item.client_revision_state === 'outdated'"
                class="device-update-indicator"
                title="Client update available"
              >
                <CaretTop />
              </el-icon>
            </div>
            <div class="device-os">
              {{ formatOsLabel(item.os_type, item.os_ver) }}
            </div>
          </div>

          <div
            class="device-dot"
            :class="getConnectionStatusDotClass(item)"
          ></div>
        </div>

        <div class="device-ip">
          {{ formatAddress(item.addr) }}
        </div>

        <div class="device-status-row">
          <span class="device-status-text">
            {{ getConnectionStatusText(item) }}
          </span>
          <span class="device-status-sep">·</span>
          <span class="device-status-text">
            last seen {{ formatConnectionLastSeenRelative(item) }}
          </span>
        </div>
      </div>
    </div>

    <Teleport to="body">
      <div
        v-if="contextMenuVisible"
        ref="deviceContextMenuRef"
        class="device-context-menu"
        :style="contextMenuStyle"
        @click.stop
        @contextmenu.prevent.stop
      >
        <button
          type="button"
          class="device-context-menu-item"
          @click="triggerDeviceContextCommand('rename-machine')"
        >
          Set alias
        </button>

        <button
          type="button"
          class="device-context-menu-item"
          :disabled="!contextMenuItem || !contextMenuItem.machine_id"
          @click="triggerDeviceContextCommand('connection-history')"
        >
          Connection history
        </button>

        <button
          type="button"
          class="device-context-menu-item device-context-menu-group-toggle"
          :disabled="!contextMenuItem || !contextMenuItem.machine_id"
          @click.stop="toggleContextGroupMenu"
        >
          <span>Set group</span>
          <span class="device-context-menu-arrow">{{ contextGroupMenuVisible ? '▾' : '›' }}</span>
        </button>

        <div v-if="contextGroupMenuVisible" class="device-context-group-list">
          <button
            type="button"
            class="device-context-menu-item device-context-group-item"
            @click="assignContextMachineGroup('')"
          >
            <span>No group</span>
            <span v-if="!contextMachineGroupId" class="device-context-group-check">✓</span>
          </button>

          <button
            v-for="group in deviceGroups"
            :key="group.group_id"
            type="button"
            class="device-context-menu-item device-context-group-item"
            @click="assignContextMachineGroup(group.group_id)"
          >
            <span class="device-context-group-name">{{ group.name }}</span>
            <span v-if="contextMachineGroupId === group.group_id" class="device-context-group-check">✓</span>
          </button>
        </div>

        <div class="device-context-menu-separator"></div>

        <button
          type="button"
          class="device-context-menu-item"
          :class="{ positive: contextMenuItem && contextMenuItem.device_hidden_by_client }"
          @click="triggerDeviceContextCommand('toggle-client-hidden')"
        >
          {{ contextMenuItem && contextMenuItem.device_hidden_by_client ? 'Unhide current connection' : 'Hide current connection' }}
        </button>

        <button
          type="button"
          class="device-context-menu-item"
          :class="{ positive: contextMenuItem && contextMenuItem.device_hidden_by_machine }"
          :disabled="!contextMenuItem || !contextMenuItem.machine_id"
          @click="triggerDeviceContextCommand('toggle-machine-hidden')"
        >
          {{ contextMenuItem && contextMenuItem.device_hidden_by_machine ? 'Unhide this machine' : 'Hide this machine' }}
        </button>

        <div class="device-context-menu-separator"></div>

        <button
          type="button"
          class="device-context-menu-item"
          :disabled="!canRunContextConnectionCommand"
          @click="triggerDeviceContextCommand('duplicate-connection')"
        >
          Duplicate connection
        </button>

        <button
          type="button"
          class="device-context-menu-item is-danger"
          :disabled="!canRunContextConnectionCommand"
          @click="triggerDeviceContextCommand('restart-connection')"
        >
          Restart connection
        </button>

        <button
          type="button"
          class="device-context-menu-item is-danger"
          :disabled="!canDisconnectContextConnection"
          @click="triggerDeviceContextCommand('disconnect')"
        >
          Disconnect
        </button>

        <button
          type="button"
          class="device-context-menu-item is-danger"
          :disabled="!canRemoveContextConnection"
          @click="triggerDeviceContextCommand('remove-connection')"
        >
          Remove connection
        </button>

      </div>
    </Teleport>
  </aside>
</template>

<script>

import { ElMessage, ElMessageBox } from 'element-plus'
import {CaretTop} from '@element-plus/icons-vue'
import {
  killConnection as killConnectionApi,
  removeConnection as removeConnectionApi,
  sendCommand as sendCommandApi,
} from '../api/connectionsApi.js'

export default {
  name: 'DeviceSidebar',

  components: {
    CaretTop,
  },

  props: {
    connections: {
      type: Array,
      default: () => [],
    },

    selectedId: {
      type: String,
      default: '',
    },

    statusNowTick: {
      type: Number,
      default: () => Date.now(),
    },

    deviceGroups: {
      type: Array,
      default: () => [],
    },

    machineGroupAssignments: {
      type: Object,
      default: () => ({}),
    },

    selectedGroupId: {
      type: String,
      default: '',
    },

    deviceGroupCounts: {
      type: Object,
      default: () => ({}),
    },

    showHiddenDevices: {
      type: Boolean,
      default: false,
    },

    getTabScopedHeaders: {
      type: Function,
      default: null,
    },
  },

  emits: [
    'refresh',
    'select',
    'toggle-hidden-devices',
    'toggle-client-hidden',
    'toggle-machine-hidden',
    'group-filter-change',
    'manage-groups',
    'assign-machine-group',
    'rename-machine',
    'open-connection-history',
    'connection-removed',
    'connection-remove-failed',
  ],

  data() {
    return {
      contextMenuVisible: false,
      contextMenuClientId: '',
      contextMenuItem: null,
      contextMenuX: 0,
      contextMenuY: 0,
      contextGroupMenuVisible: false,

      touchMenuTimer: null,
      touchStartX: 0,
      touchStartY: 0,
      touchMoved: false,
      suppressNextDeviceClick: false,

      // 移动端长按打开菜单后，浏览器可能补发 click / scroll。
      // 这两个时间窗用来避免菜单刚打开又被自动关闭。
      ignoreNextDocumentClickUntil: 0,
      ignoreNextScrollUntil: 0,
    }
  },

computed: {
  contextMenuStyle() {
    return {
      left: `${this.contextMenuX}px`,
      top: `${this.contextMenuY}px`,
    }
  },

  canRunContextConnectionCommand() {
    if (!this.contextMenuItem || !this.contextMenuItem.client_id) {
      return false
    }

    return this.getConnectionDisplayState(this.contextMenuItem) !== 'offline'
  },

  canDisconnectContextConnection() {
    return this.canRunContextConnectionCommand
  },

  canRemoveContextConnection() {
    return Boolean(this.contextMenuItem && this.contextMenuItem.client_id)
  },

  contextMachineGroupId() {
    const machineKey = String(this.contextMenuItem?.machine_id || '').trim().toLowerCase()
    if (!machineKey) return ''
    return String(this.machineGroupAssignments?.[machineKey] || '').trim()
  },

  selectedGroupLabel() {
    if (!this.selectedGroupId) return 'All Devices'

    const group = (this.deviceGroups || []).find(item => {
      return String(item?.group_id || '').trim() === String(this.selectedGroupId || '').trim()
    })

    return String(group?.name || '').trim() || 'All Devices'
  },

  selectedGroupMachineCount() {
    return this.getDeviceGroupCount(this.selectedGroupId)
  },
},

  mounted() {
    document.addEventListener('click', this.handleDocumentClick, true)
    document.addEventListener('keydown', this.handleDocumentKeydown, true)
    window.addEventListener('resize', this.closeDeviceContextMenu)
    window.addEventListener('scroll', this.handleWindowScroll, true)
  },

  beforeUnmount() {
    document.removeEventListener('click', this.handleDocumentClick, true)
    document.removeEventListener('keydown', this.handleDocumentKeydown, true)
    window.removeEventListener('resize', this.closeDeviceContextMenu)
    window.removeEventListener('scroll', this.handleWindowScroll, true)
    this.clearDeviceTouchTimer()
    document.body.classList.remove('device-touch-callout-guard')
  },

  methods: {
    handleToolbarCommand(command) {
      if (command === 'refresh') {
        this.$emit('refresh')
        return
      }

      if (command === 'toggle-hidden') {
        this.$emit('toggle-hidden-devices')
        return
      }

      if (command === 'manage-groups') {
        this.$emit('manage-groups')
      }
    },

    handleGroupFilterCommand(command) {
      this.closeDeviceContextMenu()
      const groupId = command === '__all_devices__' ? '' : String(command || '').trim()
      this.$emit('group-filter-change', groupId)
    },

    getDeviceGroupCount(groupId) {
      const key = String(groupId || '').trim() || '__all__'
      const count = Number(this.deviceGroupCounts?.[key] || 0)
      return Number.isFinite(count) ? Math.max(0, Math.floor(count)) : 0
    },

    toggleContextGroupMenu() {
      if (!this.contextMenuItem?.machine_id) return
      this.contextGroupMenuVisible = !this.contextGroupMenuVisible
      this.$nextTick(() => this.adjustDeviceContextMenuPosition())
    },

    assignContextMachineGroup(groupId) {
      const item = this.contextMenuItem
      if (!item?.machine_id) return
      this.closeDeviceContextMenu()
      this.$emit('assign-machine-group', item, String(groupId || '').trim())
    },

    handleDeviceClick(item, event) {
      if (this.suppressNextDeviceClick) {
        this.suppressNextDeviceClick = false

        if (event && typeof event.preventDefault === 'function') {
          event.preventDefault()
        }

        if (event && typeof event.stopPropagation === 'function') {
          event.stopPropagation()
        }

        return
      }

      this.closeDeviceContextMenu()
      this.$emit('select', item.client_id)
    },

    openDeviceContextMenu(event, item) {
      this.openDeviceContextMenuAt(event.clientX, event.clientY, item, {
        fromTouch: false,
      })
    },

    openDeviceContextMenuAt(x, y, item, options = {}) {
      this.clearDeviceTouchTimer()

      const now = Date.now()

      // 移动端长按打开菜单后，浏览器可能补发一次 click。
      // document 捕获阶段会先收到这个 click，如果不忽略，菜单会刚出现就关闭。
      this.ignoreNextDocumentClickUntil = now + 420

      // 长按附近可能伴随轻微滚动 / 惯性滚动，不要刚打开就被 scroll 关掉。
      if (options.fromTouch) {
        this.ignoreNextScrollUntil = now + 420
      }

      this.contextMenuItem = item
      this.contextGroupMenuVisible = false
      this.contextMenuClientId = String(item?.client_id || '')
      this.contextMenuX = x
      this.contextMenuY = y
      this.contextMenuVisible = true

      this.$nextTick(() => {
        this.adjustDeviceContextMenuPosition()
      })
    },

    clearDeviceTouchTimer() {
      if (this.touchMenuTimer) {
        window.clearTimeout(this.touchMenuTimer)
        this.touchMenuTimer = null
      }
    },

    handleDeviceTouchStart(event, item) {
      if (!event.touches || event.touches.length !== 1) return

      const touch = event.touches[0]

      this.clearDeviceTouchTimer()

      this.touchStartX = touch.clientX
      this.touchStartY = touch.clientY
      this.touchMoved = false
      this.suppressNextDeviceClick = false

      // 不在 touchstart 立刻 preventDefault，否则会阻止列表上下滚动。
      // 先用 body class 尽量压住 iOS 的 Copy / Look Up。
      document.body.classList.add('device-touch-callout-guard')

      this.touchMenuTimer = window.setTimeout(() => {
        if (this.touchMoved) return

        // 到这里说明是真的长按，不是滑动。
        // 这里再 preventDefault，尽量阻止 iOS 长按系统菜单。
        if (event.cancelable && typeof event.preventDefault === 'function') {
          event.preventDefault()
        }

        this.suppressNextDeviceClick = true
        this.openDeviceContextMenuAt(this.touchStartX, this.touchStartY, item, {
          fromTouch: true,
        })
      }, 520)
    },

    handleDeviceTouchMove(event) {
      if (!this.touchMenuTimer || !event.touches || event.touches.length !== 1) return

      const touch = event.touches[0]
      const dx = Math.abs(touch.clientX - this.touchStartX)
      const dy = Math.abs(touch.clientY - this.touchStartY)

      // 用户开始上下滑动，取消长按菜单，保留浏览器原生滚动。
      if (dx > 8 || dy > 8) {
        this.touchMoved = true
        this.clearDeviceTouchTimer()
        document.body.classList.remove('device-touch-callout-guard')
      }
    },

    handleDeviceTouchEnd() {
      this.clearDeviceTouchTimer()

      if (!this.contextMenuVisible) {
        document.body.classList.remove('device-touch-callout-guard')
      }
    },

    adjustDeviceContextMenuPosition() {
      const menu = this.$refs.deviceContextMenuRef
      if (!menu) return

      const rect = menu.getBoundingClientRect()
      const padding = 8
      const maxX = window.innerWidth - rect.width - padding
      const maxY = window.innerHeight - rect.height - padding

      this.contextMenuX = Math.max(padding, Math.min(this.contextMenuX, maxX))
      this.contextMenuY = Math.max(padding, Math.min(this.contextMenuY, maxY))
    },

    closeDeviceContextMenu() {
      this.contextMenuVisible = false
      this.contextMenuClientId = ''
      this.contextMenuItem = null
      this.contextGroupMenuVisible = false
      this.ignoreNextDocumentClickUntil = 0
      this.ignoreNextScrollUntil = 0
      document.body.classList.remove('device-touch-callout-guard')
    },

    handleDocumentClick(event) {
      if (!this.contextMenuVisible) return

      if (Date.now() < this.ignoreNextDocumentClickUntil) {
        return
      }

      const menu = this.$refs.deviceContextMenuRef
      if (menu && menu.contains(event.target)) return

      this.closeDeviceContextMenu()
    },

    handleDocumentKeydown(event) {
      if (event.key === 'Escape') {
        this.closeDeviceContextMenu()
      }
    },

    handleWindowScroll() {
      if (!this.contextMenuVisible) return

      if (Date.now() < this.ignoreNextScrollUntil) {
        return
      }

      this.closeDeviceContextMenu()
    },

async triggerDeviceContextCommand(command) {
  const item = this.contextMenuItem
  if (!item) return

  this.closeDeviceContextMenu()

  if (command === 'rename-machine') {
    this.$emit('rename-machine', item)
    return
  }

  if (command === 'connection-history') {
    this.$emit('open-connection-history', item)
    return
  }

  if (command === 'toggle-client-hidden') {
    this.$emit('toggle-client-hidden', item)
    return
  }

  if (command === 'toggle-machine-hidden') {
    this.$emit('toggle-machine-hidden', item)
    return
  }

  if (command === 'duplicate-connection') {
    await this.runConnectionSessionCommand(item, 'spawn_instance', 'Duplicate connection command submitted')
    return
  }

  if (command === 'restart-connection') {
    await this.runConnectionSessionCommand(item, 'relaunch_instance', 'Restart command submitted')
    return
  }

  if (command === 'disconnect') {
    await this.disconnectConnection(item)
    return
  }

  if (command === 'remove-connection') {
    await this.removeConnectionPermanently(item)
  }
},

async runConnectionSessionCommand(item, command, successMessage) {
  const clientId = String(item?.client_id || '').trim()

  if (!clientId) {
    ElMessage.warning('Invalid connection')
    return
  }

  if (this.getConnectionDisplayState(item) === 'offline') {
    ElMessage.warning('This connection is already offline')
    return
  }

  try {
    const headers = typeof this.getTabScopedHeaders === 'function'
      ? this.getTabScopedHeaders()
      : {}
    await sendCommandApi(clientId, command, headers)
    ElMessage.success(successMessage)
  } catch (e) {
    ElMessage.error(e.message || 'Failed to submit connection command')
  }
},

async disconnectConnection(item) {
  const clientId = String(item?.client_id || '').trim()

  if (!clientId) {
    ElMessage.warning('Invalid connection')
    return
  }

  if (this.getConnectionDisplayState(item) === 'offline') {
    ElMessage.warning('This connection is already offline')
    return
  }

  const deviceName = this.formatDeviceName(item)

  try {
    await ElMessageBox.confirm(
      `Disconnect "${deviceName}"?`,
      'Disconnect Connection',
      {
        type: 'warning',
        confirmButtonText: 'Disconnect',
        cancelButtonText: 'Cancel',
        confirmButtonClass: 'el-button--danger',
      },
    )

    await killConnectionApi(clientId)
    ElMessage.success('Disconnect request sent')
  } catch (e) {
    if (e === 'cancel' || e === 'close' || e?.message === 'cancel') {
      return
    }

    ElMessage.error(e.message || 'Failed to disconnect connection')
  }
},

async removeConnectionPermanently(item) {
  const clientId = String(item?.client_id || '').trim()

  if (!clientId) {
    ElMessage.warning('Invalid connection')
    return
  }

  const machineId = String(item?.machine_id || '').trim()
  const deviceName = this.formatDeviceName(item)
  const isOffline = this.getConnectionDisplayState(item) === 'offline'

  try {
    await ElMessageBox.confirm(
      isOffline
        ? `Remove "${deviceName}" from recent devices?`
        : `Remove "${deviceName}"? The session will be disconnected and the connection will be removed from recent devices.`,
      'Remove Connection',
      {
        type: 'warning',
        confirmButtonText: 'Remove Connection',
        cancelButtonText: 'Cancel',
        confirmButtonClass: 'el-button--danger',
      },
    )

    const removedPayload = {
      client_id: clientId,
      machine_id: machineId,
    }

    // Optimistically remove it from the sidebar immediately after confirmation.
    // loadConnections/upsertConnection will also suppress it while the backend delete is in flight.
    this.$emit('connection-removed', removedPayload)

    await removeConnectionApi(clientId, { machine_id: machineId })

    ElMessage.success('Connection removed')
  } catch (e) {
    if (e === 'cancel' || e === 'close' || e?.message === 'cancel') {
      return
    }

    this.$emit('connection-remove-failed', {
      client_id: clientId,
      machine_id: machineId,
    })

    ElMessage.error(e.message || 'Failed to remove connection')
  }
},

    formatDeviceName(item) {
      return item?.device_display_name || item?.display_hostname || item?.device_alias || item?.hostname || 'Unknown Host'
    },

    // 根据连接状态统一计算设备展示态
    getConnectionDisplayState(conn) {
      const state = String((conn && conn.connection_state) || '').trim()
      if (state === 'offline') return 'offline'

      if (conn && conn.is_transfer_active) {
        return 'online'
      }

      const disconnectedAt = String((conn && conn.disconnected_at) || '').trim()
      if (disconnectedAt) return 'offline'

      const lastSeenAt = String((conn && conn.last_seen_at) || '').trim()
      if (!lastSeenAt) return state || 'online'

      const staleAfterSeconds = Number((conn && conn.stale_after_seconds) || 45)
      const seenMs = Date.parse(lastSeenAt)
      if (!Number.isFinite(seenMs)) return state || 'online'

      const ageMs = Math.max(this.statusNowTick - seenMs, 0)
      if (ageMs > staleAfterSeconds * 1000) return 'stale'

      return 'online'
    },

    getConnectionStatusDotClass(conn) {
      const state = this.getConnectionDisplayState(conn)
      if (state === 'online') return 'device-dot-online'
      if (state === 'stale') return 'device-dot-stale'
      return 'device-dot-offline'
    },

    getConnectionStatusText(conn) {
      const state = this.getConnectionDisplayState(conn)
      if (state === 'online') return 'online'
      if (state === 'stale') return 'stale'
      return 'offline'
    },

    formatConnectionLastSeenRelative(conn) {
      if (!conn) return '-'

      const state = this.getConnectionDisplayState(conn)
      const baseText = state === 'offline'
        ? String(conn.disconnected_at || '').trim()
        : String(conn.last_seen_at || '').trim()

      if (!baseText) return '-'

      const ts = Date.parse(baseText)
      if (!Number.isFinite(ts)) return '-'

      const diffMs = Math.max(this.statusNowTick - ts, 0)
      const diffSec = Math.floor(diffMs / 1000)

      if (diffSec < 5) return 'just now'
      if (diffSec < 60) return `${diffSec}s ago`

      const diffMin = Math.floor(diffSec / 60)
      if (diffMin < 60) return `${diffMin}m ago`

      const diffHour = Math.floor(diffMin / 60)
      if (diffHour < 24) return `${diffHour}h ago`

      const diffDay = Math.floor(diffHour / 24)
      return `${diffDay}d ago`
    },

    formatOsLabel(osType, osVer) {
      const type = osType || 'Unknown'
      return osVer ? `${type}` : type
    },

    formatAddress(addr) {
      if (!addr) return '-'
      const raw = String(addr)
      const parts = raw.split(':')
      if (parts.length >= 2) return parts.slice(0, -1).join(':') || raw
      return raw
    },
  },
}
</script>

<style scoped>
/* ========== 设备侧边栏 ========== */
.sidebar {
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.panel-header {
  min-height: 54px;
  padding: 11px 14px 10px 16px;
  border-bottom: 1px solid var(--line);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-shrink: 0;
}

.device-group-switcher {
  min-width: 0;
  max-width: calc(100% - 38px);
}

.device-group-switcher-trigger {
  display: inline-flex;
  align-items: center;
  min-width: 0;
  max-width: 100%;
  height: 32px;
  gap: 7px;
  padding: 0 7px 0 0;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: var(--text);
  font: inherit;
  text-align: left;
  cursor: pointer;
  transition: background 0.16s ease;
}

.device-group-switcher-trigger:hover,
.device-group-switcher-trigger:focus-visible {
  background: rgba(148, 163, 184, 0.08);
  outline: none;
}

.device-group-switcher-name {
  min-width: 0;
  overflow: hidden;
  color: var(--text);
  font-size: 15px;
  font-weight: 700;
  letter-spacing: 0.005em;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.device-group-switcher-count {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  border-radius: 999px;
  background: rgba(148, 163, 184, 0.12);
  color: var(--muted);
  font-size: 10px;
  font-weight: 700;
  line-height: 18px;
  font-variant-numeric: tabular-nums;
}

.device-group-switcher-chevron {
  width: 6px;
  height: 6px;
  margin: -3px 1px 0 0;
  border-right: 1.5px solid var(--muted-2);
  border-bottom: 1.5px solid var(--muted-2);
  transform: rotate(45deg);
  flex-shrink: 0;
}

.device-group-dropdown-item {
  display: grid;
  grid-template-columns: 16px minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px;
  min-width: 190px;
}

.device-group-dropdown-check {
  color: var(--el-color-primary);
  font-size: 12px;
  font-weight: 700;
  visibility: hidden;
}

.device-group-dropdown-check.visible {
  visibility: visible;
}

.device-group-dropdown-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.device-group-dropdown-count {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}

.device-toolbar-more-btn {
  min-width: 28px;
  width: 28px;
  height: 28px;
  padding: 0;
  color: var(--muted);
}

.device-toolbar-more-btn:hover,
.device-toolbar-more-btn:focus {
  color: var(--text);
}

.device-toolbar-more-icon {
  font-size: 17px;
  line-height: 1;
}

.sidebar-body {
  padding: 12px;
  overflow-y: auto;
  min-height: 0;
}

/* ========== 设备列表 ========== */
.device-item {
  -webkit-touch-callout: none;
  user-select: none;
  padding: 14px;
  margin-bottom: 10px;
  border-radius: var(--radius-md);
  background: rgba(255, 255, 255, 0.96);
  border: 1px solid rgba(15, 23, 42, 0.06);
  cursor: pointer;
  transition: border-color 0.18s ease, background 0.18s ease, opacity 0.18s ease;
}

.device-item:hover {
  border-color: rgba(37, 99, 235, 0.14);
  background: #fff;
}

.device-item.active {
  border-color: rgba(37, 99, 235, 0.22);
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(239, 246, 255, 0.96));
}

.device-item.context-active {
  border-color: rgba(37, 99, 235, 0.34);
}

.device-item-hidden:not(.active) {
  opacity: 0.64;
  border-style: dashed;
}

.device-item-hidden.active {
  border-style: dashed;
}

.device-item-hidden .device-name,
.device-item-hidden .device-os,
.device-item-hidden .device-ip,
.device-item-hidden .device-status-row {
  color: #64748b;
}

.device-item-top {
  display: flex;
  align-items: center;
  gap: 12px;
}

.device-text {
  min-width: 0;
  flex: 1;
}

.device-name-row {
  display: flex;
  align-items: center;
  gap: 5px;
  min-width: 0;
}

.device-name {
  min-width: 0;
  font-size: 14px;
  font-weight: 700;
  color: var(--text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.device-update-indicator {
  flex: 0 0 auto;
  font-size: 12px;
  color: var(--muted-2);
  opacity: 0.58;
}

.device-os {
  margin-top: 4px;
  font-size: 12px;
  color: var(--muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.device-ip {
  margin-top: 9px;
  font-size: 12px;
  color: var(--muted-2);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.device-status-row {
  margin-top: 7px;
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  font-size: 12px;
  color: var(--muted);
}

.device-status-text {
  line-height: 1.4;
}

.device-status-sep {
  color: var(--muted-2);
}

.device-dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  flex-shrink: 0;
}

.device-dot-online {
  background: #22c55e;
}

.device-dot-stale {
  background: #f59e0b;
}

.device-dot-offline {
  background: #94a3b8;
}
</style>

<style>
body.device-touch-callout-guard,
body.device-touch-callout-guard * {
  -webkit-touch-callout: none !important;
  -webkit-user-select: none !important;
  user-select: none !important;
}

.device-context-menu {
  position: fixed;
  z-index: 5000;
  min-width: 176px;
  padding: 5px 0;
  margin: 0;
  border: 1px solid var(--el-border-color-light);
  border-radius: var(--el-border-radius-base);
  background-color: var(--el-bg-color-overlay);
  box-shadow: var(--el-box-shadow-light);
  box-sizing: border-box;
  user-select: none;
  -webkit-user-select: none;
  -webkit-touch-callout: none;
}

.device-context-menu-item {
  display: flex;
  align-items: center;
  width: 100%;
  min-height: 34px;
  padding: 5px 16px;
  margin: 0;
  border: 0;
  background: transparent;
  color: var(--el-text-color-regular);
  font-size: var(--el-font-size-base);
  font-size: 14px;
  line-height: 22px;
  text-align: left;
  white-space: nowrap;
  cursor: pointer;
  outline: none;
  box-sizing: border-box;
  -webkit-touch-callout: none;
}

.device-context-menu-item:hover,
.device-context-menu-item:focus {
  background-color: var(--el-fill-color-light);
  color: var(--el-text-color-regular);
}

.device-context-menu-item:disabled {
  background-color: transparent;
  color: var(--el-text-color-disabled);
  cursor: not-allowed;
}

.device-context-menu-item:disabled:hover,
.device-context-menu-item:disabled:focus {
  background-color: transparent;
  color: var(--el-text-color-disabled);
}

.device-context-menu-separator {
  height: 1px;
  margin: 6px 0;
  background-color: var(--el-border-color-light);
}


.device-context-menu-group-toggle {
  justify-content: space-between;
  gap: 18px;
}

.device-context-menu-arrow {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.device-context-group-list {
  max-height: 210px;
  padding: 2px 0 4px 10px;
  overflow-y: auto;
}

.device-context-group-item {
  min-height: 31px;
  padding-left: 20px;
  padding-right: 16px;
  font-size: 13px;
}

.device-context-group-name {
  min-width: 0;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.device-context-group-check {
  margin-left: auto;
  color: var(--el-color-primary);
  font-weight: 700;
}

.device-context-menu-item.is-danger {
  color: #be123c;
}

.device-context-menu-item.is-danger:hover,
.device-context-menu-item.is-danger:focus {
  background-color: #fff1f2;
  color: #be123c;
}
</style>