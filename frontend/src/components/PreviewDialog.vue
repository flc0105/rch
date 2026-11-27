<template>
  <el-dialog
      v-model="previewDialogVisible"
      :title="previewTitle || 'File Preview'"
      :width="previewDialogWidth"
      :top="previewDialogTop"
      :class="previewDialogClass"
      :show-close="false"
  >
    <template #header>
      <div class="preview-dialog-header">
        <span class="preview-dialog-title">{{ previewTitle || 'File Preview' }}</span>
        <div class="preview-header-actions">
          <el-tooltip
              v-if="previewType === 'text'"
              :content="previewFullscreen ? 'Exit Fullscreen' : 'Fullscreen'"
              placement="bottom"
          >
            <button
                type="button"
                class="preview-header-action"
                :aria-label="previewFullscreen ? 'Exit Fullscreen' : 'Fullscreen'"
                @click="togglePreviewFullscreen"
            >
              <el-icon><FullScreen /></el-icon>
            </button>
          </el-tooltip>
          <button
              type="button"
              class="preview-header-action"
              aria-label="Close"
              title="Close"
              @click="previewDialogVisible = false"
          >
            <el-icon><Close /></el-icon>
          </button>
        </div>
      </div>
    </template>
    <div
        v-loading="previewLoading"
        class="preview-wrap"
    >
      <PreviewToolbar
        :preview-type="previewType"
        :preview-source="previewSource"
        :preview-cache-artifact-id="previewCacheArtifactId"
        :preview-saving="previewSaving"
        :preview-edit-mode="previewEditMode"
        :preview-truncated="previewTruncated"
        :preview-editable="previewEditable"
        :preview-reloading="previewReloading"
        :preview-url="previewUrl"
        :preview-image-info="previewImageInfo"
        :preview-source-label="previewSourceLabel"
        :preview-file-size="previewFileSize"
        :preview-file-codec="previewFileCodec"
        :preview-file-encoding="previewFileEncoding"
        :preview-detected-language="previewDetectedLanguage"
        @save-to-saved="saveRemotePreviewToSaved"
        @copy="copyPreviewText"
        @edit="enterEditMode"
        @save="saveEditedContent"
        @cancel-edit="cancelEditMode"
        @image-info="openPreviewImageInfoDialog"
        @open-original="openPreviewOriginal"
        @more="handlePreviewMoreCommand"
      />

      <template v-if="previewType === 'image' && previewUrl">
        <div class="image-preview-box">
          <img
              :src="previewUrl"
              alt="preview"
              class="preview-image"
          >
        </div>
      </template>

      <template v-else-if="previewType === 'archive'">
        <ArchivePreviewPanel
          :key="`archive-${previewLoadSeq}`"
          ref="archivePreviewRef"
          :inspect="archiveInspect"
          :read-entry="archiveReadEntry"
          :entry-actions="previewSource === 'remote_file'"
          @download-entry="downloadArchiveEntry"
          @extract-entry="extractArchiveEntry"
        />
        <RemoteZipEntryActions
          v-if="previewSource === 'remote_file'"
          :key="`actions-${previewLoadSeq}`"
          ref="archiveActionsRef"
          :selected-id="previewRemoteClientId"
          :archive-path="previewFilePath"
          @artifacts-maybe-changed="$emit('artifacts-maybe-changed')"
          @remote-directory-maybe-changed="$emit('remote-directory-maybe-changed')"
        />
      </template>

      <template v-else-if="previewType === 'text'">
        <!-- Monaco Editor 容器：这个 id 保留，方便调试定位 -->
        <div
            id="monaco-editor-container"
            ref="monacoEditorContainerRef"
            class="monaco-editor-container"
        />
      </template>

      <template v-else-if="previewType === 'unsupported'">
        <div class="empty-state">
          This file type is not supported for preview.
        </div>
      </template>

      <template v-else>
        <div class="empty-state">
          No preview available.
        </div>
      </template>
    </div>
  </el-dialog>

  <PreviewImageInfoDialog
      v-model:visible="previewImageInfoDialogVisible"
      :info="previewImageInfo"
  />
</template>

<script>
import { Close, FullScreen } from '@element-plus/icons-vue'
import PreviewToolbar from './PreviewToolbar.vue'
import PreviewImageInfoDialog from './PreviewImageInfoDialog.vue'
import ArchivePreviewPanel from './ArchivePreviewPanel.vue'
import RemoteZipEntryActions from './RemoteZipEntryActions.vue'
import usePreviewMonaco from '../composables/usePreviewMonaco.js'
import usePreviewFile from '../composables/usePreviewFile.js'
import usePreviewResourceEditor from '../composables/usePreviewResourceEditor.js'
import usePreviewSave from '../composables/usePreviewSave.js'
import usePreviewReload from '../composables/usePreviewReload.js'
import { PREVIEW_SOURCE_OPERATIONS } from '../utils/previewSources.js'

export default {
  name: 'PreviewDialog',
  components: { PreviewToolbar, PreviewImageInfoDialog, ArchivePreviewPanel, RemoteZipEntryActions, Close, FullScreen },
  mixins: [usePreviewMonaco, usePreviewFile, usePreviewResourceEditor, usePreviewSave, usePreviewReload],
  props: {
    selectedId: {
      type: [String, Number],
      default: '',
    },

    remoteFilesDialogVisible: {
      type: Boolean,
      default: false,
    },

    getTabScopedHeaders: {
      type: Function,
      default: () => ({}),
    },
  },

  emits: [
    'remote-directory-maybe-changed',
    'artifacts-maybe-changed',
    'scripts-maybe-changed',
    'background-job-modules-maybe-changed',
    'external-tools-maybe-changed',
  ],

  data() {
    return {
      previewReloading: false,
      previewDialogVisible: false,
      previewFullscreen: false,
      previewLoading: false,
      previewType: '',
      archiveInspect: null,
      archiveReadEntry: null,
      previewTitle: '',
      previewUrl: '',
      previewText: '',
      previewEditMode: false,  // 是否处于编辑模式
      previewSaving: false,    // 保存中状态
      previewFilePath: '',     // 当前编辑的文件路径
      previewRemoteClientId: '',  // Remote Files 预览固定使用打开时的目标设备
      previewOriginalContent: '',  // 原始内容副本（用于取消编辑时恢复）
      previewTruncated: false,     // 是否被截断
      previewEditable: true,       // 文件解码是否无损可编辑
      previewFileCodec: 'utf-8',   // 服务端确认的写回编码（与显示标签分离）
      previewFileSize: '',         // 文件大小显示
      previewFileEncoding: 'UTF-8', // 文件编码
      previewSource: '',  // 由 PREVIEW_SOURCE_OPERATIONS 定义可用来源
      previewArtifactInfo: null,
      sharedCreateFolderId: '',
      previewCacheArtifactId: '',
      previewImageInfo: null,
      previewImageInfoDialogVisible: false,
      previewDetectedLanguage: 'Plain Text', // Monaco 识别语言
      previewLoadSeq: 0,
      monacoInitSeq: 0,
      monacoReadySession: -1,
    }
  },

  computed: {
    previewDialogClass() {
      return [
        'fixed-dialog',
        'preview-dialog',
        {'preview-dialog-fullscreen': this.previewFullscreen},
      ]
    },

    previewDialogWidth() {
      return this.previewFullscreen ? '100vw' : '1080px'
    },

    previewDialogTop() {
      return this.previewFullscreen ? '0' : '5vh'
    },

    previewSourceLabel() {
      return PREVIEW_SOURCE_OPERATIONS[this.previewSource]?.label || 'Unknown'
    },
  },

  watch: {
    previewDialogVisible: {
      flush: 'sync',
      handler(val) {
        if (!val) this.resetPreviewState()
      },
    },
  },

  beforeUnmount() {
    this.previewLoadSeq += 1
  },

  methods: {
    handlePreviewMoreCommand(command) {
      if (command === 'paste') this.pastePreviewText()
      else if (command === 'clear') this.clearPreviewContent()
      else if (command === 'reload') this.reloadPreviewContent()
    },

    startPreviewSession({ source, path = '', remoteClientId = '', artifactInfo = null } = {}) {
      this.resetPreviewState()
      this.previewSource = source || ''
      this.previewFilePath = path
      this.previewRemoteClientId = remoteClientId
      this.previewArtifactInfo = artifactInfo
      return this.previewLoadSeq
    },

    isPreviewSessionCurrent(seq) {
      return seq === this.previewLoadSeq
    },

    resetPreviewState() {
      this.previewLoadSeq += 1
      this.monacoInitSeq += 1
      this.monacoReadySession = -1
      this.cancelPendingMonacoFrames()
      this.blurMonacoEditor()
      this.previewLoading = false
      this.previewSource = ''
      this.previewFilePath = ''
      this.previewFileSize = ''
      this.sharedCreateFolderId = ''
      this.previewCacheArtifactId = ''
      this.previewFullscreen = false
      this.previewType = ''
      this.archiveInspect = null
      this.archiveReadEntry = null
      this.previewTitle = ''
      this.previewUrl = ''
      this.previewText = ''
      this.previewOriginalContent = ''
      this.previewTruncated = false
      this.previewEditable = true
      this.previewFileCodec = 'utf-8'
      this.previewFileEncoding = 'UTF-8'
      this.previewRemoteClientId = ''
      this.previewEditMode = false
      this.previewSaving = false
      this.previewArtifactInfo = null
      this.previewImageInfo = null
      this.previewImageInfoDialogVisible = false
      this.previewDetectedLanguage = 'Plain Text'
      this.previewReloading = false
    },
  },
}
</script>

<style scoped>
/* ========== 文件预览 ========== */

.preview-dialog-header {
  width: 100%;
  min-width: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.preview-dialog-title {
  flex: 1 1 0;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--el-text-color-primary);
  font-size: var(--el-dialog-title-font-size);
  line-height: var(--el-dialog-font-line-height);
}

.preview-header-actions {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
}

.preview-header-action {
  width: 32px;
  height: 32px;
  padding: 0;
  border: 0;
  border-radius: 4px;
  background: transparent;
  color: var(--el-color-info);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  line-height: 1;
  cursor: pointer;
  transition: color 0.15s ease, background-color 0.15s ease;
}

.preview-header-action:hover,
.preview-header-action:focus-visible {
  color: var(--el-color-primary);
  background: var(--el-fill-color-light);
  outline: none;
}

.preview-header-action .el-icon {
  width: 18px;
  height: 18px;
}

.preview-wrap {
  min-height: 280px;
  height: 100%;
}

.image-preview-box {
  display: flex;
  justify-content: center;
  align-items: center;
  max-height: 72vh;
  overflow: auto;
  border-radius: 18px;
  background: #fff;
  padding: 14px;
}

.preview-image {
  max-width: 100%;
  max-height: 70vh;
  object-fit: contain;
  border-radius: 12px;
}

/* 预览对话框 */

/* Element Plus only spaces adjacent buttons; flex gap also covers dropdowns. */

.edit-text-area {
  min-height: 400px;
}

.monaco-editor-container :deep(.preview-truncation-zone) {
  padding: 5px 10px;
  color: var(--el-color-danger);
  font-size: 12px;
  font-style: italic;
}

.monaco-editor-container {
  width: 100%;
  height: 74vh;
  min-height: 520px;
  border: 1px solid var(--line);
  border-radius: 12px;
  overflow: hidden;
}

.monaco-editor-container :deep(.monaco-editor) {
  border-radius: 12px;
}

.monaco-editor-container :deep(.monaco-scrollable-element) {
  border-radius: 12px;
}

@media (max-width: 768px), (max-height: 720px) {
  .preview-wrap {
      display: flex;
      flex-direction: column;
      min-height: 0;
      height: 100%;
      overflow: hidden;
    }

  .image-preview-box {
      flex: 1 1 auto;
      min-height: 0;
      max-height: none;
    }

  .monaco-editor-container {
      flex: 1 1 auto;
      height: auto;
      min-height: 0;
    }
}
</style>

<style>
.preview-dialog.preview-dialog-fullscreen.el-dialog {
  width: 100vw !important;
  max-width: 100vw !important;
  height: 100dvh !important;
  max-height: 100dvh !important;
  margin: 0 !important;
  top: 0 !important;
  border-radius: 0 !important;
  display: flex !important;
  flex-direction: column !important;
}

.preview-dialog.preview-dialog-fullscreen .el-dialog__header {
  flex: 0 0 auto !important;
  padding: 12px 14px 8px !important;
}

.preview-dialog.preview-dialog-fullscreen .el-dialog__body {
  flex: 1 1 auto !important;
  min-height: 0 !important;
  overflow: hidden !important;
  padding: 10px 12px 12px !important;
  display: flex !important;
  flex-direction: column !important;
}

.preview-dialog.preview-dialog-fullscreen .preview-wrap {
  display: flex !important;
  flex-direction: column !important;
  min-height: 0 !important;
  height: 100% !important;
  overflow: hidden !important;
}

.preview-dialog.preview-dialog-fullscreen .image-preview-box {
  flex: 1 1 auto !important;
  min-height: 0 !important;
  max-height: none !important;
}

.preview-dialog.preview-dialog-fullscreen .monaco-editor-container {
  flex: 1 1 auto !important;
  height: auto !important;
  min-height: 0 !important;
}

@media (max-width: 768px) {
  .preview-dialog.el-dialog {
    width: 100vw !important;
    max-width: 100vw !important;
    height: 100dvh !important;
    max-height: 100dvh !important;
    margin: 0 !important;
    top: 0 !important;
    border-radius: 0 !important;
    display: flex;
    flex-direction: column;
  }

  .preview-dialog .el-dialog__header {
    flex: 0 0 auto;
    min-width: 0;
    padding: 12px 14px 8px;
  }

  .preview-dialog .el-dialog__body {
    flex: 1 1 auto;
    min-height: 0;
    overflow: hidden;
    padding: 10px 12px 12px;
    display: flex;
    flex-direction: column;
  }
}


.monaco-menu-container,
.monaco-menu-container .monaco-menu {
  background: #ffffff !important;
  color: #111827 !important;
  border: 1px solid rgba(15, 23, 42, 0.12) !important;
  border-radius: 10px !important;
  box-shadow: 0 18px 45px rgba(15, 23, 42, 0.22) !important;
  overflow: hidden !important;
  z-index: 3000 !important;
}

.monaco-menu-container .monaco-action-bar .action-item {
  color: #111827 !important;
}

.monaco-menu-container .monaco-action-bar .action-item .action-label {
  color: #111827 !important;
  background: transparent !important;
}

.monaco-menu-container .monaco-action-bar .action-item.focused,
.monaco-menu-container .monaco-action-bar .action-item:hover {
  background: #eef2ff !important;
}

.monaco-menu-container .monaco-action-bar .action-item.disabled .action-label {
  color: #9ca3af !important;
}
</style>
