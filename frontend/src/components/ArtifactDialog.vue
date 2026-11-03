<template>
  <el-dialog
    :model-value="visible"
    title="Artifact Manager"
    width="1160px"
    top="5vh"
    class="fixed-dialog artifact-dialog"
    modal-class="artifact-overlay"
    @update:model-value="handleVisibleChange"
  >
    <div class="fixed-dialog-body">
      <div class="dialog-head">
        <div class="dialog-head-left">
          <el-button
            class="artifact-toolbar-btn"
            size="small"
            @click="loadArtifacts"
          >
            Refresh
          </el-button>

          <el-button
            class="artifact-toolbar-btn"
            size="small"
            type="danger"
            :disabled="!selectedArtifactIds.length"
            :loading="artifactBulkDeleting"
            @click="deleteSelectedArtifacts"
          >
            Delete {{ selectedArtifactIds.length ? ` (${selectedArtifactIds.length})` : '' }}
          </el-button>

          <el-button
            class="artifact-toolbar-btn"
            size="small"
            type="danger"
            :loading="artifactClearing"
            @click="clearArtifactCategory"
          >
            Clear
          </el-button>

          <div
            v-if="isSharedFilesTab"
            class="artifact-shared-actions"
          >
            <el-button
              class="artifact-toolbar-btn"
              size="small"

              plain
              @click="createSharedFilePrompt"
            >
              Create File
            </el-button>

            <el-button
              class="artifact-toolbar-btn"
              size="small"

              plain
              :loading="sharedFileUploading"
              @click="triggerSharedFileUpload"
            >
              Upload
            </el-button>
          </div>
        </div>

        <div class="dialog-head-right">
          <div class="dialog-path-box artifact-search-box">
            <el-input
              v-model="artifactKeyword"
              clearable
              size="small"
              placeholder="Search"
            />
          </div>
          <div
            v-if="showArtifactMachineFilter"
            class="dialog-path-box artifact-filter-box"
          >
            <el-select
              v-model="artifactMachineIdFilter"
              clearable
              filterable
              size="small"
              placeholder="Filter by device"
              @change="handleMachineFilterChange"
            >
              <el-option
                v-for="item in artifactMachineOptions"
                :key="item.machine_id"
                :label="formatArtifactMachineOptionLabel(item)"
                :value="item.machine_id"
              />
            </el-select>
          </div>
        </div>
      </div>

      <el-tabs
        :model-value="artifactActiveTab"
        class="artifact-tabs"
        @update:model-value="handleActiveTabChange"
      >
        <el-tab-pane name="files">
          <template #label>
            Downloads ({{ artifactCountMap.files || 0 }})
          </template>
        </el-tab-pane>

        <el-tab-pane name="command_output">
          <template #label>
            Command Output ({{ artifactCountMap.command_output || 0 }})
          </template>
        </el-tab-pane>

        <el-tab-pane name="previews">
          <template #label>
            Previews ({{ artifactCountMap.previews || 0 }})
          </template>
        </el-tab-pane>

        <el-tab-pane name="shared_files">
          <template #label>
            Shared Files ({{ artifactCountMap.shared_files || 0 }})
          </template>
        </el-tab-pane>
      </el-tabs>

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
            width="46"
            align="center"
          />
          <el-table-column
            prop="original_name"
            label="Name"
            min-width="270"
            show-overflow-tooltip
          >

            <template #default="{ row }">
              <div class="ellipsis">
                {{ formatArtifactName(row) }}
              </div>
            </template>
          </el-table-column>

          <el-table-column
            v-if="!isSharedFilesTab"
            label="Hostname"
            min-width="180"
            show-overflow-tooltip
          >
            <template #default="{ row }">
              <div class="ellipsis">
                {{ row.hostname || '-' }}
              </div>
            </template>
          </el-table-column>

          <el-table-column
            v-if="!isSharedFilesTab"
            label="Category"
            min-width="150"
            show-overflow-tooltip
          >
            <template #default="{ row }">
              <div class="ellipsis">
                {{ row.category || '-' }}
              </div>
            </template>
          </el-table-column>

          <el-table-column
            label="Size"
            width="110"
            align="center"
          >
            <template #default="{ row }">
              {{ formatBytes(row.size) }}
            </template>
          </el-table-column>

<!--          <el-table-column-->
<!--            label="Created"-->
<!--            width="170"-->
<!--            show-overflow-tooltip-->
<!--          >-->

<el-table-column
  label="Created"
  :width="isSharedFilesTab ? 220 : 170"
  show-overflow-tooltip
>
            <template #default="{ row }">
              <div class="ellipsis">
                {{ row.created_at || '-' }}
              </div>
            </template>
          </el-table-column>

          <el-table-column
            label="Actions"
            :width="isSharedFilesTab ? 190 : 200"
            align="center"
            fixed="right"
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
                        <el-dropdown-item command="rename">
                          Rename
                        </el-dropdown-item>
                        <el-dropdown-item
                          v-if="isSharedFileItem(row)"
                          command="send-current-device"
                          :disabled="!selectedId"
                        >
                          Send to Current Device
                        </el-dropdown-item>
                        <el-dropdown-item
                          v-if="isSharedFileItem(row)"
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
                <div class="mobile-file-icon">📄</div>

                <div class="mobile-file-main">
                  <div class="mobile-file-name">
                    {{ formatArtifactName(row) }}
                  </div>

                  <div
                    v-if="row.hostname && !isSharedFileItem(row)"
                    class="mobile-file-tags"
                  >
                    <el-tag size="small">
                      {{ row.hostname }}
                    </el-tag>
                  </div>

                  <div class="mobile-file-meta">
                    <div
                      v-if="!isSharedFileItem(row)"
                      class="mobile-file-meta-item"
                    >
                      <div class="mobile-file-meta-label">Category</div>
                      <div class="mobile-file-meta-value">
                        {{ row.category || '-' }}
                      </div>
                    </div>

                    <div class="mobile-file-meta-item">
                      <div class="mobile-file-meta-label">Size</div>
                      <div class="mobile-file-meta-value">
                        {{ formatBytes(row.size) }}
                      </div>
                    </div>

                    <div class="mobile-file-meta-item">
                      <div class="mobile-file-meta-label">Created</div>
                      <div class="mobile-file-meta-value">
                        {{ row.created_at || '-' }}
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
                            <el-dropdown-item command="rename">
                              Rename
                            </el-dropdown-item>
                            <el-dropdown-item
                              v-if="isSharedFileItem(row)"
                              command="send-current-device"
                              :disabled="!selectedId"
                            >
                              Send
                            </el-dropdown-item>
                            <el-dropdown-item
                              v-if="isSharedFileItem(row)"
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
    </div>
  </el-dialog>

  <DragUploadDialog
    v-model="sharedFileUploadDialogVisible"
    title="Upload Shared Files"
    helper-text="Drag files here or click the drop zone to choose files. Files will not upload until you click Upload."
    button-text="Upload"
    :multiple="true"
    :loading="sharedFileUploading"
    @upload="uploadSharedFiles"
  />

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
import { listArtifacts, uploadArtifact, renameArtifact as requestRenameArtifact, sendArtifactToClient, deleteArtifact as deleteArtifactRequest, clearArtifacts } from '../api/artifactsApi.js'
import { ElMessage, ElMessageBox } from 'element-plus'
import { setRemoteClipboardArtifactFile } from '../api/clipboardApi.js'
import { formatBytes as formatBytesValue } from '../utils/formatters.js'
import DragUploadDialog from './DragUploadDialog.vue'

export default {
  name: 'ArtifactDialog',

  components: {
    DragUploadDialog,
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
      visible: false,
      artifactLoading: false,
      artifactItems: [],
      artifactMachines: [],
      artifactActiveTab: 'files',
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
      return String(this.artifactActiveTab || '').trim() === 'shared_files'
    },

    isCommandOutputTab() {
      return String(this.artifactActiveTab || '').trim() === 'command_output'
    },

    showArtifactMachineFilter() {
      return !this.isSharedFilesTab
    },

    showArtifactCategoryColumn() {
      return !this.isSharedFilesTab && !this.isCommandOutputTab
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
      const activeType = String(this.artifactActiveTab || '').trim()
      const machineId = String(this.artifactMachineIdFilter || '').trim()
      const keyword = String(this.artifactKeyword || '').trim().toLowerCase()

      return (this.artifactItems || []).filter(item => {
        if (activeType && item.artifact_type !== activeType) return false
        if (!this.isSharedFileItem(item) && machineId && item.machine_id !== machineId) return false

        if (keyword) {
          const fileName = this.formatArtifactName(item).toLowerCase()
          const category = String(item?.category || '').trim().toLowerCase()
          if (!fileName.includes(keyword) && !category.includes(keyword)) return false
        }

        return true
      })
    },

    selectedArtifacts() {
      const selected = new Set(this.selectedArtifactIds)
      return (this.artifactItems || []).filter(item => selected.has(String(item?.artifact_id || '').trim()))
    },

    artifactCountMap() {
      const machineId = String(this.artifactMachineIdFilter || '').trim()
      const keyword = String(this.artifactKeyword || '').trim().toLowerCase()
      const counts = { files: 0, previews: 0, shared_files: 0, command_output: 0 }

      ;(this.artifactItems || []).forEach(item => {
        if (!item) return

        const type = String(item.artifact_type || '').trim()
        if (!Object.prototype.hasOwnProperty.call(counts, type)) return
        if (type !== 'shared_files' && machineId && item.machine_id !== machineId) return

        if (keyword) {
          const fileName = this.formatArtifactName(item).toLowerCase()
          const category = String(item?.category || '').trim().toLowerCase()
          if (!fileName.includes(keyword) && !category.includes(keyword)) return
        }

        counts[type] += 1
      })

      return counts
    },

    formattedArtifactInfoSections() {
      return this.formatArtifactInfoSections(this.artifactInfoItem)
    },
  },

  methods: {
    formatBytes(value) {
      return formatBytesValue(value)
    },

    async open() {
      this.artifactMachineIdFilter = this.getCurrentMachineId()
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
            ['category', 'Category'],
            ['size', 'Size'],
            ['created_at', 'Created At'],
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
            ['job_id', 'Job ID'],
            ['job_name', 'Job Name'],
            ['job_key', 'Job Key'],
          ],
        },
        {
          key: 'paths',
          title: 'Paths / URLs',
          fields: [
            ['saved_path', 'Saved Path'],
            ['_meta_path', 'Meta Path'],
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
      return String(item?.artifact_type || '').trim() === 'shared_files'
    },

    useArtifactMoreMenu(item) {
      const type = String(item?.artifact_type || '').trim()
      return type === 'files' || type === 'command_output' || type === 'shared_files'
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
      this.artifactActiveTab = tabName || 'files'
      this.selectedArtifactIds = []
      if (!this.isSharedFilesTab && !this.artifactMachineIdFilter) {
        this.artifactMachineIdFilter = this.getCurrentMachineId()
      }
      await this.loadArtifacts()
    },

    async handleMachineFilterChange() {
      await this.loadArtifacts()
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
        this.pruneArtifactSelection()
      } catch (e) {
        this.artifactItems = []
        this.artifactMachines = []
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

        this.$emit('open-new-shared-file-editor', filename)
      } catch (e) {
        if (e === 'cancel' || e === 'close') return
      }
    },

    triggerSharedFileUpload() {
      this.sharedFileUploadDialogVisible = true
    },

    async uploadSingleSharedFile(file) {
      const formData = new FormData()
      formData.append('file', file)
      formData.append('artifact_type', 'shared_files')

      const res = await uploadArtifact(formData, this.buildJsonHeaders())
      const json = await res.json()

      if (!res.ok || json.code !== 0) {
        throw new Error(json.message || `Upload failed: ${file.name}`)
      }

      return json.data || {}
    },

    async uploadSharedFiles(files) {
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

      this.$emit(
        'append-output',
        clientId,
        `> [Artifact Send] ${displayName} -> ${deviceLabel} :: ${targetCwdLabel}`,
        'command'
      )

      try {
        const res = await sendArtifactToClient(
          row.artifact_id, clientId, targetCwd, this.buildJsonHeaders({ 'Content-Type': 'application/json' }),
        )
        const json = await res.json()

        if (!res.ok || json.code !== 0) {
          throw new Error(json.message || 'Send failed')
        }

        const taskId = json.data && json.data.task_id
        this.$emit('set-active-task', clientId, taskId || '')
        ElMessage.success(`Send started: ${displayName}`)
      } catch (e) {
        this.$emit(
          'append-output',
          clientId,
          `[Artifact send failed] ${e.message || 'unknown error'}`,
          'error'
        )
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

    async clearArtifactCategory() {
      const activeType = String(this.artifactActiveTab || '').trim()

      if (!activeType) {
        ElMessage.warning('Please select a category')
        return
      }

      try {
        const suffix = this.showArtifactMachineFilter && this.artifactMachineIdFilter ? ' for selected device' : ''

        await ElMessageBox.confirm(
          `Clear all ${activeType}${suffix}?`,
          'Clear Artifacts',
          { type: 'warning', confirmButtonText: 'Clear', cancelButtonText: 'Cancel' }
        )

        this.artifactClearing = true

        const res = await clearArtifacts(
          activeType, this.showArtifactMachineFilter ? (this.artifactMachineIdFilter || '') : '',
        )

        const json = await res.json()
        if (!res.ok || json.code !== 0) {
          throw new Error(json.message || 'Clear failed')
        }

        ElMessage.success(`Cleared ${json.data?.deleted_count || 0} item(s)`)
        await this.loadArtifacts()
      } catch (e) {
        if (e === 'cancel' || e === 'close' || e?.toString?.().includes('cancel')) return
        ElMessage.error(e.message || 'Clear failed')
      } finally {
        this.artifactClearing = false
      }
    },
  },
}
</script>

<style scoped>
.fixed-dialog-body {
  height: 100%;
  min-height: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.dialog-head {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 12px;
  align-items: center;
  margin-bottom: 12px;
  flex-shrink: 0;
}

.dialog-head-left,
.dialog-head-right,
.artifact-shared-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.dialog-head-left {
  justify-content: flex-start;
  flex-wrap: nowrap;
}

.dialog-head-right {
  justify-content: flex-end;
  width: auto;
  margin-left: auto;
}

.dialog-head :deep(.el-button.artifact-toolbar-btn) {
  height: 32px;
  min-height: 32px;
  margin: 0;
  padding-inline: 12px;
  border-radius: 10px;
  white-space: nowrap;
}

.artifact-filter-box {
  display: flex;
  justify-content: flex-end;
  min-width: 280px;
}

.artifact-search-box {
  flex: 0 1 260px;
  min-width: 220px;
  max-width: 280px;
}

.artifact-search-box :deep(.el-input__wrapper) {
  min-height: 32px;
  height: 32px;
  border-radius: 10px;
  font-size: 12px;
}

.artifact-filter-box :deep(.el-select) {
  display: block;
  width: 300px;
  font-size: 12px;
}

.artifact-filter-box :deep(.el-select__wrapper),
.artifact-filter-box :deep(.el-input__wrapper) {
  min-height: 32px;
  height: 32px;
  border-radius: 10px;
  font-size: 12px;
}


.artifact-tabs {
  flex: 0 0 auto;
  min-height: 0;
}

.artifact-tabs :deep(.el-tabs__header) {
  margin-bottom: 12px;
}

.dialog-table-shell {
  flex: 1 1 auto;
  min-height: 320px;
  height: auto;
  max-height: none;
  overflow: hidden;
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
  gap: 10px;
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

.mobile-file-tags {
  margin-top: 10px;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
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
  word-break: break-word;
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

@media (max-width: 960px) {
  .dialog-head {
    grid-template-columns: 1fr;
  }

  .dialog-head-left,
  .dialog-head-right,
  .artifact-shared-actions {
    width: 100%;
  }

  .dialog-head-left {
    flex-wrap: wrap;
  }

  .dialog-head-right,
  .artifact-filter-box,
  .artifact-shared-actions {
    justify-content: flex-start;
    margin-left: 0;
  }

  .artifact-filter-box,
  .artifact-filter-box :deep(.el-select) {
    width: 100%;
    min-width: 0;
  }
}

@media (max-width: 768px), (max-height: 720px) {
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
  .dialog-head-left,
  .dialog-head-right,
  .artifact-shared-actions {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    align-items: stretch;
    gap: 8px;
  }

  .dialog-head :deep(.el-button.artifact-toolbar-btn) {
    width: 100%;
    padding-inline: 8px;
  }

  .artifact-filter-box,
  .artifact-filter-box :deep(.el-select),
  .artifact-search-box {
    width: 100%;
    min-width: 0;
    max-width: none;
  }

  .artifact-search-box,
  .artifact-filter-box {
    grid-column: 1 / -1;
  }

  .mobile-file-meta {
    grid-template-columns: 1fr;
  }

  .mobile-file-actions {
    gap: 6px;
  }

  .mobile-file-actions :deep(.el-button),
  .mobile-file-actions :deep(.el-dropdown),
  .mobile-file-actions .table-action-link {
    flex: 1 1 calc(50% - 6px);
  }
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
  min-height: 320px !important;
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

@media (max-width: 768px), (max-height: 720px) {
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
