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
    <div
        class="fixed-dialog-body"
        :class="{ 'remote-mobile-panel-collapsed': remoteMobilePanelCollapsed }"
    >
      <div class="dialog-head remote-files-head">
        <div class="dialog-head-left remote-files-head-main">
          <div class="remote-breadcrumb-bar">
            <template v-if="remoteBreadcrumbItems.length">
              <button
                  v-for="(item, index) in remoteBreadcrumbItems"
                  :key="`breadcrumb-${index}-${item.path}`"
                  type="button"
                  class="remote-breadcrumb-item"
                  :class="{ active: item.isCurrent }"
                  :disabled="item.isCurrent"
                  @click="goToRemoteBreadcrumb(item)"
              >
                <span v-if="index > 0" class="remote-breadcrumb-sep">/</span>
                <span>{{ item.label }}</span>
              </button>
            </template>

            <span v-else class="remote-breadcrumb-empty">No path</span>
          </div>

          <el-button size="small"

                     class="remote-mobile-panel-toggle"
                     @click="toggleRemoteMobilePanel"
          >
            {{ remoteMobilePanelCollapsed ? 'Show tools' : 'Hide tools' }}
          </el-button>

          <div class="remote-files-toolbar">
            <div class="remote-toolbar-group">
              <el-button size="small" @click="refreshRemoteDirectory">
                Refresh
              </el-button>

              <el-button
                  size="small"
                  :disabled="!remoteFilesParentPath"
                  @click="goToRemoteParent"
              >
                Up
              </el-button>

              <el-dropdown
                  :loading="quickJumpLoading || remotePinnedJumpLoading"
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
<!--                    <el-dropdown-item command="icloud">iCloud</el-dropdown-item>-->
                    <el-dropdown-item command="executable">
                      Program Directory
                    </el-dropdown-item>

                    <el-dropdown-item
                        v-for="(item, index) in remotePinnedJumpItems"
                        :key="`pinned-jump-${item.display_name}-${item.path}`"
                        :divided="index === 0"
                        :command="{
                        type: 'pinned_jump',
                        display_name: item.display_name,
                        path: item.path,
                      }"
                    >
                      {{ item.display_name }}
                    </el-dropdown-item>

                    <el-dropdown-item divided command="input_navigate">
                      Go to Folder
                    </el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </div>

            <span class="remote-toolbar-divider"></span>

            <div class="remote-toolbar-group">
              <el-button size="small" @click="createRemoteDirectory">
                New Folder
              </el-button>

              <el-button
                  size="small"
                  :loading="remoteUploadLoading"
                  @click="triggerRemoteUpload"
              >
                Upload
              </el-button>

              <el-button
                  size="small"
                  type="primary"
                  :disabled="!hasRemoteSelection"
                  :loading="remoteZipDownloading"
                  @click="downloadSelectedRemoteEntries"
              >
                Download
                <span v-if="remoteSelectedPaths.length">
                  ({{ remoteSelectedPaths.length }})
                </span>
              </el-button>

              <el-button
                  size="small"
                  type="danger"
                  :disabled="!hasRemoteSelection"
                  @click="deleteSelectedRemoteEntries"
              >
                Delete
                <span v-if="remoteSelectedPaths.length">
                  ({{ remoteSelectedPaths.length }})
                </span>
              </el-button>
            </div>

            <span class="remote-toolbar-divider"></span>

            <div class="remote-toolbar-group">
              <el-dropdown
                  trigger="click"
                  @command="handleRemoteToolbarMoreCommand"
              >
                <el-button size="small">More</el-button>

                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item command="toggle_pin">
                      {{ remotePinButtonText }}
                    </el-dropdown-item>

                    <el-dropdown-item
                        v-if="hasPinnedQuickJumps"
                        command="manage_pins"
                    >
                      Manage Pins
                    </el-dropdown-item>

                    <el-dropdown-item
                        command="copy"
                        :disabled="!hasRemoteSelection"
                        divided
                    >
                      Copy
                      <span v-if="remoteSelectedPaths.length">
                        ({{ remoteSelectedPaths.length }})
                      </span>
                    </el-dropdown-item>

                    <el-dropdown-item
                        command="cut"
                        :disabled="!hasRemoteSelection"
                    >
                      Cut
                      <span v-if="remoteSelectedPaths.length">
                        ({{ remoteSelectedPaths.length }})
                      </span>
                    </el-dropdown-item>

                    <el-dropdown-item
                        command="create_zip"
                        :disabled="!hasRemoteSelection || remoteZipCreating"
                    >
                      Create ZIP
                      <span v-if="remoteSelectedPaths.length">
                        ({{ remoteSelectedPaths.length }})
                      </span>
                    </el-dropdown-item>

                    <el-dropdown-item
                        command="paste"
                        :disabled="!hasRemoteClipboard"
                    >
                      Paste
                      <span v-if="hasRemoteClipboard">
                        ({{ remoteClipboardPaths.length }})
                      </span>
                    </el-dropdown-item>

                    <el-dropdown-item
                        command="clear_clipboard"
                        :disabled="!hasRemoteClipboard"
                    >
                      Clear Clipboard
                    </el-dropdown-item>

                    <el-dropdown-item
                        v-if="!isRemoteCurrentPageAllSelected"
                        command="toggle_select_all"
                        divided
                        :disabled="!visibleRemoteSelectablePaths.length"
                    >
                      Select All
                    </el-dropdown-item>

                    <el-dropdown-item
                        :divided="isRemoteCurrentPageAllSelected"
                        command="clear_selection"
                        :disabled="!hasRemoteSelection"
                    >
                      Clear Selection
                    </el-dropdown-item>

                    <el-dropdown-item command="toggle_hidden">
                      {{ showHiddenFiles ? 'Hide Hidden' : 'Show Hidden' }}
                    </el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </div>

            <div class="remote-toolbar-spacer"></div>



            <div class="remote-toolbar-search">

                            <div class="remote-recursive-control">
                <span class="remote-recursive-label">Recursive</span>
                <el-switch
                    v-model="remoteSearchRecursive"
                    size="small"
                    @change="handleRemoteSearchRecursiveChange"
                />
              </div>
              <el-input
                  v-model="remoteSearchKeyword"
                  clearable
                  size="small"
                  class="remote-toolbar-search-input"
                  placeholder="Search"
                  @input="scheduleRemoteSearch"
                  @clear="applyRemoteSearch"
                  @keyup.enter="applyRemoteSearch"
              />


            </div>
          </div>
        </div>
      </div>

<!--      <div class="dialog-path-row remote-files-meta-row">-->
<!--        <div v-if="hasRemoteClipboard" class="dialog-pagination-meta">-->
<!--          Clipboard: {{ remoteClipboardActionText }} {{ remoteClipboardPaths.length }} item(s)-->
<!--          <span v-if="remoteClipboardSourcePath">-->
<!--            · From {{ remoteClipboardSourcePath }}-->
<!--          </span>-->
<!--        </div>-->
<!--      </div>-->

      <div class="dialog-table-shell">
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
        >
          <el-table-column
              type="selection"
              width="52"
              align="center"
              :selectable="row => !row.is_parent_entry"
          />

          <el-table-column label="Name" min-width="320" show-overflow-tooltip>
            <template #default="{ row }">
              <div class="file-cell">
                <span>{{ row.is_dir ? '📁' : '📄' }}</span>
                <span class="file-cell-text">
                  {{ row.is_parent_entry ? '..' : row.name }}
                </span>

                <el-tag v-if="row.is_parent_entry" size="small" type="info">
                  Parent
                </el-tag>

                <el-tag v-else-if="row.is_symlink" size="small" type="info">
                  Link
                </el-tag>

                <el-tag
                    v-if="!row.is_parent_entry && row.is_hidden"
                    size="small"
                    type="warning"
                >
                  Hidden
                </el-tag>
              </div>
            </template>
          </el-table-column>

          <el-table-column
              v-if="isRemoteSearchActive"
              label="Location"
              min-width="240"
              show-overflow-tooltip
          >
            <template #default="{ row }">
              <div class="ellipsis">
                {{ remoteEntryLocation(row) }}
              </div>
            </template>
          </el-table-column>

          <el-table-column label="Type" width="110" align="center">
            <template #default="{ row }">
              {{ row.is_parent_entry ? 'Parent' : (row.is_dir ? 'Folder' : 'File') }}
            </template>
          </el-table-column>

          <el-table-column label="Size" width="120" align="center">
            <template #default="{ row }">
              {{ row.is_dir ? '-' : formatBytes(row.size) }}
            </template>
          </el-table-column>

          <el-table-column
              prop="modified_at"
              label="Modified"
              width="180"
              show-overflow-tooltip
          >
            <template #default="{ row }">
              <div class="ellipsis">
                {{ row.is_parent_entry ? '-' : (row.modified_at || '-') }}
              </div>
            </template>
          </el-table-column>

          <el-table-column label="Actions" width="220" align="center" fixed="right">
            <template #default="{ row }">
              <div class="table-actions table-actions-links">
                <template v-if="row.is_parent_entry">
                  <el-button
                      size="small"
                      link
                      type="primary"
                      @click="goToRemoteParent"
                  >
                    Open
                  </el-button>
                </template>

                <template v-else>
                  <el-button
                      v-if="row.is_dir"
                      size="small"
                      link
                      type="primary"
                      @click="enterRemoteDirectory(row)"
                  >
                    Open
                  </el-button>

                  <template v-if="!row.is_dir">
                    <el-button
                        size="small"
                        link
                        type="primary"
                        @click="previewRow(row)"
                    >
                      Preview
                    </el-button>

                    <el-button
                        size="small"
                        link
                        type="primary"
                        @click="downloadRemoteEntry(row)"
                    >
                      Download
                    </el-button>
                  </template>

                  <el-dropdown
                      trigger="click"
                      @command="command => handleRemoteMoreAction(command, row)"
                  >
                    <el-button size="small" link type="primary">
                      More
                    </el-button>

                    <template #dropdown>
                      <el-dropdown-menu>
                        <el-dropdown-item command="rename">Rename</el-dropdown-item>
                        <el-dropdown-item command="copy">Copy</el-dropdown-item>
                        <el-dropdown-item command="cut">Cut</el-dropdown-item>
                        <el-dropdown-item command="copy_path">Copy Path</el-dropdown-item>
                        <el-dropdown-item v-if="isZipEntry(row)" command="extract" divided :disabled="remoteZipExtracting">Extract Here</el-dropdown-item>
                        <el-dropdown-item command="delete">Delete</el-dropdown-item>
                      </el-dropdown-menu>
                    </template>
                  </el-dropdown>
                </template>
              </div>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <div class="dialog-pagination-wrap">
        <div class="dialog-pagination-bar">
          <div class="dialog-pagination-meta">

            <span v-if="hasRemoteClipboard">
              {{ remoteClipboardActionText }} {{ remoteClipboardPaths.length }} ·
            </span>


            <span v-if="isRemoteSearchActive">
              Search "{{ normalizeRemoteSearchKeyword() }}"{{ remoteSearchRecursive ? ' recursively' : '' }} ·
            </span>

            <span>Visible {{ remoteFilesTotal }} </span>

            <span v-if="!showHiddenFiles && remoteFilesHiddenTotal > 0">
              · Hidden {{ remoteFilesHiddenTotal }}
            </span>

            <span v-if="remoteFilesAllTotal > remoteFilesTotal">
              · All {{ remoteFilesAllTotal }}
            </span>

            <span v-if="remoteFilesTotalPages > 1">
              · Page {{ remoteFilesPage }} / {{ remoteFilesTotalPages }}
            </span>




          </div>

          <el-pagination
              background
              layout="total, sizes, prev, pager, next"
              :current-page="remoteFilesPage"
              :page-size="remoteFilesPageSize"
              :page-sizes="remoteFilesPageSizeOptions"
              :total="remoteFilesTotal"
              :pager-count="5"
              @current-change="handleRemotePageChange"
              @size-change="handleRemotePageSizeChange"
          />
        </div>
      </div>

      <div class="mobile-file-list-shell">
        <div class="mobile-file-list" v-loading="remoteFilesLoading">
          <div
              v-if="!displayRemoteFilesEntries.length && !remoteFilesLoading"
              class="empty-state"
          >
            This folder is empty
          </div>

          <div v-else class="mobile-file-grid" ref="remoteMobileFileGridRef">
            <div
                v-for="row in displayRemoteFilesEntries"
                :key="`${row.is_parent_entry ? 'parent-' : ''}${row.path}`"
                class="mobile-file-card"
                style="position: relative;"
            >
              <div
                  v-if="!row.is_parent_entry"
                  style="position:absolute; top:6px; right:12px; z-index:1;"
              >
                <el-checkbox
                    :model-value="isRemoteEntrySelected(row)"
                    @change="toggleRemoteSelection(row)"
                />
              </div>

              <div class="mobile-file-card-top">
                <div class="mobile-file-icon">
                  {{ row.is_dir ? '📁' : '📄' }}
                </div>

                <div class="mobile-file-main">
                  <div
                      class="mobile-file-name"
                      :style="row.is_parent_entry ? '' : 'padding-right: 42px;'"
                  >
                    {{ row.is_parent_entry ? '..' : row.name }}
                  </div>

                  <div class="mobile-file-tags">
                    <el-tag size="small" type="info">
                      {{ row.is_parent_entry ? 'Parent' : (row.is_dir ? 'Folder' : 'File') }}
                    </el-tag>

                    <el-tag
                        v-if="!row.is_parent_entry && row.is_symlink"
                        size="small"
                        type="info"
                    >
                      Link
                    </el-tag>

                    <el-tag
                        v-if="!row.is_parent_entry && row.is_hidden"
                        size="small"
                        type="warning"
                    >
                      Hidden
                    </el-tag>
                  </div>

                  <div class="mobile-file-meta">
                    <div class="mobile-file-meta-item">
                      <div class="mobile-file-meta-label">Size</div>
                      <div class="mobile-file-meta-value">
                        {{ row.is_dir ? '-' : formatBytes(row.size) }}
                      </div>
                    </div>

                    <div class="mobile-file-meta-item">
                      <div class="mobile-file-meta-label">Modified</div>
                      <div class="mobile-file-meta-value">
                        {{ row.is_parent_entry ? '-' : (row.modified_at || '-') }}
                      </div>
                    </div>

                    <div v-if="isRemoteSearchActive" class="mobile-file-meta-item mobile-file-meta-item-wide">
                      <div class="mobile-file-meta-label">Location</div>
                      <div class="mobile-file-meta-value">
                        {{ remoteEntryLocation(row) }}
                      </div>
                    </div>
                  </div>

                  <div class="mobile-file-actions">
                    <template v-if="row.is_parent_entry">
                      <div class="mobile-file-action-item">
                        <el-button
                            size="small"
                            type="primary"
                            plain
                            @click="goToRemoteParent"
                        >
                          Open
                        </el-button>
                      </div>
                    </template>

                    <template v-else>
                      <template v-if="row.is_dir">
                        <div class="mobile-file-action-item">
                          <el-button
                              size="small"
                              type="primary"
                              plain
                              @click="enterRemoteDirectory(row)"
                          >
                            Open
                          </el-button>
                        </div>
                      </template>

                      <template v-else>
                        <div class="mobile-file-action-item">
                          <el-button
                              size="small"
                              type="primary"
                              plain
                              @click="previewRow(row)"
                          >
                            Preview
                          </el-button>
                        </div>

                        <div class="mobile-file-action-item">
                          <el-button
                              size="small"
                              type="primary"
                              plain
                              @click="downloadRemoteEntry(row)"
                          >
                            Download
                          </el-button>
                        </div>
                      </template>

                      <div class="mobile-file-action-item">
                        <el-dropdown
                            trigger="click"
                            class="mobile-file-more"
                            @command="command => handleRemoteMoreAction(command, row)"
                        >
                          <el-button size="small" plain>
                            More
                          </el-button>

                          <template #dropdown>
                            <el-dropdown-menu>
                              <el-dropdown-item command="rename">Rename</el-dropdown-item>
                              <el-dropdown-item command="copy">Copy</el-dropdown-item>
                              <el-dropdown-item command="cut">Cut</el-dropdown-item>
                              <el-dropdown-item command="copy_path">Copy Path</el-dropdown-item>
                              <el-dropdown-item v-if="isZipEntry(row)" command="extract" divided :disabled="remoteZipExtracting">Extract Here</el-dropdown-item>
                              <el-dropdown-item command="delete">Delete</el-dropdown-item>
                            </el-dropdown-menu>
                          </template>
                        </el-dropdown>
                      </div>
                    </template>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </el-dialog>


  <RemoteZipPeekDialog
      ref="remoteZipPeekDialogRef"
      :selected-id="remoteFilesClientId"
  />

  <RemotePinsDialog
      v-model="pinManagerVisible"
      :selected-id="remoteFilesClientId"
      :items="remotePinnedJumpItems"
      @updated="handlePinnedQuickJumpsUpdated"
  />
</template>

<script>
import {ElMessage, ElMessageBox} from 'element-plus'
import RemotePinsDialog from './RemotePinsDialog.vue'
import RemoteZipPeekDialog from './RemoteZipPeekDialog.vue'
import { formatBytes as formatBytesValue } from '../utils/formatters.js'
import { uploadRemoteFileToClient } from '../api/transferApi.js'


export default {
  name: 'RemoteFilesDialog',

  components: {
    RemotePinsDialog,
    RemoteZipPeekDialog,
  },

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
  ],

  data() {
    return {
      visible: false,
      pinManagerVisible: false,

      remoteFilesLoading: false,
      remoteFilesClientId: '',
      remoteFilesContextSeq: 0,
      remoteDirectoryRequestSeq: 0,
      remoteDirectoryAbortController: null,
      remoteFilesCurrentPath: '',
      remoteFilesParentPath: '',
      remoteFilesEntries: [],
      remoteFilesPathInput: '',
      remoteFilesPage: 1,
      remoteFilesPageSize: 50,
      remoteFilesPageSizeOptions: [50, 100, 200],
      remoteFilesTotal: 0,
      remoteFilesTotalPages: 1,
      remoteFilesAllTotal: 0,
      remoteFilesHiddenTotal: 0,
      remoteSearchKeyword: '',
      remoteSearchRecursive: false,
      remoteSearchTimer: null,

      remoteUploadLoading: false,
      showHiddenFiles: false,
      remoteSelectedPaths: [],
      remoteZipDownloading: false,
      remoteZipCreating: false,
      remoteZipExtracting: false,

      quickJumpPaths: {},
      quickJumpLoading: false,
      remotePinnedJumpItems: [],
      remotePinnedJumpLoading: false,

      remoteClipboardPaths: [],
      remoteClipboardMode: '',
      remoteClipboardSourcePath: '',

      remoteMobilePanelCollapsed: true,
    }
  },

  computed: {
    displayRemoteFilesEntries() {
      const entries = Array.isArray(this.remoteFilesEntries)
          ? [...this.remoteFilesEntries]
          : []

      if (!this.isRemoteSearchActive && this.remoteFilesParentPath && this.remoteFilesPage === 1) {
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
      return this.isRemoteSearchActive ? 'No matching files or folders' : 'This folder is empty'
    },

    isRemoteSearchActive() {
      return !!this.normalizeRemoteSearchKeyword()
    },

    hasRemoteSelection() {
      return this.remoteSelectedPaths.length > 0
    },

    visibleRemoteSelectablePaths() {
      return this.displayRemoteFilesEntries
          .filter(row => row && !row.is_parent_entry && row.path)
          .map(row => row.path)
    },

    isRemoteCurrentPageAllSelected() {
      const paths = this.visibleRemoteSelectablePaths

      if (!paths.length) return false

      return paths.every(path => this.remoteSelectedPaths.includes(path))
    },

    // remoteSelectAllText() {
    //   return this.isRemoteCurrentPageAllSelected ? 'Clear Page Selection' : 'Select All'
    // },

    hasRemoteClipboard() {
      return this.remoteClipboardPaths.length > 0 && !!this.remoteClipboardMode
    },

    remoteClipboardActionText() {
      return this.remoteClipboardMode === 'move' ? 'Cut' : 'Copy'
    },

    remoteBreadcrumbItems() {
      const items = this.buildRemoteBreadcrumbItems(this.remoteFilesCurrentPath || '')

      return items.map(item => ({
        ...item,
        isCurrent: item.path === (this.remoteFilesCurrentPath || ''),
      }))
    },

    hasPinnedQuickJumps() {
      return Array.isArray(this.remotePinnedJumpItems) && this.remotePinnedJumpItems.length > 0
    },

    currentPinnedQuickJumpItem() {
      const currentPath = String(this.remoteFilesCurrentPath || '').trim()
      if (!currentPath) return null

      return (this.remotePinnedJumpItems || []).find(item => {
        return String(item?.path || '').trim() === currentPath
      }) || null
    },

    remotePinButtonText() {
      return this.currentPinnedQuickJumpItem ? 'Unpin' : 'Pin'
    },
  },

  methods: {

    formatBytes(value) {
  return formatBytesValue(value)
},

    normalizeRemoteSearchKeyword() {
      return String(this.remoteSearchKeyword || '').trim()
    },

    remoteEntryLocation(row) {
      if (!row || row.is_parent_entry) return '-'

      const relativePath = String(row.relative_path || '').trim()
      if (relativePath && relativePath !== row.name) {
        const normalized = relativePath.replace(/\\/g, '/')
        const index = normalized.lastIndexOf('/')
        return index > -1 ? normalized.slice(0, index) || '.' : '.'
      }

      return String(row.parent_path || this.remoteFilesCurrentPath || '.').trim() || '.'
    },

    scheduleRemoteSearch() {
      if (this.remoteSearchTimer) {
        clearTimeout(this.remoteSearchTimer)
      }

      this.remoteSearchTimer = window.setTimeout(() => {
        this.applyRemoteSearch()
      }, 300)
    },

    async applyRemoteSearch() {
      if (this.remoteSearchTimer) {
        clearTimeout(this.remoteSearchTimer)
        this.remoteSearchTimer = null
      }

      await this.loadRemoteDirectory(this.remoteFilesCurrentPath || '', 1)
    },

    clearRemoteSearchKeyword() {
      if (this.remoteSearchTimer) {
        clearTimeout(this.remoteSearchTimer)
        this.remoteSearchTimer = null
      }

      this.remoteSearchKeyword = ''
    },

    async navigateRemoteDirectory(path) {
      this.clearRemoteSearchKeyword()
      await this.loadRemoteDirectory(path || '', 1)
    },

    async handleRemoteSearchRecursiveChange() {
      if (!this.isRemoteSearchActive) return
      await this.loadRemoteDirectory(this.remoteFilesCurrentPath || '', 1)
    },

    scrollRemoteMobileFileListToTop() {
      this.$nextTick(() => {
        const el = this.$refs.remoteMobileFileGridRef

        if (el && typeof el.scrollTo === 'function') {
          el.scrollTo({
            top: 0,
            left: 0,
            behavior: 'auto',
          })
          return
        }

        if (el) {
          el.scrollTop = 0
        }
      })
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
        this.visible &&
        context.contextSeq === this.remoteFilesContextSeq &&
        context.clientId === this.remoteFilesClientId
      )
    },

    abortRemoteDirectoryRequest() {
      this.remoteDirectoryRequestSeq += 1
      const controller = this.remoteDirectoryAbortController
      this.remoteDirectoryAbortController = null
      if (controller) controller.abort()
    },

    async open() {
      const clientId = String(this.selectedId || '').trim()
      if (!clientId) {
        ElMessage.warning('Please select a device')
        return
      }

      this.abortRemoteDirectoryRequest()
      this.remoteFilesContextSeq += 1
      this.remoteFilesClientId = clientId
      this.visible = true
      this.$emit('visible-change', true)

      this.loadQuickJumpPaths()
      this.loadPinnedQuickJumps()
      await this.loadRemoteDirectory('', 1)
    },

    close() {
      this.handleVisibleChange(false)
    },

    clearTableSelection() {
      const table = this.$refs.remoteFilesTableRef

      if (table && typeof table.clearSelection === 'function') {
        table.clearSelection()
      }
    },

    toggleRemoteMobilePanel() {
      this.remoteMobilePanelCollapsed = !this.remoteMobilePanelCollapsed
    },

    triggerRemoteUpload() {
      if (!this.remoteFilesClientId) {
        ElMessage.warning('Please select a device')
        return
      }

      if (!this.remoteFilesCurrentPath) {
        ElMessage.warning('Current directory is empty')
        return
      }

      this.$emit('request-upload')
    },

    async handleUploadChange(event) {
      const file = event.target.files && event.target.files[0]
      if (!file) return

      const clientId = String(this.remoteFilesClientId || '').trim()
      if (!clientId) {
        ElMessage.warning('Please select a device')
        return
      }

      if (!this.remoteFilesCurrentPath) {
        ElMessage.warning('Current directory is empty')
        return
      }

      const targetPath = this.remoteFilesCurrentPath
      this.remoteUploadLoading = true

      this.$emit(
          'append-output',
          clientId,
          `> [Remote Upload] ${file.name} -> ${targetPath}`,
          'command'
      )

      try {
        const result = await uploadRemoteFileToClient({
          file, clientId, destinationPath: targetPath,
          headers: this.getTabScopedHeaders(),
        })
        const taskId = result.task_id

        this.$emit('set-active-task', clientId, taskId || '')
        this.$emit('upload-started', {
          taskId: taskId || '',
          clientId,
          path: targetPath || '',
        })

        ElMessage.success(`Upload started: ${file.name}`)
      } catch (e) {
        this.$emit(
            'append-output',
            clientId,
            `[Upload failed] ${e.message || 'unknown error'}`,
            'error'
        )

        ElMessage.error(e.message || 'Upload failed')
      } finally {
        this.remoteUploadLoading = false
        if (event?.target) event.target.value = ''
      }
    },

    async loadRemoteDirectory(path = '', page = 1) {
      const context = this.captureRemoteFilesContext()
      if (!context.clientId) {
        ElMessage.warning('Please select a device')
        return
      }

      this.abortRemoteDirectoryRequest()
      const requestSeq = ++this.remoteDirectoryRequestSeq
      const controller = new AbortController()
      this.remoteDirectoryAbortController = controller
      this.remoteFilesLoading = true

      try {
        const url = new URL(
            `/api/connections/${encodeURIComponent(context.clientId)}/remote-files`,
            window.location.origin
        )

        if (path) url.searchParams.set('path', path)

        url.searchParams.set('page', String(page || 1))
        url.searchParams.set('page_size', String(this.remoteFilesPageSize || 50))
        url.searchParams.set('show_hidden', this.showHiddenFiles ? 'true' : 'false')

        const searchKeyword = this.normalizeRemoteSearchKeyword()
        if (searchKeyword) {
          url.searchParams.set('search', searchKeyword)
          url.searchParams.set('recursive', this.remoteSearchRecursive ? 'true' : 'false')
        }

        const res = await fetch(url.pathname + url.search, {signal: controller.signal})
        const json = await res.json()

        if (!this.isRemoteFilesContextActive(context) || requestSeq !== this.remoteDirectoryRequestSeq) return
        if (!res.ok || json.code !== 0) {
          throw new Error(json.message || 'Failed to load remote directory')
        }

        const data = json.data || {}
        const pagination = data.pagination || {}
        const summary = data.summary || {}

        this.remoteFilesCurrentPath = data.current_path || ''
        this.remoteFilesParentPath = data.parent_path || ''
        this.remoteFilesEntries = data.entries || []
        this.remoteFilesPathInput = this.remoteFilesCurrentPath || ''
        this.remoteFilesPage = Number(pagination.page || page || 1)
        this.remoteFilesPageSize = Number(pagination.page_size || this.remoteFilesPageSize || 50)
        this.remoteFilesTotal = Number(pagination.total_visible || 0)
        this.remoteFilesTotalPages = Number(pagination.total_pages || 1)
        this.remoteFilesAllTotal = Number(summary.total_all || this.remoteFilesTotal || 0)
        this.remoteFilesHiddenTotal = Number(summary.total_hidden || 0)
        this.showHiddenFiles = !!summary.show_hidden
        this.remoteSelectedPaths = []
        this.clearTableSelection()
        this.scrollRemoteMobileFileListToTop() // 切换目录后，移动端文件列表回到顶部
      } catch (e) {
        if (e?.name === 'AbortError' || !this.isRemoteFilesContextActive(context)) return
        ElMessage.error(e.message || 'Failed to load remote directory')
      } finally {
        if (requestSeq === this.remoteDirectoryRequestSeq) {
          this.remoteDirectoryAbortController = null
          if (this.isRemoteFilesContextActive(context)) this.remoteFilesLoading = false
        }
      }
    },

    async refreshRemoteDirectory() {
      await this.loadRemoteDirectory(this.remoteFilesCurrentPath || '', this.remoteFilesPage || 1)
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

    async handleRemotePageChange(page) {
      await this.loadRemoteDirectory(this.remoteFilesCurrentPath || '', page || 1)
    },

    async handleRemotePageSizeChange(pageSize) {
      this.remoteFilesPageSize = Number(pageSize || 50)
      await this.loadRemoteDirectory(this.remoteFilesCurrentPath || '', 1)
    },

    async toggleRemoteHiddenFiles() {
      this.showHiddenFiles = !this.showHiddenFiles
      await this.loadRemoteDirectory(this.remoteFilesCurrentPath || '', 1)
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

    handleRemoteSelectionChange(rows) {
      this.remoteSelectedPaths = Array.isArray(rows)
          ? rows
              .filter(item => item && !item.is_parent_entry)
              .map(item => item.path)
              .filter(Boolean)
          : []
    },

    isRemoteEntrySelected(row) {
      if (!row || row.is_parent_entry) return false
      return !!(row.path && this.remoteSelectedPaths.includes(row.path))
    },

    toggleRemoteSelection(row) {
      if (!row || !row.path || row.is_parent_entry) return

      const exists = this.remoteSelectedPaths.includes(row.path)

      if (exists) {
        this.remoteSelectedPaths = this.remoteSelectedPaths.filter(item => item !== row.path)
      } else {
        this.remoteSelectedPaths = [...this.remoteSelectedPaths, row.path]
      }
    },

    clearRemoteSelection() {
      this.remoteSelectedPaths = []
      this.clearTableSelection()
    },

    toggleRemoteCurrentPageSelection() {
      const paths = this.visibleRemoteSelectablePaths

      if (!paths.length) return

      if (this.isRemoteCurrentPageAllSelected) {
        this.remoteSelectedPaths = this.remoteSelectedPaths.filter(path => {
          return !paths.includes(path)
        })

        const table = this.$refs.remoteFilesTableRef

        if (table && typeof table.toggleRowSelection === 'function') {
          this.displayRemoteFilesEntries.forEach(row => {
            if (row && !row.is_parent_entry && row.path && paths.includes(row.path)) {
              table.toggleRowSelection(row, false)
            }
          })
        }

        return
      }

      const next = new Set(this.remoteSelectedPaths)

      paths.forEach(path => {
        next.add(path)
      })

      this.remoteSelectedPaths = Array.from(next)

      const table = this.$refs.remoteFilesTableRef

      if (table && typeof table.toggleRowSelection === 'function') {
        this.displayRemoteFilesEntries.forEach(row => {
          if (row && !row.is_parent_entry && row.path && paths.includes(row.path)) {
            table.toggleRowSelection(row, true)
          }
        })
      }
    },

    async copyRemotePath(row) {
      if (!row || !row.path || row.is_parent_entry) {
        ElMessage.warning('Invalid path')
        return
      }

      const text = String(row.path)

      try {
        if (
            window.isSecureContext &&
            navigator.clipboard &&
            typeof navigator.clipboard.writeText === 'function'
        ) {
          await navigator.clipboard.writeText(text)
          ElMessage.success('Path copied')
          return
        }

        this.copyTextFallback(text)
        ElMessage.success('Path copied')
      } catch (e) {
        try {
          this.copyTextFallback(text)
          ElMessage.success('Path copied')
        } catch (fallbackError) {
          ElMessage.error('Failed to copy path')
        }
      }
    },

    copyTextFallback(text) {
      const textarea = document.createElement('textarea')

      textarea.value = String(text || '')
      textarea.setAttribute('readonly', '')
      textarea.style.position = 'fixed'
      textarea.style.left = '-9999px'
      textarea.style.top = '0'
      textarea.style.opacity = '0'

      document.body.appendChild(textarea)

      textarea.focus()
      textarea.select()
      textarea.setSelectionRange(0, textarea.value.length)

      const ok = document.execCommand('copy')

      document.body.removeChild(textarea)

      if (!ok) {
        throw new Error('Fallback copy failed')
      }
    },

    // async copyRemotePath(row) {
    //   if (!row || !row.path || row.is_parent_entry) {
    //     ElMessage.warning('Invalid path')
    //     return
    //   }
    //
    //   try {
    //     await navigator.clipboard.writeText(row.path)
    //     ElMessage.success('Path copied')
    //   } catch (e) {
    //     ElMessage.error('Failed to copy path')
    //   }
    // },

    cacheRemoteClipboard(mode) {
      const paths = [...this.remoteSelectedPaths]

      if (!paths.length) {
        ElMessage.warning('Please select at least one file or folder')
        return
      }

      this.remoteClipboardPaths = paths
      this.remoteClipboardMode = mode === 'move' ? 'move' : 'copy'
      this.remoteClipboardSourcePath = this.remoteFilesCurrentPath || ''

      const actionText = this.remoteClipboardMode === 'move' ? 'Cut' : 'Copied'
      ElMessage.success(`${actionText} ${paths.length} item(s)`)
    },

    copySelectedRemoteEntries() {
      this.cacheRemoteClipboard('copy')
    },

    cutSelectedRemoteEntries() {
      this.cacheRemoteClipboard('move')
    },

    copySingleRemoteEntry(row) {
      if (!row?.path) return
      this.remoteSelectedPaths = [row.path]
      this.copySelectedRemoteEntries()
    },

    cutSingleRemoteEntry(row) {
      if (!row?.path) return
      this.remoteSelectedPaths = [row.path]
      this.cutSelectedRemoteEntries()
    },

    clearRemoteClipboard() {
      this.remoteClipboardPaths = []
      this.remoteClipboardMode = ''
      this.remoteClipboardSourcePath = ''
    },

    async pasteRemoteClipboard() {
      const context = this.captureRemoteFilesContext()
      const clientId = context.clientId
      if (!clientId) {
        ElMessage.warning('Please select a device')
        return
      }

      if (!this.remoteFilesCurrentPath) {
        ElMessage.warning('Current directory is empty')
        return
      }

      const paths = [...this.remoteClipboardPaths]

      if (!paths.length || !this.remoteClipboardMode) {
        ElMessage.warning('Clipboard is empty')
        return
      }

      try {
        const res = await fetch(`/api/connections/${encodeURIComponent(clientId)}/remote-files/paste`, {
          method: 'POST',
          headers: {'Content-Type': 'application/json', 'X-RCH-Origin': 'web_ui'},
          body: JSON.stringify({
            paths,
            destination_dir: this.remoteFilesCurrentPath,
            operation: this.remoteClipboardMode,
          }),
        })

        const json = await res.json()

        if (!this.isRemoteFilesContextActive(context)) return
        if (!res.ok || json.code !== 0) {
          throw new Error(json.message || 'Paste failed')
        }

        const actionText = this.remoteClipboardMode === 'move' ? 'Moved' : 'Copied'
        const message = json.data?.message || `${actionText} ${paths.length} item(s)`

        ElMessage.success(`${actionText} ${paths.length} item(s)`)
        await this.refreshRemoteDirectory()

        if (this.remoteClipboardMode === 'move') {
          this.clearRemoteClipboard()
        }

        if (message && !message.startsWith(`${actionText} ${paths.length} item(s)`)) {
          ElMessage.info(message)
        }
      } catch (e) {
        if (!this.isRemoteFilesContextActive(context)) return
        ElMessage.error(e.message || 'Paste failed')
      }
    },

    handleRemoteToolbarMoreCommand(command) {
      if (command === 'toggle_pin') {
        this.toggleCurrentPinnedQuickJump()
        return
      }

      if (command === 'manage_pins') {
        this.openPinnedQuickJumpManager()
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

    handleRemoteMoreAction(command, row) {
      if (!row || row.is_parent_entry) return

      if (command === 'rename') {
        this.renameRemoteEntry(row)
        return
      }

      if (command === 'copy_path') {
        this.copyRemotePath(row)
        return
      }

      if (command === 'copy') {
        this.copySingleRemoteEntry(row)
        return
      }

      if (command === 'cut') {
        this.cutSingleRemoteEntry(row)
        return
      }

      if (command === 'extract') {
        this.extractRemoteZip(row)
        return
      }

      if (command === 'delete') {
        this.deleteRemoteEntry(row)
      }
    },

    isZipEntry(row) {
      if (!row || row.is_dir || row.is_parent_entry) return false
      const name = String(row.name || row.path || '').trim().toLowerCase()
      return name.endsWith('.zip')
    },

    remotePathBaseName(path) {
      const normalized = String(path || '').replace(/[\\/]+$/, '')
      const parts = normalized.split(/[\\/]/)
      return parts[parts.length - 1] || 'archive'
    },

    buildRemoteZipDefaultName() {
      const paths = [...this.remoteSelectedPaths]
      if (paths.length === 1) {
        const baseName = this.remotePathBaseName(paths[0])
        const stem = baseName.replace(/\.[^.]+$/, '') || baseName || 'archive'
        return baseName.toLowerCase().endsWith('.zip') ? `${stem}_archive.zip` : `${stem}.zip`
      }

      const now = new Date()
      const pad = value => String(value).padStart(2, '0')
      const stamp = `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}-${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`
      return `archive_${stamp}.zip`
    },

    async createSelectedRemoteZip() {
      const context = this.captureRemoteFilesContext()
      const clientId = context.clientId
      if (!clientId) {
        ElMessage.warning('Please select a device')
        return
      }

      const paths = [...this.remoteSelectedPaths]
      if (!paths.length) {
        ElMessage.warning('Please select at least one file or folder')
        return
      }
      if (!this.remoteFilesCurrentPath) {
        ElMessage.warning('Current directory is empty')
        return
      }

      try {
        const {value} = await ElMessageBox.prompt(
            'The ZIP archive will be created in the current remote directory.',
            'Create ZIP',
            {
              confirmButtonText: 'Create',
              cancelButtonText: 'Cancel',
              inputValue: this.buildRemoteZipDefaultName(),
              inputPattern: /.+/,
              inputErrorMessage: 'ZIP name is required',
            }
        )

        let archiveName = String(value || '').trim()
        if (!archiveName) return
        if (!archiveName.toLowerCase().endsWith('.zip')) archiveName += '.zip'
        if (!this.isRemoteFilesContextActive(context)) return

        this.remoteZipCreating = true
        const res = await fetch(`/api/connections/${encodeURIComponent(clientId)}/remote-files/create-zip`, {
          method: 'POST',
          headers: {'Content-Type': 'application/json', 'X-RCH-Origin': 'web_ui'},
          body: JSON.stringify({
            paths,
            destination_dir: this.remoteFilesCurrentPath,
            archive_name: archiveName,
          }),
        })
        const json = await res.json()

        if (!this.isRemoteFilesContextActive(context)) return
        if (!res.ok || json.code !== 0) {
          throw new Error(json.message || 'Create ZIP failed')
        }

        const data = json.data || {}
        ElMessage.success(`ZIP created: ${data.archive_name || archiveName}`)
        await this.refreshRemoteDirectory()
      } catch (e) {
        if (!this.isRemoteFilesContextActive(context)) return
        if (this.isDialogCancel(e)) return
        ElMessage.error(e.message || 'Create ZIP failed')
      } finally {
        if (this.isRemoteFilesContextActive(context)) this.remoteZipCreating = false
      }
    },

    async extractRemoteZip(row) {
      const context = this.captureRemoteFilesContext()
      const clientId = context.clientId
      if (!clientId) {
        ElMessage.warning('Please select a device')
        return
      }
      if (!this.isZipEntry(row) || !row.path) {
        ElMessage.warning('Please select a ZIP file')
        return
      }
      if (!this.remoteFilesCurrentPath) {
        ElMessage.warning('Current directory is empty')
        return
      }

      try {
        await ElMessageBox.confirm(
            `Extract "${row.name}" into the current directory? A ZIP with one root folder is extracted directly; otherwise a new folder is created automatically.`,
            'Extract ZIP',
            {
              type: 'warning',
              confirmButtonText: 'Extract',
              cancelButtonText: 'Cancel',
            }
        )

        if (!this.isRemoteFilesContextActive(context)) return
        this.remoteZipExtracting = true
        const res = await fetch(`/api/connections/${encodeURIComponent(clientId)}/remote-files/extract-zip`, {
          method: 'POST',
          headers: {'Content-Type': 'application/json', 'X-RCH-Origin': 'web_ui'},
          body: JSON.stringify({
            path: row.path,
            destination_dir: this.remoteFilesCurrentPath,
          }),
        })
        const json = await res.json()

        if (!this.isRemoteFilesContextActive(context)) return
        if (!res.ok || json.code !== 0) {
          throw new Error(json.message || 'Extract ZIP failed')
        }

        const data = json.data || {}
        ElMessage.success(`Extracted to: ${data.extracted_to || this.remoteFilesCurrentPath}`)
        await this.refreshRemoteDirectory()
      } catch (e) {
        if (!this.isRemoteFilesContextActive(context)) return
        if (this.isDialogCancel(e)) return
        ElMessage.error(e.message || 'Extract ZIP failed')
      } finally {
        if (this.isRemoteFilesContextActive(context)) this.remoteZipExtracting = false
      }
    },

    async createRemoteDirectory() {
      const context = this.captureRemoteFilesContext()
      const clientId = context.clientId
      if (!clientId) {
        ElMessage.warning('Please select a device')
        return
      }

      if (!this.remoteFilesCurrentPath) {
        ElMessage.warning('Current directory is empty')
        return
      }

      try {
        const {value} = await ElMessageBox.prompt(
            'Enter the new folder name',
            'Create Directory',
            {
              confirmButtonText: 'Create',
              cancelButtonText: 'Cancel',
              inputPattern: /.+/,
              inputErrorMessage: 'Folder name is required',
            }
        )

        const folderName = String(value || '').trim()
        if (!folderName || !this.isRemoteFilesContextActive(context)) return

        const base = this.remoteFilesCurrentPath.replace(/[\\/]+$/, '')
        const separator = base.includes('\\') ? '\\' : '/'
        const fullPath = `${base}${base ? separator : ''}${folderName}`

        const res = await fetch(`/api/connections/${encodeURIComponent(clientId)}/remote-files/mkdir`, {
          method: 'POST',
          headers: {'Content-Type': 'application/json', 'X-RCH-Origin': 'web_ui'},
          body: JSON.stringify({path: fullPath}),
        })

        const json = await res.json()

        if (!this.isRemoteFilesContextActive(context)) return
        if (!res.ok || json.code !== 0) {
          throw new Error(json.message || 'Create directory failed')
        }

        ElMessage.success('Directory created')
        await this.refreshRemoteDirectory()
      } catch (e) {
        if (!this.isRemoteFilesContextActive(context)) return
        if (this.isDialogCancel(e)) return
        ElMessage.error(e.message || 'Create directory failed')
      }
    },

    async renameRemoteEntry(row) {
      const context = this.captureRemoteFilesContext()
      const clientId = context.clientId
      if (!clientId) {
        ElMessage.warning('Please select a device')
        return
      }
      if (!row || !row.path || row.is_parent_entry) {
        ElMessage.warning('Invalid path')
        return
      }

      try {
        const {value} = await ElMessageBox.prompt(
            'Enter the new name',
            'Rename',
            {
              confirmButtonText: 'Rename',
              cancelButtonText: 'Cancel',
              inputValue: row.name || '',
              inputPattern: /.+/,
              inputErrorMessage: 'New name is required',
            }
        )

        const newName = String(value || '').trim()
        if (!newName || newName === row.name || !this.isRemoteFilesContextActive(context)) return

        const res = await fetch(`/api/connections/${encodeURIComponent(clientId)}/remote-files/rename`, {
          method: 'POST',
          headers: {'Content-Type': 'application/json', 'X-RCH-Origin': 'web_ui'},
          body: JSON.stringify({
            old_path: row.path,
            new_name: newName,
          }),
        })

        const json = await res.json()

        if (!this.isRemoteFilesContextActive(context)) return
        if (!res.ok || json.code !== 0) {
          throw new Error(json.message || 'Rename failed')
        }

        ElMessage.success('Renamed')
        await this.refreshRemoteDirectory()
      } catch (e) {
        if (!this.isRemoteFilesContextActive(context)) return
        if (this.isDialogCancel(e)) return
        ElMessage.error(e.message || 'Rename failed')
      }
    },

    async downloadRemoteEntry(row) {
      const context = this.captureRemoteFilesContext()
      const clientId = context.clientId
      if (!clientId) {
        ElMessage.warning('Please select a device')
        return
      }
      if (!row || !row.path || row.is_dir || row.is_parent_entry) {
        ElMessage.warning('Please select a file')
        return
      }

      try {
        const url = new URL(
            `/api/connections/${encodeURIComponent(clientId)}/remote-files/download`,
            window.location.origin
        )

        url.searchParams.set('path', row.path)

        ElMessage.success({
          message: `Download started: ${row.name || 'file'}`,
          duration: 1800,
        })

        const res = await fetch(url.pathname + url.search, {
          method: 'POST',
          headers: this.getTabScopedHeaders(),
        })
        const json = await res.json()

        if (!this.isRemoteFilesContextActive(context)) return
        if (!res.ok || json.code !== 0) {
          throw new Error(json.message || 'Download failed')
        }

        const file = (json.data && (json.data.file || json.data.artifact)) || null

        if (!file || !file.artifact_id) {
          throw new Error('Download finished, but artifact was not found')
        }

        const downloadUrl = file.download_url || `/api/artifacts/${encodeURIComponent(file.artifact_id)}/download`
        window.open(downloadUrl, '_blank')

        ElMessage.success(`Downloaded: ${row.name}`)
        this.$emit('artifacts-maybe-changed')
      } catch (e) {
        if (!this.isRemoteFilesContextActive(context)) return
        ElMessage.error(e.message || 'Download failed')
      }
    },

    async downloadSelectedRemoteEntries() {
      const context = this.captureRemoteFilesContext()
      const clientId = context.clientId
      if (!clientId) {
        ElMessage.warning('Please select a device')
        return
      }

      const paths = [...this.remoteSelectedPaths]

      if (!paths.length) {
        ElMessage.warning('Please select at least one file or folder')
        return
      }

      this.remoteZipDownloading = true

      try {
        ElMessage.success({
          message: `Download started: ${paths.length} selected item(s)`,
          duration: 1800,
        })

        const res = await fetch(`/api/connections/${encodeURIComponent(clientId)}/remote-files/download-zip`, {
          method: 'POST',
          headers: {
            ...this.getTabScopedHeaders(),
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            paths,
            archive_name: '',
          }),
        })

        const json = await res.json()

        if (!this.isRemoteFilesContextActive(context)) return
        if (!res.ok || json.code !== 0) {
          throw new Error(json.message || 'ZIP download failed')
        }

        const file = (json.data && (json.data.file || json.data.artifact)) || null

        if (!file || !file.artifact_id) {
          throw new Error('ZIP download finished, but artifact was not found')
        }

        const downloadUrl = file.download_url || `/api/artifacts/${encodeURIComponent(file.artifact_id)}/download`
        window.open(downloadUrl, '_blank')

        ElMessage.success(`ZIP ready: ${file.original_name || file.stored_name}`)
        this.$emit('artifacts-maybe-changed')
      } catch (e) {
        if (!this.isRemoteFilesContextActive(context)) return
        ElMessage.error(e.message || 'ZIP download failed')
      } finally {
        if (this.isRemoteFilesContextActive(context)) this.remoteZipDownloading = false
      }
    },

    async deleteRemoteEntry(row) {
      const context = this.captureRemoteFilesContext()
      const clientId = context.clientId
      if (!clientId) {
        ElMessage.warning('Please select a device')
        return
      }
      if (!row || !row.path || row.is_parent_entry) {
        ElMessage.warning('Invalid path')
        return
      }

      try {
        await ElMessageBox.confirm(
            `Delete "${row.name}"?${row.is_dir ? ' All nested contents will be removed as well.' : ''}`,
            'Delete Confirmation',
            {
              type: 'warning',
              confirmButtonText: 'Delete',
              cancelButtonText: 'Cancel',
            }
        )

        if (!this.isRemoteFilesContextActive(context)) return
        const url = new URL(
            `/api/connections/${encodeURIComponent(clientId)}/remote-files`,
            window.location.origin
        )

        url.searchParams.set('path', row.path)

        const res = await fetch(url.pathname + url.search, {method: 'DELETE', headers: {'X-RCH-Origin': 'web_ui'}})
        const json = await res.json()

        if (!this.isRemoteFilesContextActive(context)) return
        if (!res.ok || json.code !== 0) {
          throw new Error(json.message || 'Delete failed')
        }

        ElMessage.success('Deleted')
        await this.refreshRemoteDirectory()
      } catch (e) {
        if (!this.isRemoteFilesContextActive(context)) return
        if (this.isDialogCancel(e)) return
        ElMessage.error(e.message || 'Delete failed')
      }
    },

    async deleteSelectedRemoteEntries() {
      const context = this.captureRemoteFilesContext()
      const clientId = context.clientId
      if (!clientId) {
        ElMessage.warning('Please select a device')
        return
      }

      const paths = [...this.remoteSelectedPaths]

      if (!paths.length) {
        ElMessage.warning('Please select at least one file or folder to delete')
        return
      }

      try {
        await ElMessageBox.confirm(
            `Delete ${paths.length} selected item(s)?`,
            'Delete Multiple Items',
            {
              type: 'warning',
              confirmButtonText: 'Delete',
              cancelButtonText: 'Cancel',
              confirmButtonClass: 'el-button--danger',
              dangerouslyUseHTMLString: false,
            }
        )

        if (!this.isRemoteFilesContextActive(context)) return
        const res = await fetch(`/api/connections/${encodeURIComponent(clientId)}/remote-files/batch`, {
          method: 'DELETE',
          headers: {'Content-Type': 'application/json', 'X-RCH-Origin': 'web_ui'},
          body: JSON.stringify({paths}),
        })

        const json = await res.json()

        if (!this.isRemoteFilesContextActive(context)) return
        if (!res.ok || json.code !== 0) {
          throw new Error(json.message || 'Batch delete failed')
        }

        const message = json.data?.message || 'Delete completed'

        ElMessage.success(`Deleted ${paths.length} item(s)`)
        await this.refreshRemoteDirectory()
        this.clearRemoteSelection()

        if (message && message !== 'Delete completed') {
          ElMessage.info(message)
        }
      } catch (e) {
        if (!this.isRemoteFilesContextActive(context)) return
        if (this.isDialogCancel(e)) return
        ElMessage.error(e.message || 'Batch delete failed')
      }
    },

    async loadPinnedQuickJumps() {
      const context = this.captureRemoteFilesContext()
      if (!context.clientId) return

      this.remotePinnedJumpLoading = true

      try {
        const res = await fetch(`/api/connections/${encodeURIComponent(context.clientId)}/pinned_paths`)
        const json = await res.json()

        if (!this.isRemoteFilesContextActive(context)) return
        if (res.ok && json.code === 0 && json.data) {
          this.remotePinnedJumpItems = Array.isArray(json.data.items)
              ? json.data.items
              : []
        }
      } catch (e) {
        if (this.isRemoteFilesContextActive(context)) console.error('Failed to load pinned paths:', e)
      } finally {
        if (this.isRemoteFilesContextActive(context)) this.remotePinnedJumpLoading = false
      }
    },

    async promptSavePinnedQuickJump() {
      const context = this.captureRemoteFilesContext()
      const clientId = context.clientId
      if (!clientId) {
        ElMessage.warning('Please select a device')
        return
      }

      const currentPath = String(this.remoteFilesCurrentPath || '').trim()

      if (!currentPath) {
        ElMessage.warning('Current directory is empty')
        return
      }

      const currentItems = Array.isArray(this.remotePinnedJumpItems)
          ? this.remotePinnedJumpItems
          : []

      const currentPinnedItem = this.currentPinnedQuickJumpItem

      const currentDirectoryName = currentPath
          .replace(/[\\/]+$/, '')
          .split(/[\\/]/)
          .filter(Boolean)
          .pop() || 'Pinned Path'

      try {
        const {value} = await ElMessageBox.prompt(
            `Current path:<br><span style="word-break: break-all; color: var(--muted);">${this.escapeRemoteHtml(currentPath)}</span>`,
            currentPinnedItem ? 'Edit Pinned Path' : 'Pin Path',
            {
              confirmButtonText: currentPinnedItem ? 'Update' : 'Save',
              cancelButtonText: 'Cancel',
              dangerouslyUseHTMLString: true,
              inputValue: currentPinnedItem?.display_name || currentDirectoryName,
              inputPattern: /.+/,
              inputErrorMessage: 'Display name is required',
            }
        )

        const displayName = String(value || '').trim()
        if (!displayName || !this.isRemoteFilesContextActive(context)) return

        const exists = currentItems.find(item => {
          return (item?.display_name || '').trim() === displayName
        })

        if (
            exists &&
            (
                !currentPinnedItem ||
                (exists.display_name || '').trim() !== (currentPinnedItem.display_name || '').trim()
            )
        ) {
          await ElMessageBox.confirm(
              `A pinned path named "${this.escapeRemoteHtml(displayName)}" already exists. Update it to the current path?`,
              'Overwrite Pinned Path',
              {
                confirmButtonText: 'Overwrite',
                cancelButtonText: 'Cancel',
                type: 'warning',
                dangerouslyUseHTMLString: true,
              }
          )
        }

        const method = currentPinnedItem ? 'PUT' : 'POST'
        const body = currentPinnedItem
            ? {
              original_display_name: currentPinnedItem.display_name,
              display_name: displayName,
              path: currentPath,
            }
            : {
              display_name: displayName,
              path: currentPath,
            }

        if (!this.isRemoteFilesContextActive(context)) return
        const res = await fetch(`/api/connections/${encodeURIComponent(clientId)}/pinned_paths`, {
          method,
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(body),
        })

        const json = await res.json()

        if (!this.isRemoteFilesContextActive(context)) return
        if (!res.ok || json.code !== 0) {
          throw new Error(json.message || 'Failed to save pinned path')
        }

        this.remotePinnedJumpItems = Array.isArray(json.data?.items)
            ? json.data.items
            : []

        ElMessage.success(json.data?.message || 'Pinned path saved')
      } catch (e) {
        if (!this.isRemoteFilesContextActive(context)) return
        if (this.isDialogCancel(e)) return
        ElMessage.error(e.message || 'Failed to save pinned path')
      }
    },

    async deletePinnedQuickJump(item, options = {}) {
      const context = this.captureRemoteFilesContext()
      const clientId = context.clientId
      if (!clientId || !item?.display_name) return false

      const shouldConfirm = options.confirm !== false

      try {
        if (shouldConfirm) {
          await ElMessageBox.confirm(
              `Remove pinned path "${this.escapeRemoteHtml(item.display_name)}"?`,
              'Delete Pinned path',
              {
                confirmButtonText: 'Delete',
                cancelButtonText: 'Cancel',
                type: 'warning',
                dangerouslyUseHTMLString: true,
              }
          )
        }

        if (!this.isRemoteFilesContextActive(context)) return false
        const res = await fetch(`/api/connections/${encodeURIComponent(clientId)}/pinned_paths`, {
          method: 'DELETE',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({display_name: item.display_name}),
        })

        const json = await res.json()

        if (!this.isRemoteFilesContextActive(context)) return false
        if (!res.ok || json.code !== 0) {
          throw new Error(json.message || 'Failed to delete pinned path')
        }

        this.remotePinnedJumpItems = Array.isArray(json.data?.items)
            ? json.data.items
            : []

        if (options.toast !== false) {
          ElMessage.success(json.data?.message || 'Pinned path removed')
        }

        return true
      } catch (e) {
        if (!this.isRemoteFilesContextActive(context)) return false
        if (this.isDialogCancel(e)) return false
        ElMessage.error(e.message || 'Failed to delete pinned path')
        return false
      }
    },


    async toggleCurrentPinnedQuickJump() {
      const currentItem = this.currentPinnedQuickJumpItem

      if (currentItem) {
        await this.deletePinnedQuickJump(currentItem)
        return
      }

      await this.promptSavePinnedQuickJump()
    },

    openPinnedQuickJumpManager() {
      this.pinManagerVisible = true
    },

    handlePinnedQuickJumpsUpdated(items) {
      this.remotePinnedJumpItems = Array.isArray(items) ? items : []
    },

    async loadQuickJumpPaths() {
      const context = this.captureRemoteFilesContext()
      if (!context.clientId) return

      this.quickJumpLoading = true

      try {
        const res = await fetch(`/api/connections/${encodeURIComponent(context.clientId)}/system-paths`)
        const json = await res.json()

        if (!this.isRemoteFilesContextActive(context)) return
        if (res.ok && json.code === 0 && json.data) {
          this.quickJumpPaths = json.data
        }
      } catch (e) {
        if (this.isRemoteFilesContextActive(context)) console.error('Failed to load system paths:', e)
      } finally {
        if (this.isRemoteFilesContextActive(context)) this.quickJumpLoading = false
      }
    },

    async jumpToPath(command) {
      if (command === 'input_navigate') {
        await this.promptRemotePathNavigate()
        return
      }

      if (command && typeof command === 'object') {
        if (command.type === 'pinned_jump') {
          const path = String(command.path || '').trim()

          if (!path) {
            ElMessage.warning('Path not available')
            return
          }

          await this.navigateRemoteDirectory(path)
          return
        }
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
        const {value} = await ElMessageBox.prompt(
            'Enter the target path',
            'Go to Folder',
            {
              confirmButtonText: 'Go',
              cancelButtonText: 'Cancel',
              inputValue: this.remoteFilesCurrentPath || this.remoteFilesPathInput || '',
              inputPattern: /.+/,
              inputErrorMessage: 'Path is required',
            }
        )

        const path = String(value || '').trim()
        if (!path) return

        this.remoteFilesPathInput = path
        await this.navigateRemoteDirectory(path)
      } catch (e) {
        if (this.isDialogCancel(e)) return
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
        const items = [{label: drive, path: `${drive}\\`}]
        let accumulated = `${drive}\\`

        parts.forEach(part => {
          accumulated = accumulated.replace(/[\\/]+$/, '') + '\\' + part
          items.push({label: part, path: accumulated})
        })

        return items
      }

      const isAbsolute = currentPath.startsWith('/')
      const parts = currentPath.split('/').filter(Boolean)
      const items = []

      if (isAbsolute) {
        items.push({label: 'Root', path: '/'})
      }

      let accumulated = ''

      parts.forEach(part => {
        if (isAbsolute) {
          accumulated += `/${part}`
        } else {
          accumulated = accumulated ? `${accumulated}/${part}` : part
        }

        items.push({label: part, path: accumulated})
      })

      if (!items.length && isAbsolute) {
        items.push({label: 'Root', path: '/'})
      }

      return items
    },

    async goToRemoteBreadcrumb(item) {
      if (!item || !item.path || item.isCurrent) return
      await this.navigateRemoteDirectory(item.path)
    },

    previewRow(row) {
      if (!row || row.is_dir || row.is_parent_entry) return
      if (this.isZipEntry(row)) {
        this.$refs.remoteZipPeekDialogRef?.open(row)
        return
      }
      this.$emit('preview', {
        ...row,
        client_id: this.remoteFilesClientId,
      })
    },

    escapeRemoteHtml(text) {
      return String(text || '')
          .replace(/&/g, '&amp;')
          .replace(/</g, '&lt;')
          .replace(/>/g, '&gt;')
          .replace(/"/g, '&quot;')
          .replace(/'/g, '&#39;')
    },

    resetRemoteFilesState() {
      this.abortRemoteDirectoryRequest()
      this.remoteFilesContextSeq += 1
      this.remoteFilesClientId = ''
      this.remoteFilesLoading = false
      this.remoteFilesCurrentPath = ''
      this.remoteFilesParentPath = ''
      this.remoteFilesEntries = []
      this.remoteFilesPathInput = ''
      this.remoteFilesPage = 1
      this.remoteFilesPageSize = 50
      this.remoteFilesTotal = 0
      this.remoteFilesTotalPages = 1
      this.remoteFilesAllTotal = 0
      this.remoteFilesHiddenTotal = 0
      this.remoteSearchKeyword = ''
      this.remoteSearchRecursive = false
      if (this.remoteSearchTimer) {
        clearTimeout(this.remoteSearchTimer)
        this.remoteSearchTimer = null
      }
      this.showHiddenFiles = false
      this.remoteSelectedPaths = []
      this.remoteZipDownloading = false
      this.remoteZipCreating = false
      this.remoteZipExtracting = false
      this.remotePinnedJumpItems = []
      this.remotePinnedJumpLoading = false
      this.pinManagerVisible = false
      this.remoteMobilePanelCollapsed = false
      this.clearRemoteClipboard()
      this.clearTableSelection()
    },

    isDialogCancel(e) {
      return e === 'cancel' || e === 'close' || e?.toString?.().includes('cancel')
    },
  },
}
</script>

<style scoped>
.remote-files-head {
  display: block;
  flex: 0 0 auto;
  margin-bottom: 10px;
}

.remote-files-head-main {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 8px;
  width: 100%;
  min-width: 0;
}

.remote-breadcrumb-bar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 2px;
  min-height: 28px;
  padding: 0 2px;
}

.remote-breadcrumb-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: none;
  background: transparent;
  color: var(--muted-2);
  padding: 3px 6px;
  border-radius: 8px;
  cursor: pointer;
  font-size: 14px;
  line-height: 1.4;
}

.remote-breadcrumb-item:hover {
  background: rgba(148, 163, 184, 0.12);
  color: var(--text);
}

.remote-breadcrumb-item.active {
  color: var(--text);
  font-weight: 400;
  cursor: default;
}

.remote-breadcrumb-item:disabled {
  opacity: 1;
}

.remote-breadcrumb-sep {
  color: var(--muted-2);
  margin-right: 2px;
}

.remote-breadcrumb-empty {
  color: var(--muted-2);
  font-size: 13px;
}

.remote-mobile-panel-toggle {
  display: none;
}

.remote-files-toolbar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.remote-toolbar-group {
  display: inline-flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.remote-toolbar-spacer {
  flex: 1 1 auto;
  min-width: 12px;
}

.remote-toolbar-search {
  display: inline-flex;
  align-items: center;
  justify-content: flex-end;
  gap: 12px;
  flex: 0 0 auto;
  flex-wrap: nowrap;
  width: 430px;
  margin-left: auto;
}

.remote-toolbar-search-input {
  flex: 0 0 240px;
  width: 240px;
}

.remote-toolbar-search-input :deep(.el-input__wrapper) {
  min-height: 32px;
  height: 32px;
  border-radius: 10px;
}

.remote-recursive-control {
  display: inline-flex;
  align-items: center;
  justify-content: flex-end;
  gap: 6px;
  flex: 0 0 auto;
  height: 32px;
  min-height: 32px;
  color: var(--muted-2);
  font-size: 12px;
  line-height: 32px;
  white-space: nowrap;
}

.remote-recursive-label {
  display: inline-flex;
  align-items: center;
  height: 32px;
  line-height: 32px;
}

.remote-recursive-control :deep(.el-switch) {
  display: inline-flex;
  align-items: center;
  height: 32px;
}

.remote-toolbar-divider {
  width: 1px;
  height: 18px;
  flex: 0 0 auto;
  background: rgba(148, 163, 184, 0.25);
}

.remote-files-meta-row {
  flex: 0 0 auto;
  margin-bottom: 8px;
}

/* 按钮只微调，不改变布局逻辑 */
.remote-files-toolbar :deep(.el-button) {
  height: 32px;
  min-height: 32px;
  padding-inline: 12px;
  border-radius: 10px;
  margin: 0;
}

.remote-files-toolbar :deep(.el-button + .el-button) {
  margin-left: 0;
}

/* 桌面表格：只吃剩余高度，只内部滚动 */
:deep(.dialog-table-shell) {
  flex: 1 1 auto !important;
  min-height: 0 !important;
  height: auto !important;
  max-height: none !important;
  overflow: hidden !important;
}

:deep(.dialog-table-shell .el-table) {
  width: 100%;
  height: 100% !important;
}

:deep(.dialog-table-shell .el-table__inner-wrapper),
:deep(.dialog-table-shell .el-scrollbar),
:deep(.dialog-table-shell .el-scrollbar__wrap) {
  height: 100% !important;
}

:deep(.dialog-table-shell .el-scrollbar__wrap) {
  overflow-y: auto !important;
  overflow-x: auto !important;
}

:deep(.dialog-table-shell .el-table__body-wrapper) {
  overflow-y: auto !important;
}

:deep(.dialog-pagination-wrap) {
  flex: 0 0 auto;
}

/* 移动端卡片：默认隐藏，移动端显示 */
:deep(.mobile-file-list-shell),
:deep(.mobile-file-list) {
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

.mobile-file-main {
  min-width: 0;
  flex: 1;
}

.mobile-file-name {
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

.mobile-file-meta-item-wide {
  grid-column: 1 / -1;
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


/*mobile file actions*/
.mobile-file-actions {
  margin-top: 12px;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  align-items: stretch;
}

.mobile-file-action-item {
  min-width: 0;
}

/* 如果动作数是奇数，最后一个独占整行 */
.mobile-file-actions > .mobile-file-action-item:last-child:nth-child(odd) {
  grid-column: 1 / -1;
}

.mobile-file-actions :deep(.el-button),
.mobile-file-actions :deep(.table-action-link),
.mobile-file-actions :deep(.el-dropdown),
.mobile-file-actions :deep(.mobile-file-more) {
  width: 100%;
  min-width: 0;
  margin: 0;
}

.mobile-file-actions :deep(.el-button) {
  min-height: 32px;
  height: 32px;
  border-radius: 10px;
  padding-inline: 12px;
  justify-content: center;
}

.mobile-file-actions :deep(.el-dropdown) {
  display: block;
}

.mobile-file-actions :deep(.el-dropdown .el-button) {
  width: 100%;
}

@media (max-width: 640px) {
  .mobile-file-meta {
    grid-template-columns: 1fr;
  }

  .mobile-file-actions {
    gap: 6px;
  }
}


/* 移动端 breadcrumb 还原横向滚动 */
@media (max-width: 768px) {
  .remote-files-head,
  .remote-files-head-main {
    min-width: 0;
  }

  .remote-breadcrumb-bar {
    display: block;
    width: 100%;
    min-width: 0;
    min-height: 32px;
    padding: 2px 0 6px;
    overflow-x: auto;
    overflow-y: hidden;
    white-space: nowrap;
    text-align: left;
    -webkit-overflow-scrolling: touch;
    touch-action: pan-x;
    overscroll-behavior-x: contain;
    scrollbar-width: thin;
  }

  .remote-breadcrumb-bar::-webkit-scrollbar {
    height: 4px;
  }

  .remote-breadcrumb-item {
    display: inline-flex;
    vertical-align: middle;
    align-items: center;
    justify-content: flex-start;
    max-width: 72vw;
    min-width: 0;
    margin: 0 2px 0 0;
    padding: 4px 6px;
    text-align: left;
    white-space: nowrap;
  }

  .remote-breadcrumb-item > span:last-child {
    display: inline-block;
    min-width: 0;
    max-width: 100%;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    text-align: left;
  }

  .remote-breadcrumb-sep {
    flex: 0 0 auto;
    margin-right: 4px;
  }

  .remote-breadcrumb-empty {
    display: inline-block;
    white-space: nowrap;
    text-align: left;
  }

  .remote-mobile-panel-toggle {
    display: inline-flex;
    align-self: flex-start;
    width: auto;
    margin: 0;
  }

  .remote-mobile-panel-collapsed .remote-files-toolbar {
    display: none;
  }

  .remote-mobile-panel-collapsed :deep(.dialog-pagination-wrap) {
    display: none !important;
  }
}

@media (max-width: 960px) {
  .remote-toolbar-divider {
    display: none;
  }

  .remote-files-toolbar {
    gap: 6px 10px;
  }

  .remote-toolbar-spacer {
    display: none;
  }

  .remote-toolbar-search {
    width: 100%;
    min-width: 0;
    margin-left: 0;
    justify-content: flex-start;
  }

  .remote-toolbar-search-input {
    flex: 1 1 220px;
    width: auto;
    min-width: 0;
  }
}

@media (max-width: 768px), (max-height: 720px) {
  :deep(.dialog-table-shell) {
    display: none !important;
  }

  :deep(.mobile-file-list-shell) {
    display: flex !important;
    flex: 1 1 auto !important;
    min-height: 0 !important;
    overflow: hidden !important;
  }

  :deep(.mobile-file-list) {
    display: block !important;
    flex: 1 1 auto !important;
    min-height: 0 !important;
    overflow: hidden !important;
  }
}


</style>


<style>
/* RemoteFilesDialog: 强制固定弹窗高度，禁止被内容撑开 */
.remote-files-overlay .el-overlay-dialog {
  overflow: hidden !important;
}

.remote-files-overlay .el-dialog {
  height: 78vh !important;
  max-height: 78vh !important;
  margin-top: 4vh !important;
  display: flex !important;
  flex-direction: column !important;
  overflow: hidden !important;
}

.remote-files-overlay .el-dialog__header {
  flex: 0 0 auto !important;
}

.remote-files-overlay .el-dialog__body {
  flex: 1 1 auto !important;
  min-height: 0 !important;
  overflow: hidden !important;
  padding-top: 12px !important;
  padding-bottom: 12px !important;
}

.remote-files-overlay .fixed-dialog-body {
  height: 100% !important;
  min-height: 0 !important;
  overflow: hidden !important;
  display: flex !important;
  flex-direction: column !important;
}

/* 桌面：文件表格滚，不许撑 dialog */
.remote-files-overlay .dialog-table-shell {
  flex: 1 1 auto !important;
  min-height: 0 !important;
  height: auto !important;
  max-height: none !important;
  overflow: hidden !important;
}

.remote-files-overlay .dialog-table-shell .el-table,
.remote-files-overlay .dialog-table-shell .el-table__inner-wrapper,
.remote-files-overlay .dialog-table-shell .el-scrollbar,
.remote-files-overlay .dialog-table-shell .el-scrollbar__wrap {
  height: 100% !important;
}

.remote-files-overlay .dialog-table-shell .el-scrollbar__wrap {
  overflow-y: auto !important;
  overflow-x: auto !important;
}

/* 移动端：恢复卡片列表，不显示表格 */
@media (max-width: 768px), (max-height: 720px) {
  .remote-files-overlay .el-dialog {
    width: 100vw !important;
    max-width: 100vw !important;
    height: 100dvh !important;
    max-height: 100dvh !important;
    margin: 0 !important;
    border-radius: 0 !important;
  }

  .remote-files-overlay .dialog-table-shell {
    display: none !important;
  }

  .remote-files-overlay .mobile-file-list-shell {
    display: flex !important;
    flex: 1 1 auto !important;
    min-height: 0 !important;
    overflow: hidden !important;
  }

  .remote-files-overlay .mobile-file-list {
    display: block !important;
    flex: 1 1 auto !important;
    min-height: 0 !important;
    overflow: hidden !important;
  }

  .remote-files-overlay .mobile-file-grid {
    height: 100% !important;
    min-height: 0 !important;
    overflow-y: auto !important;
    /*给移动端文件列表底部加 padding*/
    /*padding-bottom: calc(96px + env(safe-area-inset-bottom)) !important;
    box-sizing: border-box !important;*/
  }
}
</style>