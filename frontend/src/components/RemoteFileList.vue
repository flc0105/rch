<template>
      <div class="dialog-table-shell">
        <RemoteDirectoryTable
          ref="remoteFilesTableRef"
          :entries="displayRemoteFilesEntries"
          :loading="remoteFilesLoading"
          :empty-text="remoteFilesEmptyText"
          :name-width="320"
          :type-width="110"
          :size-width="120"
          @row-dblclick="handleRemoteRowDblClick"
          @selection-change="handleRemoteSelectionChange"
        >
          <template #selection>
            <el-table-column
                type="selection"
                width="52"
                align="center"
                :selectable="row => !row.is_parent_entry"
            />
          </template>
          <template #name-badges="{ row }">
                  <el-tag
                      v-if="!row.is_parent_entry && row.is_hidden"
                      size="small"
                      type="warning"
                  >
                    Hidden
                  </el-tag>
          </template>
          <template #after-name>
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
          </template>
          <template #after-size>
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
          </template>
          <template #actions>
            <el-table-column label="Actions" width="270" align="center" fixed="right">
              <template #default="{ row }">
                <div class="table-actions table-actions-links">
                  <template v-if="row.is_parent_entry">
                    <el-button
                        size="small"
                        link
                        type="primary"
                        @click="goToRemoteParent"
                        :icon="remoteActionIcon('open')"
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
                        :icon="remoteActionIcon('open')"
                    >
                      Open
                    </el-button>
  
                    <template v-if="!row.is_dir">
                      <el-button
                          size="small"
                          link
                          type="primary"
                          @click="previewRow(row)"
                          :icon="remoteActionIcon('preview')"
                      >
                        Preview
                      </el-button>
  
                      <el-button
                          size="small"
                          link
                          type="primary"
                          @click="downloadRemoteEntry(row)"
                          :icon="remoteActionIcon('download')"
                      >
                        Download
                      </el-button>
                    </template>
  
                    <el-dropdown
                        trigger="click"
                        @command="command => handleRemoteMoreAction(command, row)"
                    >
                      <el-button size="small" link type="primary" :icon="remoteActionIcon('more')">
                        More
                      </el-button>
  
                      <template #dropdown>
                        <el-dropdown-menu>
                          <el-dropdown-item command="rename" :icon="remoteActionIcon('rename')">Rename</el-dropdown-item>
                          <el-dropdown-item command="copy" :icon="remoteActionIcon('copy')">Copy</el-dropdown-item>
                          <el-dropdown-item command="cut" :icon="remoteActionIcon('cut')">Cut</el-dropdown-item>
                          <el-dropdown-item command="copy_to" :icon="remoteActionIcon('copy_to')">Copy To</el-dropdown-item>
                          <el-dropdown-item command="move_to" :icon="remoteActionIcon('move_to')">Move To</el-dropdown-item>
                          <el-dropdown-item command="copy_path" :icon="remoteActionIcon('copy_path')">Copy Path</el-dropdown-item>
                          <el-dropdown-item v-if="row.is_dir" command="set_cwd" :icon="remoteActionIcon('set_cwd')">Set as CWD</el-dropdown-item>
                          <el-dropdown-item v-if="row.is_dir" command="open_pty" :icon="remoteActionIcon('open_pty')">Open PTY Here</el-dropdown-item>
                          <el-dropdown-item v-if="isZipEntry(row)" command="extract" divided :disabled="remoteZipExtracting" :icon="remoteActionIcon('extract')">Extract Here</el-dropdown-item>
                          <el-dropdown-item command="delete" :icon="remoteActionIcon('delete')">Delete</el-dropdown-item>
                        </el-dropdown-menu>
                      </template>
                    </el-dropdown>
                  </template>
                </div>
              </template>
            </el-table-column>
          </template>
        </RemoteDirectoryTable>
      </div>
      <div class="mobile-file-list-shell">
        <div class="mobile-file-list" v-loading="remoteFilesLoading">
          <div
              v-if="!displayRemoteFilesEntries.length && !remoteFilesLoading"
              class="empty-state"
          >
            This folder is empty
          </div>

          <div
              v-else
              class="mobile-file-grid"
              :class="{ 'mobile-file-grid-list': remoteMobileViewMode === 'list' }"
              ref="remoteMobileFileGridRef"
          >
            <template v-if="remoteMobileViewMode === 'card'">
            <div
                v-for="row in displayRemoteFilesEntries"
                :key="`${row.is_parent_entry ? 'parent-' : ''}${row.path}`"
                class="mobile-file-card"
                style="position: relative;"
            >
              <div style="position:absolute; top:6px; right:12px; z-index:1;">
                <el-checkbox
                    :model-value="isRemoteEntrySelected(row)"
                    :disabled="row.is_parent_entry"
                    :aria-label="row.is_parent_entry ? 'Parent directory cannot be selected' : 'Select ' + row.name"
                    @change="toggleRemoteSelection(row)"
                />
              </div>

              <div class="mobile-file-card-top">
                <div class="mobile-file-icon">
                  <RemoteFileEntryIcon :entry="row" :size="20" />
                </div>

                <div class="mobile-file-main">
                  <div class="mobile-file-name" style="padding-right: 42px;">
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
                            :icon="remoteActionIcon('open')"
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
                              :icon="remoteActionIcon('open')"
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
                              :icon="remoteActionIcon('preview')"
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
                              :icon="remoteActionIcon('download')"
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
                          <el-button size="small" plain :icon="remoteActionIcon('more')">
                            More
                          </el-button>

                          <template #dropdown>
                            <el-dropdown-menu>
                              <el-dropdown-item command="rename" :icon="remoteActionIcon('rename')">Rename</el-dropdown-item>
                              <el-dropdown-item command="copy" :icon="remoteActionIcon('copy')">Copy</el-dropdown-item>
                              <el-dropdown-item command="cut" :icon="remoteActionIcon('cut')">Cut</el-dropdown-item>
                              <el-dropdown-item command="copy_to" :icon="remoteActionIcon('copy_to')">Copy To</el-dropdown-item>
                              <el-dropdown-item command="move_to" :icon="remoteActionIcon('move_to')">Move To</el-dropdown-item>
                              <el-dropdown-item command="copy_path" :icon="remoteActionIcon('copy_path')">Copy Path</el-dropdown-item>
                              <el-dropdown-item v-if="row.is_dir" command="set_cwd" :icon="remoteActionIcon('set_cwd')">Set as CWD</el-dropdown-item>
                        <el-dropdown-item v-if="row.is_dir" command="open_pty" :icon="remoteActionIcon('open_pty')">Open PTY Here</el-dropdown-item>
                              <el-dropdown-item v-if="isZipEntry(row)" command="extract" divided :disabled="remoteZipExtracting" :icon="remoteActionIcon('extract')">Extract Here</el-dropdown-item>
                              <el-dropdown-item command="delete" :icon="remoteActionIcon('delete')">Delete</el-dropdown-item>
                            </el-dropdown-menu>
                          </template>
                        </el-dropdown>
                      </div>
                    </template>
                  </div>
                </div>
              </div>
            </div>
            </template>
            <template v-else>
              <div
                  v-for="row in displayRemoteFilesEntries"
                  :key="`list-${row.is_parent_entry ? 'parent-' : ''}${row.path}`"
                  class="remote-mobile-file-row"
                  role="button"
                  tabindex="0"
                  @click="handleRemoteMobileListRowClick(row)"
                  @keydown.enter.prevent="handleRemoteMobileListRowClick(row)"
              >
                <div class="remote-mobile-file-checkbox" @click.stop>
                  <el-checkbox
                      :model-value="isRemoteEntrySelected(row)"
                      :disabled="row.is_parent_entry"
                      :aria-label="row.is_parent_entry ? 'Parent directory cannot be selected' : 'Select ' + row.name"
                      @change="toggleRemoteSelection(row)"
                  />
                </div>
                <span class="remote-mobile-file-icon" aria-hidden="true">
                  <RemoteFileEntryIcon :entry="row" :size="20" />
                </span>
                <div class="remote-mobile-file-row-main">
                  <div class="remote-mobile-file-row-name">
                    {{ row.is_parent_entry ? '..' : row.name }}
                  </div>
                  <div v-if="row.is_parent_entry || row.modified_at || !row.is_dir" class="remote-mobile-file-row-meta">
                    <template v-if="!row.is_dir">{{ formatBytes(row.size) }} · </template>{{ row.is_parent_entry ? 'Parent directory' : (row.modified_at || '-') }}
                  </div>
                </div>
                <div class="remote-mobile-file-row-actions" @click.stop>
                  <el-dropdown
                      trigger="click"
                      @command="command => handleRemoteMobileListAction(command, row)"
                  >
                    <button
                        type="button"
                        class="remote-mobile-file-more-button"
                        :aria-label="`Actions for ${row.name || 'parent directory'}`"
                        aria-haspopup="menu"
                    >
                      <EllipsisVertical :size="20" aria-hidden="true" />
                    </button>
                    <template #dropdown>
                      <el-dropdown-menu>
                        <el-dropdown-item v-if="row.is_parent_entry || row.is_dir" command="open" :icon="remoteActionIcon('open')">Open</el-dropdown-item>
                        <template v-if="!row.is_parent_entry && !row.is_dir">
                          <el-dropdown-item command="preview" :icon="remoteActionIcon('preview')">Preview</el-dropdown-item>
                          <el-dropdown-item command="download" :icon="remoteActionIcon('download')">Download</el-dropdown-item>
                        </template>
                        <el-dropdown-item v-if="!row.is_parent_entry" command="rename" divided :icon="remoteActionIcon('rename')">Rename</el-dropdown-item>
                        <el-dropdown-item v-if="!row.is_parent_entry" command="copy" :icon="remoteActionIcon('copy')">Copy</el-dropdown-item>
                        <el-dropdown-item v-if="!row.is_parent_entry" command="cut" :icon="remoteActionIcon('cut')">Cut</el-dropdown-item>
                        <el-dropdown-item v-if="!row.is_parent_entry" command="copy_to" :icon="remoteActionIcon('copy_to')">Copy To</el-dropdown-item>
                        <el-dropdown-item v-if="!row.is_parent_entry" command="move_to" :icon="remoteActionIcon('move_to')">Move To</el-dropdown-item>
                        <el-dropdown-item v-if="!row.is_parent_entry" command="copy_path" :icon="remoteActionIcon('copy_path')">Copy Path</el-dropdown-item>
                        <el-dropdown-item v-if="row.is_dir && !row.is_parent_entry" command="set_cwd" :icon="remoteActionIcon('set_cwd')">Set as CWD</el-dropdown-item>
                        <el-dropdown-item v-if="row.is_dir && !row.is_parent_entry" command="open_pty" :icon="remoteActionIcon('open_pty')">Open PTY Here</el-dropdown-item>
                        <el-dropdown-item v-if="isZipEntry(row)" command="extract" :disabled="remoteZipExtracting" :icon="remoteActionIcon('extract')">Extract Here</el-dropdown-item>
                        <el-dropdown-item v-if="!row.is_parent_entry" command="delete" :icon="remoteActionIcon('delete')">Delete</el-dropdown-item>
                      </el-dropdown-menu>
                    </template>
                  </el-dropdown>
                </div>
              </div>
            </template>
          </div>
        </div>
      </div>
</template>

<script>
import { remoteActionIcon } from '../utils/remoteFileIcons.js'
import RemoteFileEntryIcon from './RemoteFileEntryIcon.vue'
import { EllipsisVertical } from '@lucide/vue'
import RemoteDirectoryTable from './RemoteDirectoryTable.vue'
import { formatBytes as formatBytesValue } from '../utils/formatters.js'
import { isZipEntry } from '../utils/remotePaths.js'

export default {
  name: 'RemoteFileList',
  components: { RemoteFileEntryIcon, EllipsisVertical, RemoteDirectoryTable },
  props: {
    displayRemoteFilesEntries: { type: Array, required: true },
    remoteFilesLoading: { type: Boolean, required: true },
    remoteFilesEmptyText: { type: String, required: true },
    isRemoteSearchActive: { type: Boolean, required: true },
    remoteFilesCurrentPath: { type: String, required: true },
    remoteZipExtracting: { type: Boolean, required: true },
    remoteMobileViewMode: { type: String, required: true },
    remoteSelectedPaths: { type: Array, required: true },
  },
  emits: ['row-double-click', 'selection-change', 'up', 'open-directory', 'preview', 'download', 'row-command', 'toggle-selection', 'mobile-row-click', 'mobile-row-command'],
  methods: {
    remoteActionIcon,
    handleRemoteRowDblClick(...args) { this.$emit('row-double-click', ...args) },
    handleRemoteSelectionChange(...args) { this.$emit('selection-change', ...args) },
    goToRemoteParent(...args) { this.$emit('up', ...args) },
    enterRemoteDirectory(...args) { this.$emit('open-directory', ...args) },
    previewRow(...args) { this.$emit('preview', ...args) },
    downloadRemoteEntry(...args) { this.$emit('download', ...args) },
    handleRemoteMoreAction(...args) { this.$emit('row-command', ...args) },
    toggleRemoteSelection(...args) { this.$emit('toggle-selection', ...args) },
    handleRemoteMobileListRowClick(...args) { this.$emit('mobile-row-click', ...args) },
    handleRemoteMobileListAction(...args) { this.$emit('mobile-row-command', ...args) },
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
    isZipEntry,
    formatBytes(value) { return formatBytesValue(value) },
    isRemoteEntrySelected(row) { return !!(row && !row.is_parent_entry && row.path && this.remoteSelectedPaths.includes(row.path)) },
    clearSelection() { this.$refs.remoteFilesTableRef?.clearSelection() },
    toggleRowSelection(row, selected) { this.$refs.remoteFilesTableRef?.toggleRowSelection(row, selected) },
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
  },
}
</script>
