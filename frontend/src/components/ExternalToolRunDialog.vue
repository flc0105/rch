<template>
  <el-dialog
    :key="dialogKey"
    v-model="startDialogVisible"
    :title="startDialogTitle"
    width="650px"
    append-to-body
    @close="resetStartDialog"
  >
    <div v-if="pendingItem" class="external-tool-run-body">
      <div class="external-tool-run-summary">
        <div><strong>{{ pendingItem.display_name || pendingItem.id }}</strong></div>
        <div class="mono">{{ pendingItem.id }} / {{ target.label }}</div>
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
        <ParamFormField
          v-for="param in pendingParams"
          :key="param.name"
          :param="param"
          :model-value="paramForm[param.name]"
          :form-values="paramForm"
          @update:model-value="paramForm[param.name] = $event"
          @browse="openRemoteFilePicker"
          @pick-keychain="openKeychainPicker"
        />

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
    :key="`remote-${generation}`"
    v-model:visible="remoteFilePickerVisible"
    :selected-id="target.clientId || ''"
    :multiple="pendingRemoteFileParamMultiple"
    :initial-path="pendingRemoteFileParamInitialPath"
    :selection-mode="pendingRemoteFileParamSelectionMode"
    :get-tab-scoped-headers="getTabScopedHeaders"
    @select="handleRemoteFileSelected"
    @append-output="forwardAppendOutput"
    @set-active-task="forwardSetActiveTask"
    @upload-started="forwardRemoteUploadStarted"
  />

  <KeychainPicker
    :key="`keychain-${generation}`"
    v-model:visible="keychainPickerVisible"
    :machine-id="target.machineId || ''"
    :kind="pendingKeychainParam?.keychain_picker?.kind || 'secret'"
    @select="handleKeychainSelected"
  />
</template>

<script>
import { ElMessage, ElMessageBox } from 'element-plus'
import * as externalToolsApi from '../api/externalToolsApi.js'
import RemoteFilePicker from './RemoteFilePicker.vue'
import KeychainPicker from './KeychainPicker.vue'
import ParamFormField from './ParamFormField.vue'
import { cloneParamValue, isRemoteMultiParam, mapKeychainPickerValues, normalizeParamSpecs, normalizeParamType, remoteParamInitialPath, remoteParamSelectionMode } from '../utils/parameterSchema.js'
import { getModuleLauncher, getModuleExecution, isOneshotModule } from '../utils/externalToolPresentation.js'

export default {
  name: 'ExternalToolRunDialog',
  components: { RemoteFilePicker, KeychainPicker, ParamFormField },
  props: {
    executeRun: { type: Function, required: true },
    getTabScopedHeaders: { type: Function, default: null },
  },
  emits: ['append-output', 'set-active-task', 'upload-started', 'show-detail', 'show-result'],
  data() {
    return {
      submitting: false,
      previewingCommand: false,
      presetLoading: false,
      presetSaving: false,
      startDialogVisible: false,
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
      keychainPickerVisible: false,
      pendingKeychainParam: null,
      pendingItem: null,
      target: {},
      generation: 0,
      dialogKey: 0,
    }
  },
  computed: {
    pendingParams() {
      return normalizeParamSpecs(this.pendingItem?.params)
    },

    pendingLauncherConfig() {
      return this.getModuleLauncher(this.pendingItem)
    },

    pendingRemoteFileParamMultiple() {
      return isRemoteMultiParam(this.pendingRemoteFileParam || {})
    },

    pendingRemoteFileParamSelectionMode() {
      return remoteParamSelectionMode(this.pendingRemoteFileParam || {})
    },

    pendingRemoteFileParamInitialPath() {
      const param = this.pendingRemoteFileParam || {}
      return remoteParamInitialPath(param, this.paramForm?.[param.name])
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
  methods: {
    getModuleLauncher, getModuleExecution, isOneshotModule,
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

    openKeychainPicker(param) {
      if (!param?.name || !param?.keychain_picker) return
      this.pendingKeychainParam = param
      this.keychainPickerVisible = true
    },

    handleKeychainSelected(item) {
      const param = this.pendingKeychainParam
      if (!param) return
      const values = mapKeychainPickerValues(param, item, this.pendingParams)
      if (!values) {
        ElMessage.error('The selected credential does not match this parameter')
        return
      }
      this.paramForm = {
        ...this.paramForm,
        ...values,
      }
      this.pendingKeychainParam = null
      this.keychainPickerVisible = false
    },

    loadRemoteFilePickerDirectory(path = '') {
      return this.$refs.remoteFilePickerRef?.loadRemoteDirectory(path || '', 1)
    },

    forwardAppendOutput(clientId, line, kind, meta) {
      this.$emit('append-output', clientId, line, kind, meta)
    },

    forwardSetActiveTask(clientId, taskId, cancelPolicy = '', historyEntryId = '', operationId = '') {
      this.$emit('set-active-task', clientId, taskId, cancelPolicy, historyEntryId, operationId)
    },

    forwardRemoteUploadStarted(payload) {
      this.$emit('upload-started', {
        ...(payload && typeof payload === 'object' ? payload : {}),
        source: 'external_tool_remote_file_picker',
      })
    },

    buildParamDefaults(item) {
      const form = {}
      for (const param of normalizeParamSpecs(item?.params)) {
        const name = String(param?.name || '').trim()
        if (!name) continue

        const type = normalizeParamType(param?.type)
        if (name === 'instance_name' && (param.default === undefined || param.default === null || String(param.default).trim() === '')) {
          form[name] = this.defaultInstanceName(item)
        } else if (param.default !== undefined && param.default !== null) {
          form[name] = cloneParamValue(param.default)
        } else if (['remote_files', 'remote_folders'].includes(type)) {
          form[name] = []
        } else if (type === 'boolean') {
          form[name] = false
        } else {
          form[name] = ''
        }
      }
      return form
    },

    applyParamPreset(preset) {
      const item = this.pendingItem
      const form = this.buildParamDefaults(item)
      const params = preset?.params && typeof preset.params === 'object' ? preset.params : {}
      for (const [name, value] of Object.entries(params)) {
        if (!Object.prototype.hasOwnProperty.call(form, name)) continue
        form[name] = cloneParamValue(value)
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
      const generation = this.generation
      this.paramPresets = []
      this.selectedParamPresetId = '__module_defaults__'
      if (!toolId) return

      try {
        this.presetLoading = true
        const data = await externalToolsApi.loadExternalToolParamPresets(toolId)
        if (generation !== this.generation) return
        this.paramPresets = Array.isArray(data?.items) ? data.items : []
      } catch (e) {
        if (generation === this.generation) ElMessage.error(e.message || 'Failed to load parameter presets')
      } finally {
        if (generation === this.generation) this.presetLoading = false
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
      const generation = this.generation
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

        if (generation !== this.generation) return
        this.presetSaving = true
        const created = await externalToolsApi.createExternalToolParamPreset(item.id, { name, params })
        if (generation !== this.generation) return
        this.upsertParamPreset(created)
        this.selectedParamPresetId = String(created?.preset_id || '')
        ElMessage.success(`Preset saved: ${created?.name || name}`)
      } catch (e) {
        if (e === 'cancel' || e === 'close' || e?.action === 'cancel' || e?.action === 'close') return
        if (generation === this.generation) ElMessage.error(e.message || 'Failed to save parameter preset')
      } finally {
        if (generation === this.generation) this.presetSaving = false
      }
    },

    async updateCurrentParamPreset() {
      const generation = this.generation
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
        if (generation !== this.generation) return
        this.presetSaving = true
        const updated = await externalToolsApi.updateExternalToolParamPreset(item.id, preset.preset_id, { params })
        if (generation !== this.generation) return
        this.upsertParamPreset(updated)
        ElMessage.success(`Preset updated: ${updated?.name || preset.name}`)
      } catch (e) {
        if (e === 'cancel' || e === 'close' || e?.action === 'cancel' || e?.action === 'close') return
        if (generation === this.generation) ElMessage.error(e.message || 'Failed to update parameter preset')
      } finally {
        if (generation === this.generation) this.presetSaving = false
      }
    },

    async deleteCurrentParamPreset() {
      const generation = this.generation
      const item = this.pendingItem
      const preset = this.currentParamPreset()
      if (!item || !preset) return

      try {
        await ElMessageBox.confirm(
          `Delete preset "${preset.name}"?`,
          'Delete Parameter Preset',
          { confirmButtonText: 'Delete', cancelButtonText: 'Cancel', type: 'warning' },
        )
        if (generation !== this.generation) return
        this.presetSaving = true
        await externalToolsApi.deleteExternalToolParamPreset(item.id, preset.preset_id)
        if (generation !== this.generation) return
        this.paramPresets = this.paramPresets.filter(entry => entry?.preset_id !== preset.preset_id)
        this.selectedParamPresetId = '__module_defaults__'
        this.paramForm = this.buildParamDefaults(item)
        ElMessage.success(`Preset deleted: ${preset.name}`)
      } catch (e) {
        if (e === 'cancel' || e === 'close' || e?.action === 'cancel' || e?.action === 'close') return
        if (generation === this.generation) ElMessage.error(e.message || 'Failed to delete parameter preset')
      } finally {
        if (generation === this.generation) this.presetSaving = false
      }
    },

    defaultInstanceName(item) {
      if (item?.name === 'frps') return 'frps-7000'
      if (item?.name === 'frpc') return 'vite-8087'
      return 'default'
    },

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
      if (!this.getModuleLauncher(item)) return

      const toolId = String(item?.id || '').trim()
      const generation = this.generation
      try {
        this.launcherResolving = true
        this.launcherResolveError = ''
        const targetDeviceId = this.target.clientId
        if (!targetDeviceId) throw new Error('Please select a target machine')

        const requestPlatform = this.target.platform
        const requestArch = this.target.arch
        if (!requestPlatform || !requestArch) {
          throw new Error(`Unable to resolve target platform/arch for client ${targetDeviceId}`)
        }

        const data = await externalToolsApi.resolveClientLauncher(
          targetDeviceId,
          toolId,
          { platform: requestPlatform, arch: requestArch },
          this.buildJsonHeaders(),
        )
        if (generation !== this.generation) return

        const executable = String(data?.executable || '').trim()
        if (!executable) throw new Error('Client returned an empty launcher executable')
        this.launcherDefaultExecutable = executable
        this.launcherExecutable = executable
        this.launcherOverrideDirty = false
      } catch (e) {
        if (generation !== this.generation) return
        this.launcherDefaultExecutable = ''
        this.launcherExecutable = ''
        this.launcherOverrideDirty = false
        this.launcherResolveError = `Default launcher unavailable: ${e.message || e}`
      } finally {
        if (generation === this.generation) this.launcherResolving = false
      }
    },

    buildStartParams() {
      const params = {}
      for (const param of this.pendingParams || []) {
        const name = String(param?.name || '').trim()
        if (!name) continue

        const type = normalizeParamType(param?.type)
        let value = this.paramForm[name]

        const hasRemoteMultiValue = ['remote_files', 'remote_folders'].includes(type) && Array.isArray(value) && value.length > 0
        if (param.required && !hasRemoteMultiValue && (value === '' || value === undefined || value === null)) {
          throw new Error(`Param ${name} is required`)
        }

        if (['remote_files', 'remote_folders'].includes(type)) {
          if (!Array.isArray(value)) throw new Error(`Param ${name} must be a path list`)
          params[name] = value.map(item => String(item || '').trim()).filter(Boolean)
        } else if (['remote_file', 'remote_folder'].includes(type)) {
          if (Array.isArray(value)) throw new Error(`Param ${name} must be a single path`)
          params[name] = String(value || '').trim()
        } else if (type === 'select') {
          const text = value === null || value === undefined ? '' : String(value)
          if (Array.isArray(param.options) && param.options.length && !param.options.map(String).includes(text)) {
            throw new Error(`Param ${name} has invalid option`)
          }
          params[name] = value
        } else {
          params[name] = value
        }
      }

      return params
    },

    open(item, target) {
      this.resetStartDialog()
      this.dialogKey += 1
      this.pendingItem = item
      this.target = { ...target }
      this.paramForm = this.buildParamDefaults(item)
      this.startDialogVisible = true
      this.loadParamPresets(item)
      this.loadPendingLauncher(item)
    },

    resetStartDialog() {
      this.generation += 1
      this.startDialogVisible = false
      this.remoteFilePickerVisible = false
      this.keychainPickerVisible = false
      this.pendingRemoteFileParam = null
      this.pendingKeychainParam = null
      this.submitting = false
      this.previewingCommand = false
      this.presetLoading = false
      this.presetSaving = false
      this.pendingItem = null
      this.target = {}
      this.paramForm = {}
      this.resetLauncherFormState()
      this.paramPresets = []
      this.selectedParamPresetId = '__module_defaults__'
    },

    async previewStartCommand() {
      const generation = this.generation
      const item = this.pendingItem
      if (!item || this.isOneshotModule(item)) return

      try {
        this.previewingCommand = true
        const params = this.buildStartParams()
        const targetDeviceId = this.target.clientId
        if (!targetDeviceId) throw new Error('Please select a target machine')

        const requestPlatform = this.target.platform
        const requestArch = this.target.arch
        if (!requestPlatform || !requestArch) {
          throw new Error(`Unable to resolve target platform/arch for client ${targetDeviceId}`)
        }

        const launcherOverride = this.buildLauncherOverride()
        const requestPayload = {
          params,
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
        if (generation !== this.generation) return
        const shellCommand = String(data?.shell_command || data?.command || '').trim()
        if (!shellCommand) throw new Error('Preview returned an empty command')
        const instanceId = String(data?.instance_id || 'default').trim() || 'default'

        this.$emit('show-detail', {
          title: `Preview Command - ${item.display_name || item.id}`,
          subtitle: `${this.target.label} / ${instanceId}`,
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
        if (generation === this.generation) ElMessage.error(e.message || 'Failed to preview external tool command')
      } finally {
        if (generation === this.generation) this.previewingCommand = false
      }
    },

    async confirmStart() {
      if (this.submitting) return
      const generation = this.generation
      const item = this.pendingItem
      const target = this.target
      if (!item) return
      try {
        this.submitting = true
        const params = this.buildStartParams()
        const launcherOverride = this.buildLauncherOverride()
        const result = await this.executeRun(item, params, target, launcherOverride)
        if (generation === this.generation) this.resetStartDialog()
        if (this.isOneshotModule(item)) this.$emit('show-result', item, result)
      } catch (e) {
        ElMessage.error(e.message || 'Failed to run external tool')
      } finally {
        if (generation === this.generation) this.submitting = false
      }
    },

    buildJsonHeaders(extra = {}) {
      if (typeof this.getTabScopedHeaders === 'function') {
        return this.getTabScopedHeaders(extra)
      }
      return extra
    },
  },
}
</script>

<style scoped>
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

.external-tool-param-help {
  margin-top: 4px;
  color: var(--muted, #64748b);
  font-size: 12px;
  line-height: 1.45;
}

.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
}
</style>
