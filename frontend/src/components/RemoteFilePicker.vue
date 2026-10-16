<template>
  <el-dialog
    :model-value="visible"
    :title="pickerTitle"
    width="760px"
    top="8vh"
    class="fixed-dialog remote-file-picker-dialog"
    modal-class="remote-file-picker-overlay"
    @update:model-value="handleVisibleChange"
  >
    <div class="remote-file-picker-body">
      <div class="remote-file-picker-head">
        <div class="remote-file-picker-breadcrumb">
          <template v-if="remoteBreadcrumbItems.length">
            <button
              v-for="(item, index) in remoteBreadcrumbItems"
              :key="`picker-breadcrumb-${index}-${item.path}`"
              type="button"
              class="remote-file-picker-breadcrumb-item"
              :class="{ active: item.isCurrent }"
              :disabled="item.isCurrent"
              @click="goToRemoteBreadcrumb(item)"
            >
              <span v-if="index > 0" class="remote-file-picker-breadcrumb-sep">/</span>
              <span>{{ item.label }}</span>
            </button>
          </template>

          <span v-else class="remote-file-picker-breadcrumb-empty">No path</span>
        </div>

        <div class="remote-file-picker-toolbar">
          <el-button
            size="small"
            :loading="remoteFilesLoading"
            @click="refreshRemoteDirectory"
          >
            Refresh
          </el-button>

          <el-dropdown
            :loading="quickJumpLoading"
            @command="jumpToPath"
          >
            <el-button size="small">
              Quick Jump
            </el-button>

            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="root">Root</el-dropdown-item>
                <el-dropdown-item command="home">Home</el-dropdown-item>
                <el-dropdown-item command="desktop">Desktop</el-dropdown-item>
                <el-dropdown-item command="documents">Documents</el-dropdown-item>
                <el-dropdown-item command="downloads">Downloads</el-dropdown-item>
                <el-dropdown-item command="temp">Temp</el-dropdown-item>
                <el-dropdown-item command="executable">
                  Program Directory
                </el-dropdown-item>
                <el-dropdown-item divided command="input_navigate">
                  Go to Folder
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>

          <el-button
            size="small"
            :loading="remoteUploadLoading"
            @click="triggerRemoteUpload"
          >
            Upload
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
        <el-table
          ref="remoteFilesTableRef"
          :data="displayRemoteFilesEntries"
          v-loading="remoteFilesLoading"
          stripe
          width="100%"
          height="100%"
          :empty-text="remoteFilesEmptyText"
          table-layout="fixed"
          @row-dblclick="handleRemoteRowDblClick"
          @selection-change="handleRemoteSelectionChange"
          @row-click="handleRemoteRowClick"
        >
          <el-table-column
            v-if="multiple"
            type="selection"
            width="48"
            align="center"
            :selectable="isRemoteRowSelectable"
          />

          <el-table-column label="Name" min-width="280" show-overflow-tooltip>
            <template #default="{ row }">
              <div class="remote-file-picker-file-cell">
                <span>{{ row.is_dir ? '📁' : '📄' }}</span>
                <span class="remote-file-picker-file-name">
                  {{ row.is_parent_entry ? '..' : row.name }}
                </span>

                <el-tag v-if="row.is_parent_entry" size="small" type="info">
                  Parent
                </el-tag>

                <el-tag v-else-if="row.is_symlink" size="small" type="info">
                  Link
                </el-tag>
              </div>
            </template>
          </el-table-column>

          <el-table-column label="Type" width="90" align="center">
            <template #default="{ row }">
              {{ row.is_parent_entry ? 'Parent' : (row.is_dir ? 'Folder' : 'File') }}
            </template>
          </el-table-column>

          <el-table-column label="Size" width="105" align="center">
            <template #default="{ row }">
              {{ row.is_dir ? '-' : formatBytes(row.size) }}
            </template>
          </el-table-column>

          <el-table-column label="Actions" :width="selectionMode === 'folder' ? 132 : 92" align="center" fixed="right">
            <template #default="{ row }">
              <el-button
                v-if="row.is_parent_entry || row.is_dir"
                size="small"
                link
                type="primary"
                @click.stop="enterRemoteDirectory(row)"
              >
                Open
              </el-button>

              <el-button
                v-if="isRemoteRowSelectable(row)"
                size="small"
                link
                type="primary"
                @click.stop="selectRemoteEntry(row)"
              >
                Select
              </el-button>
            </template>
          </el-table-column>
        </el-table>
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
        <el-button @click="closePicker">
          Cancel
        </el-button>

        <el-button
          v-if="multiple"
          type="primary"
          :disabled="!remoteSelectedPaths.length"
          @click="confirmMultipleSelection"
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
import { ElMessage, ElMessageBox } from 'element-plus'
import { formatBytes as formatBytesValue } from '../utils/formatters.js'
import { uploadRemoteFileToClient } from '../api/transferApi.js'

export default {
  name: 'RemoteFilePicker',

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

  data() {
    return {
      remoteFilesLoading: false,
      remoteFilesCurrentPath: '',
      remoteFilesParentPath: '',
      remoteFilesEntries: [],
      remoteFilesPage: 1,
      remoteFilesPageSize: 50,
      remoteFilesTotal: 0,
      remoteFilesTotalPages: 1,
      remoteSelectedPaths: [],
      quickJumpLoading: false,
      quickJumpPaths: {},
      remoteUploadLoading: false,
    }
  },

  computed: {
    pickerTitle() {
      return this.selectionMode === 'folder' ? 'Select Remote Folder' : 'Select Remote File'
    },

    displayRemoteFilesEntries() {
      const sourceEntries = Array.isArray(this.remoteFilesEntries)
        ? [...this.remoteFilesEntries]
        : []
      const entries = this.selectionMode === 'folder'
        ? sourceEntries.filter(item => item && item.is_dir)
        : sourceEntries

      if (this.remoteFilesParentPath && this.remoteFilesPage === 1) {
        entries.unshift({
          name: '..',
          path: this.remoteFilesParentPath,
          is_dir: true,
          is_symlink: false,
          is_hidden: false,
          size: 0,
          modified_at: '',
          is_parent_entry: true,
        })
      }

      return entries
    },

    remoteFilesEmptyText() {
      return this.selectionMode === 'folder' ? 'No folders found' : 'This folder is empty'
    },

    remoteBreadcrumbItems() {
      const items = this.buildRemoteBreadcrumbItems(this.remoteFilesCurrentPath || '')

      return items.map(item => ({
        ...item,
        isCurrent: item.path === (this.remoteFilesCurrentPath || ''),
      }))
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
    formatBytes(value) {
      return formatBytesValue(value)
    },

    handleVisibleChange(value) {
      this.$emit('update:visible', value)
    },

    closePicker() {
      this.$emit('update:visible', false)
    },

    async openPicker() {
      if (!this.selectedId) {
        ElMessage.warning('Please select a device')
        this.closePicker()
        return
      }

      this.remoteSelectedPaths = []
      await Promise.all([
        this.loadQuickJumpPaths(),
        this.loadRemoteDirectory(this.initialPath || this.remoteFilesCurrentPath || '', 1),
      ])
    },

    resetPicker() {
      this.remoteFilesLoading = false
      this.remoteFilesCurrentPath = ''
      this.remoteFilesParentPath = ''
      this.remoteFilesEntries = []
      this.remoteFilesPage = 1
      this.remoteFilesTotal = 0
      this.remoteFilesTotalPages = 1
      this.remoteSelectedPaths = []
      this.remoteUploadLoading = false
    },

    async loadRemoteDirectory(path = '', page = 1) {
      if (!this.selectedId) return

      this.remoteFilesLoading = true

      try {
        const url = new URL(
          `/api/connections/${encodeURIComponent(this.selectedId)}/remote-files`,
          window.location.origin
        )

        if (path) url.searchParams.set('path', path)
        url.searchParams.set('page', String(page || 1))
        url.searchParams.set('page_size', String(this.remoteFilesPageSize || 50))
        url.searchParams.set('show_hidden', 'false')

        const res = await fetch(url.pathname + url.search)
        const json = await res.json()

        if (!res.ok || json.code !== 0) {
          throw new Error(json.message || 'Failed to load remote directory')
        }

        const data = json.data || {}
        const pagination = data.pagination || {}

        this.remoteFilesCurrentPath = data.current_path || ''
        this.remoteFilesParentPath = data.parent_path || ''
        this.remoteFilesEntries = Array.isArray(data.entries) ? data.entries : []
        this.remoteFilesPage = Number(pagination.page || page || 1)
        this.remoteFilesPageSize = Number(pagination.page_size || this.remoteFilesPageSize || 50)
        this.remoteFilesTotal = Number(pagination.total_visible || 0)
        this.remoteFilesTotalPages = Number(pagination.total_pages || 1)
        this.remoteSelectedPaths = []
        this.clearTableSelection()
      } catch (e) {
        ElMessage.error(e.message || 'Failed to load remote directory')
      } finally {
        this.remoteFilesLoading = false
      }
    },

    async refreshRemoteDirectory() {
      await this.loadRemoteDirectory(this.remoteFilesCurrentPath || '', this.remoteFilesPage || 1)
    },

    async navigateRemoteDirectory(path) {
      await this.loadRemoteDirectory(path || '', 1)
    },

    async goToRemoteParent() {
      if (!this.remoteFilesParentPath) return
      await this.navigateRemoteDirectory(this.remoteFilesParentPath)
    },

    async enterRemoteDirectory(row) {
      if (!row || !row.is_dir) return

      if (row.is_parent_entry) {
        await this.goToRemoteParent()
        return
      }

      await this.navigateRemoteDirectory(row.path)
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

    handleRemoteSelectionChange(rows) {
      if (!this.multiple) return

      this.remoteSelectedPaths = Array.isArray(rows)
        ? rows
            .filter(item => this.isRemoteRowSelectable(item))
            .map(item => item.path)
            .filter(Boolean)
        : []
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

    confirmMultipleSelection() {
      if (!this.remoteSelectedPaths.length) return

      this.$emit('select', [...this.remoteSelectedPaths])
      this.closePicker()
    },

    async handleRemotePageChange(page) {
      await this.loadRemoteDirectory(this.remoteFilesCurrentPath || '', page || 1)
    },

    clearTableSelection() {
      this.$nextTick(() => {
        const table = this.$refs.remoteFilesTableRef
        if (table && typeof table.clearSelection === 'function') {
          table.clearSelection()
        }
      })
    },

    buildRequestHeaders(extra = {}) {
      if (typeof this.getTabScopedHeaders === 'function') {
        return this.getTabScopedHeaders(extra)
      }

      return extra
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
      const file = event?.target?.files && event.target.files[0]
      if (!file) return

      if (!this.selectedId) {
        ElMessage.warning('Please select a device')
        return
      }

      if (!this.remoteFilesCurrentPath) {
        ElMessage.warning('Current directory is empty')
        return
      }

      this.remoteUploadLoading = true

      this.$emit(
        'append-output',
        this.selectedId,
        `> [Remote Upload] ${file.name} -> ${this.remoteFilesCurrentPath}`,
        'command'
      )

      try {
        const result = await uploadRemoteFileToClient({
          file, clientId: this.selectedId, destinationPath: this.remoteFilesCurrentPath,
          headers: this.buildRequestHeaders(),
        })
        const taskId = result.task_id
        this.$emit('set-active-task', this.selectedId, taskId || '')
        this.$emit('upload-started', {
          source: 'remote_file_picker',
          taskId: taskId || '',
          clientId: this.selectedId,
          path: this.remoteFilesCurrentPath || '',
        })
        ElMessage.success(`Upload started: ${file.name}`)
      } catch (e) {
        this.$emit(
          'append-output',
          this.selectedId,
          `[Upload failed] ${e.message || 'unknown error'}`,
          'error'
        )
        ElMessage.error(e.message || 'Upload failed')
      } finally {
        this.remoteUploadLoading = false
        if (event?.target) event.target.value = ''
      }
    },

    async loadQuickJumpPaths() {
      if (!this.selectedId) return

      this.quickJumpLoading = true

      try {
        const res = await fetch(`/api/connections/${encodeURIComponent(this.selectedId)}/system-paths`)
        const json = await res.json()

        if (res.ok && json.code === 0 && json.data) {
          this.quickJumpPaths = json.data
        }
      } catch (e) {
        console.error('Failed to load system paths:', e)
      } finally {
        this.quickJumpLoading = false
      }
    },

    async jumpToPath(command) {
      if (command === 'input_navigate') {
        await this.promptRemotePathNavigate()
        return
      }

      const path = this.quickJumpPaths[command]
      if (!path) {
        ElMessage.warning('Path not available')
        return
      }

      await this.navigateRemoteDirectory(path)
    },

    async promptRemotePathNavigate() {
      try {
        const { value } = await ElMessageBox.prompt(
          'Enter the target path',
          'Go to Folder',
          {
            confirmButtonText: 'Go',
            cancelButtonText: 'Cancel',
            inputValue: this.remoteFilesCurrentPath || '',
            inputPattern: /.+/,
            inputErrorMessage: 'Path is required',
          }
        )

        const path = String(value || '').trim()
        if (!path) return

        await this.navigateRemoteDirectory(path)
      } catch (e) {
        if (e === 'cancel' || e === 'close') return
        ElMessage.error(e.message || 'Navigate failed')
      }
    },

    buildRemoteBreadcrumbItems(path) {
      const currentPath = String(path || '').trim()
      if (!currentPath) return []

      const windowsMatch = currentPath.match(/^([A-Za-z]:)([\\/].*)?$/)

      if (windowsMatch) {
        const drive = windowsMatch[1]
        const rest = String(windowsMatch[2] || '').replace(/^[\\/]+/, '')
        const parts = rest ? rest.split(/[\\/]+/).filter(Boolean) : []
        const items = [{ label: drive, path: `${drive}\\` }]
        let accumulated = `${drive}\\`

        parts.forEach(part => {
          accumulated = accumulated.replace(/[\\/]+$/, '') + '\\' + part
          items.push({ label: part, path: accumulated })
        })

        return items
      }

      const isAbsolute = currentPath.startsWith('/')
      const parts = currentPath.split('/').filter(Boolean)
      const items = []

      if (isAbsolute) {
        items.push({ label: 'Root', path: '/' })
      }

      let accumulated = ''

      parts.forEach(part => {
        if (isAbsolute) {
          accumulated += `/${part}`
        } else {
          accumulated = accumulated ? `${accumulated}/${part}` : part
        }

        items.push({ label: part, path: accumulated })
      })

      if (!items.length && isAbsolute) {
        items.push({ label: 'Root', path: '/' })
      }

      return items
    },

    async goToRemoteBreadcrumb(item) {
      if (!item || !item.path || item.isCurrent) return
      await this.navigateRemoteDirectory(item.path)
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

.remote-file-picker-breadcrumb {
  display: block;
  width: 100%;
  min-height: 30px;
  overflow-x: auto;
  overflow-y: hidden;
  white-space: nowrap;
  scrollbar-width: thin;
}

.remote-file-picker-breadcrumb-item {
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

.remote-file-picker-breadcrumb-item.active,
.remote-file-picker-breadcrumb-item:disabled {
  color: var(--muted);
  cursor: default;
}

.remote-file-picker-breadcrumb-item > span:last-child {
  display: inline-block;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.remote-file-picker-breadcrumb-sep {
  margin-right: 4px;
  color: var(--muted);
}

.remote-file-picker-breadcrumb-empty,
.remote-file-picker-footer-meta {
  font-size: 12px;
  color: var(--muted);
}

.remote-file-picker-toolbar {
  display: flex;
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

.remote-file-picker-file-cell {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.remote-file-picker-file-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
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

@media (max-width: 768px), (max-height: 720px) {
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
