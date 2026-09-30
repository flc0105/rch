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
            <el-radio value="inproc">
              In-process (Thread)
            </el-radio>
            <el-radio value="subprocess">
              Subprocess
            </el-radio>
          </el-radio-group>

          <div class="hint-text background-job-param-hint">
            In-process keeps direct access to the Client runtime. Subprocess isolates the Job and can be force-stopped.
          </div>
        </el-form-item>

        <el-form-item
          v-for="param in params"
          :key="`job-param-${param.name}`"
          :label="`${param.name} (${param.type || 'string'})`"
        >
          <div
            v-if="isRemoteFileParam(param)"
            class="background-job-file-param"
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

          <el-input
            v-else
            :model-value="paramForm[param.name]"
            :placeholder="param.description || param.name"
            @update:model-value="$emit('update-param', param.name, $event)"
          />

          <div class="hint-text background-job-param-hint">
            {{ param.description || 'No description' }}

            <template v-if="param.required">
              · required
            </template>

            <template v-if="param.default !== undefined && param.default !== null">
              · default: {{ param.default }}
            </template>

            <template v-if="param.min !== undefined">
              · min: {{ param.min }}
            </template>

            <template v-if="param.max !== undefined">
              · max: {{ param.max }}
            </template>
          </div>
        </el-form-item>
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

export default {
  name: 'BackgroundJobStartDialog',

  components: {
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
  },

  methods: {
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

.background-job-file-param {
  width: 100%;
}

.background-job-param-hint {
  margin-top: 6px;
}
</style>
