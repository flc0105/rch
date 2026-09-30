<template>
  <el-dialog
    v-model="visible"
    title="Settings"
    width="920px"
    class="settings-dialog"
    :close-on-click-modal="true"
    append-to-body
  >
    <el-tabs v-model="activeTab" class="settings-tabs">
      <el-tab-pane label="Toolbar" name="toolbar">
        <div v-loading="toolbarLoading" class="settings-tab-scroll">
          <div class="settings-note">
            Order items inside each section. Move less-used actions to More.
          </div>

          <div class="toolbar-manager-grid">
            <section class="settings-section">
              <div class="settings-section-title">Toolbar</div>
              <div class="toolbar-manager-list">
                <div
                  v-for="(actionId, index) in toolbarDraft.toolbar"
                  :key="`toolbar-${actionId}`"
                  class="toolbar-manager-row"
                >
                  <span class="toolbar-manager-label">{{ actionLabel(actionId) }}</span>
                  <div class="toolbar-manager-actions">
                    <el-button size="small" text :disabled="index === 0" @click="moveToolbarItem('toolbar', index, -1)">↑</el-button>
                    <el-button size="small" text :disabled="index === toolbarDraft.toolbar.length - 1" @click="moveToolbarItem('toolbar', index, 1)">↓</el-button>
                    <el-button size="small" @click="moveToolbarItemAcross('toolbar', index)">To More</el-button>
                  </div>
                </div>
              </div>
            </section>

            <section class="settings-section">
              <div class="settings-section-title">More</div>
              <div class="toolbar-manager-list">
                <div
                  v-for="(actionId, index) in toolbarDraft.more"
                  :key="`more-${actionId}`"
                  class="toolbar-manager-row"
                >
                  <span class="toolbar-manager-label">{{ actionLabel(actionId) }}</span>
                  <div class="toolbar-manager-actions">
                    <el-button size="small" text :disabled="index === 0" @click="moveToolbarItem('more', index, -1)">↑</el-button>
                    <el-button size="small" text :disabled="index === toolbarDraft.more.length - 1" @click="moveToolbarItem('more', index, 1)">↓</el-button>
                    <el-button size="small" @click="moveToolbarItemAcross('more', index)">To Toolbar</el-button>
                  </div>
                </div>
              </div>
            </section>
          </div>
        </div>
      </el-tab-pane>

      <el-tab-pane label="Notifications" name="notifications">
        <div v-loading="notificationLoading" class="settings-tab-scroll">
          <div class="notification-master-row">
            <div>
              <div class="settings-section-heading">SSE Notifications</div>
              <div class="settings-note settings-note-inline">
                Events still update application state when notifications are disabled.
              </div>
            </div>
            <el-switch v-model="notificationDraft.enabled" />
          </div>

          <div class="notification-groups">
            <section
              v-for="group in notificationGroups"
              :key="group.title"
              class="settings-section"
            >
              <div class="settings-section-title">{{ group.title }}</div>
              <div class="notification-group-list">
                <div
                  v-for="item in group.items"
                  :key="item.key"
                  class="notification-option-row"
                >
                  <span>{{ item.label }}</span>
                  <el-switch
                    v-model="notificationDraft.events[item.key]"
                    :disabled="!notificationDraft.enabled"
                  />
                </div>
              </div>
            </section>
          </div>
        </div>
      </el-tab-pane>
    </el-tabs>

    <template #footer>
      <div class="settings-footer">
        <el-button :disabled="activeLoading || activeSaving" @click="resetActiveDefaults">
          Reset Default
        </el-button>
        <span class="settings-footer-spacer"></span>
        <el-button :disabled="activeSaving" @click="visible = false">Cancel</el-button>
        <el-button
          type="primary"
          :loading="activeSaving"
          :disabled="activeLoading"
          @click="saveActiveSettings"
        >
          Save
        </el-button>
      </div>
    </template>
  </el-dialog>
</template>

<script>
import { ElMessage } from 'element-plus'
import {
  loadToolbarPreferences,
  saveToolbarPreferences,
} from '../api/toolbarPreferencesApi.js'
import {
  loadNotificationPreferences,
  saveNotificationPreferences,
} from '../api/notificationPreferencesApi.js'
import {
  DEFAULT_TOOLBAR_PREFERENCES,
  TOOLBAR_ACTION_CATALOG,
  cloneToolbarPreferences,
  normalizeToolbarPreferences,
} from '../data/toolbarPreferences.js'
import {
  DEFAULT_SSE_NOTIFICATION_PREFERENCES,
  SSE_NOTIFICATION_GROUPS,
  cloneSseNotificationPreferences,
  normalizeSseNotificationPreferences,
} from '../data/sseNotificationPreferences.js'

export default {
  name: 'SettingsDialog',

  emits: ['toolbar-saved', 'notification-saved'],

  data() {
    return {
      visible: false,
      activeTab: 'toolbar',

      toolbarLoading: false,
      toolbarSaving: false,
      toolbarDraft: cloneToolbarPreferences(DEFAULT_TOOLBAR_PREFERENCES),

      notificationLoading: false,
      notificationSaving: false,
      notificationGroups: SSE_NOTIFICATION_GROUPS,
      notificationDraft: cloneSseNotificationPreferences(DEFAULT_SSE_NOTIFICATION_PREFERENCES),
    }
  },

  computed: {
    activeLoading() {
      return this.activeTab === 'notifications' ? this.notificationLoading : this.toolbarLoading
    },
    activeSaving() {
      return this.activeTab === 'notifications' ? this.notificationSaving : this.toolbarSaving
    },
  },

  methods: {
    async open(tab = 'toolbar') {
      this.visible = true
      this.activeTab = tab === 'notifications' ? 'notifications' : 'toolbar'

      await Promise.all([
        this.loadToolbarSettings(),
        this.loadNotificationSettings(),
      ])
    },

    actionLabel(actionId) {
      return TOOLBAR_ACTION_CATALOG.find((item) => item.id === actionId)?.label || actionId
    },
    moveToolbarItem(section, index, direction) {
      const items = this.toolbarDraft[section]
      const targetIndex = index + direction
      if (!Array.isArray(items) || targetIndex < 0 || targetIndex >= items.length) return
      const next = [...items]
      const [item] = next.splice(index, 1)
      next.splice(targetIndex, 0, item)
      this.toolbarDraft = {
        ...this.toolbarDraft,
        [section]: next,
      }
    },
    moveToolbarItemAcross(section, index) {
      const targetSection = section === 'toolbar' ? 'more' : 'toolbar'
      const sourceItems = [...(this.toolbarDraft[section] || [])]
      const targetItems = [...(this.toolbarDraft[targetSection] || [])]
      const [item] = sourceItems.splice(index, 1)
      if (!item) return
      targetItems.push(item)
      this.toolbarDraft = {
        ...this.toolbarDraft,
        [section]: sourceItems,
        [targetSection]: targetItems,
      }
    },
    async loadToolbarSettings() {
      this.toolbarLoading = true
      try {
        this.toolbarDraft = cloneToolbarPreferences(
          normalizeToolbarPreferences(await loadToolbarPreferences()),
        )
      } catch (e) {
        ElMessage.error(e.message || 'Failed to load toolbar settings')
      } finally {
        this.toolbarLoading = false
      }
    },
    resetToolbarDefaults() {
      this.toolbarDraft = cloneToolbarPreferences(DEFAULT_TOOLBAR_PREFERENCES)
    },
    async saveToolbarSettings() {
      if (this.toolbarSaving) return
      this.toolbarSaving = true
      try {
        // Toolbar Settings only owns placement/order. Preserve Quick Actions pins,
        // which are managed from the Quick Action editor.
        const latest = normalizeToolbarPreferences(await loadToolbarPreferences())
        const payload = {
          ...this.toolbarDraft,
          quick_actions_pinned: latest.quick_actions_pinned,
        }
        const saved = normalizeToolbarPreferences(
          await saveToolbarPreferences(payload),
        )
        this.toolbarDraft = cloneToolbarPreferences(saved)
        this.$emit('toolbar-saved', saved)
        ElMessage.success('Toolbar settings updated')
      } catch (e) {
        ElMessage.error(e.message || 'Failed to save toolbar settings')
      } finally {
        this.toolbarSaving = false
      }
    },

    async loadNotificationSettings() {
      this.notificationLoading = true
      try {
        this.notificationDraft = cloneSseNotificationPreferences(
          normalizeSseNotificationPreferences(await loadNotificationPreferences()),
        )
      } catch (e) {
        ElMessage.error(e.message || 'Failed to load notification settings')
      } finally {
        this.notificationLoading = false
      }
    },
    resetNotificationDefaults() {
      this.notificationDraft = cloneSseNotificationPreferences(DEFAULT_SSE_NOTIFICATION_PREFERENCES)
    },
    async saveNotificationSettings() {
      if (this.notificationSaving) return
      this.notificationSaving = true
      try {
        const saved = normalizeSseNotificationPreferences(
          await saveNotificationPreferences(this.notificationDraft),
        )
        this.notificationDraft = cloneSseNotificationPreferences(saved)
        this.$emit('notification-saved', saved)
        ElMessage.success('Notification settings updated')
      } catch (e) {
        ElMessage.error(e.message || 'Failed to save notification settings')
      } finally {
        this.notificationSaving = false
      }
    },

    resetActiveDefaults() {
      if (this.activeTab === 'notifications') {
        this.resetNotificationDefaults()
        return
      }
      this.resetToolbarDefaults()
    },
    saveActiveSettings() {
      if (this.activeTab === 'notifications') {
        return this.saveNotificationSettings()
      }
      return this.saveToolbarSettings()
    },
  },
}
</script>

<style scoped>
.settings-note {
  margin-bottom: 14px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.5;
}

.settings-note-inline {
  margin: 4px 0 0;
}

.settings-section-heading,
.settings-section-title {
  font-weight: 650;
}

.settings-section {
  min-width: 0;
  border: 1px solid var(--el-border-color-light);
  border-radius: 9px;
  overflow: hidden;
}

.settings-section-title {
  padding: 10px 12px;
  border-bottom: 1px solid var(--el-border-color-lighter);
  background: var(--el-fill-color-light);
  font-size: 12px;
}

.toolbar-manager-grid,
.notification-groups {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}

.toolbar-manager-row,
.toolbar-manager-actions,
.notification-master-row,
.notification-option-row,
.settings-footer {
  display: flex;
  align-items: center;
}

.toolbar-manager-row {
  justify-content: space-between;
  gap: 12px;
  min-height: 46px;
  padding: 7px 10px 7px 12px;
  border-bottom: 1px solid var(--el-border-color-extra-light);
}

.toolbar-manager-row:last-child,
.notification-option-row:last-child {
  border-bottom: none;
}

.toolbar-manager-label {
  min-width: 0;
  font-size: 13px;
}

.toolbar-manager-actions {
  flex: 0 0 auto;
  gap: 4px;
}

.notification-master-row {
  justify-content: space-between;
  gap: 20px;
  padding: 14px 16px;
  margin-bottom: 14px;
  border: 1px solid var(--el-border-color-light);
  border-radius: 10px;
  background: var(--el-fill-color-light);
}

.notification-group-list {
  padding: 2px 12px;
}

.notification-option-row {
  justify-content: space-between;
  gap: 16px;
  min-height: 42px;
  border-bottom: 1px solid var(--el-border-color-extra-light);
  font-size: 13px;
}

.settings-footer {
  width: 100%;
}

.settings-footer-spacer {
  flex: 1;
}

@media (max-width: 760px) {
  .toolbar-manager-grid,
  .notification-groups {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>

<style>
.settings-dialog.el-dialog {
  height: 680px;
  max-height: calc(100vh - 32px);
  display: flex;
  flex-direction: column;
}

.settings-dialog .el-dialog__header,
.settings-dialog .el-dialog__footer {
  flex: 0 0 auto;
}

.settings-dialog .el-dialog__body {
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
  padding-top: 0;
  padding-bottom: 0;
}

.settings-dialog .settings-tabs {
  height: 100%;
  display: flex;
  flex-direction: column;
}

.settings-dialog .el-tabs__header {
  flex: 0 0 auto;
  margin-bottom: 12px;
}

.settings-dialog .el-tabs__content {
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
}

.settings-dialog .el-tab-pane {
  height: 100%;
}

.settings-dialog .settings-tab-scroll {
  box-sizing: border-box;
  height: 100%;
  overflow-y: auto;
  padding: 4px 6px 4px 0;
}
</style>
