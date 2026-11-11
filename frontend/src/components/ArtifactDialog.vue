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
        <el-tab-pane :name="ARTIFACT_SCOPE.SAVED">
          <template #label>Saved Files ({{ artifactCountMap.saved || 0 }})</template>
        </el-tab-pane>
        <el-tab-pane :name="ARTIFACT_SCOPE.SHARED">
          <template #label>Shared Files ({{ artifactCountMap.shared || 0 }})</template>
        </el-tab-pane>
      </el-tabs>

      <div class="artifact-dialog-toolbar" role="toolbar" aria-label="Artifact actions">
        <div class="artifact-toolbar-group">
          <el-button class="toolbar-btn" size="small" @click="loadArtifacts">Refresh</el-button>
          <el-button v-if="isSharedFilesTab" class="toolbar-btn" size="small" @click="createSharedFilePrompt">Create File</el-button>
          <el-button v-if="isSharedFilesTab" class="toolbar-btn" size="small" :loading="sharedFileUploading" @click="triggerSharedFileUpload">Upload</el-button>
          <span class="artifact-toolbar-divider" aria-hidden="true"></span>
          <el-button v-if="isSharedFilesTab" class="toolbar-btn" size="small" :disabled="!canEditSelectedFolder" @click="renameFolderPrompt">Rename Folder</el-button>
          <el-button v-if="isSharedFilesTab" class="toolbar-btn" size="small" :disabled="!canEditSelectedFolder" @click="deleteSelectedFolder">Delete Folder</el-button>
          <el-button class="toolbar-btn" size="small" type="danger" plain :disabled="!selectedArtifactIds.length"
                     :loading="artifactBulkDeleting" @click="deleteSelectedArtifacts">
            Delete {{ selectedArtifactIds.length ? ` (${selectedArtifactIds.length})` : '' }}
          </el-button>
          <el-button class="toolbar-btn" size="small" type="danger" :loading="artifactClearing"
                     @click="clearCurrentArtifacts">Clear</el-button>
        </div>
        <div class="artifact-toolbar-filters">
          <el-input v-model="artifactKeyword" class="artifact-toolbar-search" clearable size="small" placeholder="Search" />
          <el-select v-if="showArtifactMachineFilter" v-model="artifactMachineIdFilter"
                     class="artifact-toolbar-device" clearable filterable size="small"
                     placeholder="Filter by device" @change="handleMachineFilterChange">
            <el-option v-for="item in artifactMachineOptions" :key="item.machine_id"
                       :label="formatArtifactMachineOptionLabel(item)" :value="item.machine_id" />
          </el-select>
        </div>
      </div>

      <div class="artifact-library-body">
        <aside class="artifact-folder-sidebar">
          <div class="artifact-folder-heading">
            <span>Folders</span>
            <el-button v-if="isSharedFilesTab" size="small" text type="primary" @click="createFolderPrompt">New Folder</el-button>
          </div>
          <el-tree
            :key="artifactActiveTab"
            :data="folderTreeNodes"
            node-key="folder_id"
            :props="{ label: 'name', children: 'children' }"
            :default-expand-all="true"
            highlight-current
            :current-node-key="selectedFolderId || ARTIFACT_FOLDER_ALL"
            @node-click="handleFolderSelect"
          >
            <template #default="{ data }">
              <span class="artifact-tree-entry">
                <FolderOpen v-if="data.folder_id === ARTIFACT_FOLDER_ALL" :size="15" aria-hidden="true" />
                <Folder v-else :size="15" aria-hidden="true" />
                <span class="ellipsis">{{ data.name }}</span>
              </span>
            </template>
          </el-tree>
        </aside>

        <section class="artifact-main-panel">
          <div class="artifact-location">
            <span class="artifact-location-title" :title="currentFolderLabel">{{ currentFolderLabel }}</span>
            <span class="artifact-location-count">{{ filteredArtifactItems.length }} files</span>
          </div>

          <div class="dialog-table-shell">
        <el-table
          :data="filteredArtifactItems"
          v-loading="artifactLoading"
          stripe
          width="100%"
          height="100%"
          empty-text="No artifacts available"
          table-layout="fixed"
          row-key="artifact_id"
          @selection-change="handleArtifactSelectionChange"
        >
          <el-table-column
            type="selection"
            width="40"
            align="center"
          />
          <el-table-column
            prop="original_name"
            label="Name"
            min-width="240"
            show-overflow-tooltip
          >

            <template #default="{ row }">
              <div class="artifact-file-name" :title="formatArtifactName(row)">
                <File :size="16" aria-hidden="true" />
                <span class="ellipsis">{{ formatArtifactName(row) }}</span>
              </div>
            </template>
          </el-table-column>

          <el-table-column
            label="Size"
            width="104"
            align="right"
            show-overflow-tooltip
          >
            <template #default="{ row }">
              <span class="ellipsis" :title="formatBytes(row.size)">{{ formatBytes(row.size) }}</span>
            </template>
          </el-table-column>


          <el-table-column
            label="Saved"
            width="166"
            show-overflow-tooltip
          >
            <template #default="{ row }">
              <div class="ellipsis">
                {{ row.saved_at || '-' }}
              </div>
            </template>
          </el-table-column>

          <el-table-column
            label="Actions"
            width="188"
            align="center"
          >
            <template #default="{ row }">
              <div class="table-actions table-actions-links">
                <a
                  href="#"
                  class="table-action-link"
                  @click.prevent="$emit('preview', row)"
                >
                  Preview
                </a>

                <a
                  class="table-action-link"
                  :href="row.download_url"
                  target="_blank"
                >
                  Download
                </a>

                <template v-if="useArtifactMoreMenu(row)">
                  <el-dropdown
                    trigger="click"
                    @command="command => handleArtifactMoreCommand(row, command)"
                  >
                    <span class="table-action-link">More</span>
                    <template #dropdown>
                      <el-dropdown-menu>
                        <el-dropdown-item command="info">
                          Info
                        </el-dropdown-item>
                        <el-dropdown-item command="rename">Rename</el-dropdown-item>
                        <el-dropdown-item v-if="isSharedFileItem(row)" command="move">Move to Folder</el-dropdown-item>
                        <el-dropdown-item
                          v-if="isSharedFileItem(row) && !standaloneMode"
                          command="send-current-device"
                          :disabled="!selectedId"
                        >
                          Send to Current Device
                        </el-dropdown-item>
                        <el-dropdown-item
                          v-if="isSharedFileItem(row) && !standaloneMode"
                          command="send-current-device-clipboard"
                          :disabled="!selectedId"
                        >
                          Send to Current Device Clipboard
                        </el-dropdown-item>
                        <el-dropdown-item
                          command="delete"
                          divided
                        >
                          Delete
                        </el-dropdown-item>
                      </el-dropdown-menu>
                    </template>
                  </el-dropdown>
                </template>

                <a
                  v-else
                  href="#"
                  class="table-action-link danger"
                  @click.prevent="deleteArtifact(row)"
                >
                  Delete
                </a>
              </div>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <div class="mobile-file-list-shell">
        <div
          class="mobile-file-list"
          v-loading="artifactLoading"
        >
          <div
            v-if="!filteredArtifactItems.length && !artifactLoading"
            class="empty-state"
          >
            No artifacts available
          </div>

          <div
            v-else
            class="mobile-file-grid"
          >
            <div
              v-for="row in filteredArtifactItems"
              :key="row.artifact_id"
              class="mobile-file-card"
            >
              <div class="mobile-file-check-anchor">
                <el-checkbox
                  :model-value="isArtifactSelected(row)"
                  @change="checked => toggleArtifactSelection(row, checked)"
                />
              </div>

              <div class="mobile-file-card-top">
                <div class="mobile-file-icon"><File :size="20" aria-hidden="true" /></div>

                <div class="mobile-file-main">
                  <div class="mobile-file-name">
                    {{ formatArtifactName(row) }}
                  </div>

                  <div class="mobile-file-meta">
                    <div class="mobile-file-meta-item">
                      <div class="mobile-file-meta-label">Size</div>
                      <div class="mobile-file-meta-value">
                        {{ formatBytes(row.size) }}
                      </div>
                    </div>

                    <div class="mobile-file-meta-item">
                      <div class="mobile-file-meta-label">Created</div>
                      <div class="mobile-file-meta-value">
                        {{ row.saved_at || '-' }}
                      </div>
                    </div>
                  </div>

                  <div class="mobile-file-actions">
                    <el-button
                      size="small"
                      type="primary"
                      plain
                      @click="$emit('preview', row)"
                    >
                      Preview
                    </el-button>

                    <a :href="row.download_url" target="_blank">
                      <el-button size="small" type="primary" plain>
                        Download
                      </el-button>
                    </a>

                    <template v-if="useArtifactMoreMenu(row)">
                      <el-dropdown
                        trigger="click"
                        @command="command => handleArtifactMoreCommand(row, command)"
                      >
                        <el-button size="small" type="primary" plain>
                          More
                        </el-button>
                        <template #dropdown>
                          <el-dropdown-menu>
                            <el-dropdown-item command="info">
                              Info
                            </el-dropdown-item>
                            <el-dropdown-item command="rename">Rename</el-dropdown-item>
                            <el-dropdown-item v-if="isSharedFileItem(row)" command="move">Move to Folder</el-dropdown-item>
                            <el-dropdown-item
                              v-if="isSharedFileItem(row) && !standaloneMode"
                              command="send-current-device"
                              :disabled="!selectedId"
                            >
                              Send
                            </el-dropdown-item>
                            <el-dropdown-item
                              v-if="isSharedFileItem(row) && !standaloneMode"
                              command="send-current-device-clipboard"
                              :disabled="!selectedId"
                            >
                              Send to Current Device Clipboard
                            </el-dropdown-item>
                            <el-dropdown-item
                              command="delete"
                              divided
                            >
                              Delete
                            </el-dropdown-item>
                          </el-dropdown-menu>
                        </template>
                      </el-dropdown>
                    </template>

                    <el-button
                      v-else
                      size="small"
                      type="danger"
                      plain
                      @click="deleteArtifact(row)"
                    >
                      Delete
                    </el-button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
          </div>
        </section>
      </div>
    </div>
  </el-dialog>

  <DragUploadDialog
    v-model="sharedFileUploadDialogVisible"
    title="Upload Shared Files"
    helper-text="Drag files here or choose files to upload to the selected file space."
    button-text="Upload"
    :multiple="true"
    :loading="sharedFileUploading"
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

  <el-dialog
    v-model="artifactInfoDialogVisible"
    title="Artifact Info"
    width="760px"
    top="8vh"
    class="fixed-dialog"
  >
    <div class="preview-image-info-body">
      <template v-if="artifactInfoItem">
        <div
          v-for="section in formattedArtifactInfoSections"
          :key="section.key"
          class="preview-image-info-section"
        >
          <div class="preview-image-info-title">
            {{ section.title }}
          </div>

          <div
            v-for="item in section.items"
            :key="section.key + '-' + item.key"
            class="preview-image-info-row"
          >
            <div class="preview-image-info-label">
              {{ item.label }}
            </div>

            <div class="preview-image-info-value">
              {{ item.value }}
            </div>
          </div>
        </div>
      </template>

      <el-empty
        v-else
        description="No artifact info available"
      />
    </div>
  </el-dialog>
</template>

<script>
import { listArtifacts, uploadArtifact, renameArtifact as requestRenameArtifact, sendArtifactToClient, deleteArtifact as deleteArtifactRequest, clearArtifacts, createArtifactFolder, renameArtifactFolder, deleteArtifactFolder, moveArtifactToFolder } from '../api/artifactsApi.js'
import { prepareUploadConflict } from '../utils/remoteFileConflicts.js'
import { createTerminalOperation, operationHeaders } from '../utils/terminalOperation.js'
import { formatTerminalCommandFinishedLine } from '../composables/terminalMarkers.js'
import { ElMessage, ElMessageBox } from 'element-plus'
import { setRemoteClipboardArtifactFile } from '../api/clipboardApi.js'
import { formatBytes as formatBytesValue } from '../utils/formatters.js'
import DragUploadDialog from './DragUploadDialog.vue'
import { File, Folder, FolderOpen } from '@lucide/vue'
import { ARTIFACT_SCOPE, ARTIFACT_FOLDER_ALL } from '../data/artifactConstants.js'

export default {
  name: 'ArtifactDialog',

  components: {
    DragUploadDialog,
    File,
    Folder,
    FolderOpen,
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
    return {
      ARTIFACT_SCOPE,
      ARTIFACT_FOLDER_ALL,
      visible: false,
      standaloneMode: false,
      artifactLoading: false,
      artifactItems: [],
      artifactMachines: [],
      artifactActiveTab: ARTIFACT_SCOPE.SAVED,
      artifactFolders: [],
      moveDialogVisible: false,
      moveArtifactItem: null,
      moveTargetFolderId: '',
      selectedFolderId: '',
      artifactMachineIdFilter: '',
      artifactKeyword: '',
      selectedArtifactIds: [],
      artifactClearing: false,
      artifactBulkDeleting: false,
      sharedFileUploading: false,
      sharedFileUploadDialogVisible: false,
      artifactInfoDialogVisible: false,
      artifactInfoItem: null,
    }
  },

  computed: {
    isSharedFilesTab() {
      return this.artifactActiveTab === ARTIFACT_SCOPE.SHARED
    },

    showArtifactMachineFilter() {
      return !this.isSharedFilesTab
    },

    currentFolderLabel() {
      if (!this.selectedFolderId) return 'All Files'
      return (this.artifactFolders || []).find(folder => folder.folder_id === this.selectedFolderId)?.name || 'All Files'
    },

    folderTreeNodes() {
      const folders = (this.artifactFolders || [])
        .filter(folder => folder.scope === this.artifactActiveTab)
      const nodes = folders.map(folder => ({ ...folder, children: [] }))
      const byId = Object.fromEntries(nodes.map(node => [node.folder_id, node]))
      const roots = []
      nodes.forEach(node => {
        if (node.parent_id && byId[node.parent_id]) byId[node.parent_id].children.push(node)
        else roots.push(node)
      })
      return [{ folder_id: ARTIFACT_FOLDER_ALL, name: 'All Files', children: [] }, ...roots]
    },

    moveFolderOptions() {
      return (this.artifactFolders || []).filter(folder =>
        folder.scope === ARTIFACT_SCOPE.SHARED &&
        this.moveArtifactItem?.scope === ARTIFACT_SCOPE.SHARED)
    },

    canEditSelectedFolder() {
      const folder = (this.artifactFolders || []).find(item => item.folder_id === this.selectedFolderId)
      return Boolean(this.isSharedFilesTab && folder && !folder.preset)
    },

    artifactMachineOptions() {
      const map = {}

      ;(this.artifactMachines || []).forEach(item => {
        const machineId = this.normalizeMachineId(item?.machine_id)
        if (!machineId) return

        map[machineId] = {
          ...item,
          machine_id: machineId,
          hostname: String(item?.hostname || '').trim(),
        }
      })

      const currentMachineId = this.getCurrentMachineId()
      if (currentMachineId) {
        const existing = map[currentMachineId] || {}
        const currentHostname = String(this.currentConnection?.hostname || '').trim()

        map[currentMachineId] = {
          ...existing,
          machine_id: currentMachineId,
          hostname: currentHostname || String(existing.hostname || '').trim(),
        }
      }

      return Object.values(map).sort((a, b) =>
        this.formatArtifactMachineOptionLabel(a).localeCompare(
          this.formatArtifactMachineOptionLabel(b)
        )
      )
    },

    filteredArtifactItems() {
      const machineId = this.normalizeMachineId(this.artifactMachineIdFilter)
      const keyword = String(this.artifactKeyword || '').trim().toLowerCase()
      return (this.artifactItems || []).filter(item => {
        if (item.scope !== this.artifactActiveTab) return false
        if (this.selectedFolderId && item.folder_id !== this.selectedFolderId) return false
        if (!this.isSharedFilesTab && machineId && this.normalizeMachineId(item.machine_id) !== machineId) return false
        if (keyword) {
          const searchable = [this.formatArtifactName(item), item.category, item.hostname,
            this.folderNameForArtifact(item)].join(' ').toLowerCase()
          if (!searchable.includes(keyword)) return false
        }
        return true
      })
    },

    selectedArtifacts() {
      const selected = new Set(this.selectedArtifactIds)
      return (this.artifactItems || []).filter(item => selected.has(String(item?.artifact_id || '').trim()))
    },

    artifactCountMap() {
      const counts = { saved: 0, shared: 0 }
      const machineId = this.normalizeMachineId(this.artifactMachineIdFilter)
      ;(this.artifactItems || []).forEach(item => {
        if (!Object.prototype.hasOwnProperty.call(counts, item.scope)) return
        if (item.scope === ARTIFACT_SCOPE.SAVED && machineId && this.normalizeMachineId(item.machine_id) !== machineId) return
        counts[item.scope] += 1
      })
      return counts
    },

    formattedArtifactInfoSections() {
      return this.formatArtifactInfoSections(this.artifactInfoItem)
    },
  },

  watch: {
    'currentConnection.machine_id'(machineId) {
      if (!this.visible || this.standaloneMode) return
      this.artifactMachineIdFilter = this.normalizeMachineId(machineId)
      if (this.isSharedFilesTab) return
      this.selectedArtifactIds = []
      this.selectedFolderId = ''
    },
  },

  methods: {
    folderNameForArtifact(item) {
      return (this.artifactFolders || []).find(folder => folder.folder_id === item?.folder_id)?.name || 'Unfiled'
    },

    handleFolderSelect(node) {
      this.selectedFolderId = node.folder_id === ARTIFACT_FOLDER_ALL ? '' : node.folder_id
      this.selectedArtifactIds = []
    },

    async requestArtifactMutation(request, fallback) {
      const response = await request
      const json = await response.json()
      if (!response.ok || json.code !== 0) throw new Error(json.message || fallback)
      await this.loadArtifacts()
      return json.data || {}
    },

    async createFolderPrompt() {
      if (!this.isSharedFilesTab) return
      try {
        const { value } = await ElMessageBox.prompt('Folder name', 'New Folder', {
          inputPattern: /\S/, inputErrorMessage: 'Folder name is required',
        })
        await this.requestArtifactMutation(createArtifactFolder(this.artifactActiveTab,
          String(value || '').trim(), this.selectedFolderId), 'Failed to create folder')
      } catch (error) {
        if (!this.isDialogCancel(error)) ElMessage.error(error.message || 'Failed to create folder')
      }
    },

    async renameFolderPrompt() {
      if (!this.canEditSelectedFolder) return
      try {
        const folder = this.artifactFolders.find(item => item.folder_id === this.selectedFolderId)
        const { value } = await ElMessageBox.prompt('Folder name', 'Rename Folder', { inputValue: folder.name })
        await this.requestArtifactMutation(renameArtifactFolder(folder.folder_id, String(value || '').trim()),
          'Failed to rename folder')
      } catch (error) {
        if (!this.isDialogCancel(error)) ElMessage.error(error.message || 'Failed to rename folder')
      }
    },

    async deleteSelectedFolder() {
      if (!this.canEditSelectedFolder) return
      try {
        await ElMessageBox.confirm('Delete this empty folder?', 'Delete Folder', { type: 'warning' })
        await this.requestArtifactMutation(deleteArtifactFolder(this.selectedFolderId), 'Failed to delete folder')
        this.selectedFolderId = ''
      } catch (error) {
        if (!this.isDialogCancel(error)) ElMessage.error(error.message || 'Failed to delete folder')
      }
    },

    folderFolderPath(folder) {
      const byId = Object.fromEntries((this.artifactFolders || []).map(item => [item.folder_id, item]))
      const parts = [folder.name]
      let current = folder.parent_id
      const seen = new Set([folder.folder_id])
      while (current && byId[current] && !seen.has(current)) {
        seen.add(current)
        parts.unshift(byId[current].name)
        current = byId[current].parent_id
      }
      return parts.join(' / ')
    },

    moveArtifactPrompt(row) {
      if (!this.isSharedFileItem(row)) return
      this.moveArtifactItem = row
      this.moveTargetFolderId = row.folder_id || ''
      this.moveDialogVisible = true
    },

    async confirmMoveArtifact() {
      if (!this.isSharedFileItem(this.moveArtifactItem) || !this.moveTargetFolderId) return
      try {
        await this.requestArtifactMutation(moveArtifactToFolder(this.moveArtifactItem.artifact_id,
          this.moveTargetFolderId), 'Failed to move file')
        this.moveDialogVisible = false
      } catch (error) {
        ElMessage.error(error.message || 'Failed to move file')
      }
    },

    formatBytes(value) {
      return formatBytesValue(value)
    },

    async open({ standalone = false } = {}) {
      this.standaloneMode = standalone
      this.artifactActiveTab = ARTIFACT_SCOPE.SAVED
      this.artifactMachineIdFilter = standalone ? '' : this.getCurrentMachineId()
      this.selectedFolderId = ''
      this.selectedArtifactIds = []
      this.visible = true
      await this.loadArtifacts()
    },

    normalizeMachineId(value) {
      return String(value || '').trim()
    },

    getCurrentMachineId() {
      return this.normalizeMachineId(this.currentConnection?.machine_id)
    },

    shortenMachineId(machineId) {
      const value = this.normalizeMachineId(machineId)
      if (!value) return '-'

      return value.length > 12 ? value.slice(0, 12) : value
    },

    getMachineAlias(machineId) {
      const id = this.normalizeMachineId(machineId)
      if (!id) return ''
      return String(this.machineAliasMap?.[id] || '').trim()
    },

    formatArtifactMachineOptionLabel(machine) {
      const machineId = this.normalizeMachineId(machine?.machine_id)
      if (!machineId) return '-'

      const alias = this.getMachineAlias(machineId)
      const shortId = this.shortenMachineId(machineId)
      const hostname = String(machine?.hostname || '').trim()

      if (alias) return `${alias} (${shortId})`
      return hostname ? `${shortId} (${hostname})` : shortId
    },

    formatCurrentDeviceLabel() {
      const conn = this.currentConnection || {}
      const machineId = this.normalizeMachineId(conn.machine_id || conn.client_id || this.selectedId)
      const alias = this.getMachineAlias(machineId)
      const hostname = String(conn.hostname || '').trim()
      const shortId = machineId ? this.shortenMachineId(machineId) : String(this.selectedId || '').trim()

      if (alias) return `${alias} (${shortId})`
      if (shortId && hostname) return `${shortId} (${hostname})`
      return shortId || hostname || 'current device'
    },

    getCurrentDeviceCwd() {
      return String(this.currentConnection?.cwd || '').trim()
    },

    formatCurrentDeviceCwd() {
      return this.getCurrentDeviceCwd() || 'current working directory'
    },

    formatArtifactName(row) {
      return row?.original_name || row?.stored_name || 'artifact'
    },

    openArtifactInfoDialog(row) {
      if (!row || !row.artifact_id) {
        ElMessage.warning('Invalid artifact')
        return
      }

      this.artifactInfoItem = { ...row }
      this.artifactInfoDialogVisible = true
    },

    formatArtifactInfoSections(row) {
      if (!row || typeof row !== 'object') {
        return []
      }

      const sections = [
        {
          key: 'basic',
          title: 'Basic',
          fields: [
            ['original_name', 'Original Name'],
            ['stored_name', 'Stored Name'],
            ['artifact_id', 'Artifact ID'],
            ['artifact_type', 'Artifact Type'],
            ['size', 'Size'],
            ['saved_at', 'Saved At'],
            ['is_available', 'Available'],
            ['status_text', 'Status'],
          ],
        },
        {
          key: 'source',
          title: 'Source',
          fields: [
            ['hostname', 'Hostname'],
            ['machine_id', 'Machine ID'],
            ['client_id', 'Client ID'],
            ['addr', 'Address'],
            ['source_command_id', 'Source Command ID'],
            ['linked_jobs', 'Jobs'],
          ],
        },
        {
          key: 'paths',
          title: 'Paths / URLs',
          fields: [
            ['saved_path', 'Saved Path'],
            ['download_url', 'Download URL'],
            ['raw_url', 'Raw URL'],
            ['preview_url', 'Preview URL'],
          ],
        },
        {
          key: 'extra',
          title: 'Extra',
          fields: [
            ['extra', 'Extra'],
          ],
        },
      ]

      const usedKeys = new Set()
      const result = []

      sections.forEach(section => {
        const items = []

        section.fields.forEach(([key, label]) => {
          if (!Object.prototype.hasOwnProperty.call(row, key)) return

          const formattedValue = this.formatArtifactInfoValue(key, row[key])
          if (formattedValue === '-') return

          items.push({
            key,
            label,
            value: formattedValue,
          })
          usedKeys.add(key)
        })

        if (items.length) {
          result.push({
            key: section.key,
            title: section.title,
            items,
          })
        }
      })

      const otherItems = Object.keys(row)
        .filter(key => !usedKeys.has(key))
        .sort((a, b) => a.localeCompare(b))
        .map(key => ({
          key,
          label: key,
          value: this.formatArtifactInfoValue(key, row[key]),
        }))
        .filter(item => item.value !== '-')

      if (otherItems.length) {
        result.push({
          key: 'other',
          title: 'Other Meta',
          items: otherItems,
        })
      }

      return result
    },

    formatArtifactInfoValue(key, value) {
      if (value === null || value === undefined || value === '') return '-'

      if (key === 'size') {
        const numericValue = Number(value || 0)
        return `${this.formatBytes(numericValue)} (${numericValue} bytes)`
      }

      if (typeof value === 'boolean') {
        return value ? 'Yes' : 'No'
      }

      if (Array.isArray(value)) {
        if (!value.length) return '-'
        return value.map(item => this.formatArtifactInfoNestedValue(item)).join(', ')
      }

      if (typeof value === 'object') {
        const keys = Object.keys(value)
        if (!keys.length) return '-'

        try {
          return JSON.stringify(value, null, 2)
        } catch (_e) {
          return String(value)
        }
      }

      return String(value)
    },

    formatArtifactInfoNestedValue(value) {
      if (value === null || value === undefined || value === '') return '-'

      if (typeof value === 'object') {
        try {
          return JSON.stringify(value)
        } catch (_e) {
          return String(value)
        }
      }

      return String(value)
    },

    isSharedFileItem(item) {
      return item?.scope === ARTIFACT_SCOPE.SHARED
    },

    useArtifactMoreMenu(item) {
      return item?.scope === ARTIFACT_SCOPE.SAVED || item?.scope === ARTIFACT_SCOPE.SHARED
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
        this.artifactMachineIdFilter = ''
        this.artifactKeyword = ''
        this.selectedArtifactIds = []
        this.sharedFileUploadDialogVisible = false
        this.artifactInfoDialogVisible = false
        this.artifactInfoItem = null
      }
    },

    handleArtifactSelectionChange(rows) {
      this.selectedArtifactIds = (rows || [])
        .map(item => String(item?.artifact_id || '').trim())
        .filter(Boolean)
    },

    isArtifactSelected(row) {
      const artifactId = String(row?.artifact_id || '').trim()
      return Boolean(artifactId && this.selectedArtifactIds.includes(artifactId))
    },

    toggleArtifactSelection(row, checked) {
      const artifactId = String(row?.artifact_id || '').trim()
      if (!artifactId) return

      if (checked) {
        if (!this.selectedArtifactIds.includes(artifactId)) {
          this.selectedArtifactIds = [...this.selectedArtifactIds, artifactId]
        }
        return
      }

      this.selectedArtifactIds = this.selectedArtifactIds.filter(item => item !== artifactId)
    },

    async handleActiveTabChange(tabName) {
      this.artifactActiveTab = tabName || ARTIFACT_SCOPE.SAVED
      this.selectedFolderId = ''
      this.selectedArtifactIds = []
      await this.loadArtifacts()
    },

    handleMachineFilterChange() {
      this.selectedArtifactIds = []
    },

    async loadArtifacts() {
      this.artifactLoading = true

      try {
        const res = await listArtifacts()
        const json = await res.json()

        if (!res.ok || json.code !== 0) {
          throw new Error(json.message || 'Failed to load artifacts')
        }

        const data = json.data || {}
        this.artifactItems = Array.isArray(data.items) ? data.items : []
        this.artifactMachines = Array.isArray(data.machines) ? data.machines : []
        this.artifactFolders = Array.isArray(data.folders) ? data.folders : []
        this.pruneArtifactSelection()
      } catch (e) {
        this.artifactItems = []
        this.artifactMachines = []
        this.artifactFolders = []
        ElMessage.error(e.message || 'Failed to load artifacts')
      } finally {
        this.artifactLoading = false
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

    pruneArtifactSelection() {
      const available = new Set(
        (this.artifactItems || [])
          .map(item => String(item?.artifact_id || '').trim())
          .filter(Boolean)
      )
      this.selectedArtifactIds = this.selectedArtifactIds.filter(item => available.has(item))
    },

    async createSharedFilePrompt() {
      if (!this.isSharedFilesTab) return

      try {
        const { value } = await ElMessageBox.prompt(
          'Enter the new shared file name',
          'Create File',
          {
            confirmButtonText: 'Create',
            cancelButtonText: 'Cancel',
            inputValue: 'new_file.txt',
            inputPlaceholder: 'new_file.txt',
          }
        )

        const filename = String(value || 'new_file.txt').trim()
        if (!filename) {
          ElMessage.warning('File name is required')
          return
        }

        this.$emit('open-new-shared-file-editor', filename, this.selectedFolderId)
      } catch (e) {
        if (e === 'cancel' || e === 'close') return
      }
    },

    triggerSharedFileUpload() {
      if (!this.isSharedFilesTab) return
      this.sharedFileUploadDialogVisible = true
    },

    async uploadSingleSharedFile(file) {
      const formData = new FormData()
      formData.append('file', file)
      formData.append('artifact_type', 'shared_files')
      if (this.selectedFolderId) formData.append('folder_id', this.selectedFolderId)

      const res = await uploadArtifact(formData, this.buildJsonHeaders())
      const json = await res.json()

      if (!res.ok || json.code !== 0) {
        throw new Error(json.message || `Upload failed: ${file.name}`)
      }

      return json.data || {}
    },

    async uploadSharedFiles(files) {
      if (!this.isSharedFilesTab) return
      const uploadFiles = Array.isArray(files) ? files.filter(Boolean) : []
      if (!uploadFiles.length) return

      this.sharedFileUploading = true

      try {
        for (const file of uploadFiles) {
          await this.uploadSingleSharedFile(file)
        }

        const message = uploadFiles.length === 1
          ? `Uploaded: ${uploadFiles[0].name}`
          : `Uploaded ${uploadFiles.length} file(s)`
        ElMessage.success(message)
        this.sharedFileUploadDialogVisible = false
        await this.loadArtifacts()
      } catch (e) {
        ElMessage.error(e.message || 'Upload failed')
      } finally {
        this.sharedFileUploading = false
      }
    },

    async handleArtifactMoreCommand(row, command) {
      if (command === 'info') {
        this.openArtifactInfoDialog(row)
        return
      }

      if (command === 'move') {
        if (!this.isSharedFileItem(row)) return
        await this.moveArtifactPrompt(row)
        return
      }

      if (command === 'rename') {
        await this.renameArtifact(row)
        return
      }

      if (command === 'send-current-device') {
        await this.sendArtifactToCurrentDevice(row)
        return
      }

      if (command === 'send-current-device-clipboard') {
        await this.sendArtifactToCurrentDeviceClipboard(row)
        return
      }

      if (command === 'delete') {
        await this.deleteArtifact(row)
      }
    },

    async renameArtifact(row) {
      if (!row || !row.artifact_id) {
        ElMessage.warning('Invalid artifact')
        return
      }

      const oldName = this.formatArtifactName(row)

      try {
        const { value } = await ElMessageBox.prompt(
          'Enter the new file name',
          'Rename',
          {
            confirmButtonText: 'Rename',
            cancelButtonText: 'Cancel',
            inputValue: oldName,
            inputPattern: /.+/,
            inputErrorMessage: 'New name is required',
          }
        )

        const newName = String(value || '').trim()
        if (!newName || newName === oldName) return

        const res = await requestRenameArtifact(
          row.artifact_id, newName, this.buildJsonHeaders({ 'Content-Type': 'application/json' }),
        )

        const json = await this.readJsonResponse(res, 'Rename failed')
        if (!res.ok || json.code !== 0) {
          throw new Error(json.message || 'Rename failed')
        }

        ElMessage.success(`Renamed: ${newName}`)
        await this.loadArtifacts()
      } catch (e) {
        if (this.isDialogCancel(e)) return
        ElMessage.error(e.message || 'Rename failed')
      }
    },

    async sendArtifactToCurrentDeviceClipboard(row) {
      if (this.standaloneMode) return
      if (!row || !row.artifact_id || !this.isSharedFileItem(row)) {
        ElMessage.warning('Invalid shared file')
        return
      }

      const clientId = String(this.selectedId || this.currentConnection?.client_id || '').trim()
      if (!clientId) {
        ElMessage.warning('Please select a device')
        return
      }

      try {
        await setRemoteClipboardArtifactFile(clientId, row.artifact_id)
        ElMessage.success(`Sent to clipboard: ${this.formatArtifactName(row)}`)
      } catch (e) {
        ElMessage.error(e.message || 'Failed to send file to target clipboard')
      }
    },

    async sendArtifactToCurrentDevice(row) {
      if (this.standaloneMode) return
      if (!row || !row.artifact_id) {
        ElMessage.warning('Invalid artifact')
        return
      }

      const clientId = String(this.selectedId || this.currentConnection?.client_id || '').trim()
      if (!clientId) {
        ElMessage.warning('Please select a device')
        return
      }

      const displayName = this.formatArtifactName(row)
      const deviceLabel = this.formatCurrentDeviceLabel()
      const targetCwd = this.getCurrentDeviceCwd()
      const targetCwdLabel = this.formatCurrentDeviceCwd()

      try {
        await ElMessageBox.confirm(
          `Send "${displayName}" to ${deviceLabel} directory: ${targetCwdLabel}?`,
          'Send to Current Device',
          {
            confirmButtonText: 'Send',
            cancelButtonText: 'Cancel',
            type: 'warning',
          }
        )
      } catch (e) {
        if (this.isDialogCancel(e)) return
        return
      }

      if (this.standaloneMode) return
      let operation = null
      try {
        const conflictPolicy = await prepareUploadConflict(clientId, targetCwd || '.', displayName)
        if (conflictPolicy === false || this.standaloneMode ||
            String(this.selectedId || this.currentConnection?.client_id || '').trim() !== clientId ||
            this.getCurrentDeviceCwd() !== targetCwd) return
        operation = createTerminalOperation({ kind: 'transfer', action: 'upload_files', clientId,
          invocation: { source: 'artifact_send', artifact_id: row.artifact_id, destination: targetCwd }, replay: null })
        this.$emit(
          'append-output', clientId,
          `> [Artifact Send] ${displayName} -> ${deviceLabel} :: ${targetCwdLabel}`, 'command',
          { operation },
        )
        const res = await sendArtifactToClient(
          row.artifact_id, clientId, targetCwd, operationHeaders(operation, this.buildJsonHeaders({ 'Content-Type': 'application/json' })), conflictPolicy,
        )
        const json = await res.json()

        if (!res.ok || json.code !== 0) {
          throw new Error(json.message || 'Send failed')
        }

        const taskId = json.data && json.data.task_id
        this.$emit('set-active-task', clientId, taskId || '', '', '', operation.operation_id)
        ElMessage.success(`Send started: ${displayName}`)
      } catch (e) {
        const failedDuringPreflight = !operation
        const title = `[Artifact Send] ${displayName} -> ${deviceLabel} :: ${targetCwdLabel}`
        if (failedDuringPreflight) {
          operation = createTerminalOperation({ kind: 'transfer', action: 'upload_files', clientId,
            invocation: { source: 'artifact_send', artifact_id: row.artifact_id, destination: targetCwd }, replay: null })
          this.$emit('append-output', clientId, `> ${title}`, 'command', { operation })
        }
        this.$emit('append-output', clientId, `[Artifact send failed] ${e.message || 'unknown error'}`,
          'error', { operation_id: operation.operation_id, event_type: 'submission_error' })
        if (failedDuringPreflight) {
          this.$emit('append-output', clientId, formatTerminalCommandFinishedLine(title, 'Failed'),
            'error', { operation_id: operation.operation_id, event_type: 'completed', execution_status: 'failed', execution_success: false })
        }
        ElMessage.error(e.message || 'Send failed')
      }
    },

    async requestDeleteArtifact(row) {
      const artifactId = String(row?.artifact_id || '').trim()
      if (!artifactId) throw new Error('Invalid artifact')

      const res = await deleteArtifactRequest(artifactId)
      const json = await this.readJsonResponse(res, 'Delete failed')

      if (!res.ok || json.code !== 0) {
        throw new Error(json.message || 'Delete failed')
      }

      return json.data || {}
    },

    async deleteArtifact(row) {
      if (!row || !row.artifact_id) {
        ElMessage.warning('Invalid artifact')
        return
      }

      try {
        await ElMessageBox.confirm(
          `Delete "${this.formatArtifactName(row)}"?`,
          'Delete Confirmation',
          { type: 'warning', confirmButtonText: 'Delete', cancelButtonText: 'Cancel' }
        )

        await this.requestDeleteArtifact(row)
        this.selectedArtifactIds = this.selectedArtifactIds.filter(id => id !== String(row.artifact_id || '').trim())
        ElMessage.success('Deleted')
        await this.loadArtifacts()
      } catch (e) {
        if (this.isDialogCancel(e)) return
        ElMessage.error(e.message || 'Delete failed')
      }
    },

    async deleteSelectedArtifacts() {
      const selected = this.selectedArtifacts
      if (!selected.length || this.artifactBulkDeleting) return

      try {
        await ElMessageBox.confirm(
          `Delete ${selected.length} selected artifact(s)?`,
          'Delete Selected Artifacts',
          { type: 'warning', confirmButtonText: 'Delete', cancelButtonText: 'Cancel' }
        )
      } catch (e) {
        if (this.isDialogCancel(e)) return
        return
      }

      this.artifactBulkDeleting = true
      let deletedCount = 0
      let failedCount = 0

      try {
        for (const item of selected) {
          try {
            await this.requestDeleteArtifact(item)
            deletedCount += 1
          } catch (_e) {
            failedCount += 1
          }
        }

        this.selectedArtifactIds = []
        await this.loadArtifacts()

        if (failedCount) {
          ElMessage.warning(`Deleted ${deletedCount}, failed ${failedCount}`)
        } else {
          ElMessage.success(`Deleted ${deletedCount} item(s)`)
        }
      } finally {
        this.artifactBulkDeleting = false
      }
    },

    async clearCurrentArtifacts() {
      const scope = this.artifactActiveTab
      try {
        const where = this.selectedFolderId ? ` in ${this.folderNameForArtifact({ folder_id: this.selectedFolderId })}` : ''
        const device = !this.isSharedFilesTab && this.artifactMachineIdFilter ? ' for selected device' : ''
        await ElMessageBox.confirm(`Clear all ${scope} files${where}${device}?`,
          'Clear Artifacts', { type: 'warning', confirmButtonText: 'Clear', cancelButtonText: 'Cancel' })
        this.artifactClearing = true
        const result = await this.requestArtifactMutation(clearArtifacts('',
          this.isSharedFilesTab ? '' : this.artifactMachineIdFilter, scope, this.selectedFolderId), 'Clear failed')
        ElMessage.success(`Cleared ${result.deleted_count || 0} item(s)`)
      } catch (error) {
        if (!this.isDialogCancel(error)) ElMessage.error(error.message || 'Clear failed')
      } finally {
        this.artifactClearing = false
      }
    },
  },
}
</script>

<style scoped>
/* Artifacts: navigation on the left, current folder and operations on the right. */
.fixed-dialog-body {
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.artifact-tabs {
  flex: 0 0 auto;
}

.artifact-tabs :deep(.el-tabs__header) {
  margin-bottom: 12px;
}

.artifact-library-body {
  display: flex;
  flex: 1 1 auto;
  min-height: 0;
  min-width: 0;
  gap: 14px;
}

.artifact-folder-sidebar {
  display: flex;
  flex-direction: column;
  flex: 0 0 204px;
  min-height: 0;
  min-width: 0;
  padding: 10px 8px;
  background: var(--el-fill-color-lighter, #f8fafc);
  border: 1px solid var(--el-border-color-light);
  border-radius: 10px;
}

.artifact-folder-heading {
  display: flex;
  height: 34px;
  min-height: 34px;
  box-sizing: border-box;
  align-items: center;
  justify-content: space-between;
  gap: 4px;
  padding: 0 4px 10px;
  font-weight: 600;
  font-size: 13px;
}

.artifact-folder-heading :deep(.el-button) {
  margin: 0;
  padding: 0 4px;
  font-size: 12px;
}

.artifact-folder-sidebar :deep(.el-tree) {
  flex: 1 1 auto;
  min-height: 0;
  overflow-x: hidden;
  overflow-y: auto;
  background: transparent;
  font-size: 13px;
}

.artifact-folder-sidebar :deep(.el-tree-node__content) {
  min-height: 32px;
  height: auto;
  border-radius: 6px;
}

.artifact-main-panel {
  display: flex;
  flex: 1 1 0;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}

.artifact-dialog-toolbar {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px 14px;
  padding: 1px 0 13px;
}

.artifact-toolbar-group,
.artifact-toolbar-filters {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 7px;
  min-width: 0;
}

.artifact-toolbar-filters {
  margin-left: auto;
}

.artifact-dialog-toolbar :deep(.el-button) {
  margin: 0;
  height: 32px;
  padding: 0 11px;
  white-space: nowrap;
}

.artifact-toolbar-divider {
  width: 1px;
  height: 22px;
  margin: 0 2px;
  background: var(--el-border-color);
}

.artifact-toolbar-search { width: 170px; }
.artifact-toolbar-device { width: 205px; }

.artifact-dialog-toolbar :deep(.el-input__wrapper),
.artifact-dialog-toolbar :deep(.el-select__wrapper) {
  min-height: 32px;
}

.artifact-location {
  display: flex;
  align-items: baseline;
  flex: 0 0 auto;
  gap: 9px;
  padding: 3px 0 12px;
  min-width: 0;
  white-space: nowrap;
}

.artifact-location-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--el-text-color-primary);
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
}

.artifact-location-count {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  flex-shrink: 0;
}

.artifact-tree-entry,
.artifact-file-name {
  display: flex;
  align-items: center;
  gap: 7px;
  min-width: 0;
  white-space: nowrap;
}

.artifact-tree-entry > svg,
.artifact-file-name > svg {
  flex: 0 0 auto;
  color: var(--el-text-color-secondary);
}

.artifact-file-name .ellipsis,
.artifact-tree-entry .ellipsis {
  display: block;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
}

.dialog-table-shell {
  flex: 1 1 auto;
  min-height: 0;
  min-width: 0;
  height: 100%;
  overflow: hidden;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
}

.dialog-table-shell :deep(.el-table),
.dialog-table-shell :deep(.el-table__inner-wrapper),
.dialog-table-shell :deep(.el-scrollbar),
.dialog-table-shell :deep(.el-scrollbar__wrap) {
  width: 100%;
  height: 100% !important;
}

.dialog-table-shell :deep(.el-scrollbar__wrap) {
  overflow-y: auto !important;
  overflow-x: auto !important;
}

.dialog-table-shell :deep(.el-table__body-wrapper) {
  overflow-y: auto !important;
}

.dialog-table-shell :deep(.el-table th.el-table__cell) {
  background: #f8fafc !important;
  color: #475569;
  font-weight: 700;
}

.dialog-table-shell :deep(.el-table tr) {
  background: #fff;
}

.dialog-table-shell :deep(.el-table .cell) {
  line-height: 1.5;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.ellipsis {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.table-actions {
  display: flex;
  align-items: center;
  justify-content: center;
  flex-wrap: nowrap;
  min-height: 28px;
  white-space: nowrap;
}

.table-actions-links {
  gap: 8px;
}

.table-action-link {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  line-height: 1;
  color: var(--el-color-primary);
  text-decoration: none;
  font-size: 12px;
  white-space: nowrap;
  vertical-align: middle;
  cursor: pointer;
}

.table-action-link:hover {
  color: var(--el-color-primary-light-5);
  text-decoration: underline;
}

.table-action-link.danger {
  color: var(--danger);
}

.mobile-file-list-shell,
.mobile-file-list {
  display: none;
}

.mobile-file-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: 12px;
  height: 100%;
  min-height: 0;
  overflow-y: auto;
  padding-right: 2px;
}

.mobile-file-card {
  position: relative;
  background: #fff;
  border: 1px solid rgba(15, 23, 42, 0.06);
  border-radius: 14px;
  padding: 12px;
  box-shadow: 0 4px 14px rgba(15, 23, 42, 0.04);
}

.mobile-file-card-top {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  min-width: 0;
}

.mobile-file-icon {
  flex: 0 0 auto;
  font-size: 20px;
  line-height: 1;
  margin-top: 2px;
}

.mobile-file-check-anchor {
  position: absolute;
  top: 6px;
  right: 12px;
  z-index: 1;
}

.mobile-file-main {
  min-width: 0;
  flex: 1;
}

.mobile-file-name {
  padding-right: 42px;
  font-size: 14px;
  font-weight: 700;
  color: var(--text);
  line-height: 1.4;
  word-break: break-word;
}

.mobile-file-meta {
  margin-top: 8px;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 6px 10px;
}

.mobile-file-meta-item {
  min-width: 0;
}

.mobile-file-meta-label {
  font-size: 11px;
  color: var(--muted-2);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.mobile-file-meta-value {
  margin-top: 2px;
  font-size: 12px;
  color: var(--text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  line-height: 1.4;
}

.mobile-file-actions {
  margin-top: 12px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.mobile-file-actions :deep(.el-button),
.mobile-file-actions :deep(.el-dropdown),
.mobile-file-actions .table-action-link,
.mobile-file-actions a {
  flex: 1 1 calc(33.333% - 8px);
  min-height: 32px;
  margin: 0;
  border-radius: 10px;
  justify-content: center;
}

.mobile-file-actions :deep(.el-dropdown) {
  display: inline-flex;
}

.mobile-file-actions :deep(.el-dropdown .el-button) {
  width: 100%;
}

.mobile-file-actions a {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  text-decoration: none;
}

.mobile-file-actions a .el-button {
  width: 100%;
  height: 100%;
  margin: 0;
}

.mobile-file-actions .table-action-link {
  height: auto;
  padding: 6px 10px;
  background: #f8fafc;
  border: 1px solid rgba(15, 23, 42, 0.06);
}

.empty-state {
  padding: 32px 12px;
  color: var(--muted);
  text-align: center;
  font-size: 13px;
}

.preview-image-info-body {
  max-height: 65vh;
  overflow: auto;
}

.preview-image-info-section {
  margin-bottom: 20px;
}

.preview-image-info-title {
  font-weight: 600;
  font-size: 14px;
  margin-bottom: 10px;
}

.preview-image-info-row {
  display: grid;
  grid-template-columns: 180px 1fr;
  gap: 12px;
  padding: 8px 0;
  border-bottom: 1px solid #ebeef5;
}

.preview-image-info-label {
  color: #606266;
  font-weight: 500;
}

.preview-image-info-value {
  word-break: break-word;
  white-space: pre-wrap;
  font-family: Monaco, Menlo, "Ubuntu Mono", Consolas, monospace;
  font-size: 12px;
  line-height: 1.5;
}

@media (max-width: 1080px) {
  .artifact-library-body { gap: 10px; }
  .artifact-folder-sidebar { flex-basis: 180px; }
  .artifact-toolbar-filters { margin-left: 0; }
}

@media (max-width: 860px) {
  .artifact-library-body { flex-direction: column; }
  .artifact-folder-sidebar { flex: 0 0 auto; max-height: 174px; }
  .artifact-folder-sidebar :deep(.el-tree) { min-height: 70px; }
  .artifact-main-panel { min-height: 0; }
}

@media (max-width: 1080px), (max-height: 720px) {
  .dialog-table-shell {
    display: none !important;
  }

  .mobile-file-list-shell {
    display: flex !important;
    flex: 1 1 auto !important;
    min-height: 0 !important;
    overflow: hidden !important;
  }

  .mobile-file-list {
    display: block !important;
    flex: 1 1 auto !important;
    min-height: 0 !important;
    overflow: hidden !important;
  }

  .mobile-file-grid {
    height: 100% !important;
    min-height: 0 !important;
    overflow-y: auto !important;
  }
}

@media (max-width: 640px) {
  .artifact-dialog-toolbar { align-items: stretch; }
  .artifact-toolbar-group { width: 100%; }
  .artifact-toolbar-filters { width: 100%; }
  .artifact-toolbar-search,
  .artifact-toolbar-device { flex: 1 1 160px; width: auto; min-width: 0; }
  .mobile-file-meta { grid-template-columns: 1fr; }
  .mobile-file-actions { gap: 6px; }
  .mobile-file-actions :deep(.el-button),
  .mobile-file-actions :deep(.el-dropdown),
  .mobile-file-actions .table-action-link { flex: 1 1 calc(50% - 6px); }
}
</style>

<style>
.artifact-overlay .el-overlay-dialog {
  overflow: hidden !important;
}

.artifact-overlay .el-dialog {
  height: 78vh !important;
  max-height: 78vh !important;
  margin-top: 5vh !important;
  display: flex !important;
  flex-direction: column !important;
  overflow: hidden !important;
}

.artifact-overlay .el-dialog__header {
  flex: 0 0 auto !important;
}

.artifact-overlay .el-dialog__body {
  flex: 1 1 auto !important;
  min-height: 0 !important;
  overflow: hidden !important;
  padding-top: 12px !important;
  padding-bottom: 12px !important;
}

.artifact-overlay .fixed-dialog-body {
  height: 100% !important;
  min-height: 0 !important;
  overflow: hidden !important;
  display: flex !important;
  flex-direction: column !important;
}

.artifact-overlay .dialog-table-shell {
  flex: 1 1 auto !important;
  min-height: 0 !important;
  height: auto !important;
  max-height: none !important;
  overflow: hidden !important;
}

.artifact-overlay .dialog-table-shell .el-table,
.artifact-overlay .dialog-table-shell .el-table__inner-wrapper,
.artifact-overlay .dialog-table-shell .el-scrollbar,
.artifact-overlay .dialog-table-shell .el-scrollbar__wrap {
  height: 100% !important;
}

.artifact-overlay .dialog-table-shell .el-scrollbar__wrap {
  overflow-y: auto !important;
  overflow-x: auto !important;
}

@media (max-width: 1080px), (max-height: 720px) {
  .artifact-overlay .el-dialog {
    width: 100vw !important;
    max-width: 100vw !important;
    height: 100dvh !important;
    max-height: 100dvh !important;
    margin: 0 !important;
    border-radius: 0 !important;
  }

  .artifact-overlay .el-dialog__header {
    padding: 14px 16px 10px !important;
  }

  .artifact-overlay .el-dialog__body {
    padding: 10px 12px 12px !important;
  }

  .artifact-overlay .dialog-table-shell {
    display: none !important;
  }

  .artifact-overlay .mobile-file-list-shell {
    display: flex !important;
    flex: 1 1 auto !important;
    min-height: 0 !important;
    overflow: hidden !important;
  }

  .artifact-overlay .mobile-file-list {
    display: block !important;
    flex: 1 1 auto !important;
    min-height: 0 !important;
    overflow: hidden !important;
  }

  .artifact-overlay .mobile-file-grid {
    height: 100% !important;
    min-height: 0 !important;
    overflow-y: auto !important;
  }
}
</style>
