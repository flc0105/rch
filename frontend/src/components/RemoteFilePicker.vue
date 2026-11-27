<template>
  <el-dialog
    :model-value="visible"
    :title="pickerTitle"
    width="760px"
    top="8vh"
    class="fixed-dialog remote-file-picker-dialog"
    modal-class="remote-file-picker-overlay"
    :append-to-body="appendToBody"
    @update:model-value="handleVisibleChange"
  >
    <div class="remote-file-picker-body">
      <div class="remote-file-picker-head">
        <RemoteFileNavigation :items="remoteBreadcrumbItems" @navigate="goToRemoteBreadcrumb" />

        <div class="remote-file-picker-toolbar">
          <el-button
            size="small"
            :loading="remoteFilesLoading"
            @click="refreshRemoteDirectory"
            :icon="remoteActionIcon('refresh')"
          >
            Refresh
          </el-button>

          <el-dropdown
            :loading="quickJumpLoading"
            @command="jumpToPath"
          >
            <el-button size="small" :icon="remoteActionIcon('quick_jump')">
              Quick Jump
            </el-button>

            <template #dropdown>
              <el-dropdown-menu>
                <RemoteSystemJumpItems />
                <el-dropdown-item divided command="input_navigate" :icon="remoteActionIcon('input_navigate')">
                  Go to Folder
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>

          <el-button
            size="small"
            :loading="remoteUploadLoading"
            @click="triggerRemoteUpload"
            :icon="remoteActionIcon('upload')"
          >
            Upload
          </el-button>

          <el-button size="small" :loading="remoteCreatingFolder" :disabled="!remoteFilesCurrentPath || remoteFilesLoading" @click="createRemoteFolder" :icon="remoteActionIcon('new_folder')">
            New Folder
          </el-button>

          <input
            ref="remoteUploadInputRef"
            type="file"
            class="remote-file-picker-upload-input"
            @change="handleRemoteUploadChange"
          >
        </div>
      </div>

      <div class="remote-file-picker-table-shell">
        <RemoteDirectoryTable
          ref="remoteFilesTableRef"
          :entries="displayRemoteFilesEntries"
          :loading="remoteFilesLoading"
          :empty-text="remoteFilesEmptyText"
          :name-width="280"
          :type-width="90"
          :size-width="105"
          @row-dblclick="handleRemoteRowDblClick"
          @selection-change="multiple && handleRemoteSelectionChange($event)"
          @row-click="handleRemoteRowClick"
        >
          <template #selection>
            <el-table-column
              v-if="multiple"
              type="selection"
              width="48"
              align="center"
              :selectable="isRemoteRowSelectable"
            />
          </template>
          <template #actions>
            <el-table-column label="Actions" :width="selectionMode === 'folder' ? 170 : 112" align="center" fixed="right">
              <template #default="{ row }">
                <el-button
                  v-if="row.is_parent_entry || row.is_dir"
                  size="small"
                  link
                  type="primary"
                  @click.stop="enterRemoteDirectory(row)"
                  :icon="remoteActionIcon('open')"
                >
                  Open
                </el-button>
  
                <el-button
                  v-if="isRemoteRowSelectable(row)"
                  size="small"
                  link
                  type="primary"
                  @click.stop="selectRemoteEntry(row)"
                  :icon="remoteActionIcon('select')"
                >
                  Select
                </el-button>
              </template>
            </el-table-column>
          </template>
        </RemoteDirectoryTable>
      </div>

      <div class="remote-file-picker-footer-meta">
        <span>Visible {{ remoteFilesTotal }}</span>
        <span v-if="remoteFilesTotalPages > 1">
          · Page {{ remoteFilesPage }} / {{ remoteFilesTotalPages }}
        </span>
      </div>

      <el-pagination
        v-if="remoteFilesTotalPages > 1"
        background
        layout="prev, pager, next"
        :prev-icon="paginationPrevIcon" :next-icon="paginationNextIcon"
        :current-page="remoteFilesPage"
        :page-size="remoteFilesPageSize"
        :total="remoteFilesTotal"
        :pager-count="5"
        class="remote-file-picker-pagination"
        @current-change="handleRemotePageChange"
      />
    </div>

    <template #footer>
      <div class="remote-file-picker-footer">
        <el-button @click="closePicker" :icon="remoteActionIcon('cancel')">
          Cancel
        </el-button>

        <el-button
          v-if="selectionMode === 'folder' && !multiple"
          type="primary"
          :disabled="!remoteFilesCurrentPath || remoteFilesLoading"
          @click="selectCurrentFolder"
          :icon="remoteActionIcon('select')"
        >
          Select Current Folder
        </el-button>

        <el-button
          v-if="multiple"
          type="primary"
          :disabled="!remoteSelectedPaths.length"
          @click="confirmMultipleSelection"
          :icon="remoteActionIcon('select')"
        >
          Select
          <span v-if="remoteSelectedPaths.length">
            ({{ remoteSelectedPaths.length }})
          </span>
        </el-button>
      </div>
    </template>
  </el-dialog>
</template>

<script>
import { ChevronLeft, ChevronRight } from '@lucide/vue'
import { remoteActionIcon } from '../utils/remoteFileIcons.js'
import RemoteSystemJumpItems from './RemoteSystemJumpItems.vue'
import RemoteDirectoryTable from './RemoteDirectoryTable.vue'
import { ElMessage } from 'element-plus'
import { OPEN_TRANSFER_CENTER_KEY } from '../utils/transferStartedToast.js'

import useRemoteDirectory from '../composables/useRemoteDirectory.js'
import useRemoteFileSelection from '../composables/useRemoteFileSelection.js'
import useRemoteUpload from '../composables/useRemoteUpload.js'
import useRemoteFolderCreation from '../composables/useRemoteFolderCreation.js'

import RemoteFileNavigation from './RemoteFileNavigation.vue'

export default {
  mixins: [useRemoteDirectory, useRemoteFileSelection, useRemoteUpload, useRemoteFolderCreation],
  name: 'RemoteFilePicker',
  components: { RemoteSystemJumpItems, RemoteFileNavigation, RemoteDirectoryTable },

  inject: { openTransferCenterFromToast: { from: OPEN_TRANSFER_CENTER_KEY, default: null } },
  props: {
    visible: {
      type: Boolean,
      default: false,
    },

    selectedId: {
      type: [String, Number],
      default: '',
    },

    multiple: {
      type: Boolean,
      default: false,
    },

    initialPath: {
      type: String,
      default: '',
    },

    selectionMode: {
      type: String,
      default: 'file',
      validator: value => ['file', 'folder'].includes(value),
    },

    appendToBody: { type: Boolean, default: false },

    getTabScopedHeaders: {
      type: Function,
      default: null,
    },
  },

  emits: [
    'update:visible',
    'select',
    'append-output',
    'set-active-task',
    'upload-started',
  ],

  computed: {
    paginationPrevIcon() { return ChevronLeft },
    paginationNextIcon() { return ChevronRight },
    pickerTitle() {
      return this.selectionMode === 'folder' ? 'Select Remote Folder' : 'Select Remote File'
    },

    remoteFilesEmptyText() {
      return this.selectionMode === 'folder' ? 'No folders found' : 'This folder is empty'
    },

  },

  watch: {
    visible(value) {
      if (value) {
        this.openPicker()
      } else {
        this.resetPicker()
      }
    },

    selectedId() {
      if (this.visible) this.openPicker()
    },
  },

  methods: {
    remoteActionIcon,

    handleVisibleChange(value) {
      this.$emit('update:visible', value)
    },

    closePicker() {
      this.$emit('update:visible', false)
    },

    async openPicker() {
      const initialPath = this.initialPath || this.remoteFilesCurrentPath || ''
      this.resetPicker()
      if (!this.selectedId) {
        ElMessage.warning('Please select a device')
        this.closePicker()
        return
      }
      await Promise.all([
        this.loadQuickJumpPaths(),
        this.loadRemoteDirectory(initialPath, 1),
      ])
    },

    resetPicker() {
      this.resetRemoteDirectory()
      this.remoteCreatingFolder = false
      this.remoteUploadSequence += 1
      this.remoteUploadLoading = false
    },
    captureRemoteFilesContext() {
      return { clientId: this.selectedId, contextSeq: this.remoteFilesContextSeq }
    },
    isRemoteFilesContextActive(context) {
      return !!(this.visible && context?.clientId && context.clientId === this.selectedId && context.contextSeq === this.remoteFilesContextSeq)
    },
    isRemoteDirectoryEntryVisible(row) {
      return !!row && (this.selectionMode !== 'folder' || row.is_dir)
    },

    async createRemoteFolder() {
      if (!this.visible || !this.selectedId || !this.remoteFilesCurrentPath || this.remoteFilesLoading || this.remoteCreatingFolder) return
      return this.createRemoteDirectory()
    },

    handleRemoteRowDblClick(row) {
      if (!row) return

      if (row.is_parent_entry || row.is_dir) {
        this.enterRemoteDirectory(row)
        return
      }

      if (this.selectionMode === 'file') {
        this.selectRemoteEntry(row)
      }
    },

    handleRemoteRowClick(row) {
      if (!row || this.multiple || this.selectionMode !== 'file') return
      this.selectRemoteEntry(row)
    },

    isRemoteRowSelectable(row) {
      if (!row || row.is_parent_entry || !row.path) return false
      return this.selectionMode === 'folder' ? !!row.is_dir : !row.is_dir
    },

    selectRemoteEntry(row) {
      if (!this.isRemoteRowSelectable(row)) return

      this.$emit('select', this.multiple ? [row.path] : row.path)
      this.closePicker()
    },

    selectCurrentFolder() {
      if (this.selectionMode !== 'folder' || this.multiple || !this.remoteFilesCurrentPath || this.remoteFilesLoading) return
      this.$emit('select', this.remoteFilesCurrentPath)
      this.closePicker()
    },

    confirmMultipleSelection() {
      if (!this.remoteSelectedPaths.length) return

      this.$emit('select', [...this.remoteSelectedPaths])
      this.closePicker()
    },

    triggerRemoteUpload() {
      if (!this.selectedId) {
        ElMessage.warning('Please select a device')
        return
      }

      if (!this.remoteFilesCurrentPath) {
        ElMessage.warning('Current directory is empty')
        return
      }

      const input = this.$refs.remoteUploadInputRef
      if (input && typeof input.click === 'function') {
        input.value = ''
        input.click()
      }
    },

    async handleRemoteUploadChange(event) {
      const file = event?.target?.files?.[0]
      if (event?.target) event.target.value = ''
      if (file) return this.submitRemoteFile(file, 'remote_file_picker')
    },

  },
}
</script>

<style scoped>
.remote-file-picker-body {
  display: flex;
  flex-direction: column;
  width: 100%;
  min-height: 0;
  height: 58vh;
  gap: 10px;
  overflow: hidden;
}

.remote-file-picker-head {
  flex: 0 0 auto;
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
}

:deep(.remote-breadcrumb-bar) {
  display: block;
  width: 100%;
  min-height: 30px;
  overflow-x: auto;
  overflow-y: hidden;
  white-space: nowrap;
  scrollbar-width: thin;
}

:deep(.remote-breadcrumb-item) {
  display: inline-flex;
  align-items: center;
  max-width: 220px;
  margin: 0 2px 0 0;
  padding: 4px 6px;
  border: 0;
  border-radius: 8px;
  color: var(--el-color-primary);
  background: transparent;
  cursor: pointer;
}

:deep(.remote-breadcrumb-item.active),
:deep(.remote-breadcrumb-item:disabled) {
  color: var(--muted);
  cursor: default;
}

:deep(.remote-breadcrumb-item > span:last-child) {
  display: inline-block;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

:deep(.remote-breadcrumb-sep) {
  margin-right: 4px;
  color: var(--muted);
}

:deep(.remote-breadcrumb-empty),
.remote-file-picker-footer-meta {
  font-size: 12px;
  color: var(--muted);
}

.remote-file-picker-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.remote-file-picker-upload-input {
  display: none;
}

.remote-file-picker-table-shell {
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
}

.remote-file-picker-footer-meta {
  flex: 0 0 auto;
}

.remote-file-picker-pagination {
  flex: 0 0 auto;
  justify-content: flex-end;
}

.remote-file-picker-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
</style>

<style>
/* RemoteFilePicker: 选文件弹窗固定内部滚动，避免列表撑开 dialog。 */
.remote-file-picker-overlay .el-dialog {
  display: flex !important;
  flex-direction: column !important;
  max-height: 78vh !important;
  overflow: hidden !important;
}

.remote-file-picker-overlay .el-dialog__body {
  flex: 1 1 auto !important;
  min-height: 0 !important;
  overflow: hidden !important;
}

.remote-file-picker-overlay .remote-file-picker-table-shell .el-table,
.remote-file-picker-overlay .remote-file-picker-table-shell .el-table__inner-wrapper,
.remote-file-picker-overlay .remote-file-picker-table-shell .el-scrollbar,
.remote-file-picker-overlay .remote-file-picker-table-shell .el-scrollbar__wrap {
  height: 100% !important;
}

.remote-file-picker-overlay .remote-file-picker-table-shell .el-scrollbar__wrap {
  overflow-y: auto !important;
  overflow-x: auto !important;
}

@media (max-width: 768px) {
  .remote-file-picker-overlay .el-dialog {
    width: 100vw !important;
    max-width: 100vw !important;
    height: 100dvh !important;
    max-height: 100dvh !important;
    margin: 0 !important;
    border-radius: 0 !important;
  }

  .remote-file-picker-overlay .remote-file-picker-body {
    height: 100% !important;
  }
}
</style>
