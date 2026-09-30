<template>
  <div class="terminal-topbar">
    <div class="terminal-topbar-left">
<!--      <span class="dot dot-red"></span>-->
<!--      <span class="dot dot-yellow"></span>-->
<!--      <span class="dot dot-green"></span>-->

<!--      <span class="dot dot-red"></span>-->
<!--<span class="dot dot-yellow"></span>-->
<!--<button-->
<!--  class="dot dot-green dot-action"-->
<!--  type="button"-->
<!--  title="Toggle connection info"-->
<!--  aria-label="Toggle connection info"-->
<!--  @click="$emit('toggle-connection-info')"-->
<!--/>-->


      <span class="dot dot-red"></span>
<span class="dot dot-yellow"></span>

<el-dropdown
  trigger="click"
  placement="bottom-start"
  popper-class="terminal-layout-dropdown"
  @command="handleLayoutCommand"
>
  <button
    class="dot dot-green dot-action"
    type="button"
    title="Layout quick actions"
    aria-label="Layout quick actions"
  />

  <template #dropdown>
    <el-dropdown-menu>
      <el-dropdown-item command="toggle-device-sidebar">
        {{ deviceSidebarCollapsed ? 'Show device sidebar' : 'Hide device sidebar' }}
      </el-dropdown-item>

      <el-dropdown-item command="toggle-connection-info">
        {{ connectionInfoCollapsed ? 'Show connection info card' : 'Hide connection info card' }}
      </el-dropdown-item>

      <el-dropdown-item
        command="hide-both"
        divided
        :disabled="deviceSidebarCollapsed && connectionInfoCollapsed"
      >
        Hide both
      </el-dropdown-item>
    </el-dropdown-menu>
  </template>
</el-dropdown>






      <span class="terminal-title">{{ terminalIdentity }}</span>
    </div>

    <div class="terminal-tools">
      <template v-for="action in toolbarActions" :key="action.id">
        <el-dropdown
          v-if="action.id === 'quick-actions' && (toolbarPreferences.quick_actions_pinned || []).length > 0"
          trigger="hover"
          placement="bottom-start"
          @visible-change="handleQuickActionsDropdownVisible"
          @command="handleQuickActionsDropdownCommand"
        >
          <el-button
            size="small"
            :class="['tool-btn', 'ml-0', { 'tool-btn-accent': action.accent }]"
            :disabled="isActionDisabled(action.id)"
            @click="runAction(action.id)"
          >
            {{ action.label }}
          </el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item v-if="quickActionsLoading" disabled>
                Loading…
              </el-dropdown-item>
              <el-dropdown-item v-else-if="pinnedQuickActions.length === 0" disabled>
                No pinned actions
              </el-dropdown-item>
              <template v-else>
                <el-dropdown-item
                  v-for="(item, index) in pinnedQuickActions"
                  :key="`${item.platform}:${item.alias}`"
                  :command="String(index)"
                >
                  {{ pinnedQuickActionLabel(item) }}
                </el-dropdown-item>
              </template>
            </el-dropdown-menu>
          </template>
        </el-dropdown>

        <el-button
          v-else
          size="small"
          :class="['tool-btn', 'ml-0', { 'tool-btn-accent': action.accent }]"
          :disabled="isActionDisabled(action.id)"
          @click="runAction(action.id)"
        >
          {{ action.label }}
        </el-button>
      </template>

      <el-dropdown
        trigger="click"
        @command="handleMoreCommand"
      >
        <el-button
          size="small"
          class="tool-btn tool-btn-accent"
        >
          More
        </el-button>

        <template #dropdown>
          <el-dropdown-menu>
            <template v-for="action in moreActions" :key="action.id">
              <el-dropdown-item
                :command="`action:${action.id}`"
                :disabled="isActionDisabled(action.id)"
              >
                {{ action.label }}
              </el-dropdown-item>
            </template>

            <el-dropdown-item command="settings" :divided="moreActions.length > 0">
              Settings
            </el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>

      <el-button
        size="small"
        class="tool-btn tool-btn-danger"
        @click="killConnection"
        :disabled="deviceActionDisabled"
      >
        Disconnect
      </el-button>

      <span class="terminal-tool-separator"></span>

      <el-button
        size="small"
        class="tool-btn"
        @click="$emit('clear')"
      >
        Clear
      </el-button>

      <el-button
        size="small"
        class="tool-btn ml-0"
        @click="$emit('bottom')"
      >
        Bottom
      </el-button>
    </div>
  </div>

</template>

<script>
import { ElMessage, ElMessageBox } from 'element-plus'
import { killConnection as killConnectionApi } from '../api/connectionsApi.js'
import { loadToolbarPreferences } from '../api/toolbarPreferencesApi.js'
import { listQuickActions } from '../api/quickActionsApi.js'
import {
  DEFAULT_TOOLBAR_PREFERENCES,
  TOOLBAR_ACTION_CATALOG,
  cloneToolbarPreferences,
  normalizeToolbarPreferences,
} from '../data/toolbarPreferences.js'

export default {
  name: 'TerminalToolbar',

  props: {
    selectedId: {
      type: [String, Number],
      default: '',
    },
    currentConnection: {
      type: Object,
      default: null,
    },

    currentConnectionOffline: {
      type: Boolean,
      default: false,
    },

    deviceSidebarCollapsed: {
      type: Boolean,
      default: false,
    },

    connectionInfoCollapsed: {
      type: Boolean,
      default: false,
    },
  },

  emits: [
    'layout-command',
    'open-remote-files',
    'open-artifacts',
    'open-external-tools',
    'open-keychains',
    'open-info',
    'open-jobs',
    'open-scripts',
    'open-agents',
    'open-history',
    'open-pty',
    'open-screen-view',
    'open-clipboard',
    'open-processes',
    'open-one-liners',
    'open-quick-actions',
    'run-quick-action',
    'open-settings',
    'clear',
    'bottom',
  ],

  data() {
    return {
      toolbarPreferences: cloneToolbarPreferences(DEFAULT_TOOLBAR_PREFERENCES),
      quickActionsLoading: false,
      pinnedQuickActions: [],
    }
  },

  computed: {
    terminalIdentity() {
      const connection = this.currentConnection || {}
      const rawUsername = String(connection.username || '').trim()
      const username = rawUsername.includes('\\')
        ? rawUsername.split('\\').filter(Boolean).pop()
        : rawUsername
      const hostname = String(connection.hostname || '').trim()

      if (username && hostname) return `${username}@${hostname}`
      return username || hostname || 'Interactive Shell'
    },
    deviceActionDisabled() {
      return !this.selectedId || this.currentConnectionOffline
    },
    toolbarActions() {
      return this.actionsForIds(this.toolbarPreferences.toolbar)
    },
    moreActions() {
      return this.actionsForIds(this.toolbarPreferences.more)
    },
  },

  watch: {
    selectedId() {
      this.pinnedQuickActions = []
    },
  },

  mounted() {
    this.loadManagedToolbar()
  },

  methods: {
    clonePreferences(preferences) {
      return cloneToolbarPreferences(preferences)
    },
    normalizePreferences(preferences) {
      return normalizeToolbarPreferences(preferences)
    },
    actionsForIds(ids) {
      const byId = new Map(TOOLBAR_ACTION_CATALOG.map((item) => [item.id, item]))
      return (ids || []).map((id) => byId.get(id)).filter(Boolean)
    },
    isActionDisabled(actionId) {
      return [
        'remote-files',
        'pty',
        'screen-view',
        'clipboard',
        'processes',
        'quick-actions',
      ].includes(actionId) && this.deviceActionDisabled
    },
    async loadManagedToolbar() {
      try {
        this.toolbarPreferences = this.normalizePreferences(await loadToolbarPreferences())
      } catch (e) {
        this.toolbarPreferences = this.clonePreferences(DEFAULT_TOOLBAR_PREFERENCES)
        ElMessage.warning(e.message || 'Failed to load toolbar preferences; using defaults')
      }
    },


    async loadPinnedQuickActions() {
      const pins = this.toolbarPreferences?.quick_actions_pinned || []
      if (!this.selectedId || this.currentConnectionOffline || pins.length === 0) {
        this.pinnedQuickActions = []
        return
      }
      this.quickActionsLoading = true
      try {
        const data = await listQuickActions(this.selectedId)
        const byKey = new Map(
          (Array.isArray(data.items) ? data.items : []).map((item) => [
            `${String(item?.platform || '').trim()}\u0000${String(item?.alias || '').trim()}`,
            item,
          ]),
        )
        this.pinnedQuickActions = pins
          .map((pin) => byKey.get(`${pin.platform}\u0000${pin.alias}`))
          .filter((item) => item && item.in_current_scope === true)
      } catch (e) {
        this.pinnedQuickActions = []
        ElMessage.warning(e.message || 'Failed to load pinned Quick Actions')
      } finally {
        this.quickActionsLoading = false
      }
    },
    handleQuickActionsDropdownVisible(visible) {
      if (visible) void this.loadPinnedQuickActions()
    },
    handleQuickActionsDropdownCommand(command) {
      const index = Number.parseInt(String(command ?? ''), 10)
      const item = Number.isInteger(index) ? this.pinnedQuickActions[index] : null
      if (!item) {
        ElMessage.warning('Quick Action is unavailable')
        return
      }
      this.$emit('run-quick-action', item)
    },
    pinnedQuickActionLabel(item) {
      const duplicates = this.pinnedQuickActions.filter((candidate) => candidate.alias === item.alias).length
      if (duplicates <= 1) return item.alias
      const platformLabels = { common: 'Common', win: 'Windows', mac: 'macOS', linux: 'Linux', ios: 'iOS' }
      return `${item.alias} · ${platformLabels[item.platform] || item.platform}`
    },
    async killConnection() {
      if (!this.selectedId) {
        ElMessage.warning('Please select a device')
        return
      }

      try {
        await ElMessageBox.confirm(
            'Disconnect current device?',
            'Confirm Disconnect',
            {
              type: 'warning',
              confirmButtonText: 'Disconnect',
              cancelButtonText: 'Cancel',
              confirmButtonClass: 'el-button--danger',
            },
        )

        await killConnectionApi(this.selectedId)

        ElMessage.success('Disconnect command sent')
      } catch (e) {
        if (e === 'cancel' || e === 'close' || e?.message === 'cancel') {
          return
        }

        ElMessage.error(e.message || 'Disconnect failed')
      }
    },

    handleLayoutCommand(command) {
      this.$emit('layout-command', command)
    },

    runAction(actionId) {
      const normalizedAction = String(actionId || '').trim().toLowerCase()
      const resourceActions = [
        'external-tools',
        'keychains',
        'jobs',
        'agents',
        'processes',
        'quick-actions',
        'one-liners',
      ]
      if (resourceActions.includes(normalizedAction)) {
        this.handleResourceCommand(normalizedAction)
        return
      }

      const eventMap = {
        'remote-files': 'open-remote-files',
        artifacts: 'open-artifacts',
        info: 'open-info',
        scripts: 'open-scripts',
        history: 'open-history',
        pty: 'open-pty',
        'screen-view': 'open-screen-view',
        clipboard: 'open-clipboard',
      }
      const eventName = eventMap[normalizedAction]
      if (!eventName) {
        ElMessage.warning('Unknown toolbar action')
        return
      }
      this.$emit(eventName)
    },
    handleMoreCommand(command) {
      const normalizedCommand = String(command || '').trim().toLowerCase()
      if (normalizedCommand === 'settings') {
        this.$emit('open-settings')
        return
      }
      if (normalizedCommand.startsWith('action:')) {
        this.runAction(normalizedCommand.slice('action:'.length))
        return
      }
      ElMessage.warning('Unknown toolbar action')
    },

    // Resources 下拉只负责打开资源类弹窗，不承载执行控制逻辑。
    handleResourceCommand(command) {
      const normalizedCommand = String(command || '').trim().toLowerCase()
      const eventMap = {
        'external-tools': 'open-external-tools',
        keychains: 'open-keychains',
        jobs: 'open-jobs',
        agents: 'open-agents',
        processes: 'open-processes',
        'one-liners': 'open-one-liners',
        'quick-actions': 'open-quick-actions',
      }
      const eventName = eventMap[normalizedCommand]

      if (!eventName) {
        ElMessage.warning('Unknown resource action')
        return
      }

      this.$emit(eventName)
    },

    // Ops 下拉包含本地管理入口和通过 HTTP 独立通道下发的控制命令。
    async handleOpsCommand(command) {
      const normalizedCommand = String(command || '').trim().toLowerCase()

      const httpCommandMap = {
        'http-stop': 'stop',
        'http-restart': 'restart',
        'http-start': 'start',
      }
      const httpCommand = httpCommandMap[normalizedCommand]
      if (httpCommand) {
        await this.sendHttpControlCommand(httpCommand)
        return
      }

      ElMessage.warning('Unknown ops action')
    },
  }
}
</script>

<style scoped>
/* ========== 终端工具栏 ========== */
.terminal-topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 15px;
  border-bottom: 1px solid var(--terminal-line);
  background: rgba(255, 255, 255, 0.03);
  flex-shrink: 0;
}

.terminal-topbar-left {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
  flex-shrink: 0;
}

.dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
}

.dot-red {
  background: #fb7185;
}

.dot-yellow {
  background: #fbbf24;
}

.dot-green {
  background: #34d399;
}

.terminal-title {
  margin-left: 4px;
  color: #e2e8f0;
  font-size: 13px;
  font-weight: 650;
  white-space: nowrap;
}

.terminal-tools {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  flex-wrap: wrap;
  min-width: 0;
}

.terminal-tool-separator {
  width: 1px;
  height: 18px;
  background: rgba(255, 255, 255, 0.12);
  flex: 0 0 auto;
}

.tool-btn.el-button {
  flex: 0 0 auto;
  min-height: 30px;
  height: 30px;
  padding-inline: 10px;
  font-size: 12px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.04);
  border-color: rgba(255, 255, 255, 0.08);
  color: #dbe4f3;
  margin: 0;
}

.tool-btn.tool-btn-accent.el-button {
  background: rgba(59, 130, 246, 0.16);
  border-color: rgba(96, 165, 250, 0.22);
  color: #dbeafe;
}

.tool-btn.tool-btn-danger.el-button {
  background: rgba(220, 38, 38, 0.12);
  border-color: rgba(248, 113, 113, 0.18);
  color: #fecaca;
}

@media (max-width: 1200px) {
  .terminal-topbar {
    align-items: flex-start;
    flex-direction: column;
  }

  .terminal-topbar-left,
  .terminal-tools {
    width: 100%;
  }

  .terminal-tools {
    justify-content: flex-start;
  }
}

@media (max-width: 640px) {
  .terminal-tools {
    gap: 6px;
  }

  .terminal-tool-separator {
    display: none;
  }

  .tool-btn.el-button {
    height: 30px;
    min-height: 30px;
    padding-inline: 10px;
    font-size: 12px;
  }
}

/*dot actions*/
.dot-action {
  padding: 0;
  border: none;
  appearance: none;
  cursor: pointer;
  flex: 0 0 auto;
  transition:
      transform 0.14s ease,
      filter 0.14s ease,
      box-shadow 0.14s ease;
}

.dot-action:hover {
  transform: scale(1.14);
  filter: brightness(1.08);
  box-shadow: 0 0 0 3px rgba(52, 211, 153, 0.14);
}

.dot-action:active {
  transform: scale(0.96);
}



/*disabled toolbar button*/
.tool-btn.el-button.is-disabled,
.tool-btn.el-button.is-disabled:hover,
.tool-btn.el-button.is-disabled:focus {
  background: rgba(148, 163, 184, 0.055) !important;
  border-color: rgba(148, 163, 184, 0.09) !important;
  color: rgba(203, 213, 225, 0.34) !important;
  opacity: 0.58;
  cursor: not-allowed;
  filter: grayscale(0.45);
  box-shadow: none;
}

.tool-btn.tool-btn-accent.el-button.is-disabled,
.tool-btn.tool-btn-accent.el-button.is-disabled:hover,
.tool-btn.tool-btn-accent.el-button.is-disabled:focus {
  background: rgba(59, 130, 246, 0.045) !important;
  border-color: rgba(96, 165, 250, 0.08) !important;
  color: rgba(191, 219, 254, 0.32) !important;
}

.tool-btn.tool-btn-danger.el-button.is-disabled,
.tool-btn.tool-btn-danger.el-button.is-disabled:hover,
.tool-btn.tool-btn-danger.el-button.is-disabled:focus {
  background: rgba(220, 38, 38, 0.045) !important;
  border-color: rgba(248, 113, 113, 0.08) !important;
  color: rgba(254, 202, 202, 0.32) !important;
}


</style>