<template>
  <el-dialog
    v-model="visible"
    title="External Tool Manager"
    width="1240px"
    top="5vh"
    class="fixed-dialog external-tool-dialog"
    modal-class="external-tool-overlay"
    @closed="handleClosed"
  >
    <div class="fixed-dialog-body external-tool-body" v-loading="loading">
      <div class="external-tool-toolbar">
        <div class="external-tool-toolbar-left">
          <el-button size="small" :loading="loading" @click="refreshAll">
            Refresh
          </el-button>

          <div class="external-tool-target-control">
            <el-select
              v-model="deviceFilter"
              size="small"
              filterable
              class="external-tool-target-select"
              placeholder="Select target"
              @change="handleTargetFilterChange"
            >
              <el-option
                v-for="item in deviceFilterOptions"
                :key="item.value"
                :label="item.label"
                :value="item.value"
              />
            </el-select>
          </div>

          <el-checkbox
            v-if="activeTab === 'modules'"
            v-model="packageOnlyCompatible"
            size="small"
            @change="handlePackageOnlyCompatibleChange"
          >
            Only compatible
          </el-checkbox>
        </div>

        <div class="external-tool-toolbar-right">
          <el-input
            v-model="searchText"
            size="small"
            clearable
            class="external-tool-search"
            :placeholder="activeTab === 'modules' ? 'Search modules/packages' : 'Search instances'"
          />
        </div>
      </div>

      <el-tabs v-model="activeTab" class="external-tool-tabs">
        <el-tab-pane label="Packages" name="modules">
          <ExternalToolPackagesPanel
            :filtered-modules="filteredModules"
            :selected-package="selectedPackage"
            :search-text="searchText"
            :get-package-modules="getPackageModules"
            :get-module-install-status="getModuleInstallStatus"
            :format-platforms="formatPlatforms"
            :format-version-label="formatVersionLabel"
            :can-install-package-action="canInstallPackageAction"
            :get-install-menu-label="getInstallMenuLabel"
            :can-use-package-action="canUsePackageAction"
            :can-uninstall-package-action="canUninstallPackageAction"
            :get-uninstall-menu-label="getUninstallMenuLabel"
            :can-run-module-action="canRunModuleAction"
            @select="selectPackage"
            @install="installOnly"
            @more="handlePackageMoreCommand"
            @run="openStartDialog"
          />
        </el-tab-pane>
        <el-tab-pane label="Instances" name="instances">
          <ExternalToolInstancesPanel
            :filtered-instances="filteredInstances"
            :active-device-filter-label="activeDeviceFilterLabel"
            :search-text="searchText"
            :device-filter="deviceFilter"
            :status-tag-type="statusTagType"
            :format-port-info="formatPortInfo"
            :short-time="shortTime"
            :can-restart-instance="canRestartInstance"
            :can-modify-stopped-instance-files="canModifyStoppedInstanceFiles"
            @logs="openInstanceLogs"
            @stop="stopInstance"
            @more="handleInstanceMoreCommand"
          />
        </el-tab-pane>
      </el-tabs>
    </div>
  </el-dialog>

  <ExternalToolRunDialog
    ref="runDialogRef"
    :execute-run="executeRun"
    :get-tab-scoped-headers="getTabScopedHeaders"
    @show-detail="showDetailDialog"
    @show-result="openOneshotResultDialog"
    @append-output="forwardAppendOutput"
    @set-active-task="forwardSetActiveTask"
    @upload-started="forwardRemoteUploadStarted"
  />
  <ExternalToolResultDialog ref="resultDialogRef" />
  <ExternalToolDetailDialog ref="detailDialogRef" />
</template>

<script>
import { ElMessage } from 'element-plus'
import ExternalToolPackagesPanel from './ExternalToolPackagesPanel.vue'
import ExternalToolInstancesPanel from './ExternalToolInstancesPanel.vue'
import ExternalToolRunDialog from './ExternalToolRunDialog.vue'
import ExternalToolResultDialog from './ExternalToolResultDialog.vue'
import ExternalToolDetailDialog from './ExternalToolDetailDialog.vue'
import useExternalToolTarget from '../composables/useExternalToolTarget.js'
import useExternalToolCatalog from '../composables/useExternalToolCatalog.js'
import useExternalToolInstances from '../composables/useExternalToolInstances.js'

export default {
  name: 'ExternalToolManagerDialog',
  components: { ExternalToolPackagesPanel, ExternalToolInstancesPanel, ExternalToolRunDialog, ExternalToolResultDialog, ExternalToolDetailDialog },
  mixins: [useExternalToolTarget, useExternalToolCatalog, useExternalToolInstances],
  props: {
    selectedId: {
      type: [String, Number],
      default: '',
    },

    currentConnection: {
      type: Object,
      default: null,
    },

    connections: {
      type: Array,
      default: () => [],
    },

    machineAliasMap: {
      type: Object,
      default: () => ({}),
    },

    getTabScopedHeaders: {
      type: Function,
      default: null,
    },
  },
  emits: ['append-output', 'set-active-task', 'upload-started', 'open-tool-meta-editor', 'open-log-viewer'],
  data() {
    return {
      visible: false,
      loading: false,
      activeTab: 'modules',
      searchText: '',
    }
  },
  watch: {
    async selectedId() {
      if (!this.visible) return
      this.deviceFilter = this.defaultTargetValue()
      await this.refreshInstallStatuses(false)
      await this.refreshInstances(false)
    },
  },
  methods: {
    async open() {
      this.deviceFilter = this.defaultTargetValue()
      this.visible = true
      await this.refreshAll()
    },

    isOpen() {
      return this.visible
    },

    async openFromNotification(context = {}, options = {}) {
      const clientId = this.normalizeDeviceId(context?.client_id || '')
      const machineId = clientId ? this.getMachineIdForConnectionId(clientId) : ''
      const toolId = String(context?.tool_id || context?.module_id || '').trim()
      const packageId = String(context?.package_id || '').trim()
      const instanceId = String(context?.instance_id || '').trim()
      const viewLog = options?.viewLog === true
      const wasOpen = this.visible

      if (machineId) this.deviceFilter = machineId
      if (!wasOpen) {
        this.visible = true
        await this.refreshAll()
      } else if (machineId) {
        await this.refreshInstallStatuses(false)
        await this.refreshInstances(false)
      }

      const module = toolId
        ? (this.allModules || []).find(item => String(item?.id || '').trim() === toolId)
        : null
      const pkg = packageId
        ? this.getPackageById(packageId)
        : (module ? this.getPackageForModule(module) : null)

      if (pkg?.id) this.selectedPackageId = pkg.id
      this.activeTab = (instanceId || viewLog) ? 'instances' : 'modules'

      if (!viewLog) return

      if (clientId && toolId && instanceId && module) {
        await this.loadClientInstances(toolId, clientId, false)
        const rawRows = this.clientInstances?.[clientId]?.[toolId] || []
        const rawRow = rawRows.find(row => String(row?.instance_id || 'default') === instanceId)
        if (rawRow) {
          this.openInstanceLogs(this.normalizeInstanceRow(module, rawRow, clientId))
          return
        }
      }

      this.showNotificationErrorLog(context)
    },

    showNotificationErrorLog(context = {}) {
      const displayName = String(context?.display_name || context?.tool_id || context?.package_id || 'External Tool').trim()
      const errorText = String(context?.error || 'No error text available.').trim()
      const logExcerpt = String(context?.log_excerpt || '').trim()
      const operation = String(context?.operation || context?.action || '').trim()
      const state = String(context?.state || '').trim()
      const deviceId = this.normalizeDeviceId(context?.client_id || '')
      const machineId = deviceId ? this.getMachineIdForConnectionId(deviceId) : ''

      this.showDetailDialog({
        title: `${displayName} Error Log`,
        subtitle: [this.getMachineLabel(machineId, deviceId), operation, state].filter(Boolean).join(' / '),
        copyText: logExcerpt || errorText,
        sections: [
          {
            title: 'Error',
            rows: [
              { label: 'Operation', value: operation || '-', mono: true },
              { label: 'State', value: state || '-', mono: true },
              { label: 'Error', value: errorText, mono: true, multiline: true },
              ...(logExcerpt ? [{ label: 'Log excerpt', value: logExcerpt, mono: true, multiline: true }] : []),
            ],
          },
        ],
      })
    },

    async refreshIfOpen() {
      if (!this.visible) return
      await this.refreshAll()
    },

    handleClosed() {
      if (!this.visible) this.$refs.runDialogRef?.resetStartDialog()
    },

    refreshAll() {
      // Lifecycle SSE and the Refresh button may arrive during the same fetch.
      if (this._refreshAllPromise) return this._refreshAllPromise
      this.loading = true
      const pending = (async () => {
        try {
          await this.loadCatalog(false)
          await this.refreshInstallStatuses(false)
          await this.refreshInstances(false)
        } catch (e) {
          ElMessage.error(e.message || 'Failed to refresh external tools')
        } finally {
          this.loading = false
        }
      })()
      this._refreshAllPromise = pending
      pending.then(() => {
        if (this._refreshAllPromise === pending) this._refreshAllPromise = null
      })
      return pending
    },

    async handleTargetFilterChange() {
      await this.refreshInstallStatuses(false)
      await this.refreshInstances(false)
    },

    async handlePackageOnlyCompatibleChange() {
      await this.refreshInstallStatuses(false)
    },

    openStartDialog(item) {
      const clientId = this.normalizeDeviceId(this.getActionDeviceId(this.getPackageForModule(item)))
      if (!clientId) {
        ElMessage.warning('Please select a target machine')
        return
      }
      this.$refs.runDialogRef?.open(item, {
        clientId,
        machineId: this.selectedTargetMachineId,
        label: this.activeDeviceFilterLabel,
        platform: this.getPlatformForConnectionId(clientId),
        arch: this.getArchForConnectionId(clientId),
      })
    },

    async executeRun(item, params, target, launcherOverride) {
      if (this.isOneshotModule(item)) {
        return this.runClientOneshot(item, params, target.clientId, launcherOverride)
      }
      return this.startClientInstance(item, params, '', false, target.clientId, launcherOverride)
    },

    showDetailDialog(payload) {
      this.$refs.detailDialogRef?.showDetailDialog(payload)
    },

    openOneshotResultDialog(item, result) {
      this.$refs.resultDialogRef?.openOneshotResultDialog(item, result)
    },

    loadRemoteFilePickerDirectory(path = '') {
      return this.$refs.runDialogRef?.loadRemoteFilePickerDirectory(path)
    },

    forwardAppendOutput(clientId, line, kind, meta) {
      this.$emit('append-output', clientId, line, kind, meta)
    },

    forwardSetActiveTask(clientId, taskId, cancelPolicy = '', historyEntryId = '', operationId = '') {
      this.$emit('set-active-task', clientId, taskId, cancelPolicy, historyEntryId, operationId)
    },

    forwardRemoteUploadStarted(payload) {
      this.$emit('upload-started', payload)
    },
  },
}
</script>

<style scoped>
.external-tool-body {
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
  overflow: hidden;
}

.external-tool-toolbar {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 10px;
  align-items: center;
  flex: 0 0 auto;
}

.external-tool-toolbar-left,
.external-tool-toolbar-right {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.external-tool-toolbar-left {
  flex-wrap: wrap;
}

.external-tool-toolbar-right {
  justify-content: flex-end;
}

.external-tool-toolbar :deep(.el-button) {
  height: 32px;
  min-height: 32px;
  padding-inline: 12px;
  border-radius: 10px;
  margin: 0;
}

.external-tool-toolbar :deep(.el-button + .el-button) {
  margin-left: 0;
}

.external-tool-toolbar :deep(.el-input__wrapper),
.external-tool-toolbar :deep(.el-select__wrapper) {
  min-height: 32px;
  height: 32px;
  border-radius: 10px;
  font-size: 12px;
}

.external-tool-target-control {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0;
  border: 0;
  border-radius: 0;
  background: transparent;
}

.external-tool-target-select {
  width: 320px;
}

.external-tool-search {
  width: 280px;
}

.external-tool-tabs {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.external-tool-tabs :deep(.el-tabs__header) {
  flex: 0 0 auto;
  margin-bottom: 12px;
}

.external-tool-tabs :deep(.el-tabs__content) {
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
}

.external-tool-tabs :deep(.el-tab-pane) {
  height: 100%;
  min-height: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

@media (max-width: 960px) {
.external-tool-toolbar {
    grid-template-columns: 1fr;
  }

.external-tool-toolbar-left,
.external-tool-toolbar-right {
    width: 100%;
  }

.external-tool-toolbar-right {
    justify-content: flex-start;
  }

.external-tool-search {
    width: 100%;
  }
}

@media (max-width: 640px) {
.external-tool-toolbar-left {
    align-items: stretch;
  }

.external-tool-toolbar-left > .el-button,
.external-tool-target-control,
.external-tool-target-select,
.external-tool-toolbar-left :deep(.el-checkbox),
.external-tool-toolbar-right,
.external-tool-search {
    width: 100%;
    min-width: 0;
  }
}
</style>

<style>
/* ExternalToolManagerDialog: 固定桌面高度，移动端全屏，只让表格/卡片区域滚动。 */
.external-tool-overlay .el-overlay-dialog {
  overflow: hidden !important;
}

.external-tool-overlay .el-dialog {
  height: 78vh !important;
  max-height: 78vh !important;
  margin-top: 5vh !important;
  display: flex !important;
  flex-direction: column !important;
  overflow: hidden !important;
}

.external-tool-overlay .el-dialog__header {
  flex: 0 0 auto !important;
}

.external-tool-overlay .el-dialog__body {
  flex: 1 1 auto !important;
  min-height: 0 !important;
  overflow: hidden !important;
  padding-top: 12px !important;
  padding-bottom: 12px !important;
}

.external-tool-overlay .fixed-dialog-body {
  height: 100% !important;
  min-height: 0 !important;
  overflow: hidden !important;
  display: flex !important;
  flex-direction: column !important;
}

.external-tool-overlay .external-tool-instance-table-shell {
  flex: 0 0 auto !important;
  min-height: 0 !important;
  height: 560px !important;
  max-height: 560px !important;
  overflow: hidden !important;
}

.external-tool-overlay .external-tool-instance-table,
.external-tool-overlay .external-tool-instance-table .el-table__inner-wrapper,
.external-tool-overlay .external-tool-instance-table .el-scrollbar,
.external-tool-overlay .external-tool-instance-table .el-scrollbar__wrap {
  height: 100% !important;
}

.external-tool-overlay .external-tool-instance-table .el-scrollbar__wrap {
  overflow-y: auto !important;
  overflow-x: auto !important;
}

.external-tool-info-overlay .el-overlay-dialog {
  overflow: auto !important;
}

.external-tool-info-overlay .external-tool-info-dialog {
  margin-top: 6vh !important;
  max-height: 86vh !important;
  display: flex !important;
  flex-direction: column !important;
}

.external-tool-info-overlay .external-tool-info-dialog .el-dialog__header,
.external-tool-info-overlay .external-tool-info-dialog .el-dialog__footer {
  flex: 0 0 auto !important;
}

.external-tool-info-overlay .external-tool-info-dialog .el-dialog__body {
  flex: 1 1 auto !important;
  min-height: 0 !important;
  overflow: auto !important;
  padding-top: 12px !important;
}

@media (max-width: 768px) {
  .external-tool-overlay .el-dialog {
    width: 100vw !important;
    max-width: 100vw !important;
    height: 100dvh !important;
    max-height: 100dvh !important;
    margin: 0 !important;
    border-radius: 0 !important;
  }

  .external-tool-overlay .el-dialog__header {
    padding: 14px 16px 10px !important;
  }

  .external-tool-overlay .el-dialog__body {
    padding: 10px 12px 12px !important;
  }

  .external-tool-overlay .external-tool-instance-table-shell {
    display: none !important;
  }

  .external-tool-overlay .external-tool-instance-card-shell {
    display: flex !important;
    flex: 1 1 auto !important;
    min-height: 0 !important;
    overflow: hidden !important;
  }

  .external-tool-overlay .external-tool-instance-card-list {
    display: grid !important;
    height: 100% !important;
    min-height: 0 !important;
    overflow-y: auto !important;
  }

  .external-tool-info-overlay .external-tool-info-dialog {
    width: 100vw !important;
    max-width: 100vw !important;
    height: 100dvh !important;
    max-height: 100dvh !important;
    margin: 0 !important;
    border-radius: 0 !important;
  }

  .external-tool-info-overlay .external-tool-info-dialog .el-dialog__header {
    padding: 14px 16px 10px !important;
  }

  .external-tool-info-overlay .external-tool-info-dialog .el-dialog__body {
    padding: 10px 16px 12px !important;
  }

  .external-tool-info-overlay .external-tool-info-dialog .el-dialog__footer {
    padding: 10px 16px 14px !important;
  }
}
</style>
