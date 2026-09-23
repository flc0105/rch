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
          <div v-if="filteredModules.length" class="external-tool-package-split">
            <div class="external-tool-package-list-panel">
              <div class="external-tool-package-list">
                <div
                  v-for="item in filteredModules"
                  :key="item.id"
                  class="external-tool-card external-tool-package-list-card"
                  :class="{ active: selectedPackage?.id === item.id }"
                  @click="selectPackage(item)"
                >
                  <div class="external-tool-card-main">
                    <div class="external-tool-package-list-title" :title="item.display_name || item.id">
                      {{ item.display_name || item.id }}
                    </div>
                    <div class="external-tool-package-list-status">
                      <el-tag
                        v-if="getModuleInstallStatus(item).label"
                        size="small"
                        :type="getModuleInstallStatus(item).type"
                        effect="plain"
                      >
                        {{ getModuleInstallStatus(item).label }}
                      </el-tag>
                      <span v-else class="muted small-text">Unknown</span>
                      <template v-if="selectedPackage?.id === item.id">
                        <el-tag size="small" type="info" class="external-tool-package-list-mobile-meta-tag">
                          {{ formatPlatforms(item.platforms) }}
                        </el-tag>
                        <el-tag
                          v-if="item.version"
                          size="small"
                          type="info"
                          class="external-tool-package-list-mobile-meta-tag"
                        >
                          {{ formatVersionLabel(item.version) }}
                        </el-tag>
                      </template>
                    </div>
                    <div class="external-tool-package-list-desc" :title="item.description || ''">
                      {{ item.description || 'No description' }}
                    </div>

                    <div
                      v-if="selectedPackage?.id === item.id"
                      class="external-tool-package-mobile-detail"
                      @click.stop
                    >
                      <div class="external-tool-package-mobile-actions">
                        <el-button
                          class="external-tool-package-mobile-action-button"
                          size="small"
                          type="primary"
                          plain
                          :disabled="!canInstallPackageAction(item)"
                          @click.stop="installOnly(item)"
                        >
                          {{ getInstallMenuLabel(item) }}
                        </el-button>

                        <el-dropdown
                          trigger="click"
                          size="small"
                          @command="handlePackageMoreCommand($event, item)"
                        >
                          <el-button
                            class="external-tool-package-mobile-action-button"
                            size="small"
                            plain
                            @click.stop
                          >
                            More
                          </el-button>
                          <template #dropdown>
                            <el-dropdown-menu>
                              <el-dropdown-item command="download">
                                Download Zip
                              </el-dropdown-item>
                              <el-dropdown-item command="edit">
                                Edit Metadata
                              </el-dropdown-item>
                              <el-dropdown-item divided command="status" :disabled="!canUsePackageAction(item)">
                                Install Status
                              </el-dropdown-item>
                              <el-dropdown-item command="copy" :disabled="!canUsePackageAction(item)">
                                Copy Command
                              </el-dropdown-item>
                              <el-dropdown-item
                                command="clear_cache"
                                divided
                                :disabled="!canUsePackageAction(item)"
                              >
                                Clear Package Cache
                              </el-dropdown-item>
                              <el-dropdown-item
                                command="uninstall"
                                :disabled="!canUninstallPackageAction(item)"
                              >
                                {{ getUninstallMenuLabel(item) }}
                              </el-dropdown-item>
                            </el-dropdown-menu>
                          </template>
                        </el-dropdown>
                      </div>

                      <div class="external-tool-modules-panel external-tool-package-mobile-modules">
                        <div class="external-tool-detail-section-title">Modules</div>
                        <div v-if="getPackageModules(item).length" class="external-tool-package-modules detail">
                          <div
                            v-for="module in getPackageModules(item)"
                            :key="module.id"
                            class="external-tool-package-module-card"
                          >
                            <div class="external-tool-package-module-content">
                              <div class="external-tool-package-module-title-row">
                                <span class="strong">{{ module.display_name || module.id }}</span>
                                <el-tag size="small" :type="getExecutionTagType(module)">{{ formatExecutionLabel(module) }}</el-tag>
                              </div>
                              <div class="external-tool-package-module-desc" :title="module.description || ''">
                                {{ module.description || 'No description' }}
                              </div>
                            </div>
                            <el-button
                              size="small"
                              type="primary"
                              plain
                              :disabled="!canRunModuleAction(module)"
                              @click.stop="openStartDialog(module, 'run')"
                            >
                              {{ getRunButtonLabel(module) }}
                            </el-button>
                          </div>
                        </div>
                        <div v-else class="external-tool-empty small">
                          No runnable modules.
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <div class="external-tool-package-detail-panel">
              <div v-if="selectedPackage" class="external-tool-package-detail-card">
                <div class="external-tool-package-detail-header">
                  <div class="external-tool-package-detail-main">
                    <div class="external-tool-title large" :title="selectedPackage.display_name || selectedPackage.id">
                      {{ selectedPackage.display_name || selectedPackage.id }}
                    </div>
                    <div class="external-tool-package-detail-tags">
                      <el-tag size="small" type="info">
                        {{ formatPlatforms(selectedPackage.platforms) }}
                      </el-tag>
                      <el-tag v-if="selectedPackage.version" size="small" type="info">
                        {{ formatVersionLabel(selectedPackage.version) }}
                      </el-tag>
                      <el-tag
                        v-if="getModuleInstallStatus(selectedPackage).label"
                        size="small"
                        :type="getModuleInstallStatus(selectedPackage).type"
                        effect="plain"
                      >
                        {{ getModuleInstallStatus(selectedPackage).label }}
                      </el-tag>
                    </div>
                    <div class="external-tool-desc external-tool-package-detail-desc" :title="selectedPackage.description || ''">
                      {{ selectedPackage.description || 'No description' }}
                    </div>
                  </div>

                  <div class="external-tool-package-detail-actions">
                    <div class="external-tool-package-detail-action-row">
                      <el-button
                        class="external-tool-package-detail-action-button"
                        size="small"
                        type="primary"
                        plain
                        :disabled="!canInstallPackageAction(selectedPackage)"
                        @click="installOnly(selectedPackage)"
                      >
                        {{ getInstallMenuLabel(selectedPackage) }}
                      </el-button>

                      <el-dropdown
                        trigger="click"
                        size="small"
                        @command="handlePackageMoreCommand($event, selectedPackage)"
                      >
                        <el-button class="external-tool-package-detail-action-button" size="small" plain>
                          More
                        </el-button>
                        <template #dropdown>
                          <el-dropdown-menu>
                            <el-dropdown-item command="download">
                              Download Zip
                            </el-dropdown-item>
                            <el-dropdown-item command="edit">
                              Edit Metadata
                            </el-dropdown-item>
                            <el-dropdown-item divided command="status" :disabled="!canUsePackageAction(selectedPackage)">
                              Install Status
                            </el-dropdown-item>
                            <el-dropdown-item command="copy" :disabled="!canUsePackageAction(selectedPackage)">
                              Copy Command
                            </el-dropdown-item>
                            <el-dropdown-item
                              command="clear_cache"
                              divided
                              :disabled="!canUsePackageAction(selectedPackage)"
                            >
                              Clear Package Cache
                            </el-dropdown-item>
                            <el-dropdown-item
                              command="uninstall"
                              :disabled="!canUninstallPackageAction(selectedPackage)"
                            >
                              {{ getUninstallMenuLabel(selectedPackage) }}
                            </el-dropdown-item>
                          </el-dropdown-menu>
                        </template>
                      </el-dropdown>
                    </div>
                  </div>
                </div>

                <div class="external-tool-package-detail-section external-tool-modules-panel">
                  <div class="external-tool-detail-section-title">Modules</div>
                  <div v-if="getPackageModules(selectedPackage).length" class="external-tool-package-modules detail">
                    <div
                      v-for="module in getPackageModules(selectedPackage)"
                      :key="module.id"
                      class="external-tool-package-module-card"
                    >
                      <div class="external-tool-package-module-content">
                        <div class="external-tool-package-module-title-row">
                          <span class="strong">{{ module.display_name || module.id }}</span>
                          <el-tag size="small" :type="getExecutionTagType(module)">{{ formatExecutionLabel(module) }}</el-tag>
                        </div>
                        <div class="external-tool-package-module-desc" :title="module.description || ''">
                          {{ module.description || 'No description' }}
                        </div>
                      </div>
                      <el-button
                        size="small"
                        type="primary"
                        plain
                        :disabled="!canRunModuleAction(module)"
                        @click="openStartDialog(module, 'run')"
                      >
                        {{ getRunButtonLabel(module) }}
                      </el-button>
                    </div>
                  </div>
                  <div v-else class="external-tool-empty small">
                    No runnable modules.
                  </div>
                </div>
              </div>
              <div v-else class="external-tool-empty">
                Select a package.
              </div>
            </div>
          </div>

          <div v-else class="external-tool-empty">
            {{ searchText ? 'No matching external tool packages' : 'No external tool meta files found' }}
          </div>
        </el-tab-pane>

        <el-tab-pane label="Instances" name="instances">
          <div class="external-tool-instance-toolbar">
            <div class="external-tool-hint">
              Target: {{ activeDeviceFilterLabel }}.
            </div>
          </div>

          <div v-if="filteredInstances.length" class="external-tool-instance-table-shell">
            <el-table
              :data="filteredInstances"
              size="small"
              class="external-tool-instance-table"
              height="560"
              row-key="row_key"
            >
<!--            <el-table-column label="Target" min-width="190">-->
<!--              <template #default="{ row }">-->
<!--                <div class="mono strong" :title="row.machine_id || row.device_id">{{ row.machine_label || '-' }}</div>-->
<!--&lt;!&ndash;                <div class="muted mono" :title="row.connection_id || row.device_id">&ndash;&gt;-->
<!--&lt;!&ndash;                  {{ row.connection_id ? `conn: ${shortenDeviceId(row.connection_id)}` : '-' }}&ndash;&gt;-->
<!--&lt;!&ndash;                </div>&ndash;&gt;-->
<!--              </template>-->
<!--            </el-table-column>-->


              <el-table-column label="Instance" min-width="170">
                <template #default="{ row }">
                  <div class="mono strong" :title="row.instance_id">{{ row.instance_id }}</div>
                  <div class="muted mono" :title="row.tool_id">{{ row.tool_id }}</div>
                </template>
              </el-table-column>

              <el-table-column label="Status" width="110">
                <template #default="{ row }">
                  <el-tag size="small" :type="statusTagType(row.status)">
                    {{ row.status || '-' }}
                  </el-tag>
                </template>
              </el-table-column>



              <el-table-column label="PID" width="95">
                <template #default="{ row }">
                  <span class="mono">{{ row.pid || '-' }}</span>
                </template>
              </el-table-column>

              <el-table-column label="Port" min-width="210">
                <template #default="{ row }">
                  <span class="mono" :title="formatPortInfo(row)">{{ formatPortInfo(row) }}</span>
                </template>
              </el-table-column>

              <el-table-column label="Started" width="180">
                <template #default="{ row }">
                  <span class="mono muted">{{ shortTime(row.started_at) }}</span>
                </template>
              </el-table-column>

              <el-table-column label="Actions" width="240">
                <template #default="{ row }">
                  <div class="external-tool-table-actions">
                    <el-button size="small" plain @click="openInstanceLogs(row)">
                      Logs
                    </el-button>
<!--                  <el-button size="small" plain @click="openInstanceInfo(row)">-->
<!--                    Info-->
<!--                  </el-button>-->
                    <el-button
                      size="small"
                      type="danger"
                      plain
                      :disabled="!row.running && row.status !== 'stale'"
                      @click="stopInstance(row)"
                    >
                      Stop
                    </el-button>
                    <el-dropdown
                      trigger="click"
                      size="small"
                      @command="handleInstanceMoreCommand($event, row)"
                    >
                      <el-button size="small" plain>
                        More
                      </el-button>
                      <template #dropdown>
                        <el-dropdown-menu>
                          <el-dropdown-item command="info">
                            Info
                          </el-dropdown-item>


                          <el-dropdown-item command="restart" :disabled="!canRestartInstance(row)">
                            Restart
                          </el-dropdown-item>
                          <el-dropdown-item command="clear_logs" :disabled="!canModifyStoppedInstanceFiles(row)">
                            Clear Logs
                          </el-dropdown-item>
                          <el-dropdown-item command="remove" :disabled="!canModifyStoppedInstanceFiles(row)">
                            Remove
                          </el-dropdown-item>
                        </el-dropdown-menu>
                      </template>
                    </el-dropdown>
                  </div>
                </template>
              </el-table-column>
            </el-table>
          </div>

          <div v-if="filteredInstances.length" class="external-tool-instance-card-shell">
            <div class="external-tool-instance-card-list">
              <div
                v-for="row in filteredInstances"
                :key="row.row_key"
                class="external-tool-instance-card"
              >
                <div class="external-tool-instance-card-top">
                  <div class="external-tool-instance-icon">
                    <span :class="{ running: row.running, stale: row.status === 'stale' }"></span>
                  </div>

                  <div class="external-tool-instance-card-main">
                    <div class="external-tool-instance-name" :title="row.instance_id">
                      {{ row.instance_id }}
                    </div>

                    <div class="external-tool-instance-tags">
                      <el-tag size="small" :type="statusTagType(row.status)">
                        {{ row.status || '-' }}
                      </el-tag>
                      <el-tag size="small" type="info">
                        {{ row.display_name || row.tool_id }}
                      </el-tag>
                    </div>

                    <div class="external-tool-instance-meta">
                      <div class="external-tool-instance-meta-item">
                        <div class="external-tool-instance-meta-label">Tool</div>
                        <div class="external-tool-instance-meta-value mono" :title="row.tool_id">
                          {{ row.tool_id || '-' }}
                        </div>
                      </div>

                      <div class="external-tool-instance-meta-item">
                        <div class="external-tool-instance-meta-label">PID</div>
                        <div class="external-tool-instance-meta-value mono">
                          {{ row.pid || '-' }}
                        </div>
                      </div>

                      <div class="external-tool-instance-meta-item">
                        <div class="external-tool-instance-meta-label">Port</div>
                        <div class="external-tool-instance-meta-value mono" :title="formatPortInfo(row)">
                          {{ formatPortInfo(row) }}
                        </div>
                      </div>

                      <div class="external-tool-instance-meta-item">
                        <div class="external-tool-instance-meta-label">Started</div>
                        <div class="external-tool-instance-meta-value mono">
                          {{ shortTime(row.started_at) }}
                        </div>
                      </div>
                    </div>

                    <div class="external-tool-instance-card-actions">
                      <el-button size="small" type="primary" plain @click="openInstanceLogs(row)">
                        Logs
                      </el-button>
                      <el-button
                        size="small"
                        type="danger"
                        plain
                        :disabled="!row.running && row.status !== 'stale'"
                        @click="stopInstance(row)"
                      >
                        Stop
                      </el-button>
                      <el-dropdown
                        trigger="click"
                        size="small"
                        @command="handleInstanceMoreCommand($event, row)"
                      >
                        <el-button size="small" plain>
                          More
                        </el-button>
                        <template #dropdown>
                          <el-dropdown-menu>
                            <el-dropdown-item command="info">
                              Info
                            </el-dropdown-item>
                            <el-dropdown-item command="restart" :disabled="!canRestartInstance(row)">
                              Restart
                            </el-dropdown-item>
                            <el-dropdown-item command="clear_logs" :disabled="!canModifyStoppedInstanceFiles(row)">
                              Clear Logs
                            </el-dropdown-item>
                            <el-dropdown-item command="remove" :disabled="!canModifyStoppedInstanceFiles(row)">
                              Remove
                            </el-dropdown-item>
                          </el-dropdown-menu>
                        </template>
                      </el-dropdown>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div v-else class="external-tool-empty">
            {{ searchText || deviceFilter ? 'No matching instances' : 'No instances yet. Start one from Packages.' }}
          </div>
        </el-tab-pane>
      </el-tabs>
    </div>
  </el-dialog>

  <el-dialog
    v-model="startDialogVisible"
    :title="startDialogTitle"
    width="650px"
    append-to-body
    @closed="resetStartDialog"
  >
    <div v-if="pendingItem" class="external-tool-run-body">
      <div class="external-tool-run-summary">
        <div><strong>{{ pendingItem.display_name || pendingItem.id }}</strong></div>
        <div class="mono">{{ pendingItem.id }} / {{ activeDeviceFilterLabel }}</div>
        <div class="external-tool-param-help">
          {{ isPendingOneshot ? 'Runs once, captures stdout/stderr, and does not create an instance.' : 'Instance Name isolates config, pid, state and logs. Example: vite-8087 or ssh-6000.' }}
        </div>
      </div>

      <div class="external-tool-preset-bar">
        <div class="external-tool-preset-field">
          <div class="external-tool-preset-label">Preset</div>
          <el-select
            v-model="selectedParamPresetId"
            class="external-tool-preset-select"
            :loading="presetLoading"
            @change="applySelectedParamPreset"
            size="small"
          >
            <el-option label="Module Defaults" value="__module_defaults__" />
            <el-option
              v-for="preset in paramPresets"
              :key="preset.preset_id"
              :label="preset.name"
              :value="preset.preset_id"
            />
          </el-select>
        </div>
        <div class="external-tool-preset-actions">
          <el-button size="small" :loading="presetSaving" @click="saveCurrentParamPresetAs">
            Save As
          </el-button>
          <el-button
            size="small"
            :loading="presetSaving"
            :disabled="selectedParamPresetId === '__module_defaults__'"
            @click="updateCurrentParamPreset"
          >
            Update
          </el-button>
          <el-button
            size="small"
            type="danger"
            plain
            :disabled="selectedParamPresetId === '__module_defaults__' || presetSaving"
            @click="deleteCurrentParamPreset"
          >
            Delete
          </el-button>
        </div>
      </div>

      <el-form label-position="top" class="external-tool-param-form">
        <el-form-item v-if="pendingLauncherConfig" label="Launcher">
          <el-input
            v-model="launcherExecutable"
            :disabled="launcherResolving"
            :placeholder="launcherResolving ? 'Resolving launcher on client...' : 'Launcher executable'"
            clearable
            @input="markLauncherOverrideDirty"
          >
            <template #append>
              <el-button
                :disabled="launcherResolving || !launcherDefaultExecutable"
                @click="resetLauncherExecutable"
              >
                Reset
              </el-button>
            </template>
          </el-input>
          <div class="external-tool-param-help">
            {{ launcherResolveError || 'Resolved on the selected client. Editing this executable overrides only this run.' }}
          </div>
        </el-form-item>
        <el-form-item
          v-for="param in pendingParams"
          :key="param.name"
          :label="formatParamLabel(param)"
        >
          <div
            v-if="isRemoteFileParam(param)"
            class="external-tool-file-param"
          >
            <el-input
              :model-value="formatRemoteFileParamValue(paramForm[param.name])"
              :placeholder="param.description || param.name"
              readonly
            >
              <template #append>
                <el-button @click="openRemoteFilePicker(param)">
                  Browse
                </el-button>
              </template>
            </el-input>
          </div>

          <el-switch
            v-else-if="normalizeParamType(param.type) === 'boolean'"
            v-model="paramForm[param.name]"
          />

          <el-input-number
            v-else-if="normalizeParamType(param.type) === 'integer'"
            v-model="paramForm[param.name]"
            :placeholder="param.description || param.name"
            controls-position="right"
            class="external-tool-number"
          />

          <el-input
            v-else-if="normalizeParamType(param.type) === 'textarea'"
            v-model="paramForm[param.name]"
            type="textarea"
            :rows="8"
            :placeholder="param.description || param.name"
          />

          <el-input
            v-else
            v-model="paramForm[param.name]"
            :placeholder="param.description || param.name"
            clearable
          />

          <div v-if="param.description" class="external-tool-param-help">
            {{ param.description }}
          </div>
        </el-form-item>

        <div v-if="!pendingParams.length" class="external-tool-empty small">
          This tool has no runtime params.
        </div>
      </el-form>
    </div>

    <template #footer>
      <el-button size="small" @click="startDialogVisible = false">Cancel</el-button>
      <el-button
        v-if="!isPendingOneshot"
        size="small"
        :loading="previewingCommand"
        :disabled="submitting"
        @click="previewStartCommand"
      >
        Preview Command
      </el-button>
      <el-button
        size="small"
        type="primary"
        :loading="submitting"
        :disabled="submitting"
        @click="confirmStart"
      >
        {{ isPendingOneshot ? 'Run Once' : 'Run' }}
      </el-button>
    </template>
  </el-dialog>

  <RemoteFilePicker
    ref="remoteFilePickerRef"
    v-model:visible="remoteFilePickerVisible"
    :selected-id="selectedId"
    :multiple="pendingRemoteFileParamMultiple"
    :initial-path="pendingRemoteFileParamInitialPath"
    :selection-mode="pendingRemoteFileParamSelectionMode"
    :get-tab-scoped-headers="getTabScopedHeaders"
    @select="handleRemoteFileSelected"
    @append-output="forwardAppendOutput"
    @set-active-task="forwardSetActiveTask"
    @upload-started="forwardRemoteUploadStarted"
  />

  <el-dialog
    v-model="logDialogVisible"
    :title="logDialogTitle"
    width="940px"
    append-to-body
  >
    <div v-if="logFilePath" class="external-tool-log-path mono" :title="logFilePath">
      Log file: {{ logFilePath }}
    </div>
    <pre ref="logContentRef" class="external-tool-log-content">{{ logContent || 'No log content.' }}</pre>
    <template #footer>
      <el-button size="small" :loading="logLoading" @click="refreshCurrentLogs">Refresh Logs</el-button>
      <el-button size="small" @click="logDialogVisible = false">Close</el-button>
    </template>
  </el-dialog>

  <el-dialog
    v-model="oneshotDialogVisible"
    :title="oneshotDialogTitle"
    width="940px"
    top="6vh"
    append-to-body
    modal-class="external-tool-info-overlay"
    class="external-tool-detail-dialog external-tool-info-dialog"
  >
    <div class="external-tool-oneshot-body">
      <div class="external-tool-detail-subtitle">
        {{ formatOneshotSummary(oneshotResult) }}
      </div>

      <div class="external-tool-detail-section">
        <div class="external-tool-detail-section-title">Stdout</div>
        <pre class="external-tool-log-content external-tool-oneshot-output">{{ oneshotResult?.stdout || 'No stdout.' }}</pre>
      </div>

      <div class="external-tool-detail-section">
        <div class="external-tool-detail-section-title">Stderr</div>
        <pre class="external-tool-log-content external-tool-oneshot-output">{{ oneshotResult?.stderr || 'No stderr.' }}</pre>
      </div>

<!--      <div class="external-tool-detail-section">-->
<!--        <div class="external-tool-detail-section-title">Result</div>-->
<!--        <pre class="external-tool-detail-pre">{{ stringifyDetailValue(oneshotResult || {}) }}</pre>-->
<!--      </div>-->
    </div>

    <template #footer>
      <el-button size="small" plain @click="copyOneshotResult">Copy Result</el-button>
      <el-button size="small" @click="oneshotDialogVisible = false">Close</el-button>
    </template>
  </el-dialog>

  <el-dialog
    v-model="detailDialogVisible"
    :title="detailDialogTitle"
    width="780px"
    top="6vh"
    append-to-body
    modal-class="external-tool-info-overlay"
    class="external-tool-detail-dialog external-tool-info-dialog"
  >
    <div class="external-tool-detail-body">
      <div v-if="detailSubtitle" class="external-tool-detail-subtitle">
        {{ detailSubtitle }}
      </div>

      <div
        v-for="section in detailSections"
        :key="section.title"
        class="external-tool-detail-section"
      >
        <div class="external-tool-detail-section-title">
          {{ section.title }}
        </div>

        <div class="external-tool-detail-grid">
          <div
            v-for="row in section.rows"
            :key="`${section.title}:${row.label}`"
            class="external-tool-detail-row"
          >
            <div class="external-tool-detail-label">
              {{ row.label }}
            </div>
            <div
              class="external-tool-detail-value"
              :class="{ mono: row.mono, multiline: row.multiline }"
              :title="row.multiline ? '' : stringifyDetailValue(row.value)"
            >
              <pre v-if="row.multiline" class="external-tool-detail-pre">{{ formatDetailValue(row.value) }}</pre>
              <span v-else>{{ formatDetailValue(row.value) }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <template #footer>
      <el-button
        v-if="detailCopyText"
        size="small"
        plain
        @click="copyDetailText"
      >
        Copy Command
      </el-button>
      <el-button size="small" @click="detailDialogVisible = false">Close</el-button>
    </template>
  </el-dialog>
</template>

<script>
import { ElMessage, ElMessageBox } from 'element-plus'
import * as externalToolsApi from '../api/externalToolsApi.js'
import RemoteFilePicker from './RemoteFilePicker.vue'

export default {
  name: 'ExternalToolManagerDialog',

  components: {
    RemoteFilePicker,
  },

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

  emits: [
    'append-output',
    'set-active-task',
    'upload-started',
    'open-tool-meta-editor',
  ],

  data() {
    return {
      visible: false,
      loading: false,
      submitting: false,
      previewingCommand: false,
      presetLoading: false,
      presetSaving: false,
      logLoading: false,
      installLoading: false,
      activeTab: 'modules',
      items: [],
      clientInstances: {},
      installStatuses: {},
      searchText: '',
      deviceFilter: '',
      packageOnlyCompatible: true,
      selectedPackageId: '',
      startDialogVisible: false,
      pendingToolId: '',
      pendingStartMode: 'run',
      paramForm: {},
      launcherExecutable: '',
      launcherDefaultExecutable: '',
      launcherResolving: false,
      launcherResolveError: '',
      launcherOverrideDirty: false,
      paramPresets: [],
      selectedParamPresetId: '__module_defaults__',
      remoteFilePickerVisible: false,
      pendingRemoteFileParam: null,
      logDialogVisible: false,
      logDialogTitle: 'External Tool Logs',
      logFilePath: '',
      logContent: '',
      currentLogRow: null,
      detailDialogVisible: false,
      detailDialogTitle: '',
      detailSubtitle: '',
      detailSections: [],
      detailCopyText: '',
      oneshotDialogVisible: false,
      oneshotDialogTitle: 'External Tool Result',
      oneshotResult: null,
    }
  },

  computed: {
    currentClientPlatform() {
      return this.normalizePlatform(
        this.currentConnection?.os_alias ||
        this.currentConnection?.os_type ||
        this.currentConnection?.platform ||
        this.currentConnection?.system ||
        '',
      )
    },

    currentClientArch() {
      return this.normalizeArch(
        this.currentConnection?.arch ||
        this.currentConnection?.cpu_arch ||
        this.currentConnection?.architecture ||
        this.currentConnection?.machine_arch ||
        '',
      )
    },

    allModules() {
      const modules = []
      for (const pkg of this.items || []) {
        for (const module of this.getPackageModules(pkg)) {
          modules.push(module)
        }
      }
      return modules
    },

    currentDeviceId() {
      return this.normalizeDeviceId(this.selectedId || this.currentConnection?.client_id || '')
    },

    currentMachineId() {
      return this.normalizeMachineId(this.currentConnection?.machine_id || '')
    },

    deviceFilterOptions() {
      const options = []
      const seen = new Set()
      for (const conn of this.connections || []) {
        const machineId = this.normalizeMachineId(conn?.machine_id)
        if (!machineId || seen.has(machineId)) continue
        seen.add(machineId)
        options.push({ value: machineId, label: this.formatMachineOptionLabel(conn) })
      }
      if (this.currentMachineId && !seen.has(this.currentMachineId)) {
        seen.add(this.currentMachineId)
        options.push({ value: this.currentMachineId, label: this.formatCurrentMachineLabel() })
      }
      return options
    },

    activeDeviceFilterLabel() {
      const value = this.normalizeDeviceId(this.deviceFilter)
      const option = this.deviceFilterOptions.find(item => item.value === value)
      if (option) return option.label
      if (!value) return 'current target'
      return this.shortenMachineId(value)
    },

    clientModules() {
      return this.allModules || []
    },

    selectedTargetMachineId() {
      return this.normalizeMachineId(this.deviceFilter || this.defaultTargetValue())
    },

    selectedTargetClientId() {
      return this.getClientDeviceIdForMachine(this.selectedTargetMachineId)
    },

    selectedTargetPlatform() {
      return this.getPlatformForMachineId(this.selectedTargetMachineId)
    },

    selectedTargetArch() {
      return this.getArchForMachineId(this.selectedTargetMachineId)
    },

    filteredModules() {
      const keyword = String(this.searchText || '').trim().toLowerCase()

      return (this.items || []).filter((item) => {
        if (this.packageOnlyCompatible && !this.isPackageAvailableForTarget(item)) return false
        if (!keyword) return true
        return this.moduleSearchText(item).includes(keyword)
      })
    },

    selectedPackage() {
      const list = this.filteredModules || []
      if (!list.length) return null
      const selectedId = String(this.selectedPackageId || '').trim()
      return list.find(item => item.id === selectedId) || list[0]
    },

    allInstances() {
      const rows = []
      for (const item of this.clientModules) {
        const byDevice = this.clientInstances || {}
        for (const [deviceId, toolMap] of Object.entries(byDevice)) {
          const list = toolMap?.[item.id] || []
          for (const instance of list) rows.push(this.normalizeInstanceRow(item, instance, deviceId))
        }
      }
      return rows.sort((a, b) => {
        if (a.running !== b.running) return a.running ? -1 : 1
        return String(b.started_at || '').localeCompare(String(a.started_at || ''))
      })
    },

    filteredInstances() {
      const keyword = String(this.searchText || '').trim().toLowerCase()
      const machine = this.normalizeMachineId(this.deviceFilter || this.defaultTargetValue())
      return this.allInstances.filter((row) => {
        if (machine && row.machine_id !== machine) return false
        if (!keyword) return true
        const values = [
          row.status,
          row.machine_id,
          row.machine_label,
          row.hostname,
          row.connection_id,
          row.tool_id,
          row.display_name,
          row.instance_id,
          row.pid,
          row.exec_path,
          row.config_path,
          row.stdout,
          row.pid_file,
          this.formatPortInfo(row),
        ].map(value => String(value || '').toLowerCase())
        return values.some(value => value.includes(keyword))
      })
    },

    pendingItem() {
      const target = String(this.pendingToolId || '').trim()
      return (this.allModules || []).find(item => String(item.id || '').trim() === target) || null
    },

    pendingParams() {
      return Array.isArray(this.pendingItem?.params) ? this.pendingItem.params : []
    },

    pendingLauncherConfig() {
      if (this.isPendingOneshot) return null
      return this.getModuleLauncher(this.pendingItem)
    },

    pendingRemoteFileParamMultiple() {
      const param = this.pendingRemoteFileParam || {}
      const type = String(param.type || '').trim().toLowerCase()
      return !!(param.multiple || ['remote_files', 'remote_folders'].includes(type))
    },

    pendingRemoteFileParamSelectionMode() {
      const param = this.pendingRemoteFileParam || {}
      const explicitMode = String(param.selection_mode || param.selectionMode || '').trim().toLowerCase()
      if (explicitMode === 'folder') return 'folder'

      const type = String(param.type || '').trim().toLowerCase()
      return ['remote_folder', 'remote_folders'].includes(type) ? 'folder' : 'file'
    },

    pendingRemoteFileParamInitialPath() {
      const param = this.pendingRemoteFileParam || {}
      return String(param.initial_path || param.initialPath || param.base_path || param.basePath || '').trim()
    },

    pendingExecution() {
      return this.getModuleExecution(this.pendingItem)
    },

    isPendingOneshot() {
      return this.pendingExecution === 'oneshot'
    },

    startDialogTitle() {
      const item = this.pendingItem
      const name = item ? (item.display_name || item.id) : 'External Tool'
      const action = this.isPendingOneshot ? 'Run Once' : 'Run'
      return `${action} ${name} on This Client`
    },
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
          await this.readLogs(this.normalizeInstanceRow(module, rawRow, clientId), true)
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
      this.resetStartDialog()
      this.currentLogRow = null
      this.logFilePath = ''
    },

    buildJsonHeaders(extra = {}) {
      if (typeof this.getTabScopedHeaders === 'function') {
        return this.getTabScopedHeaders(extra)
      }
      return extra
    },

    logExternalToolTarget(action, item = null, extra = {}) {
      const selectedMachineId = this.selectedTargetMachineId
      const selectedClientId = this.getClientDeviceIdForMachine(selectedMachineId)

      const payload = {
        action,
        package_id: item?.package_meta?.id || item?.package_id || item?.id || '',
        selected_machine_id: selectedMachineId,
        selected_client_id: selectedClientId,
        current_device_id: this.currentDeviceId,
        current_machine_id: this.currentMachineId,
        selected_target_platform: this.selectedTargetPlatform,
        selected_target_arch: this.selectedTargetArch,
        current_client_platform: this.currentClientPlatform,
        current_client_arch: this.currentClientArch,
        ...extra,
      }

      console.info('[external-tools] target', payload)
      return payload
    },

    selectPackage(item) {
      if (!item?.id) return
      this.selectedPackageId = item.id
    },

    async refreshAll() {
      this.loading = true
      try {
        await this.loadCatalog(false)
        await this.refreshInstallStatuses(false)
        await this.refreshInstances(false)
      } catch (e) {
        ElMessage.error(e.message || 'Failed to refresh external tools')
      } finally {
        this.loading = false
      }
    },

    async loadCatalog(showError = true) {
      try {
        const catalog = await externalToolsApi.loadExternalToolCatalog()
        this.items = Array.isArray(catalog.items) ? catalog.items : []
        if (!this.selectedPackageId && this.items.length) this.selectedPackageId = this.items[0].id || ''
      } catch (e) {
        if (showError) ElMessage.error(e.message || 'Failed to load external tools')
        throw e
      }
    },


    async loadClientCatalogStatuses(deviceId = '', showError = true) {
      const targetDeviceId = this.normalizeDeviceId(deviceId)
      if (!targetDeviceId || targetDeviceId === '__all__') return []

      const targetPlatform = this.getPlatformForConnectionId(targetDeviceId)
      const targetArch = this.getArchForConnectionId(targetDeviceId)
      this.logExternalToolTarget('client-catalog-request', null, {
        request_client_id: targetDeviceId,
        request_platform: targetPlatform,
        request_arch: targetArch,
      })
      if (!targetPlatform || !targetArch) {
        const message = `Unable to resolve target platform/arch for client ${targetDeviceId}`
        if (showError) ElMessage.error(message)
        throw new Error(message)
      }

      const targetItems = (this.items || []).filter(item => this.doesPackageBuildMatch(item, targetPlatform, targetArch))
      for (const item of targetItems) {
        const previous = this.installStatuses[this.installStatusKey(item, targetDeviceId)] || {}
        this.setInstallStatus(item, targetDeviceId, {
          ...previous,
          loading: true,
          error: '',
        })
      }

      try {
        const catalog = await externalToolsApi.loadClientExternalToolCatalog(
          targetDeviceId,
          {
            platform: targetPlatform,
            arch: targetArch,
          },
          this.buildJsonHeaders(),
        )
        const items = Array.isArray(catalog.items) ? catalog.items : []
        const seen = new Set()
        for (const item of items) {
          const status = item?.install_status
          const packageId = String(item?.id || status?.package_id || status?.tool_id || '').trim()
          if (!packageId) continue
          seen.add(packageId)
          if (status) {
            this.setInstallStatus(item, targetDeviceId, {
              ...status,
              loading: false,
              error: status.error || '',
            })
          }
        }
        for (const item of targetItems) {
          if (seen.has(String(item?.id || '').trim())) continue
          this.setInstallStatus(item, targetDeviceId, {
            tool_id: item.id,
            package_id: item.id,
            installed: false,
            loading: false,
            error: 'client status not returned',
            message: 'client status not returned',
          })
        }
        return Array.isArray(catalog.client_install_statuses) ? catalog.client_install_statuses : []
      } catch (e) {
        for (const item of targetItems) {
          this.setInstallStatus(item, targetDeviceId, {
            tool_id: item.id,
            package_id: item.id,
            installed: false,
            loading: false,
            error: e.message || 'Failed to load client install statuses',
            message: e.message || 'Failed to load client install statuses',
          })
        }
        if (showError) ElMessage.error(e.message || 'Failed to load client install statuses')
        return []
      }
    },

    getPackageById(packageId) {
      const id = String(packageId || '').trim()
      if (!id) return null
      return (this.items || []).find(item => String(item?.id || '').trim() === id) || null
    },

    normalizeModuleFromPackage(pkg, module) {
      if (!pkg || !module) return null
      const moduleId = String(module.id || module.module_id || '').trim()
      const toolId = String(module.tool_id || (moduleId ? `${pkg.id}.${moduleId}` : '')).trim()
      if (!toolId) return null
      return {
        ...module,
        id: toolId,
        tool_id: toolId,
        module_id: moduleId || toolId,
        package_id: pkg.id,
        package_meta: pkg,
        package: pkg.package || {},
        package_install: pkg.install || {},
        package_execs: pkg.execs || {},
        package_platforms: pkg.platforms || [],
        package_archs: pkg.archs || [],
        version: module.version || pkg.version || '',
        execution: this.getModuleExecution(module),
        platforms: pkg.platforms || module.platforms || [],
        archs: pkg.archs || module.archs || [],
      }
    },

    getPackageModules(pkg) {
      const result = []
      for (const module of pkg?.modules || []) {
        const normalized = this.normalizeModuleFromPackage(pkg, module)
        if (normalized) result.push(normalized)
      }
      return result
    },

    formatPackageModules(pkg) {
      return this.getPackageModules(pkg).map(module => module.display_name || module.module_id || module.id).join(', ')
    },

    getPackageForModule(module) {
      return module?.package_meta || this.getPackageById(module?.package_id || '') || module
    },

    getModuleLauncher(module) {
      if (!module) return null
      const execName = String(module.exec || '').trim()
      const execs = module.package_execs && typeof module.package_execs === 'object' ? module.package_execs : {}
      const execItem = execName && execs[execName] && typeof execs[execName] === 'object' ? execs[execName] : {}
      const launcher = execItem.launcher && typeof execItem.launcher === 'object' ? execItem.launcher : null
      const launcherType = String(launcher?.type || 'direct').trim().toLowerCase()
      return launcher && launcherType !== 'direct' ? launcher : null
    },

    getModuleExecution(module) {
      if (!module) return ''
      const value = String(module.execution || '').trim().toLowerCase()
      return value
    },

    isOneshotModule(module) {
      return this.getModuleExecution(module) === 'oneshot'
    },

    formatExecutionLabel(module) {
      const execution = this.getModuleExecution(module)
      return execution || 'unknown'
    },

    getExecutionTagType(module) {
      return this.isOneshotModule(module) ? 'success' : 'info'
    },

    canRunModuleAction(module) {
      const execution = this.getModuleExecution(module)
      if (!['daemon', 'oneshot'].includes(execution)) return false
      const pkg = this.getPackageForModule(module)
      if (!this.isPackageAvailableForTarget(pkg)) return false
      const deviceId = this.getActionDeviceId(pkg)
      const status = this.installStatuses[this.installStatusKey(pkg, deviceId)]
      return !!status?.installed
    },




    installStatusKey(itemOrToolId, deviceId = '') {
      const toolId = typeof itemOrToolId === 'object'
        ? (itemOrToolId?.package_meta?.id || itemOrToolId?.package_id || itemOrToolId?.id)
        : itemOrToolId
      return `${this.normalizeDeviceId(deviceId)}:${toolId || ''}`
    },



    getInstallStatusTargetLabel() {
      return 'This Client'
    },

    getModuleInstallDeviceId(item) {
      return this.getActionDeviceId(item)
    },

    getModuleInstallStatus(item) {
      if (!this.isPackageAvailableForTarget(item)) {
        return { label: 'Unavailable for target', type: 'info' }
      }
      const targetLabel = this.getInstallStatusTargetLabel()
      const deviceId = this.getModuleInstallDeviceId(item)
      if (!deviceId) return { label: 'Install: no client', type: 'info' }
      const status = this.installStatuses[this.installStatusKey(item, deviceId)]
      if (!status) return { label: `Status unknown on ${targetLabel}`, type: 'info' }
      if (status.loading) return { label: 'Checking...', type: 'info' }
      if (status.error) return { label: `Status unknown on ${targetLabel}`, type: 'info' }
      return status.installed
        ? { label: `Installed on ${targetLabel}`, type: 'success' }
        : { label: `Not installed on ${targetLabel}`, type: 'warning' }
    },

    setInstallStatus(itemOrToolId, deviceId, status) {
      const key = this.installStatusKey(itemOrToolId, deviceId)
      this.installStatuses = {
        ...this.installStatuses,
        [key]: { ...(status || {}) },
      }
    },

    async refreshInstallStatuses(showToast = false) {
      const deviceId = this.selectedTargetClientId
      if (!deviceId) {
        this.logExternalToolTarget('refresh-install-statuses-skip', null, {
          reason: 'no selectedTargetClientId',
        })
        if (showToast) ElMessage.warning('Please select an online client')
        return
      }
      await this.loadClientCatalogStatuses(deviceId, showToast)
      if (showToast) ElMessage.success('Install statuses refreshed')
    },

    isPackageAvailableForTarget(item) {
      if (!item) return false
      const pkg = item?.package_meta || item
      const deviceId = this.getActionDeviceId(pkg)
      const platform = this.selectedTargetPlatform
      const arch = this.selectedTargetArch
      return !!deviceId && !!platform && !!arch && this.doesPackageBuildMatch(pkg, platform, arch)
    },

    getPackageCurrentInstallStatus(item) {
      if (!item) return null
      const deviceId = this.getModuleInstallDeviceId(item)
      return this.installStatuses[this.installStatusKey(item, deviceId)] || null
    },

    canUsePackageAction(item) {
      return this.isPackageAvailableForTarget(item)
    },

    canInstallPackageAction(item) {
      if (!this.canUsePackageAction(item)) return false
      if (this.installLoading) return false
      const status = this.getPackageCurrentInstallStatus(item)
      if (status?.loading) return false
      return !status || status.installed !== true
    },

    async fetchInstallStatus(item, deviceId = '', options = {}) {
      if (!item?.id) return null
      const targetDeviceId = this.normalizeDeviceId(deviceId)
      if (!targetDeviceId) {
        this.logExternalToolTarget('fetch-install-status-skip', item, {
          reason: 'missing targetDeviceId',
          requested_device_id: deviceId,
        })
        return null
      }
      const statusKey = this.installStatusKey(item, targetDeviceId)
      const cachedStatus = this.installStatuses[statusKey]
      if (cachedStatus && !cachedStatus.loading && !cachedStatus.error && !options.force) return cachedStatus

      await this.loadClientCatalogStatuses(targetDeviceId, !options.silent)
      return this.installStatuses[statusKey] || null
    },


    async refreshInstances(showToast = true) {
      const machineId = this.normalizeMachineId(this.deviceFilter || this.defaultTargetValue())
      const deviceId = this.getClientDeviceIdForMachine(machineId)
      if (!deviceId) {
        this.logExternalToolTarget('refresh-instances-skip', null, {
          reason: 'selected machine has no matching online client_id',
          selected_machine_id: machineId,
        })
        if (showToast) ElMessage.warning('Please select an online client')
        return
      }
      await this.loadAllClientInstances(deviceId, false)
      if (showToast) ElMessage.success('Instances refreshed')
    },


    groupInstancesByTool(items = []) {
  const grouped = {}
  for (const row of items || []) {
    const toolId = String(row?.tool_id || '').trim()
    if (!toolId) continue
    if (!grouped[toolId]) grouped[toolId] = []
    grouped[toolId].push(row)
  }
  return grouped
},

normalizeInstanceByToolPayload(data = {}, modules = []) {
  if (data.by_tool && typeof data.by_tool === 'object') {
    const normalized = {}
    for (const item of modules || []) {
      if (item?.id) normalized[item.id] = []
    }
    for (const [toolId, rows] of Object.entries(data.by_tool || {})) {
      normalized[toolId] = Array.isArray(rows) ? rows : []
    }
    return normalized
  }

  const grouped = this.groupInstancesByTool(Array.isArray(data.items) ? data.items : [])
  for (const item of modules || []) {
    if (item?.id && !grouped[item.id]) grouped[item.id] = []
  }
  return grouped
},


async loadAllClientInstances(deviceId = '', showToast = true) {
  const targetDeviceId = this.normalizeDeviceId(deviceId)
  if (!targetDeviceId || targetDeviceId === '__all__') return

  try {
    const data = await externalToolsApi.loadAllClientInstances(targetDeviceId, this.buildJsonHeaders())
    const nextToolMap = this.normalizeInstanceByToolPayload(data, this.clientModules)

    this.clientInstances = {
      ...this.clientInstances,
      [targetDeviceId]: nextToolMap,
    }

    if (showToast) ElMessage.success('Client instances refreshed')
  } catch (e) {
    if (showToast) ElMessage.error(e.message || 'Failed to load client instances')
    throw e
  }
},


    async loadClientInstances(toolId, deviceId = '', showToast = true) {
      const targetDeviceId = this.normalizeDeviceId(deviceId)
      if (!toolId || !targetDeviceId || targetDeviceId === '__all__') return
      try {
        const data = await externalToolsApi.loadClientInstances(targetDeviceId, toolId, this.buildJsonHeaders())
        this.clientInstances = {
          ...this.clientInstances,
          [targetDeviceId]: {
            ...(this.clientInstances[targetDeviceId] || {}),
            [toolId]: Array.isArray(data.items) ? data.items : [],
          },
        }
        if (showToast) ElMessage.success('Client instances refreshed')
      } catch (e) {
        if (showToast) ElMessage.error(e.message || 'Failed to load client instances')
      }
    },

    defaultTargetValue() {
      if (this.currentMachineId) return this.currentMachineId
      const first = (this.connections || []).find(conn => this.normalizeMachineId(conn?.machine_id))
      return this.normalizeMachineId(first?.machine_id || '')
    },

    getClientDeviceIdForMachine(machineId) {
      const id = this.normalizeMachineId(machineId)
      if (!id || id === '__all__') return ''
      const conn = this.findConnectionByMachineId(id)
      if (conn?.client_id) return this.normalizeDeviceId(conn.client_id)
      if (id === this.currentMachineId && this.currentDeviceId) return this.currentDeviceId
      const byConnectionId = this.findConnectionById(id)
      if (byConnectionId?.client_id) return this.normalizeDeviceId(byConnectionId.client_id)
      return ''
    },

    getPlatformForMachineId(machineId) {
      const id = this.normalizeMachineId(machineId)
      if (!id || id === '__all__') return ''
      const conn = this.findConnectionByMachineId(id) || (id === this.currentMachineId ? this.currentConnection : null)
      return this.normalizePlatform(conn?.os_alias || conn?.os_type || conn?.platform || conn?.system || '')
    },

    getPlatformForConnectionId(deviceId) {
      const conn = this.findConnectionById(deviceId) || (this.normalizeDeviceId(deviceId) === this.currentDeviceId ? this.currentConnection : null)
      return this.normalizePlatform(conn?.os_alias || conn?.os_type || conn?.platform || conn?.system || '')
    },

    getArchForMachineId(machineId) {
      const id = this.normalizeMachineId(machineId)
      if (!id || id === '__all__') return ''
      const conn = this.findConnectionByMachineId(id) || (id === this.currentMachineId ? this.currentConnection : null)
      return this.normalizeArch(conn?.arch || conn?.cpu_arch || conn?.architecture || conn?.machine_arch || '')
    },

    getArchForConnectionId(deviceId) {
      const conn = this.findConnectionById(deviceId) || (this.normalizeDeviceId(deviceId) === this.currentDeviceId ? this.currentConnection : null)
      return this.normalizeArch(conn?.arch || conn?.cpu_arch || conn?.architecture || conn?.machine_arch || '')
    },

    getActionDeviceId(item) {
      if (!item) return ''

      const machineId = this.selectedTargetMachineId
      if (!machineId || machineId === '__all__') return ''

      const deviceId = this.getClientDeviceIdForMachine(machineId)
      if (!deviceId) {
        this.logExternalToolTarget('resolve-client-id-missing', item, {
          reason: 'selected machine has no matching online client_id',
        })
      }
      return deviceId
    },

    normalizeDeviceId(value) {
      return String(value || '').trim()
    },

    normalizeMachineId(value) {
      return String(value || '').trim()
    },

    shortenDeviceId(deviceId) {
      const value = this.normalizeDeviceId(deviceId)
      if (!value) return '-'
      if (value === '__all__') return 'all'
      return value.length > 12 ? value.slice(0, 12) : value
    },

    shortenMachineId(machineId) {
      const value = this.normalizeMachineId(machineId)
      if (!value) return '-'
      if (value === '__all__') return 'all'
      return value.length > 12 ? value.slice(0, 12) : value
    },

    findConnectionById(deviceId) {
      const id = this.normalizeDeviceId(deviceId)
      return (this.connections || []).find(conn => this.normalizeDeviceId(conn?.client_id) === id) || null
    },

    findConnectionByMachineId(machineId) {
      const id = this.normalizeMachineId(machineId)
      return (this.connections || []).find(conn => this.normalizeMachineId(conn?.machine_id) === id) || null
    },

    getMachineIdForConnectionId(deviceId) {
      const conn = this.findConnectionById(deviceId)
      return this.normalizeMachineId(conn?.machine_id || (deviceId === this.currentDeviceId ? this.currentConnection?.machine_id : '') || deviceId)
    },

    getHostnameForConnectionId(deviceId) {
      const conn = this.findConnectionById(deviceId) || (deviceId === this.currentDeviceId ? this.currentConnection : null)
      return String(conn?.hostname || '').trim()
    },

    getMachineAlias(machineId) {
      const id = this.normalizeMachineId(machineId)
      if (!id) return ''
      return String(this.machineAliasMap?.[id] || '').trim()
    },

    formatMachineOptionLabel(conn) {
      const machineId = this.normalizeMachineId(conn?.machine_id)
      const shortId = this.shortenMachineId(machineId)
      const hostname = String(conn?.hostname || '').trim()
      const alias = this.getMachineAlias(machineId)
      if (alias) return `${alias} (${shortId})`
      return hostname ? `${shortId} (${hostname})` : shortId
    },

    formatCurrentMachineLabel() {
      const conn = this.currentConnection || this.findConnectionById(this.currentDeviceId)
      if (conn?.machine_id) return this.formatMachineOptionLabel(conn)
      return this.shortenMachineId(this.currentMachineId)
    },

    getMachineLabel(machineId, connectionId = '') {
      const id = this.normalizeMachineId(machineId)
      const conn = this.findConnectionByMachineId(id) || this.findConnectionById(connectionId)
      if (conn?.machine_id) return this.formatMachineOptionLabel(conn)
      if (id === this.currentMachineId && this.currentConnection) return this.formatMachineOptionLabel(this.currentConnection)
      return this.shortenMachineId(id)
    },

    getClientDeviceIdsForFilter(filterValue) {
      const value = this.normalizeMachineId(filterValue)
      if (!value) return []
      if (value === '__all__') {
        const ids = []
        const seen = new Set()
        for (const conn of this.connections || []) {
          const id = this.normalizeDeviceId(conn?.client_id)
          if (!id || seen.has(id)) continue
          seen.add(id)
          ids.push(id)
        }
        return ids
      }

      const ids = []
      const seen = new Set()
      for (const conn of this.connections || []) {
        const machineId = this.normalizeMachineId(conn?.machine_id)
        const clientId = this.normalizeDeviceId(conn?.client_id)
        if (!clientId || seen.has(clientId)) continue
        if (machineId === value || clientId === value) {
          seen.add(clientId)
          ids.push(clientId)
        }
      }
      if (!ids.length && value === this.currentMachineId && this.currentDeviceId) ids.push(this.currentDeviceId)
      return ids
    },

    async handleTargetFilterChange() {
      await this.refreshInstallStatuses(false)
      await this.refreshInstances(false)
    },

    async handlePackageOnlyCompatibleChange() {
      await this.refreshInstallStatuses(false)
    },

    normalizePlatform(value) {
      const text = String(value || '').trim().toLowerCase()
      const aliases = {
        windows: 'win',
        win32: 'win',
        darwin: 'mac',
        macos: 'mac',
        osx: 'mac',
        linux: 'linux',
        ios: 'ios',
        common: '*',
        all: '*',
        '*': '*',
      }
      return aliases[text] || text
    },

    normalizeArch(value) {
      const text = String(value || '').trim().toLowerCase().replace(/-/g, '_')
      const aliases = {
        x86_64: 'amd64',
        amd64: 'amd64',
        i386: '386',
        i686: '386',
        aarch64: 'arm64',
        arm64: 'arm64',
        all: '*',
        common: '*',
        '*': '*',
      }
      return aliases[text] || text
    },

    normalizeArchs(archs) {
      const source = Array.isArray(archs)
        ? archs
        : (typeof archs === 'string' && archs.trim() ? [archs] : [])
      const result = []
      const seen = new Set()
      source.forEach((arch) => {
        const normalized = this.normalizeArch(arch)
        if (!normalized || seen.has(normalized)) return
        seen.add(normalized)
        result.push(normalized)
      })
      return result.length ? result : ['*']
    },

    normalizePlatforms(platforms) {
      const source = Array.isArray(platforms)
        ? platforms
        : (typeof platforms === 'string' && platforms.trim() ? [platforms] : [])
      const result = []
      const seen = new Set()
      source.forEach((platform) => {
        const normalized = this.normalizePlatform(platform)
        if (!normalized || seen.has(normalized)) return
        seen.add(normalized)
        result.push(normalized)
      })
      return result.length ? result : ['*']
    },

    doesPlatformMatch(item, platform) {
      const target = this.normalizePlatform(platform)
      const platforms = this.normalizePlatforms(item?.platforms || item?.package_platforms || item?.platform)
      if (!target || !platforms.length) return false
      if (platforms.includes('*')) return true
      return platforms.includes(target)
    },

    doesArchMatch(item, arch) {
      const target = this.normalizeArch(arch)
      const archs = this.normalizeArchs(item?.archs || item?.package_archs || item?.arch)
      if (!target || !archs.length) return false
      if (archs.includes('*')) return true
      return archs.includes(target)
    },

    doesPackageCompatibleTargetMatch(packageInfo, platform, arch) {
      const targetPlatform = this.normalizePlatform(platform)
      const targetArch = this.normalizeArch(arch)
      if (!targetPlatform || !targetArch) return false

      const compatibleTargets = Array.isArray(packageInfo?.compatible_targets)
        ? packageInfo.compatible_targets
        : []

      return compatibleTargets.some((item) => {
        const itemPlatform = this.normalizePlatform(item?.platform || '')
        const itemArch = this.normalizeArch(item?.arch || '')
        return itemPlatform === targetPlatform && itemArch === targetArch
      })
    },

    doesPackageBuildMatch(item, platform, arch) {
      const packages = item?.platform_packages || item?.package_meta?.platform_packages || null
      if (!packages || typeof packages !== 'object') return false
      const platformValue = this.normalizePlatform(platform)
      const archValue = this.normalizeArch(arch)
      if (!platformValue || !archValue) return false
      const exactKey = `${platformValue}-${archValue}`
      if (packages[exactKey]) return true
      return Object.values(packages).some((info) => {
        const itemPlatform = this.normalizePlatform(info?.platform || '')
        const itemArch = this.normalizeArch(info?.arch || '')
        const platformOk = itemPlatform === '*' || itemPlatform === platformValue
        const archOk = itemArch === '*' || itemArch === archValue
        if (platformOk && archOk) return true
        return this.doesPackageCompatibleTargetMatch(info, platformValue, archValue)
      })
    },



    formatPlatforms(platforms) {
      const normalized = this.normalizePlatforms(platforms)
      if (!normalized.length || normalized.includes('*')) return 'All platforms'
      return normalized.map((platform) => {
        if (platform === 'mac') return 'macOS'
        if (platform === 'win') return 'Windows'
        if (platform === 'linux') return 'Linux'
        if (platform === 'ios') return 'iOS'
        return platform
      }).join(', ')
    },

    moduleSearchText(item) {
      const moduleText = this.getPackageModules(item).map(module => [module.id, module.module_id, module.name, module.display_name, module.description].join(' ')).join(' ')
      const execText = Object.keys(item?.execs || {}).join(' ')
      return [
        item.id,
        item.name,
        item.display_name,
        item.description,
        item.package?.filename,
        item.package?.executable_rel_path,
        moduleText,
        execText,
        (item.tags || []).join(' '),
      ].map(value => String(value || '').toLowerCase()).join(' ')
    },

    isRemoteFileParam(param) {
      const type = String(param?.type || '').trim().toLowerCase()
      return [
        'remote_file',
        'remote_files',
        'remote_folder',
        'remote_folders',
      ].includes(type)
    },

    formatRemoteFileParamValue(value) {
      if (Array.isArray(value)) return value.join(', ')
      return value === null || value === undefined ? '' : String(value)
    },

    openRemoteFilePicker(param) {
      if (!param || !param.name) return

      this.pendingRemoteFileParam = param
      this.remoteFilePickerVisible = true
    },

    handleRemoteFileSelected(value) {
      const param = this.pendingRemoteFileParam
      if (!param || !param.name) return

      this.paramForm = {
        ...this.paramForm,
        [param.name]: this.pendingRemoteFileParamMultiple ? value : String(value || ''),
      }
      this.remoteFilePickerVisible = false
      this.pendingRemoteFileParam = null
    },

    loadRemoteFilePickerDirectory(path = '') {
      return this.$refs.remoteFilePickerRef?.loadRemoteDirectory(path || '', 1)
    },

    forwardAppendOutput(clientId, line, kind) {
      this.$emit('append-output', clientId, line, kind)
    },

    forwardSetActiveTask(clientId, taskId) {
      this.$emit('set-active-task', clientId, taskId)
    },

    forwardRemoteUploadStarted(payload) {
      this.$emit('upload-started', {
        ...(payload && typeof payload === 'object' ? payload : {}),
        source: 'external_tool_remote_file_picker',
      })
    },

    normalizeParamType(type) {
      const value = String(type || 'string').trim().toLowerCase()
      if (value === 'int' || value === 'number') return 'integer'
      if (value === 'bool') return 'boolean'
      if (value === 'multiline' || value === 'text') return 'textarea'
      return value || 'string'
    },

    formatParamLabel(param) {
      const label = param.label || param.name
      const required = param.required ? ' *' : ''
      return `${label}${required}`
    },

    // buildParamDefaults(item) {
    //   const form = {}
    //   for (const param of item?.params || []) {
    //     const name = String(param?.name || '').trim()
    //     if (!name) continue
    //     if (name === 'instance_name' && (param.default === undefined || param.default === null || String(param.default).trim() === '')) {
    //       form[name] = this.defaultInstanceName(item)
    //     } else if (param.default !== undefined && param.default !== null) {
    //       form[name] = param.default
    //     } else if (this.normalizeParamType(param.type) === 'boolean') {
    //       form[name] = false
    //     } else {
    //       form[name] = ''
    //     }
    //   }
    //   return form
    // },

    buildParamDefaults(item) {
      const form = {}
      for (const param of item?.params || []) {
        const name = String(param?.name || '').trim()
        if (!name) continue

        const type = String(param?.type || 'string').trim().toLowerCase()
        if (name === 'instance_name' && (param.default === undefined || param.default === null || String(param.default).trim() === '')) {
          form[name] = this.defaultInstanceName(item)
        } else if (param.default !== undefined && param.default !== null) {
          form[name] = ['remote_files', 'remote_folders'].includes(type) && Array.isArray(param.default)
            ? [...param.default]
            : param.default
        } else if (['remote_files', 'remote_folders'].includes(type)) {
          form[name] = []
        } else if (this.normalizeParamType(param.type) === 'boolean') {
          form[name] = false
        } else {
          form[name] = ''
        }
      }
      return form
    },


    cloneParamPresetValue(value) {
      if (Array.isArray(value)) return value.map(item => this.cloneParamPresetValue(item))
      if (value && typeof value === 'object') {
        return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, this.cloneParamPresetValue(item)]))
      }
      return value
    },

    applyParamPreset(preset) {
      const item = this.pendingItem
      const form = this.buildParamDefaults(item)
      const params = preset?.params && typeof preset.params === 'object' ? preset.params : {}
      for (const [name, value] of Object.entries(params)) {
        if (!Object.prototype.hasOwnProperty.call(form, name)) continue
        form[name] = this.cloneParamPresetValue(value)
      }
      this.paramForm = form
    },

    applySelectedParamPreset(presetId) {
      const targetId = String(presetId || '').trim()
      if (!targetId || targetId === '__module_defaults__') {
        this.paramForm = this.buildParamDefaults(this.pendingItem)
        return
      }
      const preset = this.paramPresets.find(item => String(item?.preset_id || '') === targetId)
      if (preset) this.applyParamPreset(preset)
    },

    async loadParamPresets(item) {
      const toolId = String(item?.id || '').trim()
      this.paramPresets = []
      this.selectedParamPresetId = '__module_defaults__'
      if (!toolId) return

      try {
        this.presetLoading = true
        const data = await externalToolsApi.loadExternalToolParamPresets(toolId)
        this.paramPresets = Array.isArray(data?.items) ? data.items : []
      } catch (e) {
        ElMessage.error(e.message || 'Failed to load parameter presets')
      } finally {
        this.presetLoading = false
      }
    },

    currentParamPreset() {
      const presetId = String(this.selectedParamPresetId || '').trim()
      if (!presetId || presetId === '__module_defaults__') return null
      return this.paramPresets.find(item => String(item?.preset_id || '') === presetId) || null
    },

    upsertParamPreset(item) {
      if (!item?.preset_id) return
      const presetId = String(item.preset_id)
      const next = this.paramPresets.filter(preset => String(preset?.preset_id || '') !== presetId)
      next.push(item)
      this.paramPresets = next.sort((a, b) => String(a?.name || '').localeCompare(String(b?.name || '')))
    },

    async saveCurrentParamPresetAs() {
      const item = this.pendingItem
      if (!item) return

      try {
        const params = this.buildStartParams()
        const result = await ElMessageBox.prompt('Enter a name for this parameter preset.', 'Save Parameter Preset', {
          confirmButtonText: 'Save',
          cancelButtonText: 'Cancel',
          inputPlaceholder: 'Preset name',
          inputValidator: value => String(value || '').trim() ? true : 'Preset name is required',
        })
        const name = String(result?.value || '').trim()
        if (!name) return

        this.presetSaving = true
        const created = await externalToolsApi.createExternalToolParamPreset(item.id, { name, params })
        this.upsertParamPreset(created)
        this.selectedParamPresetId = String(created?.preset_id || '')
        ElMessage.success(`Preset saved: ${created?.name || name}`)
      } catch (e) {
        if (e === 'cancel' || e === 'close' || e?.action === 'cancel' || e?.action === 'close') return
        ElMessage.error(e.message || 'Failed to save parameter preset')
      } finally {
        this.presetSaving = false
      }
    },

    async updateCurrentParamPreset() {
      const item = this.pendingItem
      const preset = this.currentParamPreset()
      if (!item || !preset) return

      try {
        const params = this.buildStartParams()
        await ElMessageBox.confirm(
          `Update preset "${preset.name}" with the current parameters?`,
          'Update Parameter Preset',
          { confirmButtonText: 'Update', cancelButtonText: 'Cancel', type: 'warning' },
        )
        this.presetSaving = true
        const updated = await externalToolsApi.updateExternalToolParamPreset(item.id, preset.preset_id, { params })
        this.upsertParamPreset(updated)
        ElMessage.success(`Preset updated: ${updated?.name || preset.name}`)
      } catch (e) {
        if (e === 'cancel' || e === 'close' || e?.action === 'cancel' || e?.action === 'close') return
        ElMessage.error(e.message || 'Failed to update parameter preset')
      } finally {
        this.presetSaving = false
      }
    },

    async deleteCurrentParamPreset() {
      const item = this.pendingItem
      const preset = this.currentParamPreset()
      if (!item || !preset) return

      try {
        await ElMessageBox.confirm(
          `Delete preset "${preset.name}"?`,
          'Delete Parameter Preset',
          { confirmButtonText: 'Delete', cancelButtonText: 'Cancel', type: 'warning' },
        )
        this.presetSaving = true
        await externalToolsApi.deleteExternalToolParamPreset(item.id, preset.preset_id)
        this.paramPresets = this.paramPresets.filter(entry => entry?.preset_id !== preset.preset_id)
        this.selectedParamPresetId = '__module_defaults__'
        this.paramForm = this.buildParamDefaults(item)
        ElMessage.success(`Preset deleted: ${preset.name}`)
      } catch (e) {
        if (e === 'cancel' || e === 'close' || e?.action === 'cancel' || e?.action === 'close') return
        ElMessage.error(e.message || 'Failed to delete parameter preset')
      } finally {
        this.presetSaving = false
      }
    },


    defaultInstanceName(item) {
      if (item?.name === 'frps') return 'frps-7000'
      if (item?.name === 'frpc') return 'vite-8087'
      return 'default'
    },

    // buildStartParams() {
    //   const params = {}
    //   for (const param of this.pendingParams || []) {
    //     const name = String(param?.name || '').trim()
    //     if (!name) continue
    //     const value = this.paramForm[name]
    //     if (param.required && (value === '' || value === undefined || value === null)) {
    //       throw new Error(`Param ${name} is required`)
    //     }
    //     params[name] = value
    //   }
    //   return params
    // },

    resetLauncherFormState() {
      this.launcherExecutable = ''
      this.launcherDefaultExecutable = ''
      this.launcherResolving = false
      this.launcherResolveError = ''
      this.launcherOverrideDirty = false
    },

    markLauncherOverrideDirty() {
      this.launcherOverrideDirty = true
    },

    resetLauncherExecutable() {
      this.launcherExecutable = this.launcherDefaultExecutable
      this.launcherOverrideDirty = false
    },

    buildLauncherOverride() {
      if (!this.pendingLauncherConfig || !this.launcherOverrideDirty) return null
      const executable = String(this.launcherExecutable || '').trim()
      const defaultExecutable = String(this.launcherDefaultExecutable || '').trim()
      if (executable === defaultExecutable) return null
      if (!executable) throw new Error('Launcher executable is required')
      return { executable }
    },

    async loadPendingLauncher(item) {
      if (!this.getModuleLauncher(item) || this.isOneshotModule(item)) return

      const toolId = String(item?.id || '').trim()
      try {
        this.launcherResolving = true
        this.launcherResolveError = ''
        const targetDeviceId = this.normalizeDeviceId(this.getActionDeviceId(this.getPackageForModule(item)))
        if (!targetDeviceId) throw new Error('Please select a target machine')

        const requestPlatform = this.getPlatformForConnectionId(targetDeviceId)
        const requestArch = this.getArchForConnectionId(targetDeviceId)
        if (!requestPlatform || !requestArch) {
          throw new Error(`Unable to resolve target platform/arch for client ${targetDeviceId}`)
        }

        const data = await externalToolsApi.resolveClientLauncher(
          targetDeviceId,
          toolId,
          { platform: requestPlatform, arch: requestArch },
          this.buildJsonHeaders(),
        )
        if (String(this.pendingToolId || '').trim() !== toolId) return

        const executable = String(data?.executable || '').trim()
        if (!executable) throw new Error('Client returned an empty launcher executable')
        this.launcherDefaultExecutable = executable
        this.launcherExecutable = executable
        this.launcherOverrideDirty = false
      } catch (e) {
        if (String(this.pendingToolId || '').trim() !== toolId) return
        this.launcherDefaultExecutable = ''
        this.launcherExecutable = ''
        this.launcherOverrideDirty = false
        this.launcherResolveError = `Default launcher unavailable: ${e.message || e}`
      } finally {
        if (String(this.pendingToolId || '').trim() === toolId) this.launcherResolving = false
      }
    },

    buildStartParams() {
      const params = {}
      for (const param of this.pendingParams || []) {
        const name = String(param?.name || '').trim()
        if (!name) continue

        const type = String(param?.type || 'string').trim().toLowerCase()
        let value = this.paramForm[name]

        const hasRemoteMultiValue = ['remote_files', 'remote_folders'].includes(type) && Array.isArray(value) && value.length > 0
        if (param.required && !hasRemoteMultiValue && (value === '' || value === undefined || value === null)) {
          throw new Error(`Param ${name} is required`)
        }

        if (['remote_files', 'remote_folders'].includes(type)) {
          params[name] = Array.isArray(value)
            ? value.map(item => String(item || '').trim()).filter(Boolean)
            : String(value || '').split(',').map(item => item.trim()).filter(Boolean)
        } else if (['remote_file', 'remote_folder'].includes(type)) {
          params[name] = Array.isArray(value) ? String(value[0] || '').trim() : String(value || '').trim()
        } else {
          params[name] = value
        }
      }

      return params
    },

    deriveInstanceId(params) {
      const raw = params.instance_name || params.instance_id || (
        params.proxy_name && params.remote_port ? `${params.proxy_name}-${params.remote_port}` : ''
      ) || (params.bind_port ? `frps-${params.bind_port}` : 'default')
      return String(raw || 'default').trim().replace(/[^A-Za-z0-9_.-]+/g, '-').replace(/^[._-]+|[._-]+$/g, '') || 'default'
    },

    openStartDialog(item, mode = 'run') {
      this.pendingToolId = String(item?.id || '').trim()
      this.pendingStartMode = mode
      this.paramForm = this.buildParamDefaults(item)
      this.paramPresets = []
      this.selectedParamPresetId = '__module_defaults__'
      this.resetLauncherFormState()
      this.startDialogVisible = true
      this.loadParamPresets(item)
      this.loadPendingLauncher(item)
    },

    resetStartDialog() {
      this.startDialogVisible = false
      this.submitting = false
      this.previewingCommand = false
      this.presetLoading = false
      this.presetSaving = false
      this.pendingToolId = ''
      this.pendingStartMode = 'run'
      this.paramForm = {}
      this.resetLauncherFormState()
      this.paramPresets = []
      this.selectedParamPresetId = '__module_defaults__'
    },

    downloadTool(item) {
      const id = String(item?.id || '').trim()
      if (!id) return
      const platform = this.selectedTargetPlatform
      const arch = this.selectedTargetArch

      this.logExternalToolTarget('download-package', item, {
        request_platform: platform,
        request_arch: arch,
      })

      if (!platform || !arch) {
        ElMessage.warning('Please select a valid target first')
        return
      }

      const downloadUrl = externalToolsApi.buildExternalToolDownloadUrl(id, { platform, arch })
      window.open(downloadUrl, '_blank')
    },


    getRunButtonLabel(module = null) {
      const action = this.isOneshotModule(module) ? 'Run Once' : 'Run'
      return `${action} on This Client`
    },

    getInstallMenuLabel(item = null) {
      const status = item ? this.getPackageCurrentInstallStatus(item) : null
      return status?.installed ? 'Installed on This Client' : 'Install on This Client'
    },


    getUninstallMenuLabel() {
      return 'Uninstall from This Client'
    },

handlePackageMoreCommand(command, item) {
  if (command === 'download') return this.downloadTool(item)
  if (command === 'edit') return this.$emit('open-tool-meta-editor', item.id)
  if (!this.canUsePackageAction(item)) return null
  if (command === 'status') return this.showInstallStatus(item)
  if (command === 'copy') return this.copyInstallCommand(item)
  if (command === 'clear_cache') return this.clearPackageCache(item)
  if (command === 'uninstall') return this.uninstallPackage(item)
  return null
},

    getPackageTargetMachineId(item) {
      if (!item) return ''
      return this.selectedTargetMachineId
    },

getPackageTargetConnectionIds(item) {
  if (!item) return []
  const machineId = this.getPackageTargetMachineId(item)
  const ids = this.getClientDeviceIdsForFilter(machineId)
  if (!ids.length) {
    this.logExternalToolTarget('package-target-connections-empty', item, {
      reason: 'selected machine has no matching client connections',
      selected_machine_id: machineId,
    })
  }
  return ids
},

getPackageTargetInstanceRows(item) {
  if (!item?.id) return []
  const packageId = String(item.id || '').trim()
  const machineId = this.getPackageTargetMachineId(item)
  return this.allInstances.filter(row => (
    (row.package_id === packageId || String(row.tool_id || '').startsWith(`${packageId}.`)) &&
    row.machine_id === machineId
  ))
},

hasRunningInstancesForPackage(item) {
  return this.getPackageTargetInstanceRows(item).some(row => row.running || String(row.status || '').toLowerCase() === 'running')
},

canUninstallPackageAction(item) {
  if (!this.canUsePackageAction(item)) return false
  const status = this.installStatuses[this.installStatusKey(item, this.getModuleInstallDeviceId(item))]
  if (status && status.installed === false) return false
  return !this.hasRunningInstancesForPackage(item)
},

async uninstallPackage(item) {
  if (!item?.id) return
  if (!this.canUsePackageAction(item)) {
    ElMessage.warning('Please select a supported client first')
    return
  }

  // 卸载前刷新一次实例状态，避免 UI 旧数据导致误删。
  try {
    await this.refreshInstances(false)
  } catch (_) {
    // refresh 失败不直接中断，后端/client 仍会再做一次 running 校验。
  }

  if (this.hasRunningInstancesForPackage(item)) {
    ElMessage.warning('This package still has running instances on this machine. Stop them before uninstalling.')
    return
  }

  try {
    await ElMessageBox.confirm(
      `Uninstall ${item.display_name || item.id} from this machine?`,
      'Uninstall External Tool',
      { type: 'warning', confirmButtonText: 'Uninstall', cancelButtonText: 'Cancel' },
    )
  } catch (_) {
    return
  }

  try {
    this.installLoading = true
    const deviceIds = this.getPackageTargetConnectionIds(item)
    if (!deviceIds.length) throw new Error('Please select a device')
    // 实际卸载只对当前选中的连接发命令；同 machine 多连接时，后端命令仍落在该机器本地路径。
    const deviceId = this.normalizeDeviceId(deviceIds[0])
    this.logExternalToolTarget('uninstall-client-package', item, {
      request_client_id: deviceId,
      request_platform: this.getPlatformForConnectionId(deviceId),
      request_arch: this.getArchForConnectionId(deviceId),
    })
    const data = await this.uninstallClientTool(item, deviceId)
    this.setInstallStatus(item, deviceId, {
      ...(data || {}), installed: false, loading: false, error: '',
    })
    await this.loadClientCatalogStatuses(deviceId, false)
    ElMessage.success(data?.message || `Uninstalled: ${item.display_name || item.id}`)
  } catch (e) {
    ElMessage.error(e.message || 'Failed to uninstall package')
  } finally {
    this.installLoading = false
  }
},


async uninstallClientTool(item, deviceId) {
  const targetDeviceId = this.normalizeDeviceId(deviceId)
  if (!targetDeviceId) throw new Error('Please select a device')

  const requestPlatform = this.getPlatformForConnectionId(targetDeviceId)
  const requestArch = this.getArchForConnectionId(targetDeviceId)
  this.logExternalToolTarget('uninstall-client-request', item, {
    request_client_id: targetDeviceId,
    request_platform: requestPlatform,
    request_arch: requestArch,
  })
  if (!requestPlatform || !requestArch) throw new Error(`Unable to resolve target platform/arch for client ${targetDeviceId}`)

  return externalToolsApi.uninstallClientTool(
    targetDeviceId,
    item.id,
    {
      params: {},
      platform: requestPlatform,
      arch: requestArch,
    },
    this.buildJsonHeaders(),
  )
},

    async clearPackageCache(item) {
      if (!item?.id) return
      if (!this.canUsePackageAction(item)) {
        ElMessage.warning('Please select a supported client first')
        return
      }
      try {
        await ElMessageBox.confirm(
          `Clear cached package archive for ${item.display_name || item.id} on this machine? Installed files will not be removed.`,
          'Clear Package Cache',
          { type: 'warning', confirmButtonText: 'Clear Cache', cancelButtonText: 'Cancel' },
        )
      } catch (_) {
        return
      }
      try {
        this.installLoading = true
        const deviceId = this.getActionDeviceId(item)
        if (!deviceId) throw new Error('Please select a device')
        const data = await this.clearClientPackageCache(item, deviceId)
        await this.loadClientCatalogStatuses(deviceId, false)
        ElMessage.success(data?.message || 'Package cache cleared')
      } catch (e) {
        ElMessage.error(e.message || 'Failed to clear package cache')
      } finally {
        this.installLoading = false
      }
    },


    async clearClientPackageCache(item, deviceId) {
      const targetDeviceId = this.normalizeDeviceId(deviceId)
      if (!targetDeviceId) throw new Error('Please select a device')

      const requestPlatform = this.getPlatformForConnectionId(targetDeviceId)
      const requestArch = this.getArchForConnectionId(targetDeviceId)
      this.logExternalToolTarget('clear-client-cache-request', item, {
        request_client_id: targetDeviceId,
        request_platform: requestPlatform,
        request_arch: requestArch,
      })
      if (!requestPlatform || !requestArch) throw new Error(`Unable to resolve target platform/arch for client ${targetDeviceId}`)

      return externalToolsApi.clearClientPackageCache(
        targetDeviceId,
        item.id,
        {
          params: {},
          platform: requestPlatform,
          arch: requestArch,
        },
        this.buildJsonHeaders(),
      )
    },

    async installOnly(item) {
      if (!this.canUsePackageAction(item)) {
        ElMessage.warning('Please select a supported client first')
        return
      }
      try {
        this.installLoading = true
        const deviceId = this.getActionDeviceId(item)
        if (!deviceId) throw new Error('Please select a target machine')
        const requestPlatform = this.getPlatformForConnectionId(deviceId)
        const requestArch = this.getArchForConnectionId(deviceId)
        this.logExternalToolTarget('install-client-package', item, {
          request_client_id: deviceId,
          request_platform: requestPlatform,
          request_arch: requestArch,
        })
        if (!requestPlatform || !requestArch) throw new Error(`Unable to resolve target platform/arch for client ${deviceId}`)

        const data = await externalToolsApi.installClientTool(
          deviceId,
          item.id,
          { params: {}, platform: requestPlatform, arch: requestArch },
          this.buildJsonHeaders(),
        )
        this.setInstallStatus(item, deviceId, { ...data, loading: false, error: data.error || '' })
        const sourceLabel = data.used_cache
          ? 'Installed from cached package'
          : data.downloaded
            ? 'Downloaded and installed'
            : data.package_source === 'local'
              ? 'Installed from local package file'
              : 'Installed successfully'
        const message = data.already_installed
          ? `Already installed: ${data.executable_path || data.install_dir || item.id}`
          : `${sourceLabel}: ${data.executable_path || data.install_dir || item.id}`
        ElMessage.success(message)
      } catch (e) {
        ElMessage.error(e.message || 'Failed to install package')
      } finally {
        this.installLoading = false
      }
    },

    formatBytes(value) {
      const size = Number(value || 0)
      if (!Number.isFinite(size) || size <= 0) return '0 B'
      const units = ['B', 'KB', 'MB', 'GB']
      let n = size
      let i = 0
      while (n >= 1024 && i < units.length - 1) {
        n /= 1024
        i += 1
      }
      return `${n.toFixed(i === 0 ? 0 : 1)} ${units[i]}`
    },

    formatExecMap(value) {
      const map = value && typeof value === 'object' ? value : {}
      const entries = Object.entries(map).filter(([name, path]) => String(name || '').trim() && String(path || '').trim())
      if (!entries.length) return '-'
      return entries.map(([name, path]) => `${name}: ${path}`).join('\n')
    },

    formatCommandMap(data) {
      const commands = data?.commands && typeof data.commands === 'object' ? data.commands : {}
      const entries = Object.entries(commands).filter(([name, command]) => String(name || '').trim() && String(command || '').trim())
      if (entries.length) return entries.map(([name, command]) => `${name}: ${command}`).join('\n')
      if (data?.command) return String(data.command)
      if (data?.executable_path) return String(data.executable_path)
      return '-'
    },

    packageExecNames(item) {
      return Object.keys(item?.execs || {}).filter(Boolean).join(', ') || '-'
    },

    formatInstallStatusDetails(data, item = null) {
      if (!data) return 'No install status available'
      const cache = data.cache || {}
      const newline = String.fromCharCode(10)
      const installLog = data.install_log || 'No install log available.'
      return [
        `Status: ${data.installed ? 'installed' : 'not installed'}`,
        `Install dir: ${data.install_dir || '-'}`,
        `Exec paths:${newline}${this.formatExecMap(data.exec_paths)}`,
        `Cached package: ${cache.exists || cache.cached ? 'yes' : 'no'}`,
        `Cache path: ${cache.cache_path || data.cache_path || '-'}`,
        `Cache size: ${cache.size ? this.formatBytes(cache.size) : '-'}`,
        `Cache mtime: ${cache.mtime || '-'}`,
        item?.source ? `Source: ${item.source}` : '',
        `Install log:${newline}${installLog}`,
      ].filter(Boolean).join(newline)
    },

    async getInstallStatusForAction(item) {
      const deviceId = this.getActionDeviceId(item)
      return this.fetchInstallStatus(item, deviceId, { silent: false, force: true })
    },

    async showInstallStatus(item) {
      const data = await this.getInstallStatusForAction(item)
      if (!data) return
      const modulesText = this.formatPackageModules(item) || '-'
      const execsText = this.packageExecNames(item)
      this.showDetailDialog({
        title: `${item.display_name || item.id} install status`,
        subtitle: `${item.id} / ${this.activeDeviceFilterLabel}`,
        copyText: this.formatCommandMap(data),
        sections: [
          {
            title: 'Package',
            rows: [
              { label: 'ID', value: item.id || '-', mono: true },
              { label: 'Modules', value: modulesText, mono: true, multiline: modulesText.includes('\n') },
              { label: 'Execs', value: execsText, mono: true },
              { label: 'Platform package', value: data.package_key || '-', mono: true },
              { label: 'Source', value: item.source || data.source || data.package_source || '-' },
            ],
          },
          {
            title: 'Install status',
            rows: [
              { label: 'Status', value: data.installed ? 'Installed' : (data.installed === false ? 'Not installed' : 'Unknown') },
              { label: 'Install dir', value: data.install_dir || '-', mono: true },
              { label: 'Exec paths', value: this.formatExecMap(data.exec_paths), mono: true, multiline: true },
            ],
          },
          {
            title: 'Package cache',
            rows: [
              { label: 'Cached package', value: (data.cache?.exists || data.cache?.cached || data.cached) ? 'Yes' : 'No' },
              { label: 'Cache path', value: data.cache?.cache_path || data.cache_path || '-', mono: true },
              { label: 'Cache dir', value: data.cache?.cache_dir || '-', mono: true },
              { label: 'Cache size', value: data.cache?.size ? this.formatBytes(data.cache.size) : '-' },
              { label: 'Cache mtime', value: data.cache?.mtime || '-' },
            ],
          },
          {
            title: 'Install log',
            rows: [
              { label: 'Path', value: data.install_log_path || '-', mono: true },
              { label: 'Log', value: data.install_log || 'No install log available.', mono: true, multiline: true },
            ],
          },
        ],
      })
    },

    async copyInstallCommand(item) {
      const data = await this.getInstallStatusForAction(item)
      if (!data) return
      const command = this.formatCommandMap(data)
      if (!command || command === '-') {
        ElMessage.warning('No command available to copy')
        return
      }
      try {
        if (window.isSecureContext && navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
          await navigator.clipboard.writeText(command)
        } else {
          this.copyTextFallback(command)
        }
        ElMessage.success(data.installed ? 'Command copied' : 'Command copied; package is not installed yet')
      } catch (e) {
        try {
          this.copyTextFallback(command)
          ElMessage.success(data.installed ? 'Command copied' : 'Command copied; package is not installed yet')
        } catch (_) {
          ElMessage.error('Failed to copy command')
        }
      }
    },

    copyTextFallback(text) {
      const textarea = document.createElement('textarea')
      textarea.value = String(text || '')
      textarea.setAttribute('readonly', '')
      textarea.style.position = 'fixed'
      textarea.style.left = '-9999px'
      textarea.style.top = '0'
      textarea.style.opacity = '0'
      document.body.appendChild(textarea)
      textarea.focus()
      textarea.select()
      textarea.setSelectionRange(0, textarea.value.length)
      const ok = document.execCommand('copy')
      document.body.removeChild(textarea)
      if (!ok) throw new Error('Fallback copy failed')
    },

    showDetailDialog({ title = '', subtitle = '', sections = [], copyText = '' } = {}) {
      this.detailDialogTitle = title || 'Details'
      this.detailSubtitle = subtitle || ''
      this.detailSections = (sections || []).map(section => ({
        title: section.title || 'Details',
        rows: (section.rows || []).filter(row => row && row.label),
      })).filter(section => section.rows.length)
      this.detailCopyText = copyText || ''
      this.detailDialogVisible = true
    },

    stringifyDetailValue(value) {
      if (value === undefined || value === null || value === '') return '-'
      if (typeof value === 'string') return value
      try {
        return JSON.stringify(value, null, 2)
      } catch (_) {
        return String(value)
      }
    },

    formatDetailValue(value) {
      return this.stringifyDetailValue(value)
    },

    async copyDetailText() {
      if (!this.detailCopyText) return
      try {
        if (window.isSecureContext && navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
          await navigator.clipboard.writeText(this.detailCopyText)
        } else {
          this.copyTextFallback(this.detailCopyText)
        }
        ElMessage.success('Copied')
      } catch (e) {
        try {
          this.copyTextFallback(this.detailCopyText)
          ElMessage.success('Copied')
        } catch (_) {
          ElMessage.error('Failed to copy')
        }
      }
    },

    async previewStartCommand() {
      const item = this.pendingItem
      if (!item || this.isOneshotModule(item)) return

      try {
        this.previewingCommand = true
        const params = this.buildStartParams()
        const instanceId = this.deriveInstanceId(params)
        const targetDeviceId = this.normalizeDeviceId(this.getActionDeviceId(this.getPackageForModule(item)))
        if (!targetDeviceId) throw new Error('Please select a target machine')

        const requestPlatform = this.getPlatformForConnectionId(targetDeviceId)
        const requestArch = this.getArchForConnectionId(targetDeviceId)
        if (!requestPlatform || !requestArch) {
          throw new Error(`Unable to resolve target platform/arch for client ${targetDeviceId}`)
        }

        const launcherOverride = this.buildLauncherOverride()
        const requestPayload = {
          params,
          instance_id: instanceId,
          platform: requestPlatform,
          arch: requestArch,
        }
        if (launcherOverride) requestPayload.launcher_override = launcherOverride

        const data = await externalToolsApi.previewClientInstanceCommand(
          targetDeviceId,
          item.id,
          requestPayload,
          this.buildJsonHeaders(),
        )
        const shellCommand = String(data?.shell_command || data?.command || '').trim()
        if (!shellCommand) throw new Error('Preview returned an empty command')

        this.showDetailDialog({
          title: `Preview Command - ${item.display_name || item.id}`,
          subtitle: `${this.activeDeviceFilterLabel} / ${instanceId}`,
          sections: [
            {
              title: 'Final command',
              rows: [
                { label: 'Shell', value: data?.shell || '-', mono: true },
                { label: 'Working directory', value: data?.cwd || '-', mono: true, multiline: true },
                { label: 'Command', value: shellCommand, mono: true, multiline: true },
              ],
            },
          ],
          copyText: shellCommand,
        })
      } catch (e) {
        ElMessage.error(e.message || 'Failed to preview external tool command')
      } finally {
        this.previewingCommand = false
      }
    },

    async confirmStart() {
      if (this.submitting) return

      const item = this.pendingItem
      if (!item) return
      try {
        this.submitting = true
        const params = this.buildStartParams()
        if (this.isOneshotModule(item)) {
          const result = await this.runClientOneshot(item, params)
          this.resetStartDialog()
          this.openOneshotResultDialog(item, result)
          return
        }

        const instanceId = this.deriveInstanceId(params)
        const launcherOverride = this.buildLauncherOverride()
        await this.startClientInstance(item, params, instanceId, false, '', launcherOverride)
        this.resetStartDialog()
      } catch (e) {
        ElMessage.error(e.message || 'Failed to run external tool')
      } finally {
        this.submitting = false
      }
    },


    async startClientInstance(item, params, instanceId, installIfNeeded = false, deviceId = '', launcherOverride = null) {
      const targetDeviceId = this.normalizeDeviceId(deviceId || this.getActionDeviceId(this.getPackageForModule(item)))
      if (!targetDeviceId) throw new Error('Please select a target machine')

      const requestPlatform = this.getPlatformForConnectionId(targetDeviceId)
      const requestArch = this.getArchForConnectionId(targetDeviceId)
      this.logExternalToolTarget('start-client-instance', item, {
        request_client_id: targetDeviceId,
        request_platform: requestPlatform,
        request_arch: requestArch,
      })
      if (!requestPlatform || !requestArch) throw new Error(`Unable to resolve target platform/arch for client ${targetDeviceId}`)

      const requestPayload = {
        params,
        instance_id: instanceId,
        install_if_needed: false,
        platform: requestPlatform,
        arch: requestArch,
      }
      if (launcherOverride) requestPayload.launcher_override = launcherOverride

      const data = await externalToolsApi.startClientInstance(
        targetDeviceId,
        item.id,
        requestPayload,
        this.buildJsonHeaders(),
      )
      ElMessage.success(data?.message || 'Client instance started')
      if (data?.install) this.setInstallStatus(this.getPackageForModule(item), targetDeviceId, data.install)
      await this.loadClientInstances(item.id, targetDeviceId, false)
    },


    async runClientOneshot(item, params, deviceId = '') {
      const targetDeviceId = this.normalizeDeviceId(deviceId || this.getActionDeviceId(this.getPackageForModule(item)))
      if (!targetDeviceId) throw new Error('Please select a target machine')

      const requestPlatform = this.getPlatformForConnectionId(targetDeviceId)
      const requestArch = this.getArchForConnectionId(targetDeviceId)
      this.logExternalToolTarget('run-client-oneshot', item, {
        request_client_id: targetDeviceId,
        request_platform: requestPlatform,
        request_arch: requestArch,
      })
      if (!requestPlatform || !requestArch) throw new Error(`Unable to resolve target platform/arch for client ${targetDeviceId}`)

      const data = await externalToolsApi.runClientOneshot(
        targetDeviceId,
        item.id,
        {
          params,
          platform: requestPlatform,
          arch: requestArch,
        },
        this.buildJsonHeaders(),
      )
      if (data?.install) this.setInstallStatus(this.getPackageForModule(item), targetDeviceId, data.install)
      return data || {}
    },

    openOneshotResultDialog(item, result) {
      this.oneshotResult = result || {}
      this.oneshotDialogTitle = `${item?.display_name || item?.id || 'External Tool'} Result`
      this.oneshotDialogVisible = true
      if (result?.success) {
        ElMessage.success(result.message || 'External tool completed')
      } else {
        ElMessage.error(result?.message || 'External tool failed')
      }
    },

    formatOneshotSummary(result) {
      if (!result) return ''
      const pieces = [
        result.side || '',
        result.status || '',
        `exit=${result.returncode ?? '-'}`,
        result.duration_sec !== undefined && result.duration_sec !== null ? `${result.duration_sec}s` : '',
        result.run_id || '',
      ].filter(Boolean)
      return pieces.join(' / ')
    },

    async copyOneshotResult() {
      const text = this.stringifyDetailValue(this.oneshotResult || {})
      try {
        if (window.isSecureContext && navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
          await navigator.clipboard.writeText(text)
        } else {
          this.copyTextFallback(text)
        }
        ElMessage.success('Copied')
      } catch (_) {
        ElMessage.error('Failed to copy')
      }
    },

    normalizeInstanceRow(item, instance, deviceId = '') {
      const runtime = instance.runtime || {}
      const config = instance.config || {}
      const params = instance.params || {}
      const configPath = config.target || instance.config_file || ''
      const normalizedDeviceId = this.normalizeDeviceId(deviceId)
      const machineId = this.getMachineIdForConnectionId(normalizedDeviceId)
      const hostname = this.getHostnameForConnectionId(normalizedDeviceId)
      return {
        row_key: `client:${normalizedDeviceId}:${item.id}:${instance.instance_id}`,
        device_id: normalizedDeviceId,
        connection_id: normalizedDeviceId,
        machine_id: machineId,
        machine_label: this.getMachineLabel(machineId, normalizedDeviceId),
        hostname,
        tool_id: instance.tool_id || item.id,
        package_id: instance.package_id || item.package_id || '',
        module_id: instance.module_id || item.module_id || '',
        display_name: instance.display_name || item.display_name || item.id,
        instance_id: instance.instance_id || 'default',
        status: instance.status || 'unknown',
        running: !!instance.running,
        pid: instance.pid || '',
        exec_path: instance.exec_path || instance.executable_path || runtime.argv?.[0] || '',
        config_path: configPath,
        stdout: instance.stdout || runtime.stdout || '',
        stderr: instance.stderr || runtime.stderr || '',
        pid_file: instance.pid_file || runtime.pid_file || '',
        state_file: instance.state_file || runtime.state_file || '',
        argv: instance.argv || runtime.argv || [],
        cwd: instance.cwd || runtime.cwd || '',
        params,
        started_at: instance.started_at || '',
        stopped_at: instance.stopped_at || '',
        module: item,
        raw: instance,
      }
    },

    // formatPortInfo(row) {
    //   const params = row.params || {}
    //   if (params.local_port || params.remote_port) {
    //     const localIp = params.local_ip || '127.0.0.1'
    //     const localPort = params.local_port || '-'
    //     const remotePort = params.remote_port || '-'
    //     return `${localIp}:${localPort} -> server:${remotePort}`
    //   }
    //   if (params.bind_port) return `bind:${params.bind_port}`
    //   if (params.server_port) return `control:${params.server_port}`
    //   return '-'
    // },



    formatPortInfo(row) {
  const params = row.params || {}

  // 1. 端口映射类，优先展示完整映射关系，比如 frpc。
  if (params.local_port || params.remote_port) {
    const localIp = params.local_ip || params.local_addr || params.local_host || '127.0.0.1'
    const localPort = params.local_port || '-'
    const remoteHost = params.remote_host || params.server_addr || 'server'
    const remotePort = params.remote_port || '-'
    return `${localIp}:${localPort} -> ${remoteHost}:${remotePort}`
  }

  // 2. 服务监听类，比如 filebrowser、http server、web ui。
  const listenPort =
    params.port ||
    params.listen_port ||
    params.http_port ||
    params.web_port ||
    params.ui_port ||
    params.dashboard_port ||
    params.rtsp_port ||
    params.hls_port ||
    params.webrtc_port

  if (listenPort) {
    const listenHost =
      params.address ||
      params.listen_addr ||
      params.listen_address ||
      params.host ||
      params.bind_addr ||
      params.bind_address ||
      params.ip ||
      '127.0.0.1'

    return `${listenHost}:${listenPort}`
  }

  // 3. 服务端 bind 类，比如 frps。
  if (params.bind_port) {
    const bindHost = params.bind_addr || params.bind_address || params.address || '0.0.0.0'
    return `${bindHost}:${params.bind_port}`
  }

  // 4. 控制端口类，比如 frpc 连接 frps 的 server_port。
  if (params.server_port) {
    const serverHost = params.server_addr || params.server_host || 'server'
    return `${serverHost}:${params.server_port}`
  }

  // 5. 如果 meta 里直接给了 URL，也可以显示。
  const url =
    params.url ||
    params.http_url ||
    params.web_url ||
    params.publish_url ||
    params.public_url

  if (url) return String(url)

  return '-'
},

    statusTagType(status) {
      const value = String(status || '').toLowerCase()
      if (value === 'running') return 'success'
      if (value === 'stale' || value === 'error') return 'danger'
      if (value === 'stopped') return 'info'
      return 'info'
    },

    shortTime(value) {
      const text = String(value || '').trim()
      if (!text) return '-'
      return text.replace('T', ' ').slice(0, 19)
    },

    async stopInstance(row) {
      try {
        await ElMessageBox.confirm(
          `Stop instance ${row.tool_id}/${row.instance_id}?`,
          'Stop External Tool Instance',
          { type: 'warning', confirmButtonText: 'Stop', cancelButtonText: 'Cancel' },
        )
      } catch (_) {
        return
      }
      try {
        await this.stopClientInstance(row)
        ElMessage.success(`Stop requested: ${row.instance_id}`)
      } catch (e) {
        ElMessage.error(e.message || 'Failed to stop instance')
      }
    },


    async stopClientInstance(row) {
      const deviceId = this.normalizeDeviceId(row.device_id)
      if (!deviceId) throw new Error('Client instance row is missing device_id')
      await externalToolsApi.stopClientInstance(deviceId, row.tool_id, row.instance_id, {}, this.buildJsonHeaders())
      await this.loadClientInstances(row.tool_id, deviceId, false)
    },

    async openInstanceLogs(row) {
      this.currentLogRow = row
      await this.readLogs(row, true)
    },

    async refreshCurrentLogs() {
      if (!this.currentLogRow) return
      await this.readLogs(this.currentLogRow, true)
    },

    async readLogs(row, openDialog = false) {
      try {
        this.logLoading = true
        const data = await this.readClientLogs(row)
        this.logDialogTitle = `${row.tool_id}/${row.instance_id} logs`
        this.logFilePath = data.log_file || row.stdout || ''
        this.logContent = data.content || ''
        if (openDialog) this.logDialogVisible = true
        this.scrollLogsToBottom()
      } catch (e) {
        ElMessage.error(e.message || 'Failed to read logs')
      } finally {
        this.logLoading = false
      }
    },


    async readClientLogs(row) {
      const deviceId = this.normalizeDeviceId(row.device_id)
      if (!deviceId) throw new Error('Client instance row is missing device_id')
      return externalToolsApi.readClientInstanceLogs(deviceId, row.tool_id, row.instance_id, { max_bytes: 65536 }, this.buildJsonHeaders())
    },

    scrollLogsToBottom() {
      this.$nextTick(() => {
        const el = this.$refs.logContentRef
        if (el && typeof el.scrollTop === 'number') {
          el.scrollTop = el.scrollHeight || 0
        }
      })
    },




    openInstanceInfo(row) {
      const runtime = row.raw?.runtime || {}
      const params = row.params || {}
      this.showDetailDialog({
        title: `${row.tool_id}/${row.instance_id} info`,
        subtitle: row.machine_label || row.machine_id,
        copyText: row.exec_path || '',
        sections: [
          {
            title: 'Overview',
            rows: [
              { label: 'Machine', value: row.machine_label || row.machine_id },
              { label: 'Machine ID', value: row.machine_id, mono: true },
              { label: 'Connection ID', value: row.connection_id || '-', mono: true },
              { label: 'Hostname', value: row.hostname || '-' },
              { label: 'Tool', value: row.tool_id, mono: true },
              { label: 'Instance', value: row.instance_id, mono: true },
              { label: 'Status', value: row.status },
              { label: 'PID', value: row.pid || '-' },
              { label: 'Port', value: this.formatPortInfo(row), mono: true },
              { label: 'Started', value: this.shortTime(row.started_at) },
              { label: 'Stopped', value: this.shortTime(row.stopped_at) },
              { label: 'Message', value: row.raw?.message || '-' },
            ],
          },
          {
            title: 'Runtime paths',
            rows: [
              { label: 'Executable', value: row.exec_path || runtime.argv?.[0] || '-', mono: true },
              { label: 'CWD', value: row.cwd || runtime.cwd || '-', mono: true },
              { label: 'Config', value: row.config_path || '-', mono: true },
              { label: 'Log', value: row.stdout || '-', mono: true },
              { label: 'Stderr', value: row.stderr || '-', mono: true },
              { label: 'PID file', value: row.pid_file || '-', mono: true },
              { label: 'State file', value: row.state_file || '-', mono: true },
              { label: 'Argv', value: row.argv?.length ? row.argv : (runtime.argv || []), mono: true, multiline: true },
            ],
          },
          { title: 'Params', rows: [{ label: 'Runtime params', value: params, mono: true, multiline: true }] },
        ],
      })
    },

    canModifyStoppedInstanceFiles(row) {
      if (!row || row.running) return false
      const status = String(row.status || '').toLowerCase()
      return status === 'stopped' || status === 'not_started' || status === 'error'
    },

    canRestartInstance(row) {
      if (!row || row.running) return false
      const status = String(row.status || '').toLowerCase()
      return status === 'stopped' || status === 'not_started' || status === 'error'
    },

    handleInstanceMoreCommand(command, row) {
      if (command === 'info') return this.openInstanceInfo(row)
      if (command === 'restart') return this.restartInstance(row)
      if (command === 'clear_logs') return this.clearInstanceLogs(row)
      if (command === 'remove') return this.removeInstance(row)
      return null
    },

    async restartInstance(row) {
      if (!this.canRestartInstance(row)) {
        ElMessage.warning('Please stop this instance before restarting it')
        return
      }
      try {
        await ElMessageBox.confirm(
          `Restart instance ${row.tool_id}/${row.instance_id} with the same params?`,
          'Restart External Tool Instance',
          { type: 'warning', confirmButtonText: 'Restart', cancelButtonText: 'Cancel' },
        )
      } catch (_) {
        return
      }
      try {
        await this.startClientInstance(row.module, row.params || {}, row.instance_id, false, row.connection_id || row.device_id)
        ElMessage.success(`Restarted: ${row.instance_id}`)
      } catch (e) {
        ElMessage.error(e.message || 'Failed to restart instance')
      }
    },

    async removeInstance(row) {
      if (!this.canModifyStoppedInstanceFiles(row)) {
        ElMessage.warning('Stop this instance first')
        return
      }
      try {
        await ElMessageBox.confirm(
          `Remove runtime files for instance ${row.tool_id}/${row.instance_id}?`,
          'Remove External Tool Instance',
          { type: 'warning', confirmButtonText: 'Remove', cancelButtonText: 'Cancel' },
        )
      } catch (_) {
        return
      }
      try {
        await this.removeClientInstance(row)
        ElMessage.success(`Removed: ${row.instance_id}`)
      } catch (e) {
        ElMessage.error(e.message || 'Failed to remove instance')
      }
    },


    async removeClientInstance(row) {
      const deviceId = this.normalizeDeviceId(row.connection_id || row.device_id)
      if (!deviceId) throw new Error('Client instance row is missing connection_id/device_id')
      await externalToolsApi.removeClientInstance(deviceId, row.tool_id, row.instance_id, {}, this.buildJsonHeaders())
      await this.loadClientInstances(row.tool_id, deviceId, false)
    },

    async clearInstanceLogs(row) {
      if (!this.canModifyStoppedInstanceFiles(row)) {
        ElMessage.warning('Stop this instance first')
        return
      }
      try {
        await ElMessageBox.confirm(
          `Clear log file for instance ${row.tool_id}/${row.instance_id}?`,
          'Clear External Tool Logs',
          { type: 'warning', confirmButtonText: 'Clear Logs', cancelButtonText: 'Cancel' },
        )
      } catch (_) {
        return
      }
      try {
        await this.clearClientInstanceLogs(row)
        if (this.currentLogRow?.row_key === row.row_key) {
          this.logContent = ''
          this.scrollLogsToBottom()
        }
        ElMessage.success(`Logs cleared: ${row.instance_id}`)
      } catch (e) {
        ElMessage.error(e.message || 'Failed to clear logs')
      }
    },


    async clearClientInstanceLogs(row) {
      const deviceId = this.normalizeDeviceId(row.connection_id || row.device_id)
      if (!deviceId) throw new Error('Client instance row is missing connection_id/device_id')
      await externalToolsApi.clearClientInstanceLogs(deviceId, row.tool_id, row.instance_id, {}, this.buildJsonHeaders())
    },

formatVersionLabel(version) {
  const value = String(version || '').trim()
  if (!value) return ''

  // 已经带 v 的标准数字版本，直接返回，避免 vv1.2.3
  if (/^v\d+\.\d+(?:\.\d+)?$/i.test(value)) {
    return value
  }

  // 只有 x.x 或 x.x.x 这种纯数字版本才自动加 v
  if (/^\d+\.\d+(?:\.\d+)?$/.test(value)) {
    return `v${value}`
  }

  // snapshot、commit、custom tag 等原样显示
  return value
}

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

.external-tool-filter {
  width: 150px;
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

.external-tool-target-label {
  font-size: 12px;
  font-weight: 800;
  letter-spacing: .02em;
  color: var(--muted-2, #94a3b8);
  text-transform: uppercase;
}

.external-tool-target-select {
  width: 320px;
}

.external-tool-device-filter {
  width: 230px;
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

.external-tool-module-list {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-height: none;
  overflow: auto;
  padding-right: 4px;
}

.external-tool-package-split {
  flex: 1 1 auto;
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(280px, 360px) minmax(0, 1fr);
  gap: 14px;
  overflow: hidden;
}

.external-tool-package-list-panel,
.external-tool-package-detail-panel {
  min-height: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.external-tool-package-list {
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding-right: 4px;
}

.external-tool-package-list-card {
  cursor: pointer;
  transition: border-color 0.15s ease, box-shadow 0.15s ease, background 0.15s ease;
}

.external-tool-package-list-card.active {
  border-color: rgba(59, 130, 246, 0.45);
  box-shadow: 0 6px 18px rgba(37, 99, 235, 0.12);
  background: #f8fbff;
}

.external-tool-package-list-title {
  font-size: 15px;
  font-weight: 700;
  color: var(--text, #0f172a);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.external-tool-package-list-status {
  margin-top: 8px;
  min-height: 22px;
  display: flex;
  align-items: center;
}

.external-tool-package-list-status {
  margin-top: 8px;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.external-tool-package-list-mobile-meta-tag {
  display: none;
}

.external-tool-package-list-desc {
  margin-top: 8px;
  color: var(--muted, #64748b);
  font-size: 13px;
  line-height: 1.45;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.external-tool-package-mobile-detail {
  display: none;
}

.external-tool-package-detail-tags {
  margin-top: 8px;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.external-tool-package-detail-desc {
  margin-top: 12px;
}

.small-text {
  font-size: 12px;
}

.external-tool-package-detail-card {
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
  padding: 16px;
  border: 1px solid rgba(15, 23, 42, 0.06);
  border-radius: 14px;
  background: #fff;
  box-shadow: 0 4px 14px rgba(15, 23, 42, 0.04);
}

.external-tool-package-detail-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.external-tool-package-detail-main {
  min-width: 0;
  flex: 1 1 auto;
}

.external-tool-package-detail-actions {
  flex: 0 0 auto;
}

.external-tool-package-detail-action-row {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
}

.external-tool-package-detail-actions :deep(.el-button.external-tool-package-detail-action-button),
.external-tool-package-detail-actions :deep(.el-dropdown .el-button.external-tool-package-detail-action-button) {
  width: auto;
  min-width: 0;
  height: 26px;
  min-height: 26px;
  padding: 0 9px;
  border-radius: 7px;
  font-size: 12px;
  line-height: 24px;
  margin-left: 0;
}

.external-tool-title.large {
  font-size: 17px;
}

.external-tool-package-detail-section {
  margin-top: 18px;
}

.external-tool-package-modules.detail {
  margin-top: 10px;
}

.external-tool-card {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 14px;
  border: 1px solid rgba(15, 23, 42, 0.06);
  border-radius: 14px;
  background: #fff;
  box-shadow: 0 4px 14px rgba(15, 23, 42, 0.04);
}

.external-tool-card-main {
  min-width: 0;
  flex: 1;
}

.external-tool-title-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.external-tool-title {
  font-size: 15px;
  font-weight: 700;
  color: var(--text, #0f172a);
  max-width: 420px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.external-tool-desc {
  margin-top: 8px;
  color: var(--muted, #64748b);
  line-height: 1.45;
}

.external-tool-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 9px;
  color: var(--muted, #64748b);
  font-size: 12px;
}


.external-tool-oneshot-body {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.external-tool-oneshot-output {
  min-height: 140px;
  max-height: 260px;
}

.external-tool-package-modules {
  margin-top: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.external-tool-package-module-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 8px 10px;
  border: 1px solid rgba(15, 23, 42, 0.06);
  border-radius: 10px;
  background: #f8fafc;
}

.external-tool-package-module-main {
  min-width: 0;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.external-tool-modules-panel {
  padding: 14px;
  border: 1px solid rgba(15, 23, 42, 0.06);
  border-radius: 14px;
  background: #f8fafc;
}

.external-tool-package-module-card {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 12px;
  border: 1px solid rgba(15, 23, 42, 0.06);
  border-radius: 12px;
  background: #fff;
  box-shadow: 0 2px 10px rgba(15, 23, 42, 0.03);
}

.external-tool-package-module-content {
  min-width: 0;
  flex: 1 1 auto;
}

.external-tool-package-module-title-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.external-tool-package-module-desc {
  margin-top: 6px;
  color: var(--muted, #64748b);
  font-size: 13px;
  line-height: 1.45;
}

.strong {
  font-weight: 700;
}

.muted {
  color: var(--muted, #64748b);
}

.external-tool-actions {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  justify-content: flex-start;
  gap: 8px;
  min-width: 0;
  flex: 0 0 auto;
}

.external-tool-action-row {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
}

.external-tool-action-row.single {
  display: flex;
}

.external-tool-action-row :deep(.el-button),
.external-tool-action-row :deep(.el-dropdown),
.external-tool-action-row :deep(.el-dropdown .el-button) {
  width: auto;
  min-width: 0;
  margin-left: 0;
}

.external-tool-action-row :deep(.el-button) {
  height: 32px;
  min-height: 32px;
  border-radius: 10px;
  padding-inline: 14px;
}

.external-tool-table-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.external-tool-table-actions :deep(.el-button + .el-button) {
  margin-left: 0;
}

.external-tool-instance-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex: 0 0 auto;
  margin-bottom: 8px;
}

.external-tool-hint {
  color: var(--muted, #64748b);
  font-size: 12px;
}

.external-tool-instance-table-shell {
  flex: 0 0 auto;
  min-height: 0;
  height: 560px;
  overflow: hidden;
}

.external-tool-instance-table {
  width: 100%;
  height: 100% !important;
  border-radius: 12px;
  overflow: hidden;
}

.external-tool-instance-table :deep(.el-table__inner-wrapper),
.external-tool-instance-table :deep(.el-scrollbar),
.external-tool-instance-table :deep(.el-scrollbar__wrap) {
  height: 100% !important;
}

.external-tool-instance-table :deep(.el-scrollbar__wrap) {
  overflow-y: auto !important;
  overflow-x: auto !important;
}

.external-tool-instance-table :deep(.el-table__body-wrapper) {
  overflow-y: auto !important;
}

.external-tool-instance-table :deep(th.el-table__cell) {
  background: #f8fafc !important;
  color: #475569;
  font-weight: 700;
}

.external-tool-instance-table :deep(.el-table__body td.el-table__cell) {
  padding: 10px 0;
}

.external-tool-instance-table :deep(tr) {
  background: #fff;
}

.external-tool-instance-table :deep(.cell) {
  line-height: 1.55;
}

.external-tool-instance-card-shell,
.external-tool-instance-card-list {
  display: none;
}

.external-tool-instance-card-list {
  grid-template-columns: 1fr;
  gap: 12px;
  height: 100%;
  min-height: 0;
  overflow-y: auto;
  padding-right: 2px;
}

.external-tool-instance-card {
  background: #fff;
  border: 1px solid rgba(15, 23, 42, 0.06);
  border-radius: 14px;
  padding: 12px;
  box-shadow: 0 4px 14px rgba(15, 23, 42, 0.04);
}

.external-tool-instance-card-top {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  min-width: 0;
}

.external-tool-instance-icon {
  flex: 0 0 auto;
  width: 22px;
  height: 22px;
  margin-top: 2px;
  border-radius: 999px;
  background: #f8fafc;
  border: 1px solid rgba(15, 23, 42, 0.08);
  display: flex;
  align-items: center;
  justify-content: center;
}

.external-tool-instance-icon span {
  width: 8px;
  height: 8px;
  border-radius: 999px;
  background: var(--muted-2, #94a3b8);
}

.external-tool-instance-icon span.running {
  background: var(--el-color-success);
}

.external-tool-instance-icon span.stale {
  background: var(--el-color-danger);
}

.external-tool-instance-card-main {
  min-width: 0;
  flex: 1;
}

.external-tool-instance-name {
  font-size: 14px;
  font-weight: 700;
  color: var(--text, #0f172a);
  line-height: 1.4;
  word-break: break-word;
}

.external-tool-instance-tags {
  margin-top: 10px;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.external-tool-instance-meta {
  margin-top: 8px;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 6px 10px;
}

.external-tool-instance-meta-item {
  min-width: 0;
}

.external-tool-instance-meta-label {
  font-size: 11px;
  color: var(--muted-2, #94a3b8);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.external-tool-instance-meta-value {
  margin-top: 2px;
  font-size: 12px;
  color: var(--text, #0f172a);
  word-break: break-word;
  line-height: 1.4;
}

.external-tool-instance-card-actions {
  margin-top: 12px;
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  align-items: stretch;
}

.external-tool-instance-card-actions :deep(.el-button),
.external-tool-instance-card-actions :deep(.el-dropdown),
.external-tool-instance-card-actions :deep(.el-dropdown .el-button) {
  width: 100%;
  min-width: 0;
  margin: 0;
}

.external-tool-instance-card-actions :deep(.el-button) {
  min-height: 32px;
  height: 32px;
  border-radius: 10px;
  padding-inline: 12px;
  justify-content: center;
}

.external-tool-instance-card-actions :deep(.el-dropdown) {
  display: block;
}

.path-line {
  max-width: 320px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.external-tool-empty {
  flex: 1 1 auto;
  min-height: 0;
  padding: 64px 16px;
  text-align: center;
  color: var(--muted, #64748b);
}

.external-tool-empty.small {
  padding: 20px 8px;
}

.external-tool-run-body {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.external-tool-run-summary {
  padding: 12px;
  border-radius: 10px;
  background: #f8fafc;
  line-height: 1.6;
}

.external-tool-preset-bar {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 12px;
  padding: 12px;
  border: 1px solid rgba(15, 23, 42, 0.06);
  border-radius: 10px;
  background: #f8fafc;
}

.external-tool-preset-field {
  flex: 1 1 auto;
  min-width: 0;
}

.external-tool-preset-label {
  margin-bottom: 6px;
  font-size: 12px;
  color: var(--muted, #64748b);
}

.external-tool-preset-select {
  width: 100%;
}

.external-tool-preset-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 0 0 auto;
}

.external-tool-preset-actions :deep(.el-button + .el-button) {
  margin-left: 0;
}

.external-tool-param-form {
  max-height: 460px;
  overflow: auto;
  padding-right: 4px;
}

.external-tool-number {
  width: 100%;
}

.external-tool-param-help {
  margin-top: 4px;
  color: var(--muted, #64748b);
  font-size: 12px;
  line-height: 1.45;
}

.external-tool-log-path {
  margin-bottom: 8px;
  padding: 8px 10px;
  border-radius: 8px;
  background: #f8fafc;
  color: var(--muted, #64748b);
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.external-tool-log-content {
  max-height: 560px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  padding: 12px;
  border-radius: 10px;
  background: #050505;
  color: #d9e2ff;
  border: 1px solid rgba(255,255,255,.12);
  scrollbar-color: #303544 #050505;
  scrollbar-width: thin;
}

.external-tool-log-content::-webkit-scrollbar {
  width: 10px;
  height: 10px;
}

.external-tool-log-content::-webkit-scrollbar-track {
  background: #050505;
  border-radius: 999px;
}

.external-tool-log-content::-webkit-scrollbar-thumb {
  background: #303544;
  border-radius: 999px;
  border: 2px solid #050505;
}

.external-tool-log-content::-webkit-scrollbar-thumb:hover {
  background: #495064;
}

.external-tool-detail-body {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.external-tool-detail-subtitle {
  padding: 0;
  border-radius: 0;
  background: transparent;
  color: var(--muted, #64748b);
  font-size: 12px;
}

.external-tool-detail-section {
  border: 0;
  border-radius: 0;
  overflow: visible;
  background: transparent;
}

.external-tool-detail-section-title {
  padding: 0 0 8px;
  font-weight: 700;
  border-bottom: 0;
  background: transparent;
}

.external-tool-detail-grid {
  display: grid;
  grid-template-columns: 1fr;
}

.external-tool-detail-row {
  display: grid;
  grid-template-columns: 150px minmax(0, 1fr);
  gap: 12px;
  padding: 7px 0;
  border-bottom: 0;
}

.external-tool-detail-row:last-child {
  border-bottom: 0;
}

.external-tool-detail-label {
  color: var(--muted, #64748b);
  font-size: 12px;
}

.external-tool-detail-value {
  min-width: 0;
  overflow: hidden;
}

.external-tool-detail-value.multiline {
  white-space: normal;
  overflow: visible;
}

.external-tool-detail-pre {
  margin: 0;
  max-height: 260px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  padding: 10px;
  border-radius: 8px;
  background: #050505;
  border: 1px solid rgba(255,255,255,.10);
  color: #d9e2ff;
  scrollbar-color: #303544 #050505;
  scrollbar-width: thin;
}

.external-tool-detail-pre::-webkit-scrollbar {
  width: 10px;
  height: 10px;
}

.external-tool-detail-pre::-webkit-scrollbar-track {
  background: #050505;
  border-radius: 999px;
}

.external-tool-detail-pre::-webkit-scrollbar-thumb {
  background: #303544;
  border-radius: 999px;
  border: 2px solid #050505;
}

.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
}

.strong {
  font-weight: 700;
}

.muted {
  color: var(--muted, #64748b);
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

  .external-tool-package-split {
    display: block;
    overflow: auto;
    padding-right: 4px;
  }

  .external-tool-package-list-panel {
    min-height: 0;
    max-height: none;
    overflow: visible;
  }

  .external-tool-package-list {
    overflow: visible;
    padding-right: 0;
  }

  .external-tool-package-detail-panel {
    display: none;
  }

  .external-tool-package-mobile-detail {
    display: block;
    margin-top: 12px;
    padding-top: 12px;
    border-top: 1px solid rgba(15, 23, 42, 0.08);
  }

  .external-tool-package-list-mobile-meta-tag {
    display: inline-flex;
  }

  .external-tool-package-mobile-actions {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 8px;
    margin-top: 12px;
  }

  .external-tool-package-mobile-actions :deep(.el-button),
  .external-tool-package-mobile-actions :deep(.el-dropdown),
  .external-tool-package-mobile-actions :deep(.el-dropdown .el-button) {
    width: 100%;
    min-width: 0;
    margin: 0;
  }

  .external-tool-package-mobile-actions :deep(.el-button) {
    min-height: 32px;
    height: 32px;
    border-radius: 10px;
    padding-inline: 12px;
    justify-content: center;
  }

  .external-tool-package-mobile-actions :deep(.el-dropdown) {
    display: block;
  }

  .external-tool-package-mobile-modules {
    margin-top: 12px;
  }

  .external-tool-package-mobile-modules .external-tool-package-module-card {
    flex-direction: column;
    align-items: stretch;
  }

  .external-tool-package-mobile-modules .external-tool-package-module-card > .el-button {
    width: 100%;
    min-height: 32px;
    height: 32px;
    border-radius: 10px;
    padding-inline: 12px;
    justify-content: center;
    margin-left: 0;
  }

}

@media (max-width: 768px), (max-height: 720px) {
  .external-tool-instance-table-shell {
    display: none !important;
  }

  .external-tool-instance-card-shell {
    display: flex !important;
    flex: 1 1 auto !important;
    min-height: 0 !important;
    overflow: hidden !important;
  }

  .external-tool-instance-card-list {
    display: grid !important;
    flex: 1 1 auto !important;
    min-height: 0 !important;
    overflow-y: auto !important;
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

  .external-tool-card {
    flex-direction: column;
    gap: 12px;
  }

  .external-tool-title {
    flex: 0 0 100%;
    max-width: 100%;
  }

  
.external-tool-oneshot-body {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.external-tool-oneshot-output {
  min-height: 140px;
  max-height: 260px;
}

.external-tool-package-modules {
  margin-top: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.external-tool-package-module-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 8px 10px;
  border: 1px solid rgba(15, 23, 42, 0.06);
  border-radius: 10px;
  background: #f8fafc;
}

.external-tool-package-module-main {
  min-width: 0;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.strong {
  font-weight: 700;
}

.muted {
  color: var(--muted, #64748b);
}

.external-tool-actions {
    width: 100%;
    align-items: stretch;
    min-width: 0;
  }

  .external-tool-action-row,
  .external-tool-action-row.single {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    justify-content: stretch;
    width: 100%;
  }

  .external-tool-action-row :deep(.el-button),
  .external-tool-action-row :deep(.el-dropdown),
  .external-tool-action-row :deep(.el-dropdown .el-button) {
    width: 100%;
  }

  .external-tool-package-module-card {
    flex-direction: column;
  }

  .external-tool-package-module-card > .el-button {
    width: 100%;
  }

  .external-tool-instance-meta {
    grid-template-columns: 1fr;
  }

  .external-tool-instance-card-actions {
    grid-template-columns: 1fr;
    gap: 6px;
  }

  .external-tool-detail-row {
    grid-template-columns: 1fr;
    gap: 4px;
  }
}
.external-tool-file-param {
  width: 100%;
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

@media (max-width: 768px), (max-height: 720px) {
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
