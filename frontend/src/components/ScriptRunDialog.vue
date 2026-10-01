<template>
  <el-dialog
    :model-value="visible"
    :title="item ? `Run ${item.display_name || item.script_name}` : 'Run Script'"
    width="680px"
    top="10vh"
    class="fixed-dialog script-run-dialog"
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

<el-form
  v-if="paramSpecs.length"
  label-position="top"
  class="script-run-form"
  @submit.prevent="$emit('confirm')"
>
        <ParamFormField
          v-for="param in paramSpecs"
          :key="`script-param-${param.name}`"
          :param="param"
          :model-value="paramForm[param.name]"
          @update:model-value="$emit('update-param', param.name, $event)"
          @browse="openRemoteFilePicker"
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

        <el-button
          type="primary"
          :loading="submitting"
          @click="$emit('confirm')"
        >
          Run
        </el-button>
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
</template>

<script>
import RemoteFilePicker from './RemoteFilePicker.vue'
import ParamFormField from './ParamFormField.vue'
import { isRemoteMultiParam, remoteParamInitialPath, remoteParamSelectionMode } from '../utils/parameterSchema.js'

export default {
  name: 'ScriptRunDialog',

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

    paramSpecs: {
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

    selectedId: {
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
    'update-param',
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
    forwardAppendOutput(clientId, line, kind) {
      this.$emit('append-output', clientId, line, kind)
    },

    forwardSetActiveTask(clientId, taskId) {
      this.$emit('set-active-task', clientId, taskId)
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
  overflow: hidden;
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

.script-run-form {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
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

@media (max-width: 768px), (max-height: 720px) {
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