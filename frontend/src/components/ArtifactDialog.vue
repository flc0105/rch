<template>
  <el-dialog
    :model-value="visible"
    title="Artifact Manager"
    width="min(1280px, 96vw)"
    top="5vh"
    class="fixed-dialog artifact-dialog"
    modal-class="artifact-overlay"
    @update:model-value="handleVisibleChange"
  >
    <div class="fixed-dialog-body">
      <el-tabs
        :model-value="artifactActiveTab"
        class="artifact-tabs"
        @update:model-value="handleActiveTabChange"
      >
        <el-tab-pane :name="ARTIFACT_TYPE.SAVED">
          <template #label>Saved Files ({{ artifactCountMap.saved || 0 }})</template>
        </el-tab-pane>
        <el-tab-pane :name="ARTIFACT_TYPE.SHARED">
          <template #label>Shared Files ({{ artifactCountMap.shared || 0 }})</template>
        </el-tab-pane>
      </el-tabs>

      <ArtifactToolbar
        :is-shared-files-tab="isSharedFilesTab" :shared-file-uploading="sharedFileUploading"
        :can-edit-selected-folder="canEditSelectedFolder" :selected-artifact-ids="selectedArtifactIds"
        :artifact-bulk-deleting="artifactBulkDeleting" :artifact-clearing="artifactClearing"
        v-model:artifact-keyword="artifactKeyword" :show-artifact-machine-filter="showArtifactMachineFilter"
        v-model:artifact-machine-id-filter="artifactMachineIdFilter"
        :artifact-machine-options="artifactMachineOptions.map(item => ({ ...item, label: formatArtifactMachineOptionLabel(item) }))"
        @refresh="loadArtifacts" @create-file="createSharedFilePrompt" @upload="triggerSharedFileUpload"
        @rename-folder="renameFolderPrompt" @delete-folder="deleteSelectedFolder"
        @delete-selected="deleteSelectedArtifacts" @clear="clearCurrentArtifacts"
        @machine-filter-change="handleMachineFilterChange"
      />
      <div class="artifact-library-body">
        <ArtifactFolderTree :artifact-active-tab="artifactActiveTab" :folder-tree-nodes="folderTreeNodes"
                            :selected-folder-id="selectedFolderId" :is-shared-files-tab="isSharedFilesTab"
                            @create-folder="createFolderPrompt" @select-folder="handleFolderSelect" />
        <ArtifactFileList :current-folder-label="currentFolderLabel" :filtered-artifact-items="filteredArtifactItems"
                          :artifact-loading="artifactLoading" :selected-artifact-ids="selectedArtifactIds"
                          :standalone-mode="standaloneMode" :selected-id="selectedId"
                          @selection-change="handleArtifactSelectionChange" @toggle-selection="toggleArtifactSelection"
                          @preview="$emit('preview', $event)" @more="handleArtifactMoreCommand" @delete="deleteArtifact" />
      </div>
    </div>
  </el-dialog>

  <DragUploadDialog
    v-model="sharedFileUploadDialogVisible"
    title="Upload Shared Files"
    helper-text="Files and folders are uploaded with their directory structure."
    button-text="Upload"
    :multiple="true"
    :allow-directories="true"
    :loading="sharedFileUploading"
    :stage="sharedUploadStage" :progress="sharedUploadProgress" :can-cancel="sharedUploadCanCancel"
    @cancel="sharedUploadAbort?.abort()"
    @upload="uploadSharedFiles"
  />

  <el-dialog v-model="moveDialogVisible" title="Move to Folder" width="420px">
    <el-select v-model="moveTargetFolderId" filterable placeholder="Destination folder" style="width:100%">
      <el-option v-for="folder in moveFolderOptions" :key="folder.folder_id"
                 :label="folderFolderPath(folder)" :value="folder.folder_id" />
    </el-select>
    <template #footer>
      <el-button @click="moveDialogVisible = false">Cancel</el-button>
      <el-button type="primary" :disabled="!moveTargetFolderId" @click="confirmMoveArtifact">Move</el-button>
    </template>
  </el-dialog>

  <FileInfoDialog v-model:visible="artifactInfoDialogVisible" title="Artifact Info"
                  :has-info="Boolean(artifactInfoItem)" :sections="formattedArtifactInfoSections"
                  empty-description="No artifact info available" :monospace-values="true" />
</template>

<script>
import DragUploadDialog from './DragUploadDialog.vue'
import ArtifactToolbar from './ArtifactToolbar.vue'
import ArtifactFolderTree from './ArtifactFolderTree.vue'
import ArtifactFileList from './ArtifactFileList.vue'
import FileInfoDialog from './FileInfoDialog.vue'
import useArtifactCatalog from '../composables/useArtifactCatalog.js'
import useArtifactFolders from '../composables/useArtifactFolders.js'
import useArtifactOperations from '../composables/useArtifactOperations.js'
import useArtifactUpload from '../composables/useArtifactUpload.js'
import useArtifactDelivery from '../composables/useArtifactDelivery.js'
import { ARTIFACT_TYPE } from '../data/artifactConstants.js'

export default {
  name: 'ArtifactDialog',
  components: { DragUploadDialog, ArtifactToolbar, ArtifactFolderTree, ArtifactFileList, FileInfoDialog },
  mixins: [useArtifactCatalog, useArtifactFolders, useArtifactOperations, useArtifactUpload, useArtifactDelivery],
  props: {
    selectedId: {
      type: [String, Number],
      default: '',
    },

    currentConnection: {
      type: Object,
      default: null,
    },

    machineAliasMap: {
      type: Object,
      default: () => ({}),
    },

    getTabScopedHeaders: {
      type: Function,
      default: () => ({}),
    },
  },

  emits: ['preview', 'append-output', 'set-active-task', 'open-new-shared-file-editor'],
  data() {
    return { ARTIFACT_TYPE, visible: false, standaloneMode: false }
  },
  methods: {
    async open({ standalone = false } = {}) {
      this.standaloneMode = standalone
      this.artifactActiveTab = ARTIFACT_TYPE.SAVED
      this.artifactMachineIdFilter = standalone ? '' : this.getCurrentMachineId()
      this.selectedFolderId = ''
      this.selectedArtifactIds = []
      this.visible = true
      await this.loadArtifacts()
    },

    isDialogCancel(e) {
      return e === 'cancel' || e === 'close' || e?.toString?.().includes('cancel')
    },

    buildJsonHeaders(extra = {}) {
      if (typeof this.getTabScopedHeaders === 'function') {
        return this.getTabScopedHeaders(extra)
      }
      return extra
    },

    isOpen() {
      return this.visible
    },

    async refreshIfOpen() {
      if (!this.visible) return
      await this.loadArtifacts()
    },

    handleVisibleChange(value) {
      this.visible = value

      if (!value) {
        this.artifactInfoSeq += 1
        this.artifactMachineIdFilter = ''
        this.artifactKeyword = ''
        this.selectedArtifactIds = []
        this.sharedFileUploadDialogVisible = false
        this.artifactInfoDialogVisible = false
        this.artifactInfoItem = null
      }
    },

    async readJsonResponse(res, fallbackMessage) {
      const contentType = String(res?.headers?.get?.('content-type') || '').toLowerCase()
      if (contentType.includes('application/json')) {
        return await res.json()
      }

      const text = await res.text()
      const detail = text && text.trim().startsWith('<') ? 'Server returned HTML instead of JSON' : text
      throw new Error(detail || fallbackMessage)
    },

  },
}
</script>

<style src="../styles/artifactDialog.css"></style>
