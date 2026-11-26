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

      <el-tab-pane label="Connection Context" name="connection-context">
        <div v-loading="connectionContextLoading" class="settings-tab-scroll">
          <div class="settings-note">
            Choose which connection details appear below the terminal command input. The selection applies to every device.
          </div>

          <div class="connection-context-settings-grid">
            <section class="settings-section">
              <div class="settings-section-title">Available fields</div>
              <div class="connection-context-search">
                <el-input
                  v-model="connectionContextSearch"
                  size="small"
                  clearable
                  placeholder="Search fields..."
                  aria-label="Search connection context fields"
                />
              </div>
              <div class="connection-context-available-list">
                <div
                  v-for="field in filteredConnectionContextFields"
                  :key="field.id"
                  class="connection-context-available-row"
                >
                  <el-checkbox
                    :model-value="connectionContextDraft.field_ids.includes(field.id)"
                    @change="toggleConnectionContextField(field.id, $event)"
                  >
                    <component :is="connectionContextIcons[field.icon]" :size="15" aria-hidden="true" />
                    <span>{{ field.label }}</span>
                  </el-checkbox>
                </div>
                <div v-if="filteredConnectionContextFields.length === 0" class="connection-context-empty">
                  No matching fields
                </div>
              </div>
            </section>

            <section class="settings-section">
              <div class="settings-section-title connection-context-selected-title">
                <span>Displayed tags</span>
                <span class="connection-context-count">{{ selectedConnectionContextFields.length }}</span>
              </div>
              <div v-if="selectedConnectionContextFields.length" class="connection-context-selected-list">
                <div
                  v-for="(field, index) in selectedConnectionContextFields"
                  :key="field.id"
                  class="connection-context-selected-row"
                >
                  <component :is="connectionContextIcons[field.icon]" :size="15" aria-hidden="true" />
                  <span class="connection-context-selected-label">{{ field.label }}</span>
                  <div class="connection-context-selected-actions">
                    <el-button
                      size="small"
                      text
                      :disabled="index === 0"
                      :aria-label="`Move ${field.label} up`"
                      @click="moveConnectionContextField(index, -1)"
                    >↑</el-button>
                    <el-button
                      size="small"
                      text
                      :disabled="index === selectedConnectionContextFields.length - 1"
                      :aria-label="`Move ${field.label} down`"
                      @click="moveConnectionContextField(index, 1)"
                    >↓</el-button>
                    <el-button
                      size="small"
                      text
                      :aria-label="`Remove ${field.label}`"
                      @click="toggleConnectionContextField(field.id, false)"
                    >×</el-button>
                  </div>
                </div>
              </div>
              <div v-else class="connection-context-empty connection-context-selected-empty">
                No fields selected. Choose fields to show them below the terminal input.
              </div>
            </section>
          </div>
        </div>
      </el-tab-pane>

      <el-tab-pane label="Server Preferences" name="server-preferences">
        <div v-loading="serverPreferencesLoading" class="settings-tab-scroll">
          <div class="remote-files-settings">
            <div class="remote-files-settings-heading">File operations</div>
            <div class="remote-files-settings-row">
              <div class="remote-files-settings-copy">
                <div class="remote-files-settings-title">Ask when a destination already exists</div>
                <div class="settings-note settings-note-inline">
                  Ask before copying, moving, extracting ZIPs, or uploading to an existing name. Applies to every device.
                </div>
              </div>
              <el-switch v-model="serverPreferencesDraft.ask_on_conflict" aria-label="Ask on file conflict" />
            </div>
            <div class="remote-files-settings-heading">Web preview & editor</div>
            <div class="remote-files-settings-row">
              <div class="remote-files-settings-copy">
                <div class="remote-files-settings-title">Text preview/edit limit</div>
                <div class="settings-note settings-note-inline">Maximum remote-file and Artifact text preview/edit size. Larger previews are truncated; Server Documents use the same edit limit.</div>
              </div>
              <div class="server-preference-number">
                <el-input-number v-model="serverPreferencesDraft.preview_text_max_kib" :min="64" :max="8192" :step="64" size="small" aria-label="Text preview limit KiB" />
                <span>KiB</span>
              </div>
            </div>
            <div class="remote-files-settings-heading">Log Viewer</div>
            <div class="remote-files-settings-row">
              <div class="remote-files-settings-copy">
                <div class="remote-files-settings-title">Maximum displayed log length</div>
                <div class="settings-note settings-note-inline">Retain the newest characters in Log Viewer. Streaming and Follow still work normally.</div>
              </div>
              <div class="server-preference-number">
                <el-input-number v-model="serverPreferencesDraft.log_viewer_max_kichars" :min="64" :max="8192" :step="64" size="small" aria-label="Log viewer maximum Ki characters" />
                <span>Ki chars</span>
              </div>
            </div>
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

      <el-tab-pane label="Identities" name="identities">
        <div v-loading="identitiesLoading" class="settings-tab-scroll identity-settings">
          <section class="identity-panel identity-server">
            <div class="identity-icon" aria-hidden="true">
              <el-icon :size="20"><Lock /></el-icon>
            </div>
            <div class="identity-server-copy">
              <div class="identity-heading">Server Identity</div>
              <div class="settings-note identity-description">Application-local mTLS trust material. Provision Client files before connecting; plain TCP requires no identity.</div>
            </div>
            <div class="identity-server-controls">
              <span class="identity-server-state" :class="{ 'is-ready': identities.initialized }">
                <span class="identity-status-dot" aria-hidden="true"></span>
                {{ identities.initialized ? 'Server identity initialized' : 'Server identity not initialized' }}
              </span>
              <el-button v-if="!identities.initialized" :loading="identityBusy" @click="initializeIdentity">Initialize</el-button>
            </div>
          </section>

          <section v-if="identities.initialized" class="identity-panel identity-clients">
            <div class="identity-clients-header">
              <div class="identity-heading">Client Identities</div>
              <div class="settings-note identity-description">Download and securely install client.crt, client.key and server-ca.crt in ~/client_bundle/identity/ (iOS: ~/Documents/client_bundle/identity/). On Linux/macOS, set client.key permissions to 0600 after extraction. Protect the private key; revoked identities cannot open new sessions.</div>
            </div>
            <div class="identity-create">
              <div class="identity-create-fields">
                <el-input v-model="newIdentityName" maxlength="80" placeholder="Installation identity name" class="identity-name-input" />
                <div class="identity-validity">
                  <el-input-number v-model="newIdentityDays" :min="1" :max="825" :step="1" aria-label="Certificate validity days" />
                  <span class="settings-note">days</span>
                </div>
              </div>
              <el-button type="primary" :loading="identityBusy" @click="createIdentity">Create</el-button>
            </div>
            <div class="identity-list" role="list">
              <div v-for="item in identities.clients" :key="item.id" class="identity-item" role="listitem">
                <div class="identity-item-main">
                  <span class="identity-item-icon" aria-hidden="true"><el-icon :size="17"><Key /></el-icon></span>
                  <div class="identity-item-info">
                    <div class="identity-item-title">
                      <span class="identity-item-name">{{ item.name }}</span>
                      <span class="identity-state" :class="item.revoked ? 'is-revoked' : 'is-active'">
                        <span class="identity-status-dot" aria-hidden="true"></span>
                        {{ item.revoked ? 'Revoked' : 'Active' }}
                      </span>
                    </div>
                    <div class="identity-expiry">Expires {{ formatDateTimeLocal(item.expires_at) }}</div>
                  </div>
                </div>
                <div class="identity-actions">
                  <el-button size="small" :disabled="item.revoked" @click="downloadIdentity(item.id)">Download</el-button>
                  <el-button size="small" type="primary" plain :disabled="item.revoked || identityBusy" @click="copyIdentityCommand(item.id)">Copy Command</el-button>
                  <el-button size="small" type="danger" plain :disabled="item.revoked || identityBusy" @click="revokeIdentity(item)">Revoke</el-button>
                </div>
              </div>
            </div>
          </section>
        </div>
      </el-tab-pane>

      <el-tab-pane label="Server" name="server">
        <div class="settings-tab-scroll">
          <section class="settings-section">
            <div class="settings-section-title">Server Maintenance</div>
            <div class="server-maintenance-row">
              <div>
                <div class="server-maintenance-title">Restart Server</div>
                <div class="settings-note settings-note-inline">Restart the current RCH Server process.</div>
              </div>
              <el-button :loading="maintenanceAction === 'restart'" :disabled="!!maintenanceAction" @click="confirmServerMaintenance('restart')">Restart</el-button>
            </div>
            <div class="server-maintenance-row">
              <div>
                <div class="server-maintenance-title">Shutdown Server</div>
                <div class="settings-note settings-note-inline">Stop the current RCH Server process.</div>
              </div>
              <el-button type="danger" plain :loading="maintenanceAction === 'shutdown'" :disabled="!!maintenanceAction" @click="confirmServerMaintenance('shutdown')">Shutdown</el-button>
            </div>
            <div v-if="maintenanceStatus" class="server-maintenance-status" role="status">{{ maintenanceStatus }}</div>
          </section>
        </div>
      </el-tab-pane>
    </el-tabs>

    <template #footer>
      <div v-if="activeTab !== 'server' && activeTab !== 'identities'" class="settings-footer">
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
import { ElMessage, ElMessageBox } from 'element-plus'
import { Key, Lock } from '@element-plus/icons-vue'
import {
  loadToolbarPreferences,
  saveToolbarPreferences,
} from '../api/toolbarPreferencesApi.js'
import {
  loadNotificationPreferences,
  saveNotificationPreferences,
} from '../api/notificationPreferencesApi.js'
import {
  loadTerminalContextPreferences,
  saveTerminalContextPreferences,
} from '../api/terminalContextPreferencesApi.js'
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
import {
  CONNECTION_CONTEXT_FIELD_CATALOG,
  DEFAULT_CONNECTION_CONTEXT_PREFERENCES,
  cloneConnectionContextPreferences,
  normalizeConnectionContextPreferences,
} from '../data/connectionContextFields.js'
import { CONNECTION_CONTEXT_ICONS } from '../data/connectionContextIcons.js'
import { DEFAULT_SERVER_PREFERENCES, loadServerPreferences, saveServerPreferences } from '../api/serverPreferencesApi.js'
import { getServerMaintenance, performServerMaintenance } from '../api/serverMaintenanceApi.js'
import { getAuthorizationInfo } from '../api/authApi.js'
import { getIdentities, initializeIdentities, issueClientIdentity, revokeClientIdentity, downloadClientIdentity, clientIdentityInstallCommand } from '../api/identitiesApi.js'
import { copyTextFallback } from '../utils/clipboard.js'
import { formatDateTimeLocal } from '../utils/formatters.js'

export default {
  name: 'SettingsDialog',
  components: { Key, Lock },

  emits: ['notification-saved'],

  data() {
    return {
      visible: false,
      activeTab: 'toolbar',
      identities: { initialized: false, clients: [] },
      identitiesLoading: false, identityBusy: false, newIdentityName: '', newIdentityDays: 365,
      maintenanceAction: '',
      maintenanceStatus: '',
      serverPreferencesLoading: false,
      serverPreferencesSaving: false,
      serverPreferencesDraft: { ask_on_conflict: false, preview_text_max_kib: 512, log_viewer_max_kichars: 512 },

      toolbarLoading: false,
      toolbarSaving: false,
      toolbarDraft: cloneToolbarPreferences(DEFAULT_TOOLBAR_PREFERENCES),

      notificationLoading: false,
      notificationSaving: false,
      notificationGroups: SSE_NOTIFICATION_GROUPS,
      notificationDraft: cloneSseNotificationPreferences(DEFAULT_SSE_NOTIFICATION_PREFERENCES),

      connectionContextLoading: false,
      connectionContextSaving: false,
      connectionContextSearch: '',
      connectionContextFields: CONNECTION_CONTEXT_FIELD_CATALOG,
      connectionContextDraft: cloneConnectionContextPreferences(DEFAULT_CONNECTION_CONTEXT_PREFERENCES),
    }
  },

  computed: {
    activeLoading() {
      if (this.activeTab === 'server-preferences') return this.serverPreferencesLoading
      if (this.activeTab === 'notifications') return this.notificationLoading
      if (this.activeTab === 'connection-context') return this.connectionContextLoading
      return this.toolbarLoading
    },
    activeSaving() {
      if (this.activeTab === 'server-preferences') return this.serverPreferencesSaving
      if (this.activeTab === 'notifications') return this.notificationSaving
      if (this.activeTab === 'connection-context') return this.connectionContextSaving
      return this.toolbarSaving
    },
    connectionContextIcons() {
      return CONNECTION_CONTEXT_ICONS
    },
    filteredConnectionContextFields() {
      const query = String(this.connectionContextSearch || '').trim().toLocaleLowerCase()
      if (!query) return this.connectionContextFields
      return this.connectionContextFields.filter(field =>
        `${field.label} ${field.id} ${field.description}`.toLocaleLowerCase().includes(query))
    },
    selectedConnectionContextFields() {
      const byId = new Map(this.connectionContextFields.map(field => [field.id, field]))
      return this.connectionContextDraft.field_ids.map(id => byId.get(id)).filter(Boolean)
    },
  },

  methods: {
    formatDateTimeLocal,
    async loadIdentities() {
      this.identitiesLoading = true
      try { this.identities = await getIdentities() }
      catch (error) { ElMessage.error(error.message) }
      finally { this.identitiesLoading = false }
    },
    async initializeIdentity() {
      this.identityBusy = true
      try { await initializeIdentities(); await this.loadIdentities(); ElMessage.success('Server identity initialized') }
      catch (error) { ElMessage.error(error.message) }
      finally { this.identityBusy = false }
    },
    async createIdentity() {
      if (!this.newIdentityName.trim()) return ElMessage.warning('Enter an identity name')
      this.identityBusy = true
      try {
        const identity = await issueClientIdentity(this.newIdentityName.trim(), this.newIdentityDays)
        this.newIdentityName = ''
        await this.loadIdentities()
        await downloadClientIdentity(identity.id)
        ElMessage.success('Client identity created. Store the downloaded private key securely.')
      } catch (error) { ElMessage.error(error.message) }
      finally { this.identityBusy = false }
    },
    async downloadIdentity(id) {
      try { await downloadClientIdentity(id) }
      catch (error) { ElMessage.error(error.message) }
    },
    async copyIdentityCommand(id) {
      try {
        const { command } = await clientIdentityInstallCommand(id)
        if (navigator.clipboard?.writeText) {
          try { await navigator.clipboard.writeText(command) }
          catch { copyTextFallback(command) }
        } else copyTextFallback(command)
        ElMessage.success('Identity install command copied')
      } catch (error) { ElMessage.error(error.message) }
    },
    async revokeIdentity(identity) {
      try { await ElMessageBox.confirm(`Revoke identity "${identity.name}"? All its new mTLS connections will be rejected.`, 'Revoke identity', { type: 'warning' }) }
      catch { return }
      this.identityBusy = true
      try { await revokeClientIdentity(identity.id); await this.loadIdentities(); ElMessage.success('Identity revoked') }
      catch (error) { ElMessage.error(error.message) }
      finally { this.identityBusy = false }
    },
    async confirmServerMaintenance(action) {
      if (this.maintenanceAction) return
      const restart = action === 'restart'
      try {
        await ElMessageBox.confirm(
          restart
            ? 'Restart the RCH Server? All connected clients will briefly disconnect.'
            : 'Shut down the RCH Server? All connected clients will disconnect.',
          restart ? 'Restart Server' : 'Shutdown Server',
          { type: 'warning', confirmButtonText: restart ? 'Restart' : 'Shutdown' },
        )
      } catch {
        return
      }

      this.maintenanceAction = action
      let accepted = false
      this.maintenanceStatus = restart ? 'Requesting restart...' : 'Requesting shutdown...'
      try {
        const adminToken = String((await getAuthorizationInfo())?.api_token || '').trim()
        if (!adminToken) throw new Error('Administrator API Token unavailable')
        const previous = restart ? await getServerMaintenance(adminToken) : null
        if (restart && !previous?.instance_id) throw new Error('Could not read Server instance identity')
        await performServerMaintenance(action, adminToken)
        accepted = true
        if (!restart) {
          this.maintenanceStatus = 'Server shutdown requested.'
          return
        }

        this.maintenanceStatus = 'Restarting Server...'
        // The old process can still serve HTTP after accepting the request.
        // Require a distinct startup identity before reporting success.
        for (let attempt = 0; attempt < 45; attempt++) {
          await new Promise(resolve => setTimeout(resolve, 1000))
          try {
            const current = await getServerMaintenance(adminToken)
            if (current.instance_id && current.instance_id !== previous.instance_id) {
              this.maintenanceStatus = 'Server restarted.'
              ElMessage.success('Server restarted')
              return
            }
          } catch {
            // Connection loss is expected while the Server restarts.
          }
        }
        throw new Error('Server restart was not confirmed. Check the Server log.')
      } catch (error) {
        this.maintenanceStatus = error.message || 'Server maintenance failed'
        ElMessage.error(this.maintenanceStatus)
      } finally {
        if (restart || !accepted) this.maintenanceAction = ''
      }
    },
    async open(tab = 'toolbar') {
      this.visible = true
      this.activeTab = ['notifications', 'connection-context', 'server-preferences', 'server', 'identities'].includes(tab) ? tab : 'toolbar'

      await Promise.all([
        this.loadIdentities(),
        this.loadToolbarSettings(),
        this.loadNotificationSettings(),
        this.loadConnectionContextSettings(),
        this.loadServerPreferencesSettings(),
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
        // Toolbar Settings only owns placement/order. Preserve pins managed elsewhere.
        const latest = normalizeToolbarPreferences(await loadToolbarPreferences())
        const payload = {
          ...this.toolbarDraft,
          quick_actions_pinned: latest.quick_actions_pinned,
          toolbox_shortcuts: latest.toolbox_shortcuts,
        }
        const saved = normalizeToolbarPreferences(
          await saveToolbarPreferences(payload),
        )
        this.toolbarDraft = cloneToolbarPreferences(saved)
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

    async loadConnectionContextSettings() {
      this.connectionContextLoading = true
      try {
        this.connectionContextDraft = cloneConnectionContextPreferences(
          normalizeConnectionContextPreferences(await loadTerminalContextPreferences()),
        )
      } catch (e) {
        ElMessage.error(e.message || 'Failed to load connection context settings')
      } finally {
        this.connectionContextLoading = false
      }
    },
    toggleConnectionContextField(fieldId, checked) {
      const fieldIds = [...this.connectionContextDraft.field_ids]
      const existingIndex = fieldIds.indexOf(fieldId)
      if (checked && existingIndex < 0) fieldIds.push(fieldId)
      if (!checked && existingIndex >= 0) fieldIds.splice(existingIndex, 1)
      this.connectionContextDraft = { field_ids: fieldIds }
    },
    moveConnectionContextField(index, direction) {
      const fieldIds = [...this.connectionContextDraft.field_ids]
      const targetIndex = index + direction
      if (targetIndex < 0 || targetIndex >= fieldIds.length) return
      const [fieldId] = fieldIds.splice(index, 1)
      fieldIds.splice(targetIndex, 0, fieldId)
      this.connectionContextDraft = { field_ids: fieldIds }
    },
    resetConnectionContextDefaults() {
      this.connectionContextDraft = cloneConnectionContextPreferences(DEFAULT_CONNECTION_CONTEXT_PREFERENCES)
    },
    async saveConnectionContextSettings() {
      if (this.connectionContextSaving) return
      this.connectionContextSaving = true
      try {
        const saved = cloneConnectionContextPreferences(
          normalizeConnectionContextPreferences(await saveTerminalContextPreferences(this.connectionContextDraft)),
        )
        this.connectionContextDraft = saved
        ElMessage.success('Connection context settings updated')
      } catch (e) {
        ElMessage.error(e.message || 'Failed to save connection context settings')
      } finally {
        this.connectionContextSaving = false
      }
    },

    toServerPreferencesDraft(saved = DEFAULT_SERVER_PREFERENCES) {
      return {
        ask_on_conflict: saved.ask_on_conflict === true,
        preview_text_max_kib: Math.round(saved.preview_text_max_bytes / 1024),
        log_viewer_max_kichars: Math.round(saved.log_viewer_max_chars / 1024),
      }
    },
    async loadServerPreferencesSettings() {
      this.serverPreferencesLoading = true
      try {
        this.serverPreferencesDraft = this.toServerPreferencesDraft(await loadServerPreferences())
      } catch (error) {
        ElMessage.error(error.message || 'Failed to load Server preferences')
      } finally {
        this.serverPreferencesLoading = false
      }
    },
    async saveServerPreferencesSettings() {
      this.serverPreferencesSaving = true
      try {
        const draft = this.serverPreferencesDraft
        const saved = await saveServerPreferences({
          ask_on_conflict: draft.ask_on_conflict,
          preview_text_max_bytes: draft.preview_text_max_kib * 1024,
          log_viewer_max_chars: draft.log_viewer_max_kichars * 1024,
        })
        this.serverPreferencesDraft = this.toServerPreferencesDraft(saved)
        ElMessage.success('Server preferences updated')
      } catch (error) {
        ElMessage.error(error.message || 'Failed to save Server preferences')
      } finally {
        this.serverPreferencesSaving = false
      }
    },
    resetActiveDefaults() {
      if (this.activeTab === 'server-preferences') {
        this.serverPreferencesDraft = this.toServerPreferencesDraft()
        return
      }
      if (this.activeTab === 'notifications') {
        this.resetNotificationDefaults()
        return
      }
      if (this.activeTab === 'connection-context') {
        this.resetConnectionContextDefaults()
        return
      }
      this.resetToolbarDefaults()
    },
    saveActiveSettings() {
      if (this.activeTab === 'server-preferences') return this.saveServerPreferencesSettings()
      if (this.activeTab === 'notifications') {
        return this.saveNotificationSettings()
      }
      if (this.activeTab === 'connection-context') {
        return this.saveConnectionContextSettings()
      }
      return this.saveToolbarSettings()
    },
  },
}
</script>

<style scoped>
/* Identity management keeps its own visual hierarchy without changing other Settings tabs. */
.identity-settings {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 4px 3px 12px 0;
}

.identity-panel {
  flex: 0 0 auto;
  min-width: 0;
  overflow: hidden;
  border: 1px solid var(--el-border-color-light);
  border-radius: 12px;
  background: var(--el-bg-color);
}

.identity-heading {
  color: var(--el-text-color-primary);
  font-size: 14px;
  font-weight: 650;
  line-height: 1.4;
}

.identity-description {
  margin: 7px 0 0;
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.6;
}

.identity-server {
  display: flex;
  align-items: center;
  gap: 15px;
  padding: 20px;
  background: linear-gradient(115deg, var(--el-color-primary-light-9), var(--el-bg-color) 64%);
}

.identity-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 42px;
  height: 42px;
  border-radius: 12px;
  background: var(--el-color-primary-light-8);
  color: var(--el-color-primary);
}

.identity-server-copy {
  min-width: 0;
  flex: 1;
}

.identity-server-controls {
  display: flex;
  flex: 0 0 auto;
  flex-direction: column;
  align-items: flex-end;
  gap: 9px;
}

.identity-server-state,
.identity-state {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  width: fit-content;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 99px;
  background: var(--el-fill-color-light);
  color: var(--el-text-color-secondary);
  font-size: 11px;
  line-height: 1;
  white-space: nowrap;
}

.identity-server-state {
  padding: 8px 10px;
}

.identity-state {
  padding: 6px 9px;
}

.identity-server-state.is-ready,
.identity-state.is-active {
  border-color: var(--el-color-success-light-8);
  background: var(--el-color-success-light-9);
  color: var(--el-color-success-dark-2);
}

.identity-status-dot {
  flex: 0 0 6px;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
}

.identity-clients-header {
  padding: 20px 20px 16px;
}

.identity-create {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  padding: 15px 20px;
  border-top: 1px solid var(--el-border-color-extra-light);
  border-bottom: 1px solid var(--el-border-color-extra-light);
  background: var(--el-fill-color-extra-light);
}

.identity-create-fields {
  display: flex;
  align-items: center;
  flex: 1;
  gap: 12px;
  min-width: 0;
}

.identity-name-input {
  width: 260px;
  max-width: 100%;
}

.identity-validity {
  display: inline-flex;
  align-items: center;
  gap: 9px;
}

.identity-validity :deep(.el-input-number) {
  width: 136px;
}

.identity-validity .settings-note {
  margin: 0;
}

.identity-create > :deep(.el-button) {
  min-width: 88px;
}

.identity-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  min-height: 84px;
  padding: 14px 20px;
  border-bottom: 1px solid var(--el-border-color-extra-light);
  transition: background-color 0.15s ease;
}

.identity-item:last-child {
  border-bottom: 0;
}

.identity-item:hover {
  background: var(--el-fill-color-extra-light);
}

.identity-item-main {
  display: flex;
  align-items: center;
  min-width: 0;
  gap: 12px;
}

.identity-item-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 36px;
  height: 36px;
  border: 1px solid var(--el-border-color-extra-light);
  border-radius: 10px;
  color: var(--el-text-color-regular);
  background: var(--el-fill-color-light);
}

.identity-item-info {
  min-width: 0;
}

.identity-item-title {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.identity-item-name {
  min-width: 0;
  overflow-wrap: anywhere;
  color: var(--el-text-color-primary);
  font-size: 13px;
  font-weight: 650;
}

.identity-expiry {
  margin-top: 6px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.4;
}

.identity-actions {
  display: flex;
  align-items: center;
  flex: 0 0 auto;
  gap: 8px;
}

.identity-actions :deep(.el-button + .el-button) {
  margin-left: 0;
}

@media (max-width: 760px) {
  .identity-server {
    flex-wrap: wrap;
  }

  .identity-server-controls {
    flex-basis: 100%;
    flex-direction: row;
    justify-content: flex-start;
    align-items: center;
    padding-left: 57px;
  }

  .identity-create,
  .identity-item {
    flex-wrap: wrap;
  }

  .identity-create-fields,
  .identity-actions {
    flex-wrap: wrap;
  }

  .identity-actions {
    padding-left: 48px;
  }
}

@media (max-width: 480px) {
  .identity-server-controls,
  .identity-actions {
    padding-left: 0;
  }

  .identity-name-input {
    width: 100%;
  }

  .identity-create > :deep(.el-button) {
    width: 100%;
  }
}

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

.server-maintenance-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  padding: 16px;
  border-bottom: 1px solid var(--el-border-color-extra-light);
}

.server-maintenance-row:last-of-type {
  border-bottom: none;
}

.server-maintenance-title {
  font-weight: 600;
  font-size: 13px;
}

.server-maintenance-status {
  padding: 14px 16px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

/* A single preference should read as a setting, not a card nested in a card. */
.remote-files-settings {
  padding: 6px 2px 0;
}

.remote-files-settings-heading {
  font-size: 13px;
  font-weight: 650;
  color: var(--el-text-color-primary);
}

.remote-files-settings-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  padding: 14px 0 16px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}

.remote-files-settings-copy {
  min-width: 0;
}

.remote-files-settings-title {
  font-size: 13px;
  line-height: 1.5;
  font-weight: 600;
}

.remote-files-settings-row :deep(.el-switch) {
  flex: 0 0 auto;
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

.connection-context-settings-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
  min-height: 0;
}

.connection-context-search {
  padding: 10px 10px 2px;
}

.connection-context-available-list,
.connection-context-selected-list {
  max-height: 360px;
  overflow-y: auto;
  padding: 2px 10px 8px;
}

.connection-context-available-row,
.connection-context-selected-row {
  display: flex;
  align-items: center;
  gap: 9px;
  min-height: 38px;
  border-bottom: 1px solid var(--el-border-color-extra-light);
  font-size: 12px;
}

.connection-context-available-row:last-child,
.connection-context-selected-row:last-child {
  border-bottom: none;
}

.connection-context-available-row :deep(.el-checkbox) {
  display: flex;
  align-items: center;
  width: 100%;
  margin-right: 0;
}

.connection-context-available-row :deep(.el-checkbox__label) {
  display: inline-flex;
  align-items: center;
  gap: 9px;
  min-width: 0;
  flex: 1;
}

.connection-context-selected-label {
  min-width: 0;
  flex: 1;
}

.connection-context-selected-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.connection-context-count {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 21px;
  height: 21px;
  padding: 0 5px;
  border-radius: 11px;
  background: var(--el-fill-color);
  color: var(--el-text-color-secondary);
}

.connection-context-selected-actions {
  display: flex;
  align-items: center;
  gap: 0;
}

.connection-context-selected-actions .el-button {
  min-width: 24px;
  padding: 4px;
  margin-left: 0;
}

.connection-context-empty {
  padding: 18px 12px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.5;
}

.connection-context-selected-empty {
  min-height: 90px;
  display: flex;
  align-items: center;
}

@media (max-width: 760px) {
  .toolbar-manager-grid,
  .notification-groups,
  .connection-context-settings-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
.server-preference-number { display: flex; align-items: center; gap: 10px; flex: 0 0 auto; white-space: nowrap; }
.server-preference-number :deep(.el-input-number) { width: 148px; }
@media (max-width: 640px) {
  .remote-files-settings-row { align-items: flex-start; flex-wrap: wrap; gap: 8px; }
  .server-preference-number { align-self: flex-start; }
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
