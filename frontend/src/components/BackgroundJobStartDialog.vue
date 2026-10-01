<template>
  <el-dialog
    :model-value="visible"
    :title="item ? `Start ${item.display_name || item.job_name}` : 'Start Background Job'"
    width="640px"
    top="10vh"
    class="fixed-dialog"
    @update:model-value="$emit('update:visible', $event)"
  >
    <div
      v-if="item"
      class="fixed-dialog-body"
    >
      <div class="background-jobs-section-title">
        {{ item.description || 'Configure job parameters before starting' }}
      </div>

      <div class="background-job-module-tags background-job-start-tags">
        <el-tag
          size="small"
          :type="isJobSupportedForCurrentConnection(item) ? 'info' : 'danger'"
        >
          {{ formatJobPlatformLabel(item.metadata?.platforms || []) }}
        </el-tag>
      </div>

      <el-form label-position="top">
        <el-form-item label="Execution mode">
          <el-radio-group
            :model-value="executionMode"
            @update:model-value="$emit('update-execution-mode', $event)"
          >
            <el-radio
              value="inproc"
              :disabled="!isExecutionModeAllowed('inproc')"
            >
              In-process (Thread)
            </el-radio>
            <el-radio
              value="subprocess"
              :disabled="!isExecutionModeAllowed('subprocess')"
            >
              Subprocess
            </el-radio>
          </el-radio-group>

          <div class="hint-text background-job-param-hint">
            In-process keeps direct access to the Client runtime. Subprocess isolates the Job and can be force-stopped.
            <template v-if="allowedExecutionModes.length === 1">
              This job only allows {{ formatExecutionModeLabel(allowedExecutionModes[0]) }}.
            </template>
          </div>
        </el-form-item>

        <ParamFormField
          v-for="param in params"
          :key="`job-param-${param.name}`"
          :param="param"
          :model-value="paramForm[param.name]"
          @update:model-value="$emit('update-param', param.name, $event)"
          @browse="openRemoteFilePicker"
        />
      </el-form>
    </div>

    <template #footer>
      <el-button @click="$emit('cancel')">
        Cancel
      </el-button>

      <el-button
        type="primary"
        :loading="submitting"
        @click="$emit('confirm')"
      >
        Start
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
</template>

<script>
import RemoteFilePicker from './RemoteFilePicker.vue'
import ParamFormField from './ParamFormField.vue'
import { isRemoteMultiParam, remoteParamInitialPath, remoteParamSelectionMode } from '../utils/parameterSchema.js'

export default {
  name: 'BackgroundJobStartDialog',

  components: {
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
    params: {
      type: Array,
      default: () => [],
    },
    paramForm: {
      type: Object,
      default: () => ({}),
    },
    submitting: {
      type: Boolean,
      default: false,
    },
    executionMode: {
      type: String,
      default: 'inproc',
    },
    selectedId: {
      type: [String, Number],
      default: '',
    },
    getTabScopedHeaders: {
      type: Function,
      default: null,
    },
    isJobSupportedForCurrentConnection: {
      type: Function,
      required: true,
    },
    formatJobPlatformLabel: {
      type: Function,
      required: true,
    },
  },

  emits: [
    'update:visible',
    'update-param',
    'update-execution-mode',
    'append-output',
    'set-active-task',
    'upload-started',
    'cancel',
    'confirm',
  ],

  data() {
    return {
      remoteFilePickerVisible: false,
      pendingRemoteFileParam: null,
    }
  },

  computed: {
    allowedExecutionModes() {
      const metadata = this.item?.metadata || {}
      const execution = metadata.execution && typeof metadata.execution === 'object' && !Array.isArray(metadata.execution)
        ? metadata.execution
        : {}
      const source = Array.isArray(execution.allowed)
        ? execution.allowed
        : (Array.isArray(metadata.allowed) ? metadata.allowed : ['inproc', 'subprocess'])
      const result = []
      const seen = new Set()

      for (const item of source) {
        const mode = String(item || '').trim().toLowerCase()
        if (!['inproc', 'subprocess'].includes(mode) || seen.has(mode)) continue
        seen.add(mode)
        result.push(mode)
      }

      return result.length ? result : ['inproc', 'subprocess']
    },

    pendingRemoteFileParamMultiple() {
      return isRemoteMultiParam(this.pendingRemoteFileParam || {})
    },

    pendingRemoteFileParamSelectionMode() {
      return remoteParamSelectionMode(this.pendingRemoteFileParam || {})
    },

    pendingRemoteFileParamInitialPath() {
      return remoteParamInitialPath(this.pendingRemoteFileParam || {})
    },
  },

  methods: {
    isExecutionModeAllowed(mode) {
      return this.allowedExecutionModes.includes(String(mode || '').trim().toLowerCase())
    },

    formatExecutionModeLabel(mode) {
      return String(mode || '').trim().toLowerCase() === 'subprocess'
        ? 'Subprocess'
        : 'In-process (Thread)'
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
        source: 'job_remote_file_picker',
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

      this.$emit('update-param', param.name, this.pendingRemoteFileParamMultiple ? value : String(value || ''))
      this.remoteFilePickerVisible = false
      this.pendingRemoteFileParam = null
    },
  },
}
</script>

<style scoped>
.background-job-start-tags {
  margin-bottom: 12px;
}


.background-job-param-hint {
  margin-top: 6px;
}
</style>
