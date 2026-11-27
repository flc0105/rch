<template>
  <el-dialog
      :model-value="visible"
      title="Remote File Browser"
      width="1180px"
      top="4vh"
      class="fixed-dialog remote-files-dialog"
      modal-class="remote-files-overlay"
      @update:model-value="handleVisibleChange"
  >
    <div class="fixed-dialog-body">
      <RemoteFilesToolbar
        :remote-breadcrumb-items="remoteBreadcrumbItems"
        :remote-files-parent-path="remoteFilesParentPath"
        :remote-files-current-path="remoteFilesCurrentPath"
        :remote-upload-loading="remoteUploadLoading"
        :drag-upload-loading="dragUploadLoading"
        :remote-pin-button-text="remotePinButtonText"
        :quick-jump-loading="quickJumpLoading"
        :remote-pinned-jump-loading="remotePinnedJumpLoading"
        :has-pinned-quick-jumps="hasPinnedQuickJumps"
        :remote-pinned-jump-items="remotePinnedJumpItems"
        :has-remote-selection="hasRemoteSelection"
        :remote-zip-downloading="remoteZipDownloading"
        :remote-selected-paths="remoteSelectedPaths"
        :remote-zip-creating="remoteZipCreating"
        :has-remote-clipboard="hasRemoteClipboard"
        :is-remote-current-page-all-selected="isRemoteCurrentPageAllSelected"
        :visible-remote-selectable-paths="visibleRemoteSelectablePaths"
        :remote-mobile-view-mode="remoteMobileViewMode"
        :remote-search-recursive="remoteSearchRecursive"
        :show-hidden-files="showHiddenFiles"
        :remote-search-keyword="remoteSearchKeyword"
        :remote-clipboard-paths="remoteClipboardPaths"
        @navigate-breadcrumb="goToRemoteBreadcrumb"
        @mobile-command="handleRemoteMobileToolsCommand"
        @schedule-search="scheduleRemoteSearch"
        @apply-search="applyRemoteSearch"
        @refresh="refreshRemoteDirectory"
        @up="goToRemoteParent"
        @quick-jump="jumpToPath"
        @new-folder="createRemoteDirectory"
        @upload="triggerRemoteUpload"
        @download="downloadSelectedRemoteEntries"
        @delete="deleteSelectedRemoteEntries"
        @more-command="handleRemoteToolbarMoreCommand"
        @recursive-change="handleRemoteSearchRecursiveChange"
        @update:remoteSearchKeyword="remoteSearchKeyword = $event"
        @update:remoteSearchRecursive="remoteSearchRecursive = $event"
      />

<!--      <div class="dialog-path-row remote-files-meta-row">-->
<!--        <div v-if="hasRemoteClipboard" class="dialog-pagination-meta">-->
<!--          Clipboard: {{ remoteClipboardActionText }} {{ remoteClipboardPaths.length }} item(s)-->
<!--          <span v-if="remoteClipboardSourcePath">-->
<!--            · From {{ remoteClipboardSourcePath }}-->
<!--          </span>-->
<!--        </div>-->
<!--      </div>-->

      <RemoteFileList ref="remoteFileListRef"
        :display-remote-files-entries="displayRemoteFilesEntries"
        :remote-files-loading="remoteFilesLoading"
        :remote-files-empty-text="remoteFilesEmptyText"
        :is-remote-search-active="isRemoteSearchActive"
        :remote-files-current-path="remoteFilesCurrentPath"
        :remote-zip-extracting="remoteZipExtracting"
        :remote-mobile-view-mode="remoteMobileViewMode"
        :remote-selected-paths="remoteSelectedPaths"
        @row-double-click="handleRemoteRowDblClick"
        @selection-change="handleRemoteSelectionChange"
        @up="goToRemoteParent"
        @open-directory="enterRemoteDirectory"
        @preview="previewRow"
        @download="downloadRemoteEntry"
        @row-command="handleRemoteMoreAction"
        @toggle-selection="toggleRemoteSelection"
        @mobile-row-click="handleRemoteMobileListRowClick"
        @mobile-row-command="handleRemoteMobileListAction"
      />

      <RemoteFilePagination
        :has-remote-clipboard="hasRemoteClipboard"
        :remote-clipboard-action-text="remoteClipboardActionText"
        :remote-clipboard-paths="remoteClipboardPaths"
        :is-remote-search-active="isRemoteSearchActive"
        :remote-search-keyword="remoteSearchKeyword"
        :remote-search-recursive="remoteSearchRecursive"
        :remote-files-total="remoteFilesTotal"
        :show-hidden-files="showHiddenFiles"
        :remote-files-hidden-total="remoteFilesHiddenTotal"
        :remote-files-all-total="remoteFilesAllTotal"
        :remote-files-total-pages="remoteFilesTotalPages"
        :remote-files-page="remoteFilesPage"
        :remote-files-page-size="remoteFilesPageSize"
        @page-change="handleRemotePageChange"
        @page-size-change="handleRemotePageSizeChange"
      />
    </div>
  </el-dialog>

  <RemoteFilePicker
      ref="destinationPickerRef"
      v-model:visible="destinationPickerVisible"
      :selected-id="remoteFilesClientId"
      :initial-path="destinationPickerInitialPath"
      selection-mode="folder"
      append-to-body
      :get-tab-scoped-headers="getTabScopedHeaders"
      @select="handleDestinationSelected"
      @append-output="(...args) => $emit('append-output', ...args)"
      @set-active-task="(...args) => $emit('set-active-task', ...args)"
      @upload-started="handleDestinationPickerUploadStarted"
  />
  <DragUploadDialog
      v-model="dragUploadVisible"
      title="Drag Upload"
      helper-text="Upload files and folders to the current remote directory."
      :multiple="true"
      :allow-directories="true"
      :loading="dragUploadLoading"
      :stage="dragUploadStage" :progress="dragUploadProgress"
      @upload="handleDragUpload"
  />
  <RemotePinsDialog
      v-model="pinManagerVisible"
      :selected-id="remoteFilesClientId"
      :items="remotePinnedJumpItems"
      @updated="handlePinnedQuickJumpsUpdated"
      @copy-path="path => copyRemotePath({ path })"
      @set-cwd="setRemoteDirectoryAsCwd"
      @open-pty="openRemotePtyHere"
  />
</template>

<script>
import { ElMessage } from 'element-plus'
import { OPEN_TRANSFER_CENTER_KEY } from '../utils/transferStartedToast.js'
import RemoteFilesToolbar from './RemoteFilesToolbar.vue'
import RemoteFileList from './RemoteFileList.vue'
import RemoteFilePagination from './RemoteFilePagination.vue'
import RemotePinsDialog from './RemotePinsDialog.vue'
import RemoteFilePicker from './RemoteFilePicker.vue'
import DragUploadDialog from './DragUploadDialog.vue'

import useRemoteDirectory from '../composables/useRemoteDirectory.js'
import useRemoteFileSelection from '../composables/useRemoteFileSelection.js'
import useRemoteUpload from '../composables/useRemoteUpload.js'
import useRemoteFolderCreation from '../composables/useRemoteFolderCreation.js'
import useRemoteBatchUpload from '../composables/useRemoteBatchUpload.js'
import useRemoteFileOperations from '../composables/useRemoteFileOperations.js'
import useRemotePinnedPaths from '../composables/useRemotePinnedPaths.js'

export default {
  mixins: [useRemoteDirectory, useRemoteFileSelection, useRemoteUpload, useRemoteFolderCreation, useRemoteBatchUpload, useRemoteFileOperations, useRemotePinnedPaths],
  name: 'RemoteFilesDialog',

  components: {
    RemotePinsDialog,
    RemoteFilePicker,
    DragUploadDialog,
    RemoteFilesToolbar,
    RemoteFileList,
    RemoteFilePagination,
  },

  inject: { openTransferCenterFromToast: { from: OPEN_TRANSFER_CENTER_KEY, default: null } },
  props: {
    selectedId: {type: String, default: ''},
    // formatBytes: {type: Function, required: true},
    getTabScopedHeaders: {type: Function, required: true},
  },

  emits: [
    'append-output',
    'set-active-task',
    'preview',
    'request-upload',
    'upload-started',
    'visible-change',
    'artifacts-maybe-changed',
    'open-pty',
  ],

  data() {
    return {
      visible: false,
      pinManagerVisible: false,

      remoteFilesClientId: '',

      remoteMobileViewMode: 'list',
    }
  },

  watch: {
    destinationPickerVisible(value) {
      if (!value) this.destinationRequest = null
    },
    pinManagerVisible(value) {
      if (!value && !this.visible) {
        this.remoteFilesContextSeq += 1
        this.remoteFilesClientId = ''
        this.remotePinnedJumpItems = []
      }
    },
    selectedId() {
      if (this.pinManagerVisible) this.pinManagerVisible = false
    },
  },

  computed: {

    remoteFilesEmptyText() {
      return this.isRemoteSearchActive ? 'No matching files or folders' : 'This folder is empty'
    },

    // remoteSelectAllText() {
    //   return this.isRemoteCurrentPageAllSelected ? 'Clear Page Selection' : 'Select All'
    // },

  },

  methods: {

    onRemoteDirectoryLoaded() {
      this.$refs?.remoteFileListRef?.scrollRemoteMobileFileListToTop()
    },
    getRemoteSelectionTable() {
      return this.$refs?.remoteFileListRef
    },

    handleVisibleChange(value) {
      this.visible = value
      this.$emit('visible-change', value)

      if (!value) {
        this.resetRemoteFilesState()
      }
    },

    captureRemoteFilesContext() {
      return {
        clientId: String(this.remoteFilesClientId || '').trim(),
        contextSeq: this.remoteFilesContextSeq,
      }
    },

    isRemoteFilesContextActive(context) {
      return !!(
        context?.clientId &&
        (this.visible || this.pinManagerVisible) &&
        context.contextSeq === this.remoteFilesContextSeq &&
        context.clientId === this.remoteFilesClientId
      )
    },

    async open(path = '') {
      const clientId = String(this.selectedId || '').trim()
      if (!clientId) {
        ElMessage.warning('Please select a device')
        return
      }

      if (this.remoteFilesClientId !== clientId) {
        this.clearRemoteClipboard()
        this.remotePinnedJumpItems = []
        this.remotePinnedJumpLoading = false
        this.pinManagerVisible = false
      }
      this.resetRemoteDirectory()
      this.remoteCreatingFolder = false
      this.remoteZipDownloading = false
      this.remoteZipCreating = false
      this.remoteZipExtracting = false
      this.destinationPickerVisible = false
      this.destinationRequest = null
      this.dragUploadVisible = false
      this.remoteFilesClientId = clientId
      this.visible = true
      this.$emit('visible-change', true)

      this.loadQuickJumpPaths()
      this.loadPinnedQuickJumps()
      await this.loadRemoteDirectory(path, 1)
    },

    close() {
      this.handleVisibleChange(false)
    },

    handleRemoteMobileListRowClick(row) {
      if (!row?.is_dir) return
      return row.is_parent_entry ? this.goToRemoteParent() : this.enterRemoteDirectory(row)
    },

    handleRemoteMobileListAction(command, row) {
      if (command === 'open') {
        return this.handleRemoteMobileListRowClick(row)
      }
      if (command === 'preview') return this.previewRow(row)
      if (command === 'download') return this.downloadRemoteEntry(row)
      return this.handleRemoteMoreAction(command, row)
    },

    handleRemoteRowDblClick(row) {
      if (!row) return

      if (row.is_parent_entry) {
        this.goToRemoteParent()
        return
      }

      if (row.is_dir) {
        this.enterRemoteDirectory(row)
      }
    },

    handleRemoteMobileToolsCommand(command) {
      if (command && typeof command === 'object') {
        return this.jumpToPath(command)
      }

      if (['root', 'home', 'desktop', 'documents', 'downloads', 'temp', 'executable', 'input_navigate'].includes(command)) {
        return this.jumpToPath(command)
      }

      if (command === 'set_cwd') return this.setRemoteDirectoryAsCwd(this.remoteFilesCurrentPath)
      if (command === 'open_pty') return this.openRemotePtyHere(this.remoteFilesCurrentPath)
      if (command === 'refresh') return this.refreshRemoteDirectory()
      if (command === 'up') return this.goToRemoteParent()
      if (command === 'new_folder') return this.createRemoteDirectory()
      if (command === 'upload') return this.triggerRemoteUpload()
      if (command === 'drag_upload') return this.triggerDragUpload()
      if (command === 'download_selected') return this.downloadSelectedRemoteEntries()
      if (command === 'delete_selected') return this.deleteSelectedRemoteEntries()
      if (command === 'view_card') {
        this.remoteMobileViewMode = 'card'
        return
      }
      if (command === 'view_list') {
        this.remoteMobileViewMode = 'list'
        return
      }
      if (command === 'toggle_recursive') {
        this.remoteSearchRecursive = !this.remoteSearchRecursive
        return this.handleRemoteSearchRecursiveChange()
      }

      return this.handleRemoteToolbarMoreCommand(command)
    },

    handleRemoteToolbarMoreCommand(command) {
      if (command === 'drag_upload') return this.triggerDragUpload()
      if (command === 'copy_to_selected' || command === 'move_to_selected') {
        return this.openDestinationPickerForPaths(this.remoteSelectedPaths,
          command === 'move_to_selected' ? 'move' : 'copy')
      }

      if (command === 'set_cwd') return this.setRemoteDirectoryAsCwd(this.remoteFilesCurrentPath)
      if (command === 'open_pty') return this.openRemotePtyHere(this.remoteFilesCurrentPath)
      if (command === 'toggle_pin') {
        this.toggleCurrentPinnedQuickJump()
        return
      }

      if (command === 'paste') {
        this.pasteRemoteClipboard()
        return
      }

      if (command === 'copy') {
        this.copySelectedRemoteEntries()
        return
      }

      if (command === 'cut') {
        this.cutSelectedRemoteEntries()
        return
      }

      if (command === 'create_zip') {
        this.createSelectedRemoteZip()
        return
      }

      if (command === 'toggle_select_all') {
        this.toggleRemoteCurrentPageSelection()
        return
      }

      if (command === 'clear_clipboard') {
        this.clearRemoteClipboard()
        return
      }

      if (command === 'clear_selection') {
        this.clearRemoteSelection()
        return
      }

      if (command === 'toggle_hidden') {
        this.toggleRemoteHiddenFiles()
      }
    },

    resetRemoteFilesState() {
      this.resetRemoteDirectory()
      this.remoteCreatingFolder = false
      this.remoteFilesClientId = ''
      this.remoteZipDownloading = false
      this.remoteZipCreating = false
      this.remoteZipExtracting = false
      this.remotePinnedJumpItems = []
      this.remotePinnedJumpLoading = false
      this.pinManagerVisible = false
      this.destinationPickerVisible = false
      this.destinationRequest = null
      this.dragUploadVisible = false
      this.clearRemoteClipboard()
    },

  },
}
</script>

<style src="../styles/remoteFiles.css"></style>
