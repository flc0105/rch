<template>
  <el-dialog
    :model-value="visible"
    :title="item ? `Run ${item.display_name || item.script_name}` : 'Run Script'"
    width="680px"
    top="10vh"
    class="fixed-dialog script-run-dialog rch-result-detail-fullscreen"
    append-to-body
    modal-class="script-run-overlay"
    @update:model-value="$emit('update:visible', $event)"
  >
    <div
      v-if="item"
      class="fixed-dialog-body script-run-body"
    >
      <div class="script-run-dialog-top">
        <div class="background-job-module-key mono">
          {{ item.path || item.script_name }}
        </div>

        <div
          v-if="item.description"
          class="script-run-description"
        >
          {{ item.description }}
        </div>

        <div class="background-job-module-tags script-run-tags">
          <el-tag
            size="small"
            :type="isScriptSupportedForCurrentConnection(item) ? 'info' : 'danger'"
          >
            {{ formatScriptPlatformLabel(item) }}
          </el-tag>

          <el-tag
            v-if="paramSpecs.length"
            size="small"
            type="warning"
          >
            Params
          </el-tag>
        </div>
      </div>

      <div v-if="modeError" class="script-run-description">{{ modeError }}</div>
      <div v-loading="modesLoading" class="script-run-modes">
        <button type="button" class="script-run-mode-toggle" :aria-expanded="modesExpanded" @click="modesExpanded = !modesExpanded">
          <span>Execution Mode / Output Mode</span>
          <span class="script-run-mode-summary">{{ runModes.execution_mode === 'inproc' ? 'In-process' : runModes.execution_mode === 'subprocess_pipe' ? 'Subprocess' : '—' }} / {{ runModes.output_mode === 'stream' ? 'Stream' : runModes.output_mode === 'collect' ? 'Collect' : '—' }}</span>
          <span class="script-run-mode-chevron" :class="{ 'is-expanded': modesExpanded }" aria-hidden="true">›</span>
        </button>
        <div v-show="modesExpanded" class="script-run-mode-fields">
          <el-form label-position="top">
            <el-form-item label="Execution Mode">
              <el-radio-group :model-value="runModes.execution_mode" :disabled="modesLoading || !!modeError" @update:model-value="$emit('update-mode', 'execution_mode', $event)">
                <el-radio value="inproc" :disabled="!modeOptions.execution_mode?.allowed?.includes('inproc')">In-process</el-radio>
                <el-radio value="subprocess_pipe" :disabled="!modeOptions.execution_mode?.allowed?.includes('subprocess_pipe')">Subprocess</el-radio>
              </el-radio-group>
              <div class="script-run-mode-help">{{ runModes.execution_mode === 'inproc' ? 'Runs inside the Client process. Cancellation is not supported.' : runModes.execution_mode === 'subprocess_pipe' ? 'Runs in a separate Python process. Supports cancellation.' : 'Select an available execution mode.' }}</div>
            </el-form-item>
            <el-form-item label="Output Mode">
              <el-radio-group :model-value="runModes.output_mode" :disabled="modesLoading || !!modeError" @update:model-value="$emit('update-mode', 'output_mode', $event)">
                <el-radio value="collect" :disabled="!modeOptions.output_mode?.allowed?.includes('collect')">Collect</el-radio>
                <el-radio value="stream" :disabled="!modeOptions.output_mode?.allowed?.includes('stream')">Stream</el-radio>
              </el-radio-group>
              <div class="script-run-mode-help">{{ runModes.output_mode === 'stream' ? 'Display output as the script runs.' : runModes.output_mode === 'collect' ? 'Return collected output when execution finishes.' : 'Select an available output mode.' }}</div>
            </el-form-item>
          </el-form>
        </div>
      </div>

<el-form
  v-if="paramSpecs.length"
  label-position="top"
  class="script-run-form"
  @submit.prevent="modesReady && $emit('confirm', 'dialog')"
>
        <ParamFormField
          v-for="param in paramSpecs"
          :key="`script-param-${param.name}`"
          :param="param"
          :model-value="paramForm[param.name]"
          :form-values="paramForm"
          @update:model-value="$emit('update-param', param.name, $event)"
          @browse="openRemoteFilePicker"
          @pick-keychain="openKeychainPicker"
        />
      </el-form>

      <div
        v-else
        class="empty-state script-run-empty"
      >
        This script has no declared parameters.
      </div>
    </div>

    <template #footer>
      <div class="script-run-footer">
        <el-button @click="$emit('cancel')">
          Cancel
        </el-button>

        <el-dropdown
          split-button
          type="primary"
          :disabled="submitting || !modesReady"
          @click="$emit('confirm', 'dialog')"
          @command="command => $emit('confirm', command)"
        >
          Run in Dialog
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="terminal">Run in Terminal</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
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

  <KeychainPicker
    v-model:visible="keychainPickerVisible"
    :machine-id="machineId"
    :kind="pendingKeychainParam?.keychain_picker?.kind || 'secret'"
    @select="handleKeychainSelected"
  />
</template>

<script>
import RemoteFilePicker from './RemoteFilePicker.vue'
import KeychainPicker from './KeychainPicker.vue'
import ParamFormField from './ParamFormField.vue'
import { isRemoteMultiParam, mapKeychainPickerValues, remoteParamInitialPath, remoteParamSelectionMode } from '../utils/parameterSchema.js'

export default {
  name: 'ScriptRunDialog',

  components: {
    KeychainPicker,
    ParamFormField,
    RemoteFilePicker,
  },

  props: {
    visible: {
      type: Boolean,
      default: false,
    },

    item: {
      type: Object,
      default: null,
    },

    paramSpecs: {
      type: Array,
      default: () => [],
    },

    paramForm: {
      type: Object,
      default: () => ({}),
    },

    modeOptions: { type: Object, default: () => ({}) },
    runModes: { type: Object, default: () => ({}) },
    modesLoading: { type: Boolean, default: false },
    modeError: { type: String, default: '' },

    submitting: {
      type: Boolean,
      default: false,
    },

    selectedId: {
      type: [String, Number],
      default: '',
    },
    machineId: {
      type: [String, Number],
      default: '',
    },

    getTabScopedHeaders: {
      type: Function,
      default: null,
    },

    isScriptSupportedForCurrentConnection: {
      type: Function,
      required: true,
    },

    formatScriptPlatformLabel: {
      type: Function,
      required: true,
    },
  },

  emits: [
    'update:visible',
    'update-mode',
    'update-param',
    'apply-param-values',
    'append-output',
    'set-active-task',
    'upload-started',
    'cancel',
    'confirm',
  ],

  data() {
    return {
      modesExpanded: false,
      remoteFilePickerVisible: false,
      pendingRemoteFileParam: null,
      keychainPickerVisible: false,
      pendingKeychainParam: null,
    }
  },

  watch: {
    visible(value) {
      if (value) this.modesExpanded = false
    },
  },

  computed: {
    modesReady() {
      return !this.modesLoading && !this.modeError && ['execution_mode', 'output_mode'].every(key =>
        this.modeOptions[key]?.allowed?.includes(this.runModes[key]))
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
  },

  methods: {
    forwardAppendOutput(clientId, line, kind, meta) {
      this.$emit('append-output', clientId, line, kind, meta)
    },

    forwardSetActiveTask(clientId, taskId, cancelPolicy = '', historyEntryId = '', operationId = '') {
      this.$emit('set-active-task', clientId, taskId, cancelPolicy, historyEntryId, operationId)
    },

    forwardRemoteUploadStarted(payload) {
      this.$emit('upload-started', {
        ...(payload && typeof payload === 'object' ? payload : {}),
        source: 'script_remote_file_picker',
      })
    },

    loadRemoteFilePickerDirectory(path = '') {
      return this.$refs.remoteFilePickerRef?.loadRemoteDirectory(path || '', 1)
    },

    openRemoteFilePicker(param) {
      if (!param || !param.name) return

      this.pendingRemoteFileParam = param
      this.remoteFilePickerVisible = true
    },

    handleRemoteFileSelected(value) {
      const param = this.pendingRemoteFileParam
      if (!param || !param.name) return

      // 多选时保持数组；单选直接写入路径字符串。
      this.$emit('update-param', param.name, this.pendingRemoteFileParamMultiple ? value : String(value || ''))
      this.remoteFilePickerVisible = false
      this.pendingRemoteFileParam = null
    },

    openKeychainPicker(param) {
      if (!param?.name) return
      this.pendingKeychainParam = param
      this.keychainPickerVisible = true
    },

    handleKeychainSelected(item) {
      const param = this.pendingKeychainParam
      if (!param) return
      const values = mapKeychainPickerValues(param, item, this.paramSpecs)
      if (!values) return
      this.$emit('apply-param-values', values)
      this.pendingKeychainParam = null
      this.keychainPickerVisible = false
    },
  },
}
</script>

<style scoped>
.script-run-body {
  display: flex;
  flex-direction: column;
  width: 100%;
  min-height: 0;
  max-height: calc(78vh - 150px);
  overflow-y: auto;
  gap: 14px;
}


.script-run-dialog-top {
  flex: 0 0 auto;
}

.script-run-description {
  margin-top: 8px;
  font-size: 13px;
  line-height: 1.6;
  color: var(--muted);
  word-break: break-word;
}

.script-run-tags {
  margin-top: 10px;
  margin-bottom: 0;
}

.script-run-modes { flex: 0 0 auto; padding-right: 4px; }
.script-run-mode-toggle {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  width: 100%;
  padding: 9px 10px;
  border: 1px solid var(--el-border-color-extra-light);
  border-radius: 8px;
  background: var(--el-fill-color-extra-light);
  color: var(--el-text-color-regular);
  font: inherit;
  text-align: left;
  cursor: pointer;
}
.script-run-mode-toggle:hover { background: var(--el-fill-color-lighter); }
.script-run-mode-toggle:focus-visible { outline: 2px solid var(--el-color-primary); outline-offset: 2px; }
.script-run-mode-summary { margin-left: auto; color: var(--el-text-color-secondary); font-size: 0.9em; }
.script-run-mode-chevron { font-size: 18px; line-height: 1; transform: rotate(0deg); }
.script-run-mode-chevron.is-expanded { transform: rotate(90deg); }
.script-run-mode-fields { padding-top: 12px; }

.script-run-modes :deep(.el-form-item__content) {
  display: block;
}
.script-run-mode-help {
  display: block;
  width: 100%;
  margin-top: 6px;
  color: var(--el-text-color-secondary);
  font-size: 0.9em;
  line-height: 1.5;
}

.script-run-form {
  flex: 0 0 auto;
  min-height: 0;
  overflow-x: hidden;
  padding-right: 4px;
}


.script-run-empty {
  min-height: 96px;
}

.script-run-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

/*
.script-run-footer :deep(.el-button) {
  height: 32px;
  min-height: 32px;
  margin: 0;
  padding-inline: 14px;
  border-radius: 10px;
}
*/

</style>

<style>
/* ScriptRunDialog: 保持运行参数弹窗内部滚动，不挤压页脚按钮。 */
.script-run-overlay .el-dialog {
  display: flex !important;
  flex-direction: column !important;
  max-height: 78vh !important;
  overflow: hidden !important;
}

.script-run-overlay .el-dialog__body {
  display: flex !important;
  flex: 1 1 auto !important;
  min-height: 0 !important;
    max-height: calc(78vh - 130px) !important;

  overflow: hidden !important;
}

.script-run-overlay .el-dialog__footer {
  flex: 0 0 auto !important;
}

@media (max-width: 768px) {
  .script-run-overlay .el-dialog {
    width: 100vw !important;
    max-width: 100vw !important;
    height: 100dvh !important;
    max-height: 100dvh !important;
    margin: 0 !important;
    border-radius: 0 !important;
  }
}
</style>