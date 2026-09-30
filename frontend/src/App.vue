<template>
  <div class="app">
    <header class="banner">
      <div class="banner-left">
        <div class="banner-title">Remote Control Hub</div>
        <div class="banner-subtitle">Remote access, shell control, file browsing</div>
      </div>

      <div class="banner-right">
        <span class="banner-meta-label">Online Nodes</span>
        <span class="banner-meta-value">{{ onlineConnectionsCount }}</span>

        <div class="banner-actions">
          <div class="banner-action-links">
            <span class="tool-separator" style="margin-right: 12px; margin-left: 6px"></span>

            <div class="banner-action-links">
              <button
                class="banner-transfer-action"
                type="button"
                title="Transfers"
                @click="openTransferCenter"
              >
                <span class="banner-transfer-symbol">⇅</span>
                <span v-if="activeTransferCount" class="banner-transfer-count">{{ activeTransferCount }}</span>
              </button>
              <button
                class="banner-notification-action"
                type="button"
                title="Notifications"
                @click="openNotificationCenter"
              >
                <el-icon><Bell /></el-icon>
              </button>
              <button
                class="banner-inline-action"
                type="button"
                @click="openAgentBuilderDialog"
              >
                Build Agent
              </button>
              <button
                class="banner-inline-action"
                type="button"
                onclick="window.RatAuth && window.RatAuth.logout()"
              >
                Sign out
              </button>
            </div>
          </div>
        </div>
      </div>
    </header>

    <div
      class="content"
      :class="{ 'content-sidebar-collapsed': deviceSidebarCollapsed }"
    >
      <DeviceSidebar
        v-show="!deviceSidebarCollapsed"
        :connections="deviceSidebarConnections"
        :selected-id="selectedId"
        :status-now-tick="statusNowTick"
        :show-hidden-devices="showHiddenDevices"
        :device-groups="deviceGroups"
        :machine-group-assignments="machineGroupAssignments"
        :selected-group-id="selectedDeviceGroupId"
        :device-group-counts="deviceGroupMachineCounts"
        @refresh="loadConnections"
        @select="selectConnection"
        @toggle-hidden-devices="toggleShowHiddenDevices"
        @toggle-client-hidden="toggleClientHiddenFromSidebar"
        @toggle-machine-hidden="toggleMachineHiddenFromSidebar"
        @group-filter-change="setSelectedDeviceGroup"
        @manage-groups="openDeviceGroupManagerDialog"
        @assign-machine-group="assignMachineGroupFromSidebar"
        @rename-machine="renameMachineFromSidebar"
        @open-connection-history="openMachineConnectionHistory"
        @connection-removed="forgetConnectionFromDeviceView"
        @connection-remove-failed="restoreConnectionFromDeviceView"
      />

      <main class="main panel">
        <template v-if="currentConnection">
          <div class="main-body">
            <!--            <ConnectionInfoCards-->
            <!--                :connection="currentConnection"-->
            <!--                :status-now-tick="statusNowTick"-->
            <!--            />-->

            <div
              class="connection-info-shell"
              :class="{ 'connection-info-shell-collapsed': connectionInfoCollapsed }"
            >
              <button
                class="connection-info-toggle"
                type="button"
                :title="connectionInfoCollapsed ? 'Show connection info' : 'Hide connection info'"
                @click="toggleConnectionInfo"
              >
                <el-icon class="connection-info-toggle-icon">
                  <ArrowDown v-if="connectionInfoCollapsed" />
                  <ArrowUp v-else />
                </el-icon>
              </button>

              <ConnectionInfoCards
                v-show="!connectionInfoCollapsed"
                :connection="currentConnection"
                :status-now-tick="statusNowTick"
              />
            </div>

            <section class="terminal-panel">
              <div class="terminal-frame">
                <TerminalToolbar
                  ref="terminalToolbarRef"
                  :selected-id="selectedId"
                  :current-connection="currentConnection"
                  :current-connection-offline="isCurrentConnectionOffline"
                  :device-sidebar-collapsed="deviceSidebarCollapsed"
                  :connection-info-collapsed="connectionInfoCollapsed"
                  @layout-command="handleToolbarLayoutCommand"
                  @open-remote-files="openRemoteFilesDialog"
                  @open-artifacts="openArtifactDialog"
                  @open-external-tools="openExternalToolManagerDialog"
                  @open-keychains="openKeychainManagerDialog"
                  @open-info="openConnectionInfoDialog"
                  @open-jobs="openBackgroundJobsDialog"
                  @open-scripts="openScriptLibraryDialog"
                  @open-agents="openAgentOutputsDialog"
                  @open-history="openCommandHistoryDialog"
                  @open-pty="openPtyDialog"
                  @open-screen-view="openScreenViewDialog"
                  @open-clipboard="openClipboardDialog"
                  @open-processes="openProcessDialog"
                  @open-one-liners="openOneLinersDialog"
                  @open-quick-actions="openQuickActionsDialog"
                  @run-quick-action="runPinnedQuickAction"
                  @open-settings="openSettingsDialog"
                  @clear="clearOutput"
                  @bottom="scrollToBottom"
                />

<CommandInputBar
  ref="commandInputBarRef"
  :selected-id="selectedId"
  :current-connection="currentConnection"
  :current-active-task-id="currentActiveTaskId"
  :tab-id="tabId"
  @append-output="appendOutput"
  @set-active-task="setActiveTask"
  @clear-output="clearOutput"
/>

                <!--                <TerminalOutput-->
                <!--                    ref="terminalOutputRef"-->
                <!--                    :lines="currentOutputLines"-->
                <!--                    @preview-artifact="previewArtifact"-->
                <!--                    @open-json="$refs.terminalJsonDialogRef?.open($event)"-->
                <!--                />-->

                <TerminalOutput
                  ref="terminalOutputRef"
                  :lines="currentOutputLines"
                  :selected-id="selectedId"
                  :current-connection="currentConnection"
                  @preview-artifact="previewArtifact"
                  @open-json="$refs.terminalJsonDialogRef?.open($event)"
                  @artifact-saved="refreshArtifactsIfOpen"
                  @rerun-terminal-block="rerunTerminalBlock"
                  @suggest-command="applyTerminalSuggestedCommand"
                />
              </div>
            </section>
          </div>
        </template>

        <template v-else>
          <div class="main-empty">
            <div class="main-empty-title">No device selected</div>
            <div class="main-empty-text">
              Choose a device from the left sidebar to start an interactive
              session.
            </div>
          </div>
        </template>
      </main>
    </div>
  </div>

  <input
    ref="remoteUploadInputRef"
    type="file"
    class="hidden-file-input"
    @change="handleRemoteUploadChange"
  >

  <RemoteFilesDialog
    ref="remoteFilesDialogRef"
    :selected-id="selectedId"
    :get-tab-scoped-headers="getTabScopedHeaders"
    @append-output="appendOutput"
    @set-active-task="setActiveTask"
    @preview="previewRemoteEntry"
    @request-upload="triggerRemoteUploadInput"
    @upload-started="pendingRemoteUploadRefresh = $event"
    @visible-change="remoteFilesDialogVisible = $event"
    @artifacts-maybe-changed="refreshArtifactsIfOpen"
  />

  <ArtifactDialog
    ref="artifactDialogRef"
    :selected-id="selectedId"
    :current-connection="currentConnection"
    :machine-alias-map="machineAliasMap"
    :get-tab-scoped-headers="getTabScopedHeaders"
    @preview="previewArtifact"
    @append-output="appendOutput"
    @set-active-task="setActiveTask"
    @open-new-shared-file-editor="openNewSharedFileEditor"
  />

  <ExternalToolManagerDialog
    ref="externalToolManagerDialogRef"
    :selected-id="selectedId"
    :current-connection="currentConnection"
    :connections="connections"
    :machine-alias-map="machineAliasMap"
    :get-tab-scoped-headers="getTabScopedHeaders"
    @append-output="appendOutput"
    @set-active-task="setActiveTask"
    @upload-started="pendingRemoteUploadRefresh = $event"
    @open-tool-meta-editor="openExternalToolMetaEditor"
  />

  <KeychainManagerDialog
    ref="keychainManagerDialogRef"
    :current-connection="currentConnection"
    :machine-alias-map="machineAliasMap"
  />

  <ScriptLibraryDialog
    ref="scriptLibraryDialogRef"
    :selected-id="selectedId"
    :current-connection="currentConnection"
    :get-tab-scoped-headers="getTabScopedHeaders"
    :open-script-editor="openRemoteScriptEditorInternal"
    :open-new-script-editor="openNewRemoteScriptEditor"
    @append-output="appendOutput"
    @set-active-task="setActiveTask"
    @upload-started="pendingRemoteUploadRefresh = $event"
  />

  <BackgroundJobsDialog
    ref="backgroundJobsDialogRef"
    :selected-id="selectedId"
    :current-connection="currentConnection"
    :get-tab-scoped-headers="getTabScopedHeaders"
    :format-date-time-standard="formatDateTimeStandard"
    :format-bytes="formatBytes"
    @append-output="appendOutput"
    @set-active-task="setActiveTask"
    @upload-started="pendingRemoteUploadRefresh = $event"
    @preview-file="previewBackgroundJobFile"
    @open-job-editor="openRemoteJobEditor"
    @open-new-job-editor="openNewRemoteJobEditor"
    @job-deleted="handleBackgroundJobDeleted"
  />

  <PreviewDialog
    ref="previewDialogRef"
    :selected-id="selectedId"
    :remote-files-dialog-visible="remoteFilesDialogVisible"
    @remote-directory-maybe-changed="refreshRemoteDirectory"
    @artifacts-maybe-changed="refreshArtifactsIfOpen"
    @scripts-maybe-changed="refreshScriptsIfOpen"
    @background-job-modules-maybe-changed="refreshBackgroundJobModulesIfOpen"
    @external-tools-maybe-changed="refreshExternalToolsIfOpen"
  />

  <MachineConnectionHistoryDialog
    ref="machineConnectionHistoryDialogRef"
  />

  <CommandHistoryDialog
    ref="commandHistoryDialogRef"
    :selected-id="selectedId"
    :current-connection="currentConnection"
    :format-date-time-standard="formatDateTimeStandard"
    :format-bytes="formatBytes"
    :reload-command-candidates="reloadCommandCandidatesFromHistory"
    @apply-command="applyHistoryCommand"
    @preview-file="previewArtifact"
  />

  <ConnectionInfoDialogs
    ref="connectionInfoDialogRef"
    :selected-id="selectedId"
    :current-connection="currentConnection"
    :status-now-tick="statusNowTick"
    :tab-id="tabId"
  />

  <ProcessDialogs
    ref="processDialogRef"
    :selected-id="selectedId"
    :tab-id="tabId"
  />

  <AgentBuilderDialog
    ref="agentBuilderDialogRef"
    @built="refreshAgentOutputsIfOpen"
  />

<!--  <TerminalJsonDialog-->
<!--    ref="terminalJsonDialogRef"-->
<!--    :selected-id="selectedId"-->
<!--    :current-connection="currentConnection"-->
<!--    @artifact-saved="refreshArtifactsIfOpen"-->
<!--  />-->

  <TerminalJsonDialog
  ref="terminalJsonDialogRef"
  @save-json-output="saveTerminalJsonOutputFromViewer"
/>

  <AgentOutputsDialog
    ref="agentOutputsDialogRef"
    @open-builder="openAgentBuilderDialog"
  />

  <PtyDialog
    ref="ptyDialogRef"
    :selected-id="selectedId"
    :current-connection="currentConnection"
    :get-tab-scoped-headers="getTabScopedHeaders"
  />

  <ScreenViewDialog
    ref="screenViewDialogRef"
    :selected-id="selectedId"
    :current-connection="currentConnection"
    @open-clipboard="openClipboardDialog"
  />

  <ClipboardDialog
    ref="clipboardDialogRef"
    :selected-id="selectedId"
    :current-connection="currentConnection"
    :get-tab-scoped-headers="getTabScopedHeaders"
    @artifacts-maybe-changed="refreshArtifactsIfOpen"
  />

  <OneLinersDialog
    ref="oneLinersDialogRef"
  />

  <QuickActionsDialog
    ref="quickActionsDialogRef"
    :selected-id="selectedId"
    :current-connection="currentConnection"
    :get-tab-scoped-headers="getTabScopedHeaders"
    @append-output="appendOutput"
    @set-active-task="setActiveTask"
    @toolbar-pins-updated="refreshToolbarPreferences"
  />

  <DeviceGroupManagerDialog
    ref="deviceGroupManagerDialogRef"
    :groups="deviceGroups"
    :machine-group-assignments="machineGroupAssignments"
    @groups-changed="handleDeviceGroupsChanged"
  />

  <SettingsDialog
    ref="settingsDialogRef"
    @toolbar-saved="refreshToolbarPreferences"
    @notification-saved="applySseNotificationPreferences"
  />

  <NotificationCenterDrawer
    ref="notificationCenterDrawerRef"
    :notifications="sseNotificationHistory"
    @notification-deleted="removeSseNotificationHistory"
    @notifications-cleared="clearSseNotificationHistory"
    @notification-action="handleNotificationCenterAction"
  />

  <TransferCenterDrawer
    ref="transferCenterDrawerRef"
    :transfers="transferItems"
    :tab-id="tabId"
    @transfers-changed="loadTransferItems"
  />
</template>

<script>
import AppUtilsModule from './composables/useAppUtils.js'
import AppSseModule from './composables/useSseStream.js'
import AppConnectionModule from './composables/useConnections.js'
import AppTaskModule from './composables/useTaskState.js'
import AppTerminalModule from './composables/useTerminalOutput.js'
import DeviceSidebar from './components/DeviceSidebar.vue'
import ConnectionInfoCards from './components/ConnectionInfoCards.vue'
import TerminalToolbar from './components/TerminalToolbar.vue'
import CommandInputBar from './components/CommandInputBar.vue'
import TerminalOutput from './components/TerminalOutput.vue'
import ConnectionInfoDialogs from './components/ConnectionInfoDialogs.vue'
import ProcessDialogs from './components/ProcessDialogs.vue'
import AgentBuilderDialog from './components/AgentBuilderDialog.vue'
import AgentOutputsDialog from './components/AgentOutputsDialog.vue'
import CommandHistoryDialog from './components/CommandHistoryDialog.vue'
import MachineConnectionHistoryDialog from './components/MachineConnectionHistoryDialog.vue'
import RemoteFilesDialog from './components/RemoteFilesDialog.vue'
import ArtifactDialog from './components/ArtifactDialog.vue'
import ExternalToolManagerDialog from './components/ExternalToolManagerDialog.vue'
import KeychainManagerDialog from './components/KeychainManagerDialog.vue'
import ScriptLibraryDialog from './components/ScriptLibraryDialog.vue'
import BackgroundJobsDialog from './components/BackgroundJobsDialog.vue'
import PreviewDialog from './components/PreviewDialog.vue'
import TerminalJsonDialog from './components/TerminalJsonDialog.vue'
import PtyDialog from './components/PtyDialog.vue'
import ScreenViewDialog from './components/ScreenViewDialog.vue'
import ClipboardDialog from './components/ClipboardDialog.vue'
import OneLinersDialog from './components/OneLinersDialog.vue'
import QuickActionsDialog from './components/QuickActionsDialog.vue'
import DeviceGroupManagerDialog from './components/DeviceGroupManagerDialog.vue'
import SettingsDialog from './components/SettingsDialog.vue'
import NotificationCenterDrawer from './components/NotificationCenterDrawer.vue'
import TransferCenterDrawer from './components/TransferCenterDrawer.vue'

import { ArrowDown, ArrowUp, Bell } from '@element-plus/icons-vue'

export default {
  components: {
    TransferCenterDrawer,
    NotificationCenterDrawer,
    DeviceGroupManagerDialog,
    SettingsDialog,
    ClipboardDialog,
    ScreenViewDialog,
    OneLinersDialog,
    QuickActionsDialog,
    ArrowDown,
    ArrowUp,
    Bell,
    PtyDialog,
    TerminalJsonDialog,
    PreviewDialog,
    BackgroundJobsDialog,
    ScriptLibraryDialog,
    KeychainManagerDialog,
    ExternalToolManagerDialog,
    ArtifactDialog,
    RemoteFilesDialog,
    CommandHistoryDialog,
    MachineConnectionHistoryDialog,
    AgentOutputsDialog,
    AgentBuilderDialog,
    ProcessDialogs,
    ConnectionInfoDialogs,
    TerminalOutput,
    CommandInputBar,
    TerminalToolbar,
    ConnectionInfoCards,
    DeviceSidebar,
  },

  data() {
    return {
      ...AppTerminalModule.data(),
      ...AppConnectionModule.data(),
      ...AppTaskModule.data(),
      ...AppSseModule.data(),

      statusNowTick: Date.now(),
      statusTickTimer: null,
      remoteFilesDialogVisible: false,
      pendingRemoteUploadRefresh: null,

      connectionInfoCollapsed: false,
      deviceSidebarCollapsed: false,
    }
  },

  computed: {
    ...AppConnectionModule.computed,
    ...AppTerminalModule.computed,
    ...AppTaskModule.computed,

    isCurrentConnectionOffline() {
      if (!this.currentConnection) return false
      return this.getConnectionDisplayState(this.currentConnection) === 'offline'
    },

    activeTransferCount() {
      return (this.transferItems || []).filter(item => item?.state === 'running').length
    },
  },

  watch: {
    ...AppTerminalModule.watch,
  },

  methods: {
    ...AppUtilsModule.methods,
    ...AppSseModule.methods,
    ...AppConnectionModule.methods,
    ...AppTaskModule.methods,
    ...AppTerminalModule.methods,


    saveTerminalJsonOutputFromViewer(payload = {}) {
  return this.$refs.terminalOutputRef?.saveTerminalJsonOutputFromViewer(payload)
},

    openArtifactDialog() {
      return this.$refs.artifactDialogRef?.open()
    },

    openScreenViewDialog() {
      return this.$refs.screenViewDialogRef?.open()
    },

    openClipboardDialog() {
      return this.$refs.clipboardDialogRef?.open()
    },

    toggleConnectionInfo() {
      this.connectionInfoCollapsed = !this.connectionInfoCollapsed
    },

    toggleDeviceSidebar() {
      this.deviceSidebarCollapsed = !this.deviceSidebarCollapsed
    },

    handleToolbarLayoutCommand(command) {
      const normalizedCommand = String(command || '').trim()

      if (normalizedCommand === 'toggle-device-sidebar') {
        this.toggleDeviceSidebar()
        return
      }

      if (normalizedCommand === 'toggle-connection-info') {
        this.toggleConnectionInfo()
        return
      }

      if (normalizedCommand === 'hide-both') {
        this.deviceSidebarCollapsed = true
        this.connectionInfoCollapsed = true
      }
    },

    refreshArtifactsIfOpen() {
      return this.$refs.artifactDialogRef?.refreshIfOpen()
    },

    openRemoteFilesDialog() {
      this.$refs.remoteFilesDialogRef?.open()
    },

    openExternalToolManagerDialog() {
      const dialog = this.$refs.externalToolManagerDialogRef
      if (dialog?.isOpen?.()) return
      return dialog?.open()
    },

    async handleSseNotificationAction(action = {}, context = {}) {
      const actionType = String(action?.type || '').trim().toLowerCase()

      if (actionType === 'open_external_tools') {
        return this.$refs.externalToolManagerDialogRef?.openFromNotification?.(context)
      }

      if (actionType === 'view_external_tool_log') {
        return this.$refs.externalToolManagerDialogRef?.openFromNotification?.(context, { viewLog: true })
      }

      if (actionType === 'artifact_preview') {
        return this.previewArtifact(context)
      }

      if (actionType === 'open_artifacts') {
        return this.openArtifactDialog()
      }

      if (actionType === 'open_agents') {
        const dialog = this.$refs.agentOutputsDialogRef
        if (dialog?.isOpen?.()) {
          return dialog.refreshIfOpen?.({ silent: true })
        }
        return dialog?.open()
      }

      if (actionType === 'open_transfers') {
        return this.openTransferCenter()
      }
    },

    handleNotificationCenterAction(payload = {}) {
      return this.handleSseNotificationAction(
        payload?.action || {},
        payload?.notification?.context || {},
      )
    },

    openKeychainManagerDialog() {
      return this.$refs.keychainManagerDialogRef?.open()
    },

    refreshExternalToolsIfOpen() {
      return this.$refs.externalToolManagerDialogRef?.refreshIfOpen()
    },

    openExternalToolMetaEditor(toolId) {
      return this.$refs.previewDialogRef?.openExternalToolMetaEditor(toolId)
    },

    triggerRemoteUploadInput() {
      const input = this.$refs.remoteUploadInputRef

      if (input) {
        input.value = ''
        input.click()
      }
    },

    handleRemoteUploadChange(event) {
      this.$refs.remoteFilesDialogRef?.handleUploadChange(event)
    },

    loadRemoteDirectory(path = '', page = 1) {
      return this.$refs.remoteFilesDialogRef?.loadRemoteDirectory(path, page)
    },

    refreshRemoteDirectory() {
      return this.$refs.remoteFilesDialogRef?.refreshRemoteDirectory()
    },

    openBackgroundJobsDialog() {
      return this.$refs.backgroundJobsDialogRef?.open()
    },

    refreshBackgroundJobsIfOpen() {
      return this.$refs.backgroundJobsDialogRef?.refreshIfOpen()
    },

    refreshBackgroundJobModulesIfOpen() {
      return this.$refs.backgroundJobsDialogRef?.refreshModulesIfOpen()
    },

    openScriptLibraryDialog() {
      return this.$refs.scriptLibraryDialogRef?.open()
    },

    refreshScriptsIfOpen() {
      return this.$refs.scriptLibraryDialogRef?.refreshIfOpen()
    },

    openPtyDialog() {
      return this.$refs.ptyDialogRef?.open()
    },

    openOneLinersDialog() {
      return this.$refs.oneLinersDialogRef?.open()
    },

    openQuickActionsDialog() {
      return this.$refs.quickActionsDialogRef?.open()
    },

    runPinnedQuickAction(item) {
      return this.$refs.quickActionsDialogRef?.runPinnedAction(item)
    },

    handleQuickActionCommandResult(payload = {}) {
      return this.$refs.quickActionsDialogRef?.handleCommandResult(payload) === true
    },

    handleQuickActionCommandComplete(payload = {}) {
      return this.$refs.quickActionsDialogRef?.handleCommandComplete(payload) === true
    },

    openDeviceGroupManagerDialog() {
      return this.$refs.deviceGroupManagerDialogRef?.open()
    },

    openSettingsDialog() {
      return this.$refs.settingsDialogRef?.open()
    },

    async openTransferCenter() {
      await this.loadTransferItems()
      return this.$refs.transferCenterDrawerRef?.open()
    },

    async openNotificationCenter() {
      await this.loadSseNotificationHistory()
      return this.$refs.notificationCenterDrawerRef?.open()
    },

    refreshToolbarPreferences() {
      return this.$refs.terminalToolbarRef?.loadManagedToolbar()
    },

    openProcessDialog() {
      return this.$refs.processDialogRef?.open()
    },

    openAgentBuilderDialog() {
      return this.$refs.agentBuilderDialogRef?.open()
    },

    openAgentOutputsDialog() {
      return this.$refs.agentOutputsDialogRef?.open()
    },

    refreshAgentOutputsIfOpen() {
      return this.$refs.agentOutputsDialogRef?.refreshIfOpen({ silent: true })
    },

    openConnectionInfoDialog() {
      return this.$refs.connectionInfoDialogRef?.open()
    },

    scheduleBackgroundJobsRefresh(clientId = '') {
      this.$refs.backgroundJobsDialogRef?.scheduleBackgroundJobsRefresh(clientId)
    },

    handleBackgroundJobDeleted(normalizedName) {
      this.$refs.previewDialogRef?.handleBackgroundJobDeleted(normalizedName)
    },

    previewRemoteEntry(row) {
      return this.$refs.previewDialogRef?.previewRemoteEntry(row)
    },

    previewArtifact(row) {
      return this.$refs.previewDialogRef?.previewArtifact(row)
    },

    previewBackgroundJobFile(file) {
      return this.$refs.previewDialogRef?.previewBackgroundJobFile(file)
    },

    openNewRemoteScriptEditor(scriptName = 'new_script.py') {
      return this.$refs.previewDialogRef?.openNewRemoteScriptEditor(scriptName)
    },

    openRemoteScriptEditorInternal(scriptName) {
      return this.$refs.previewDialogRef?.openRemoteScriptEditorInternal(scriptName)
    },

    openNewRemoteJobEditor(scriptName = 'new_job.py') {
      return this.$refs.previewDialogRef?.openNewRemoteJobEditor(scriptName)
    },

    openNewSharedFileEditor(filename = 'new_file.txt') {
      return this.$refs.previewDialogRef?.openNewSharedFileEditor(filename)
    },

    openRemoteJobEditor(scriptName) {
      return this.$refs.previewDialogRef?.openRemoteJobEditor(scriptName)
    },

    openMachineConnectionHistory(item) {
      return this.$refs.machineConnectionHistoryDialogRef?.open(item)
    },

    openCommandHistoryDialog() {
      return this.$refs.commandHistoryDialogRef?.open()
    },

    rerunTerminalBlock(payload = {}) {
      const type = String(payload.type || '').trim()

      if (type === 'script') {
        return this.$refs.scriptLibraryDialogRef?.runScriptFromTerminalBlock(payload)
      }

      return this.$refs.commandInputBarRef?.runCommandText(payload.command || '')
    },

    applyHistoryCommand(row) {
      if (!row || !row.command) return

      this.$refs.commandInputBarRef?.setCommandText(row.command)
    },

    applyTerminalSuggestedCommand(command) {
      this.$refs.commandInputBarRef?.setCommandText(command)
    },

    async reloadCommandCandidatesFromHistory(options = {}) {
      await this.$refs.commandInputBarRef?.reloadCommandCandidates(options)
    },

    async reloadCommandCandidatesFromRuntime(options = {}) {
      await this.$refs.commandInputBarRef?.reloadCommandCandidates(options)
    },
  },

  async mounted() {
    this.ensureTabId()
    await Promise.all([
      this.loadConnections(),
      this.loadDeviceGroups(),
      this.loadSseNotificationPreferences(),
      this.loadSseNotificationHistory(),
      this.loadTransferItems(),
    ])
    this.initSSE()

    this.statusTickTimer = setInterval(() => {
      this.statusNowTick = Date.now()
    }, 30 * 1000)
  },

  beforeUnmount() {
    if (this.eventSource) this.eventSource.close()

    if (this.statusTickTimer) {
      clearInterval(this.statusTickTimer)
      this.statusTickTimer = null
    }
  },
}
</script>

<style scoped>

.banner-transfer-action {
  margin-right: 10px;
  padding: 4px 2px;
  border: 0;
  background: transparent;
  color: rgba(238, 244, 255, 0.82);
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 3px;
  font-size: 15px;
  line-height: 1;
  transition: color 0.18s ease, opacity 0.18s ease;
}

.banner-transfer-action:hover {
  color: #ffffff;
}

.banner-transfer-action:active {
  opacity: 0.72;
}

.banner-transfer-symbol {
  font-size: 16px;
  line-height: 1;
}

.banner-transfer-count {
  min-width: 12px;
  font-size: 10px;
  font-weight: 700;
  line-height: 1;
}

.banner-notification-action {
  margin-right: 12px;
  padding: 4px 2px;
  border: 0;
  background: transparent;
  color: rgba(238, 244, 255, 0.82);
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  line-height: 1;
  transition: color 0.18s ease, opacity 0.18s ease;
}

.banner-notification-action:hover {
  color: #ffffff;
}

.banner-notification-action:active {
  opacity: 0.72;
}

/*connection info card*/
.connection-info-toggle {
  position: absolute;
  top: 7px;
  right: 10px;
  z-index: 8;
  width: 22px;
  height: 22px;
  padding: 0;
  border: 1px solid rgba(148, 163, 184, 0.2);
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.44);
  color: rgba(100, 116, 139, 0.56);
  cursor: pointer;
  opacity: 0.38;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: opacity 0.16s ease,
  background 0.16s ease,
  color 0.16s ease,
  border-color 0.16s ease,
  box-shadow 0.16s ease,
  transform 0.16s ease;
}

.connection-info-toggle:hover {
  opacity: 1;
  background: rgba(255, 255, 255, 0.92);
  color: rgba(15, 23, 42, 0.72);
  border-color: rgba(148, 163, 184, 0.34);
  box-shadow: 0 4px 12px rgba(15, 23, 42, 0.08);
  transform: translateY(-1px);
}

.connection-info-toggle-icon {
  width: 13px;
  height: 13px;
  font-size: 13px;
  line-height: 1;
}

.connection-info-shell-collapsed .connection-info-toggle {
  top: 8px;
  right: 14px;
  background: rgba(15, 23, 42, 0.2);
  color: rgba(226, 232, 240, 0.78);
  border-color: rgba(255, 255, 255, 0.14);
}

.content-sidebar-collapsed {
  grid-template-columns: minmax(0, 1fr);
}

.content-sidebar-collapsed .main {
  grid-column: 1 / -1;
}

@media (max-width: 640px) {
  .terminal-panel {
    padding-top: 8px;
    padding-left: 8px;
    padding-right: 8px;
  }
}
</style>