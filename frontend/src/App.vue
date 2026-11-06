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
          <span class="tool-separator banner-major-separator" aria-hidden="true"></span>

          <div class="banner-action-links">
            <button
              class="banner-icon-action banner-transfer-action"
              type="button"
              title="Transfers"
              aria-label="Transfers"
              @click="openTransferCenter"
            >
              <el-icon><Sort /></el-icon>
              <span v-if="activeTransferCount" class="banner-transfer-count">{{ activeTransferCount }}</span>
            </button>
            <button
              class="banner-icon-action banner-notification-action"
              type="button"
              title="Notifications"
              aria-label="Notifications"
              @click="openNotificationCenter"
            >
              <el-icon><Bell /></el-icon>
            </button>
            <el-dropdown trigger="click" @command="handleBannerUtilityCommand">
              <button
                class="banner-icon-action banner-utility-action"
                type="button"
                title="Utilities"
                aria-label="Utilities"
                aria-haspopup="menu"
              >
                <el-icon><Grid /></el-icon>
              </button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="one-liners">One-liners</el-dropdown-item>
                  <el-dropdown-item command="build-agent">Build Agent</el-dropdown-item>
                  <el-dropdown-item command="listeners">Listeners</el-dropdown-item>
                  <el-dropdown-item command="settings">Settings</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>

          <span class="tool-separator banner-major-separator" aria-hidden="true"></span>
          <el-dropdown trigger="click" @command="handleAccountCommand">
            <button
              class="banner-inline-action banner-account-action"
              type="button"
              aria-haspopup="menu"
              :title="authUsernameLabel"
            >
              <el-icon><User /></el-icon>
              <span>{{ authUsernameLabel }}</span>
              <el-icon class="banner-account-chevron"><ArrowDown /></el-icon>
            </button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="change-password">Change Password</el-dropdown-item>
                <el-dropdown-item command="authorization-info">Authorization Info</el-dropdown-item>
                <el-dropdown-item command="sign-out" divided>Sign out</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
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
        :get-tab-scoped-headers="getTabScopedHeaders"
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
                  :has-terminal-output="currentOutputLines.length > 0"
                  @layout-command="handleToolbarLayoutCommand"
                  @open-remote-files="openRemoteFilesDialog"
                  @open-manage-pins="openManagePinnedPathsDialog"
                  @open-connection-history="openSelectedMachineConnectionHistory"
                  @open-artifacts="openArtifactDialog"
                  @open-external-tools="openExternalToolManagerDialog"
                  @open-log-viewer="openLogViewerDialog"
                  @open-keychains="openKeychainManagerDialog"
                  @open-documents="openDocumentsDialog"
                  @open-info="openConnectionInfoDialog"
                  @open-jobs="openBackgroundJobsDialog"
                  @open-scripts="openScriptLibraryDialog"
                  @open-agents="openAgentOutputsDialog"
                  @open-history="openCommandHistoryDialog"
                  @open-pty="openPtyDialog"
                  @open-screen-view="openScreenViewDialog"
                  @open-screen-view-tab="openScreenViewInNewTab"
                  @open-clipboard="openClipboardDialog"
                  @open-processes="openProcessDialog"
                  @hint-preload="hintPreload"
                  @open-one-liners="openOneLinersDialog"
                  @open-quick-actions="openQuickActionsDialog"
                  @run-quick-action="runPinnedQuickAction"
                  @run-quick-action-terminal="runPinnedQuickActionInTerminal"
                  @run-toolbox-script="runToolboxScript"
                  @open-settings="openSettingsDialog"
                  @clear="clearOutput"
                  @clear-selection="clearSelectedConnection"
                  @bottom="scrollToBottom"
                  @copy-terminal-output="copyTerminalOutput('text')"
                  @copy-terminal-json="copyTerminalOutput('json')"
                  @save-terminal-output="saveTerminalOutputArtifact('text')"
                  @save-terminal-json="saveTerminalOutputArtifact('json')"
                />

<CommandInputBar
  ref="commandInputBarRef"
  :selected-id="selectedId"
  :current-connection="currentConnection"
  :status-now-tick="statusNowTick"
  :current-active-task-id="currentActiveTaskId"
  :current-active-task-cancel-policy="currentActiveTaskCancelPolicy"
  :foreground-task="currentForegroundTask"
  :tab-id="tabId"
  @append-output="appendOutput"
  @set-active-task="setActiveTask"
  @check-task-state="refreshForegroundTask"
  @terminal-submission-start="startTerminalSubmission"
  @terminal-submission-finish="finishTerminalSubmission"
  @clear-output="clearOutput"
  @edit-remote-file="editRemoteFile"
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
                  @open-task-details="openForegroundTaskDetails"
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

  <component
    :is="dialogComponents.externalTools"
    v-if="dialogComponents.externalTools"
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
    @open-log-viewer="openLogViewerDialog"
  />

  <LogViewerDialog
    ref="logViewerDialogRef"
    :selected-id="selectedId"
    :tab-id="tabId"
    :get-tab-scoped-headers="getTabScopedHeaders"
  />

  <component :is="dialogComponents.documents" v-if="dialogComponents.documents" ref="documentsDialogRef" />

  <component
    :is="dialogComponents.keychains"
    v-if="dialogComponents.keychains"
    ref="keychainManagerDialogRef"
    :current-connection="currentConnection"
    :machine-alias-map="machineAliasMap"
  />

  <ExecutionInteractionDialog ref="executionInteractionDialogRef" />

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
    @open-json="openResultJson"
  />

  <component
    :is="dialogComponents.backgroundJobs"
    v-if="dialogComponents.backgroundJobs"
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

  <component
    :is="dialogComponents.preview"
    v-if="dialogComponents.preview"
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

  <component
    :is="dialogComponents.commandHistory"
    v-if="dialogComponents.commandHistory"
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
    :foreground-task="currentForegroundTask"
    :status-now-tick="statusNowTick"
    :tab-id="tabId"
    @open-processes="openProcessDialog"
    @open-log-viewer="openLogViewerDialog"
  />

  <component
    :is="dialogComponents.processes"
    v-if="dialogComponents.processes"
    ref="processDialogRef"
    :selected-id="selectedId"
    :tab-id="tabId"
  />

  <ListenerManagerDialog ref="listenerManagerDialogRef" />

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
  :selected-id="selectedId"
  :current-connection="currentConnection"
  :machine-alias-map="machineAliasMap"
  @save-json-output="saveTerminalJsonOutputFromViewer"
  @run-result-action="runTerminalJsonResultAction"
  @rerun-json="runTerminalJsonAgain"
/>

  <AgentOutputsDialog
    ref="agentOutputsDialogRef"
    @open-builder="openAgentBuilderDialog"
  />

  <component
    :is="dialogComponents.pty"
    v-if="dialogComponents.pty"
    ref="ptyDialogRef"
    :selected-id="selectedId"
    :current-connection="currentConnection"
    :get-tab-scoped-headers="getTabScopedHeaders"
    @artifact-saved="refreshArtifactsIfOpen"
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
    @preview-file="previewRemoteEntry"
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
    @open-json="openResultJson"
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
    @connection-context-saved="applyTerminalContextPreferences"
  />

  <NotificationCenterDrawer
    ref="notificationCenterDrawerRef"
    :notifications="sseNotificationHistory"
    @notification-deleted="removeSseNotificationHistory"
    @notifications-cleared="loadSseNotificationHistory"
    @notification-action="handleNotificationCenterAction"
  />

  <TransferCenterDrawer
    ref="transferCenterDrawerRef"
    :transfers="transferItems"
    :tab-id="tabId"
    @transfers-changed="loadTransferItems"
  />

  <el-dialog
    v-model="changePasswordDialogVisible"
    title="Change Password"
    width="min(92vw, 440px)"
    append-to-body
    @closed="resetChangePasswordForm"
  >
    <el-form label-position="top" @submit.prevent="submitPasswordChange">
      <el-form-item label="Current password">
        <el-input
          v-model="changePasswordForm.currentPassword"
          type="password"
          show-password
          autocomplete="current-password"
        />
      </el-form-item>
      <el-form-item label="New password">
        <el-input
          v-model="changePasswordForm.newPassword"
          type="password"
          show-password
          autocomplete="new-password"
        />
      </el-form-item>
      <el-form-item label="Confirm new password">
        <el-input
          v-model="changePasswordForm.confirmPassword"
          type="password"
          show-password
          autocomplete="new-password"
          @keyup.enter="submitPasswordChange"
        />
      </el-form-item>
      <div class="account-dialog-hint">
        Use at least 8 characters with at least one English letter and one number.
      </div>
    </el-form>
    <template #footer>
      <el-button :disabled="changePasswordSubmitting" @click="changePasswordDialogVisible = false">Cancel</el-button>
      <el-button type="primary" :loading="changePasswordSubmitting" @click="submitPasswordChange">Change Password</el-button>
    </template>
  </el-dialog>

  <el-dialog v-model="taskDialogVisible" title="Task Details" width="min(92vw, 520px)" append-to-body>
    <div class="task-detail-grid">
      <template v-for="(value, label) in currentTaskDetails" :key="label">
        <span class="task-detail-label">{{ label }}</span>
        <span class="task-detail-value">{{ value }}</span>
      </template>
    </div>
    <template #footer>
      <el-button @click="taskDialogVisible = false">Close</el-button>
      <el-button type="danger" :disabled="!currentForegroundTask.can_cancel || taskCancelSending" :loading="taskCancelSending" @click="cancelForegroundTask">Cancel</el-button>
    </template>
  </el-dialog>

  <el-dialog
    v-model="authorizationInfoDialogVisible"
    title="Authorization Info"
    width="min(92vw, 520px)"
    append-to-body
  >
    <div v-loading="authorizationInfoLoading" class="authorization-info">
      <div class="authorization-info-row">
        <span class="authorization-info-label">Username</span>
        <span class="authorization-info-value">{{ authorizationInfo.username || '-' }}</span>
      </div>
      <div class="authorization-info-row authorization-token-row">
        <span class="authorization-info-label">API Token</span>
        <div class="authorization-token-control">
          <el-input
            :model-value="authorizationInfo.api_token"
            readonly
            class="authorization-token-input"
          />
          <el-button :disabled="!authorizationInfo.api_token" @click="copyAuthorizationToken">Copy</el-button>
          <el-button
            :loading="authorizationTokenResetting"
            :disabled="authorizationInfoLoading || authorizationTokenResetting"
            @click="resetAuthorizationToken"
          >Reset</el-button>
        </div>
      </div>
      <div class="account-dialog-hint">Use the API Token as a Bearer token for authenticated external API requests.</div>
    </div>
  </el-dialog>
</template>

<script>
import AppUtilsModule from './composables/useAppUtils.js'
import AppSseModule from './composables/useSseStream.js'
import ExecutionInteractionDialog from './components/ExecutionInteractionDialog.vue'
import AppConnectionModule from './composables/useConnections.js'
import AppTaskModule from './composables/useTaskState.js'
import AppTerminalModule from './composables/useTerminalOutput.js'
import DeviceSidebar from './components/DeviceSidebar.vue'
import ConnectionInfoCards from './components/ConnectionInfoCards.vue'
import TerminalToolbar from './components/TerminalToolbar.vue'
import CommandInputBar from './components/CommandInputBar.vue'
import TerminalOutput from './components/TerminalOutput.vue'
import ConnectionInfoDialogs from './components/ConnectionInfoDialogs.vue'
import AgentBuilderDialog from './components/AgentBuilderDialog.vue'
import ListenerManagerDialog from './components/ListenerManagerDialog.vue'
import AgentOutputsDialog from './components/AgentOutputsDialog.vue'
import MachineConnectionHistoryDialog from './components/MachineConnectionHistoryDialog.vue'
import RemoteFilesDialog from './components/RemoteFilesDialog.vue'
import ArtifactDialog from './components/ArtifactDialog.vue'
import LogViewerDialog from './components/LogViewerDialog.vue'
import ScriptLibraryDialog from './components/ScriptLibraryDialog.vue'
import TerminalJsonDialog from './components/TerminalJsonDialog.vue'
import { createTerminalTaskCapture } from './composables/terminalTaskCapture.js'
import ScreenViewDialog from './components/ScreenViewDialog.vue'
import ClipboardDialog from './components/ClipboardDialog.vue'
import OneLinersDialog from './components/OneLinersDialog.vue'
import QuickActionsDialog from './components/QuickActionsDialog.vue'
import DeviceGroupManagerDialog from './components/DeviceGroupManagerDialog.vue'
import SettingsDialog from './components/SettingsDialog.vue'
import NotificationCenterDrawer from './components/NotificationCenterDrawer.vue'
import TransferCenterDrawer from './components/TransferCenterDrawer.vue'
import { changeAdminPassword, getAuthorizationInfo, getAuthSession, resetAdminApiToken } from './api/authApi.js'
import { loadLayoutPreferences, saveLayoutPreferences } from './utils/layoutPreferences.js'
import { ElMessage, ElMessageBox } from 'element-plus'
import { markRaw } from 'vue'
import { scheduleIdleWarmup } from './utils/idleWarmup.js'
import { getConnectionTask } from './api/connectionsApi.js'
import { cancelTask } from './api/tasksApi.js'
import { normalizeForegroundTask, shouldShowTaskNotice, formatTaskTime } from './utils/foregroundTask.js'

import { ArrowDown, ArrowUp, Bell, Grid, Sort, User } from '@element-plus/icons-vue'

// Keep a single in-flight module per dialog, shared by idle warmup, hover and click.
const optionalDialogLoaders = {
  externalTools: () => import('./components/ExternalToolManagerDialog.vue'),
  commandHistory: () => import('./components/CommandHistoryDialog.vue'),
  backgroundJobs: () => import('./components/BackgroundJobsDialog.vue'),
  preview: () => import('./components/PreviewDialog.vue'),
  documents: () => import('./components/DocumentsDialog.vue'),
  pty: () => import('./components/PtyDialog.vue'),
  processes: () => import('./components/ProcessDialogs.vue'),
  keychains: () => import('./components/KeychainManagerDialog.vue'),
}
const optionalDialogRequests = new Map()
function loadOptionalDialog(name) {
  if (!optionalDialogLoaders[name]) return Promise.reject(new Error(`Unknown dialog: ${name}`))
  if (!optionalDialogRequests.has(name)) {
    const request = optionalDialogLoaders[name]().then(result => markRaw(result.default))
      .catch(error => {
        optionalDialogRequests.delete(name) // Failed imports may be retried.
        throw error
      })
    optionalDialogRequests.set(name, request)
  }
  return optionalDialogRequests.get(name)
}
const optionalDialogRefs = {
  externalTools: 'externalToolManagerDialogRef',
  commandHistory: 'commandHistoryDialogRef',
  backgroundJobs: 'backgroundJobsDialogRef',
  preview: 'previewDialogRef',
  documents: 'documentsDialogRef',
  pty: 'ptyDialogRef',
  processes: 'processDialogRef',
  keychains: 'keychainManagerDialogRef',
}
const hoverWarmupTargets = {
  'external-tools': 'externalTools',
  history: 'commandHistory',
  jobs: 'backgroundJobs',
  documents: 'documents',
  keychains: 'keychains',
  pty: 'pty',
  processes: 'processes',
  artifacts: 'preview',
}

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
    Grid,
    Sort,
    User,
    TerminalJsonDialog,
    ExecutionInteractionDialog,
    ScriptLibraryDialog,
    LogViewerDialog,
    ArtifactDialog,
    RemoteFilesDialog,
    MachineConnectionHistoryDialog,
    AgentOutputsDialog,
    AgentBuilderDialog,
    ListenerManagerDialog,
    ConnectionInfoDialogs,
    TerminalOutput,
    CommandInputBar,
    TerminalToolbar,
    ConnectionInfoCards,
    DeviceSidebar,
  },

  data() {
    const layoutPreferences = loadLayoutPreferences()
    return {
      ...AppTerminalModule.data(),
      ...AppConnectionModule.data(),
      ...AppTaskModule.data(),
      ...AppSseModule.data(),

      terminalTaskCapture: createTerminalTaskCapture(),
      statusNowTick: Date.now(),
      statusTickTimer: null,
      foregroundTasks: {},
      pendingTerminalSubmissions: {},
      foregroundQuerySequence: 0,
      taskDialogVisible: false,
      taskCancelSending: false,
      remoteFilesDialogVisible: false,
      pendingRemoteUploadRefresh: null,
      dialogComponents: {
        externalTools: null, commandHistory: null, pty: null, backgroundJobs: null,
        processes: null, keychains: null, preview: null, documents: null,
      },
      cancelIdleWarmup: null,

      connectionInfoCollapsed: layoutPreferences.connectionInfoCollapsed,
      deviceSidebarCollapsed: layoutPreferences.deviceSidebarCollapsed,

      currentAuthUsername: '',
      changePasswordDialogVisible: false,
      changePasswordSubmitting: false,
      changePasswordForm: {
        currentPassword: '',
        newPassword: '',
        confirmPassword: '',
      },
      authorizationInfoDialogVisible: false,
      authorizationInfoLoading: false,
      authorizationTokenResetting: false,
      authorizationInfo: {
        username: '',
        api_token: '',
      },
    }
  },

  computed: {
    ...AppConnectionModule.computed,
    ...AppTerminalModule.computed,
    ...AppTaskModule.computed,

    currentForegroundTask() {
      if (this.isCurrentConnectionOffline) return { state: 'Idle' }
      return this.foregroundTasks[this.selectedId] || { state: 'Idle' }
    },
    showCurrentTaskNotice() {
      return shouldShowTaskNotice(this.currentForegroundTask, this.currentActiveTaskId,
        this.pendingTerminalSubmissions[this.selectedId], this.tabId)
    },
    currentTaskDetails() {
      const task = this.currentForegroundTask
      return {
        Status: task.state || 'Idle',
        Command: task.command || '-',
        Started: task.started_at ? new Date(task.started_at).toLocaleString() : '-',
        Duration: formatTaskTime(task.started_at, this.statusNowTick),
        Source: task.source || '-',
        Type: task.task_type || '-',
        'Task ID': task.task_id || '-',
        'Command ID': task.command_id ?? '-',
        Cancellation: task.can_cancel ? 'Available' : (task.cancel_policy === 'none' ? 'Not supported' : task.cancel_state || 'Unavailable'),
      }
    },

    isCurrentConnectionOffline() {
      if (!this.currentConnection) return false
      return this.getConnectionDisplayState(this.currentConnection) === 'offline'
    },

    activeTransferCount() {
      return (this.transferItems || []).filter(item => item?.state === 'running').length
    },

    authUsernameLabel() {
      return String(this.currentAuthUsername || '').trim() || 'Account'
    },
  },

  watch: {
    ...AppTerminalModule.watch,
    selectedId() {
      this.foregroundQuerySequence += 1
      this.taskDialogVisible = false
      void this.refreshForegroundTask()
    },
    currentActiveTaskId() {
      const clientId = String(this.selectedId || '').trim()
      if (clientId) this.syncForegroundTaskNotice(clientId, this.currentForegroundTask)
    },
  },

  methods: {
    hintPreload(actionId) {
      const target = hoverWarmupTargets[String(actionId || '').trim().toLowerCase()]
      if (target) void loadOptionalDialog(target).catch(() => {})
    },

    async ensureOptionalDialog(name) {
      const component = await loadOptionalDialog(name)
      if (!this.dialogComponents[name]) this.dialogComponents[name] = component
      // Concurrent hover/click callers must both wait for the component to mount.
      await this.$nextTick()
      return this.$refs[optionalDialogRefs[name]]
    },

    async callOptionalDialog(name, method, ...args) {
      try {
        const dialog = await this.ensureOptionalDialog(name)
        if (name === 'externalTools' && method === 'open' && dialog?.isOpen?.()) return
        return dialog?.[method]?.(...args)
      } catch (error) {
        console.error(`Failed to load ${name} dialog`, error)
        ElMessage.error('Unable to open dialog')
      }
    },

    openForegroundTaskDetails() {
      if (this.showCurrentTaskNotice) this.taskDialogVisible = true
    },

    startTerminalSubmission(clientId, command) {
      const id = String(clientId || '').trim()
      if (!id) return
      this.pendingTerminalSubmissions = { ...this.pendingTerminalSubmissions, [id]: { command } }
    },

    finishTerminalSubmission(clientId) {
      const id = String(clientId || '').trim()
      if (!this.pendingTerminalSubmissions[id]) return
      const next = { ...this.pendingTerminalSubmissions }
      delete next[id]
      this.pendingTerminalSubmissions = next
      this.syncForegroundTaskNotice(id, this.foregroundTasks[id] || { state: 'Idle' })
    },

    syncForegroundTaskNotice(clientId, task) {
      this.ensureOutputBucket(clientId)
      const lines = this.outputs[clientId] || []
      const existing = lines.find(line => line?.meta?.foregroundTaskNotice === true)
      const visible = shouldShowTaskNotice(task, this.activeTaskIds[clientId] || '',
        this.pendingTerminalSubmissions[clientId], this.tabId)
      const noticeKey = `${task?.task_id || ''}:${task?.command_id || ''}:${task?.started_at || ''}`
      if (visible && existing?.meta?.foregroundTaskKey === noticeKey && existing?.meta?.foregroundTaskState === task.state) return
      if (existing) {
        this.outputs[clientId] = lines.filter(line => line?.meta?.foregroundTaskNotice !== true)
      }
      if (visible) {
        this.appendOutput(clientId,
          task.state === 'Cancelling' ? '[!] Task cancellation requested.' : '[!] Client is running a task.',
          'warning', { foregroundTaskNotice: true, foregroundTaskKey: noticeKey, foregroundTaskState: task.state })
      }
    },

    applyForegroundTaskUpdate(clientId, payload) {
      const id = String(clientId || '').trim()
      if (!id) return
      // Only this client's SSE can supersede its in-flight snapshot request.
      if (id === this.selectedId) this.foregroundQuerySequence += 1
      const task = normalizeForegroundTask(payload)
      this.foregroundTasks = { ...this.foregroundTasks, [id]: task }
      // The task slot is authoritative; a missing completion event must not leave Run disabled.
      // Never clear a different task while an actual server task is still active.
      if (task.state === 'Idle' && this.activeTaskIds[id]) {
        void this.recoverFinishedTask(id, this.activeTaskIds[id])
      }
      this.syncForegroundTaskNotice(id, task)
    },

    async refreshForegroundTask() {
      const clientId = String(this.selectedId || '').trim()
      if (!clientId) return
      if (this.isCurrentConnectionOffline) {
        this.applyForegroundTaskUpdate(clientId, { state: 'Idle' })
        return
      }
      const sequence = ++this.foregroundQuerySequence
      try {
        const nextTask = normalizeForegroundTask(await getConnectionTask(clientId))
        if (this.selectedId !== clientId || sequence !== this.foregroundQuerySequence) return
        this.applyForegroundTaskUpdate(clientId, nextTask)
      } catch (_error) {
        // A temporary status request failure must not invent an Idle transition.
      }
    },

    async cancelForegroundTask() {
      const task = this.currentForegroundTask
      if (!task.can_cancel || !task.task_id || this.taskCancelSending) return
      this.taskCancelSending = true
      try {
        await cancelTask(task.task_id)
        ElMessage.success('Cancellation requested')
      } catch (error) {
        ElMessage.error(error?.message || 'Unable to cancel task')
        await this.refreshForegroundTask()
      } finally {
        this.taskCancelSending = false
      }
    },

    ...AppUtilsModule.methods,
    ...AppSseModule.methods,
    ...AppConnectionModule.methods,
    ...AppTaskModule.methods,
    ...AppTerminalModule.methods,


    saveTerminalJsonOutputFromViewer(payload = {}) {
  return this.$refs.terminalOutputRef?.saveTerminalJsonOutputFromViewer(payload)
},

    copyTerminalOutput(format = 'text') {
      return this.$refs.terminalOutputRef?.copyAllTerminalOutput(format)
    },

    saveTerminalOutputArtifact(format = 'text') {
      return this.$refs.terminalOutputRef?.saveAllTerminalOutputArtifact(format)
    },

    openArtifactDialog() {
      return this.$refs.artifactDialogRef?.open()
    },

    openScreenViewDialog() {
      return this.$refs.screenViewDialogRef?.open()
    },

    openScreenViewInNewTab() {
      const viewer = this.$refs.screenViewDialogRef
      if (!viewer || !this.selectedId || this.isCurrentConnectionOffline) return
      // Use the original viewer's tab launcher; no duplicate session/rendering logic.
      viewer.targetClientId = String(this.selectedId)
      viewer.targetLabel = viewer.buildTargetLabel()
      return viewer.openInNewTab()
    },

    openClipboardDialog(tab = 'get') {
      return this.$refs.clipboardDialogRef?.open(tab)
    },

    toggleConnectionInfo() {
      this.connectionInfoCollapsed = !this.connectionInfoCollapsed
      this.persistLayoutPreferences()
    },

    toggleDeviceSidebar() {
      this.deviceSidebarCollapsed = !this.deviceSidebarCollapsed
      this.persistLayoutPreferences()
    },

    persistLayoutPreferences() {
      saveLayoutPreferences({
        deviceSidebarCollapsed: this.deviceSidebarCollapsed,
        connectionInfoCollapsed: this.connectionInfoCollapsed,
      })
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
        this.persistLayoutPreferences()
      }
    },

    refreshArtifactsIfOpen() {
      return this.$refs.artifactDialogRef?.refreshIfOpen()
    },

    openRemoteFilesDialog() {
      this.$refs.remoteFilesDialogRef?.open()
    },

    openManagePinnedPathsDialog() {
      this.$refs.remoteFilesDialogRef?.openPinnedQuickJumpManager()
    },

    openSelectedMachineConnectionHistory() {
      if (!this.currentConnection?.machine_id) return
      return this.openMachineConnectionHistory(this.decorateConnectionForDeviceView(this.currentConnection))
    },

    openLogViewerDialog(source = {}) {
      const requested = source && typeof source === 'object' ? source : {}
      const selectedClientId = String(this.currentConnection?.client_id || '').trim()
      const targetClientId = String(requested.clientId || this.selectedId || '').trim()
      const useDefaultLog = !String(requested.path || '').trim()
        && !!selectedClientId && targetClientId === selectedClientId
        && !this.isCurrentConnectionOffline
      const logPath = useDefaultLog ? String(this.currentConnection?.client_log_path || '').trim() : ''
      this.$refs.logViewerDialogRef?.open(logPath ? { ...requested, path: logPath } : requested)
    },

    openExternalToolManagerDialog() {
      if (this.$refs.externalToolManagerDialogRef?.isOpen?.()) return
      return this.callOptionalDialog('externalTools', 'open')
    },

    async handleSseNotificationAction(action = {}, context = {}) {
      const actionType = String(action?.type || '').trim().toLowerCase()

      if (actionType === 'open_external_tools') {
        return this.callOptionalDialog('externalTools', 'openFromNotification', context)
      }

      if (actionType === 'view_external_tool_log') {
        return this.callOptionalDialog('externalTools', 'openFromNotification', context, { viewLog: true })
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

    openDocumentsDialog() {
      return this.callOptionalDialog('documents', 'open')
    },

    openKeychainManagerDialog() {
      return this.callOptionalDialog('keychains', 'open')
    },

    refreshExternalToolsIfOpen() {
      return this.$refs.externalToolManagerDialogRef?.refreshIfOpen()
    },

    openExternalToolMetaEditor(toolId) {
      return this.callOptionalDialog('preview', 'openExternalToolMetaEditor', toolId)
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
      return this.callOptionalDialog('backgroundJobs', 'open')
    },

    refreshBackgroundJobsIfOpen() {
      return this.$refs.backgroundJobsDialogRef?.refreshIfOpen()
    },

    refreshBackgroundJobModulesIfOpen() {
      return this.$refs.backgroundJobsDialogRef?.refreshModulesIfOpen()
    },

    openResultJson(payload = {}) {
      if (!payload.jsonText || String(payload.clientId || '') !== String(this.selectedId || '')) return
      this.$refs.terminalJsonDialogRef?.open({
        isJsonMessage: true,
        jsonText: payload.jsonText,
      })
    },

    openScriptLibraryDialog() {
      return this.$refs.scriptLibraryDialogRef?.open()
    },

    refreshScriptsIfOpen() {
      return this.$refs.scriptLibraryDialogRef?.refreshIfOpen()
    },

    openPtyDialog() {
      return this.callOptionalDialog('pty', 'open')
    },

    openOneLinersDialog() {
      return this.$refs.oneLinersDialogRef?.open()
    },

    openQuickActionsDialog() {
      return this.$refs.quickActionsDialogRef?.open()
    },

    runToolboxScript(scriptName) {
      return this.$refs.scriptLibraryDialogRef?.openRunForScript(scriptName)
    },

    runPinnedQuickAction(item) {
      return this.$refs.quickActionsDialogRef?.runPinnedAction(item)
    },

    runPinnedQuickActionInTerminal(item) {
      return this.$refs.quickActionsDialogRef?.runPinnedAction(item, 'terminal')
    },

    // Both Run Again and Result Action dialogs subscribe to the existing task stream.
    routeTerminalTaskCapture(kind, payload = {}) {
      return this.terminalTaskCapture.route(kind, payload)
    },

    handleQuickActionCommandResult(payload = {}) {
      return this.$refs.quickActionsDialogRef?.handleCommandResult(payload) === true
    },

    handleQuickActionCommandComplete(payload = {}) {
      return this.$refs.quickActionsDialogRef?.handleCommandComplete(payload) === true
    },

    handleScriptCommandResult(payload = {}) {
      return this.$refs.scriptLibraryDialogRef?.handleCommandResult(payload) === true
    },

    handleScriptCommandComplete(payload = {}) {
      return this.$refs.scriptLibraryDialogRef?.handleCommandComplete(payload) === true
    },

    openDeviceGroupManagerDialog() {
      return this.$refs.deviceGroupManagerDialogRef?.open()
    },

    openSettingsDialog() {
      return this.$refs.settingsDialogRef?.open()
    },

    applyTerminalContextPreferences(preferences) {
      this.$refs.commandInputBarRef?.setConnectionContextPreferences(preferences)
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

    openProcessDialog(sortBy = '') {
      if (this.currentConnection?.feature_manifest?.process_monitor === false) return
      return this.callOptionalDialog('processes', 'open', typeof sortBy === 'string' ? sortBy : '')
    },

    async loadAuthSession() {
      try {
        const sessionInfo = await getAuthSession()
        this.currentAuthUsername = String(sessionInfo?.username || '').trim()
      } catch (_error) {
        this.currentAuthUsername = ''
      }
    },

    handleAccountCommand(command) {
      if (command === 'change-password') {
        this.resetChangePasswordForm()
        this.changePasswordDialogVisible = true
        return
      }

      if (command === 'authorization-info') {
        this.openAuthorizationInfoDialog()
        return
      }

      if (command === 'sign-out') {
        window.RatAuth?.logout?.()
      }
    },

    resetChangePasswordForm() {
      this.changePasswordForm.currentPassword = ''
      this.changePasswordForm.newPassword = ''
      this.changePasswordForm.confirmPassword = ''
      this.changePasswordSubmitting = false
    },

    validateNewAdminPassword(password) {
      const value = String(password || '')
      if ([...value].length < 8) return 'Password must be at least 8 characters'
      if (!/[A-Za-z]/.test(value)) return 'Password must include at least one English letter'
      if (!/[0-9]/.test(value)) return 'Password must include at least one number'
      return ''
    },

    async submitPasswordChange() {
      if (this.changePasswordSubmitting) return

      const currentPassword = this.changePasswordForm.currentPassword
      const newPassword = this.changePasswordForm.newPassword
      const confirmPassword = this.changePasswordForm.confirmPassword

      if (!currentPassword) {
        ElMessage.warning('Enter your current password')
        return
      }

      const passwordError = this.validateNewAdminPassword(newPassword)
      if (passwordError) {
        ElMessage.warning(passwordError)
        return
      }

      if (newPassword !== confirmPassword) {
        ElMessage.warning('New passwords do not match')
        return
      }

      this.changePasswordSubmitting = true
      try {
        await changeAdminPassword(currentPassword, newPassword)
        this.changePasswordDialogVisible = false
        ElMessage.success('Password changed. Signing out...')
        window.setTimeout(() => window.location.replace('/login.html'), 450)
      } catch (error) {
        ElMessage.error(error?.message || 'Failed to change password')
      } finally {
        this.changePasswordSubmitting = false
      }
    },

    async openAuthorizationInfoDialog() {
      this.authorizationInfoDialogVisible = true
      this.authorizationInfoLoading = true
      try {
        const info = await getAuthorizationInfo()
        this.authorizationInfo = {
          username: String(info?.username || ''),
          api_token: String(info?.api_token || ''),
        }
      } catch (error) {
        this.authorizationInfoDialogVisible = false
        ElMessage.error(error?.message || 'Failed to load authorization info')
      } finally {
        this.authorizationInfoLoading = false
      }
    },

    async copyAuthorizationToken() {
      const token = String(this.authorizationInfo?.api_token || '')
      if (!token) return

      try {
        if (window.isSecureContext && navigator.clipboard?.writeText) {
          await navigator.clipboard.writeText(token)
        } else {
          const textarea = document.createElement('textarea')
          textarea.value = token
          textarea.style.position = 'fixed'
          textarea.style.opacity = '0'
          document.body.appendChild(textarea)
          textarea.select()
          const copied = document.execCommand('copy')
          document.body.removeChild(textarea)
          if (!copied) throw new Error('Copy failed')
        }
        ElMessage.success('API Token copied')
      } catch (error) {
        ElMessage.error(error?.message || 'Failed to copy API Token')
      }
    },

    async resetAuthorizationToken() {
      try {
        await ElMessageBox.confirm(
          'A new API Token will take effect immediately. Update any external clients that use the current token.',
          'Reset API Token',
          {
            type: 'warning',
            confirmButtonText: 'Reset Token',
            cancelButtonText: 'Cancel',
            confirmButtonClass: 'el-button--danger',
          },
        )
      } catch (error) {
        if (error === 'cancel' || error === 'close' || error?.message === 'cancel') return
        ElMessage.error(error?.message || 'Failed to reset API Token')
        return
      }

      this.authorizationTokenResetting = true
      try {
        const result = await resetAdminApiToken()
        const token = String(result?.api_token || '')
        if (!token) throw new Error('Server did not return the new API Token')
        this.authorizationInfo = { ...this.authorizationInfo, api_token: token }
        ElMessage.success('API Token reset')
      } catch (error) {
        ElMessage.error(error?.message || 'Failed to reset API Token')
      } finally {
        this.authorizationTokenResetting = false
      }
    },

    handleBannerUtilityCommand(command) {
      if (command === 'one-liners') return this.openOneLinersDialog()
      if (command === 'build-agent') return this.openAgentBuilderDialog()
      if (command === 'listeners') return this.$refs.listenerManagerDialogRef?.open()
      if (command === 'settings') return this.openSettingsDialog()
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
      return this.callOptionalDialog('preview', 'previewRemoteEntry', row)
    },

    editRemoteFile(row) {
      return this.callOptionalDialog('preview', 'editRemoteEntry', row)
    },

    previewArtifact(row) {
      return this.callOptionalDialog('preview', 'previewArtifact', row)
    },

    previewBackgroundJobFile(file) {
      return this.callOptionalDialog('preview', 'previewBackgroundJobFile', file)
    },

    openNewRemoteScriptEditor(scriptName = 'new_script.py') {
      return this.callOptionalDialog('preview', 'openNewRemoteScriptEditor', scriptName)
    },

    openRemoteScriptEditorInternal(scriptName) {
      return this.callOptionalDialog('preview', 'openRemoteScriptEditorInternal', scriptName)
    },

    openNewRemoteJobEditor(scriptName = 'new_job.py') {
      return this.callOptionalDialog('preview', 'openNewRemoteJobEditor', scriptName)
    },

    openNewSharedFileEditor(filename = 'new_file.txt') {
      return this.callOptionalDialog('preview', 'openNewSharedFileEditor', filename)
    },

    openRemoteJobEditor(scriptName) {
      return this.callOptionalDialog('preview', 'openRemoteJobEditor', scriptName)
    },

    openMachineConnectionHistory(item) {
      return this.$refs.machineConnectionHistoryDialogRef?.open(item)
    },

    openCommandHistoryDialog() {
      return this.callOptionalDialog('commandHistory', 'open')
    },

    async runTerminalJsonResultAction(payload = {}) {
      const inDialog = payload.presentation === 'dialog'
      const viewer = this.$refs.terminalJsonDialogRef
      const capture = inDialog ? this.terminalTaskCapture.begin({
        clientId: payload.clientId,
        command: payload.command,
        suppress: true,
        onResult: event => viewer?.handleResultActionCommandResult(event, payload.runId),
        onComplete: event => viewer?.handleResultActionCommandComplete(event, payload.runId),
      }) : null
      const taskId = await this.$refs.commandInputBarRef?.runResultActionCommand(
        payload.command, payload.clientId, payload.presentation,
      ) || ''
      if (!taskId) capture?.cancel()
      else capture?.bind(taskId)
      payload.onDone?.(!!taskId)
      return !!taskId
    },

    async runTerminalJsonAgain(payload = {}) {
      const viewer = this.$refs.terminalJsonDialogRef
      const capture = this.terminalTaskCapture.begin({
        clientId: payload.clientId,
        command: payload.type === 'script' ? '' : payload.command,
        onResult: event => viewer?.handleJsonRefreshResult(event, payload.runId),
        onComplete: event => viewer?.handleJsonRefreshComplete(event, payload.runId),
      })
      const taskId = payload.type === 'script'
        ? await this.$refs.scriptLibraryDialogRef?.runScriptFromTerminalBlock(payload)
        : await this.$refs.commandInputBarRef?.runJsonViewerRefreshCommand(payload.command, payload.clientId)
      if (!taskId) capture.cancel()
      else capture.bind(taskId)
      payload.onDone?.(!!taskId)
      return !!taskId
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
      this.loadAuthSession(),
      this.loadSseNotificationPreferences(),
      this.loadSseNotificationHistory(),
      this.loadTransferItems(),
    ])
    this.initSSE()
    // Start code-only warmup after first paint; dialogs/PTY sockets are not mounted.
    this.cancelIdleWarmup = scheduleIdleWarmup([
      () => loadOptionalDialog('externalTools'),
      () => loadOptionalDialog('commandHistory'),
      () => loadOptionalDialog('pty'),
      () => loadOptionalDialog('backgroundJobs'),
      () => loadOptionalDialog('processes'),
      () => loadOptionalDialog('keychains'),
      () => loadOptionalDialog('preview'),
      () => loadOptionalDialog('documents'),
    ])
    this.statusTickTimer = setInterval(() => {
      const now = Date.now()
      // Keep task duration responsive without any network polling. Other
      // connection ages only need their previous 30-second refresh cadence.
      if (this.currentForegroundTask.state !== 'Idle' || now - this.statusNowTick >= 30 * 1000) {
        this.statusNowTick = now
      }
    }, 2000)
  },

  beforeUnmount() {
    this.cancelIdleWarmup?.()
    this.foregroundQuerySequence += 1
    if (this.eventSource) this.eventSource.close()

    if (this.statusTickTimer) {
      clearInterval(this.statusTickTimer)
      this.statusTickTimer = null
    }
  },
}
</script>

<style scoped>

/* Banner actions share Element Plus icon sizing without affecting other toolbars. */
.banner-right .banner-actions {
  gap: 14px;
}

.banner-right .banner-action-links {
  gap: 8px;
}

.banner-major-separator {
  height: 24px;
  background: rgba(255, 255, 255, 0.22);
}

.banner-icon-action {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 32px;
  padding: 0;
  margin: 0;
  border: 0;
  background: transparent;
  color: rgba(238, 244, 255, 0.82);
  font-size: 16px;
  line-height: 1;
  cursor: pointer;
  transition: color 0.18s ease, opacity 0.18s ease;
}

.banner-icon-action:hover {
  color: #ffffff;
}

.banner-icon-action:active {
  opacity: 0.72;
}

.banner-account-action {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.banner-account-action > span {
  max-width: 160px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.banner-account-chevron {
  font-size: 11px;
  opacity: 0.72;
}

.account-dialog-hint {
  margin-top: 4px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.5;
}

.authorization-info {
  min-height: 88px;
}

.authorization-info-row {
  display: grid;
  gap: 8px;
  margin-bottom: 16px;
}

.authorization-info-label {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  font-weight: 650;
}

.authorization-info-value {
  color: var(--el-text-color-primary);
  font-size: 14px;
}

.authorization-token-input :deep(.el-input__inner) {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}

.authorization-token-control {
  display: flex;
  align-items: stretch;
  gap: 8px;
  min-width: 0;
}

.authorization-token-control .authorization-token-input {
  flex: 1 1 auto;
  min-width: 0;
}

.authorization-token-control > .el-button + .el-button {
  margin-left: 0;
}

.banner-transfer-count {
  position: absolute;
  top: 0;
  right: -6px;
  min-width: 12px;
  font-size: 10px;
  font-weight: 700;
  line-height: 1;
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
<style scoped>
.task-detail-grid { display: grid; grid-template-columns: 110px minmax(0, 1fr); gap: 10px 12px; font-size: 13px; }
.task-detail-label { color: var(--muted); }
.task-detail-value { overflow-wrap: anywhere; }
@media (max-width: 520px) { .task-detail-grid { grid-template-columns: 1fr; gap: 4px; } }
</style>
