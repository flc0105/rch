<template>
  <el-drawer
    v-model="visible"
    direction="rtl"
    size="420px"
    :with-header="false"
    class="notification-center-drawer"
  >
    <div class="notification-center-shell">
      <div class="notification-center-header">
        <div>
          <div class="notification-center-title">Notifications</div>
          <div class="notification-center-clock">{{ formattedCurrentTime }}</div>
        </div>

        <button
          class="notification-center-close"
          type="button"
          title="Close"
          @click="visible = false"
        >
          <el-icon><Close /></el-icon>
        </button>
      </div>

      <div class="notification-center-toolbar">
        <span class="notification-center-count">
          {{ notifications.length }} {{ notifications.length === 1 ? 'notification' : 'notifications' }}
        </span>

        <div class="notification-center-toolbar-actions">
          <select
            v-model="typeFilter"
            class="notification-center-filter"
            aria-label="Filter notifications by type"
          >
            <option value="all">All</option>
            <option value="success">Success</option>
            <option value="info">Info</option>
            <option value="warning">Warning</option>
            <option value="error">Error</option>
          </select>

          <button
            class="notification-center-clear"
            type="button"
            :disabled="notifications.length === 0 || clearing"
            @click="clearAll"
          >
            Clear All
          </button>
        </div>
      </div>

      <div v-if="filteredNotifications.length" class="notification-center-list">
        <article
          v-for="notification in filteredNotifications"
          :key="notification.id"
          class="notification-center-card"
        >
          <div
            class="notification-center-type"
            :class="`notification-center-type-${normalizeType(notification.type)}`"
          >
            <el-icon>
              <CircleCheckFilled v-if="normalizeType(notification.type) === 'success'" />
              <WarningFilled v-else-if="normalizeType(notification.type) === 'warning'" />
              <CircleCloseFilled v-else-if="normalizeType(notification.type) === 'error'" />
              <InfoFilled v-else />
            </el-icon>
          </div>

          <div class="notification-center-card-body">
            <div class="notification-center-card-head">
              <div class="notification-center-card-title">{{ notification.title }}</div>
              <div class="notification-center-card-time">{{ formatDateTime(notification.shown_at) }}</div>
            </div>

            <div v-if="notification.message" class="notification-center-card-message">
              {{ notification.message }}
            </div>

            <div v-if="notification.actions?.length" class="notification-center-card-actions">
              <template
                v-for="action in notification.actions"
                :key="action.id || `${notification.id}-${action.type}-${action.label}`"
              >
                <a
                  v-if="action.url"
                  class="notification-center-card-action"
                  :href="action.url"
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  {{ action.label }}
                </a>
                <button
                  v-else
                  class="notification-center-card-action notification-center-card-action-button"
                  type="button"
                  @click="emitNotificationAction(notification, action)"
                >
                  {{ action.label }}
                </button>
              </template>
            </div>
          </div>

          <button
            class="notification-center-delete"
            type="button"
            title="Delete notification"
            :disabled="deletingId === notification.id"
            @click="deleteOne(notification.id)"
          >
            <el-icon><Delete /></el-icon>
          </button>
        </article>
      </div>

      <div v-else class="notification-center-empty">
        <el-icon class="notification-center-empty-icon"><Bell /></el-icon>
        <div class="notification-center-empty-title">
          {{ notifications.length ? 'No matching notifications' : 'No notifications' }}
        </div>
        <div class="notification-center-empty-text">
          {{ notifications.length
            ? 'Try another notification type.'
            : 'SSE notifications you receive will appear here.' }}
        </div>
      </div>
    </div>
  </el-drawer>
</template>

<script>
import { formatDateTimeLocal } from '../utils/formatters.js'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Bell,
  CircleCheckFilled,
  CircleCloseFilled,
  Close,
  Delete,
  InfoFilled,
  WarningFilled,
} from '@element-plus/icons-vue'
import {
  clearNotificationHistory,
  deleteNotificationHistory,
} from '../api/notificationHistoryApi.js'

export default {
  components: {
    Bell,
    CircleCheckFilled,
    CircleCloseFilled,
    Close,
    Delete,
    InfoFilled,
    WarningFilled,
  },

  props: {
    notifications: {
      type: Array,
      default: () => [],
    },
  },

  emits: [
    'notification-deleted',
    'notifications-cleared',
    'notification-action',
  ],

  data() {
    return {
      visible: false,
      currentTime: new Date(),
      clockTimer: null,
      deletingId: '',
      clearing: false,
      typeFilter: 'all',
    }
  },

  computed: {
    formattedCurrentTime() {
      return this.formatDateTime(this.currentTime)
    },

    filteredNotifications() {
      const notifications = Array.isArray(this.notifications) ? this.notifications : []
      if (this.typeFilter === 'all') return notifications
      return notifications.filter(notification => this.normalizeType(notification?.type) === this.typeFilter)
    },
  },

  watch: {
    visible(value) {
      if (value) {
        this.currentTime = new Date()
        this.startClock()
      } else {
        this.stopClock()
      }
    },
  },

  beforeUnmount() {
    this.stopClock()
  },

  methods: {
    open() {
      this.visible = true
      this.currentTime = new Date()
      this.startClock()
    },

    startClock() {
      if (this.clockTimer) return
      this.clockTimer = window.setInterval(() => {
        this.currentTime = new Date()
      }, 1000)
    },

    stopClock() {
      if (!this.clockTimer) return
      window.clearInterval(this.clockTimer)
      this.clockTimer = null
    },

    normalizeType(type) {
      const value = String(type || '').trim().toLowerCase()
      return ['success', 'warning', 'error', 'info'].includes(value) ? value : 'info'
    },

    formatDateTime(value) {
      return formatDateTimeLocal(value)
    },

    emitNotificationAction(notification, action) {
      if (!notification || !action) return
      this.$emit('notification-action', { notification, action })
    },

    async deleteOne(notificationId) {
      if (!notificationId || this.deletingId) return

      this.deletingId = notificationId
      try {
        await deleteNotificationHistory(notificationId)
        this.$emit('notification-deleted', notificationId)
      } catch (e) {
        ElMessage.error(e?.message || 'Failed to delete notification')
      } finally {
        this.deletingId = ''
      }
    },

    async clearAll() {
      if (!this.notifications.length || this.clearing) return

      try {
        await ElMessageBox.confirm(
          'Clear all notifications? This cannot be undone.',
          'Clear Notifications',
          {
            confirmButtonText: 'Clear All',
            cancelButtonText: 'Cancel',
            type: 'warning',
          },
        )
      } catch (e) {
        return
      }

      this.clearing = true
      try {
        await clearNotificationHistory()
        this.$emit('notifications-cleared')
      } catch (e) {
        ElMessage.error(e?.message || 'Failed to clear notifications')
      } finally {
        this.clearing = false
      }
    },
  },
}
</script>

<style scoped>
.notification-center-shell {
  min-height: 100%;
  display: flex;
  flex-direction: column;
  background: #f7f8fa;
}

.notification-center-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 22px 22px 16px;
  background: rgba(255, 255, 255, 0.92);
  border-bottom: 1px solid rgba(148, 163, 184, 0.18);
}

.notification-center-title {
  color: #111827;
  font-size: 22px;
  font-weight: 720;
  letter-spacing: -0.02em;
}

.notification-center-clock {
  margin-top: 5px;
  color: #64748b;
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}

.notification-center-close,
.notification-center-delete,
.notification-center-clear {
  border: none;
  background: transparent;
  cursor: pointer;
}

.notification-center-close {
  width: 30px;
  height: 30px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  color: #64748b;
  font-size: 18px;
}

.notification-center-close:hover {
  background: #eef2f7;
  color: #0f172a;
}

.notification-center-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 22px;
}

.notification-center-count {
  color: #64748b;
  font-size: 12px;
}

.notification-center-toolbar-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.notification-center-filter {
  width: 82px;
  height: 24px;
  padding: 0 6px;
  border: 1px solid rgba(148, 163, 184, 0.28);
  border-radius: 6px;
  outline: none;
  background: rgba(255, 255, 255, 0.7);
  color: #64748b;
  font: inherit;
  font-size: 11px;
  cursor: pointer;
}

.notification-center-filter:focus {
  border-color: rgba(100, 116, 139, 0.45);
}

.notification-center-clear {
  padding: 4px 0;
  color: #64748b;
  font-size: 12px;
}

.notification-center-clear:hover:not(:disabled) {
  color: #0f172a;
}

.notification-center-clear:disabled,
.notification-center-delete:disabled {
  cursor: default;
  opacity: 0.42;
}

.notification-center-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 0 14px 18px;
}

.notification-center-card {
  position: relative;
  display: grid;
  grid-template-columns: 30px minmax(0, 1fr) 26px;
  gap: 10px;
  padding: 14px 12px;
  border: 1px solid rgba(148, 163, 184, 0.2);
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.96);
  box-shadow: 0 5px 16px rgba(15, 23, 42, 0.055);
}

.notification-center-type {
  width: 30px;
  height: 30px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 9px;
  font-size: 18px;
}

.notification-center-type-success {
  color: #16a34a;
  background: rgba(34, 197, 94, 0.1);
}

.notification-center-type-warning {
  color: #d97706;
  background: rgba(245, 158, 11, 0.11);
}

.notification-center-type-error {
  color: #dc2626;
  background: rgba(239, 68, 68, 0.1);
}

.notification-center-type-info {
  color: #2563eb;
  background: rgba(59, 130, 246, 0.1);
}

.notification-center-card-body {
  min-width: 0;
}

.notification-center-card-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 10px;
}

.notification-center-card-title {
  min-width: 0;
  color: #111827;
  font-size: 13px;
  font-weight: 680;
  line-height: 1.4;
}

.notification-center-card-time {
  flex-shrink: 0;
  color: #94a3b8;
  font-size: 10px;
  line-height: 1.4;
  font-variant-numeric: tabular-nums;
}

.notification-center-card-message {
  margin-top: 5px;
  color: #475569;
  font-size: 12px;
  line-height: 1.55;
  overflow-wrap: anywhere;
}

.notification-center-card-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 8px;
}

.notification-center-card-action {
  color: #409eff;
  font-size: 12px;
  font-weight: 600;
  text-decoration: none;
}

.notification-center-card-action-button {
  padding: 0;
  border: none;
  background: transparent;
  font-family: inherit;
  cursor: pointer;
}

.notification-center-card-action:hover {
  text-decoration: underline;
}

.notification-center-delete {
  width: 26px;
  height: 26px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 7px;
  color: #94a3b8;
  font-size: 14px;
  opacity: 0.55;
}

.notification-center-card:hover .notification-center-delete {
  opacity: 1;
}

.notification-center-delete:hover:not(:disabled) {
  color: #dc2626;
  background: rgba(239, 68, 68, 0.08);
}

.notification-center-empty {
  flex: 1;
  min-height: 280px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 36px;
  text-align: center;
}

.notification-center-empty-icon {
  color: #cbd5e1;
  font-size: 32px;
}

.notification-center-empty-title {
  margin-top: 12px;
  color: #334155;
  font-size: 14px;
  font-weight: 650;
}

.notification-center-empty-text {
  max-width: 240px;
  margin-top: 6px;
  color: #94a3b8;
  font-size: 12px;
  line-height: 1.5;
}

@media (max-width: 640px) {
  .notification-center-header {
    padding-left: 16px;
    padding-right: 16px;
  }

  .notification-center-toolbar {
    padding-left: 16px;
    padding-right: 16px;
  }

  .notification-center-list {
    padding-left: 10px;
    padding-right: 10px;
  }
}
</style>

<style>
.notification-center-drawer .el-drawer__body {
  padding: 0;
}

@media (max-width: 640px) {
  .notification-center-drawer.el-drawer {
    width: min(94vw, 420px) !important;
  }
}
</style>
