<template>
      <div class="dialog-head remote-files-head">
        <div class="dialog-head-left remote-files-head-main">
          <div class="remote-mobile-breadcrumb-row">
            <RemoteFileNavigation :items="remoteBreadcrumbItems" @navigate="goToRemoteBreadcrumb" />

            <el-dropdown
                trigger="click"
                class="remote-mobile-tools-dropdown"
                popper-class="remote-mobile-tools-popper"
                @command="handleRemoteMobileToolsCommand"
            >
              <button type="button" class="remote-mobile-tools-button" aria-label="Remote file actions" aria-haspopup="menu">
                <Ellipsis :size="19" aria-hidden="true" />
              </button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item disabled>Current Directory</el-dropdown-item>
                  <el-dropdown-item command="refresh" :icon="remoteActionIcon('refresh')">Refresh</el-dropdown-item>
                  <el-dropdown-item command="up" :disabled="!remoteFilesParentPath" :icon="remoteActionIcon('up')">Parent Directory</el-dropdown-item>
                  <el-dropdown-item command="new_folder" :icon="remoteActionIcon('new_folder')">New Folder</el-dropdown-item>
                  <el-dropdown-item command="upload" :disabled="remoteUploadLoading || dragUploadLoading" :icon="remoteActionIcon('upload')">Upload</el-dropdown-item>
                  <el-dropdown-item command="drag_upload" :disabled="remoteUploadLoading || dragUploadLoading || !remoteFilesCurrentPath" :icon="remoteActionIcon('drag_upload')">Drag Upload</el-dropdown-item>
                  <el-dropdown-item command="set_cwd" :disabled="!remoteFilesCurrentPath" :icon="remoteActionIcon('set_cwd')">Set as CWD</el-dropdown-item>
                  <el-dropdown-item command="open_pty" :disabled="!remoteFilesCurrentPath" :icon="remoteActionIcon('open_pty')">Open PTY Here</el-dropdown-item>
                  <el-dropdown-item command="toggle_pin" :icon="remoteActionIcon(remotePinButtonText === 'Unpin' ? 'unpin' : 'toggle_pin')">{{ remotePinButtonText }}</el-dropdown-item>

                  <el-dropdown-item divided disabled>Quick Jump</el-dropdown-item>
                  <RemoteSystemJumpItems :disabled="quickJumpLoading" />
                  <el-dropdown-item v-if="hasPinnedQuickJumps" disabled>Pinned Paths</el-dropdown-item>
                  <el-dropdown-item
                      v-for="item in remotePinnedJumpItems"
                      :key="`mobile-pinned-jump-${item.display_name}-${item.path}`"
                      :command="{ type: 'pinned_jump', display_name: item.display_name, path: item.path }"
                      :disabled="remotePinnedJumpLoading"
                      :icon="remoteActionIcon('pinned_jump')"
                  >
                    {{ item.display_name }}
                  </el-dropdown-item>
                  <el-dropdown-item command="input_navigate" :icon="remoteActionIcon('input_navigate')">Go to Folder</el-dropdown-item>

                  <el-dropdown-item divided disabled>Batch &amp; Clipboard</el-dropdown-item>
                  <el-dropdown-item command="download_selected" :disabled="!hasRemoteSelection || remoteZipDownloading" :icon="remoteActionIcon('download_selected')">
                    Download Selected{{ remoteSelectedPaths.length ? ' (' + remoteSelectedPaths.length + ')' : '' }}
                  </el-dropdown-item>
                  <el-dropdown-item command="delete_selected" :disabled="!hasRemoteSelection" :icon="remoteActionIcon('delete_selected')">
                    Delete Selected{{ remoteSelectedPaths.length ? ' (' + remoteSelectedPaths.length + ')' : '' }}
                  </el-dropdown-item>
                  <el-dropdown-item command="copy" :disabled="!hasRemoteSelection" :icon="remoteActionIcon('copy')">Copy Selected</el-dropdown-item>
                  <el-dropdown-item command="cut" :disabled="!hasRemoteSelection" :icon="remoteActionIcon('cut')">Cut Selected</el-dropdown-item>
                  <el-dropdown-item command="copy_to_selected" :disabled="!hasRemoteSelection" :icon="remoteActionIcon('copy_to_selected')">Copy To</el-dropdown-item>
                  <el-dropdown-item command="move_to_selected" :disabled="!hasRemoteSelection" :icon="remoteActionIcon('move_to_selected')">Move To</el-dropdown-item>
                  <el-dropdown-item command="create_zip" :disabled="!hasRemoteSelection || remoteZipCreating" :icon="remoteActionIcon('create_zip')">Create ZIP</el-dropdown-item>
                  <el-dropdown-item command="paste" :disabled="!hasRemoteClipboard" :icon="remoteActionIcon('paste')">Paste</el-dropdown-item>
                  <el-dropdown-item command="clear_clipboard" :disabled="!hasRemoteClipboard" :icon="remoteActionIcon('clear_clipboard')">Clear Clipboard</el-dropdown-item>
                  <el-dropdown-item
                      v-if="!isRemoteCurrentPageAllSelected"
                      command="toggle_select_all"
                      :disabled="!visibleRemoteSelectablePaths.length"
                      :icon="remoteActionIcon('toggle_select_all')"
                  >
                    Select All
                  </el-dropdown-item>
                  <el-dropdown-item command="clear_selection" :disabled="!hasRemoteSelection" :icon="remoteActionIcon('clear_selection')">Clear Selection</el-dropdown-item>

                  <el-dropdown-item divided disabled>View</el-dropdown-item>
                  <el-dropdown-item command="view_card" :icon="remoteActionIcon('view_card')"><Check v-if="remoteMobileViewMode === 'card'" :size="14" class="remote-menu-check" aria-hidden="true" />Card</el-dropdown-item>
                  <el-dropdown-item command="view_list" :icon="remoteActionIcon('view_list')"><Check v-if="remoteMobileViewMode === 'list'" :size="14" class="remote-menu-check" aria-hidden="true" />List</el-dropdown-item>
                  <el-dropdown-item command="toggle_recursive" :icon="remoteActionIcon('toggle_recursive')">
                    <Check v-if="remoteSearchRecursive" :size="14" class="remote-menu-check" aria-hidden="true" />Recursive Search
                  </el-dropdown-item>
                  <el-dropdown-item command="toggle_hidden" :icon="remoteActionIcon(showHiddenFiles ? 'hide_hidden' : 'toggle_hidden')">{{ showHiddenFiles ? 'Hide Hidden' : 'Show Hidden' }}</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>

          <div class="remote-mobile-search-row">
            <el-input
                v-model="remoteSearchKeywordModel"
                clearable
                size="small"
                class="remote-mobile-search-input"
                placeholder="Search files and folders"
                aria-label="Search remote files"
                @input="scheduleRemoteSearch"
                @clear="applyRemoteSearch"
                @keyup.enter="applyRemoteSearch">
                  <template #prefix><Search :size="14" aria-hidden="true" /></template>
                </el-input>
          </div>

          <div class="remote-files-toolbar">
            <div class="remote-toolbar-group">
              <el-button size="small" @click="refreshRemoteDirectory" :icon="remoteActionIcon('refresh')">
                Refresh
              </el-button>

              <el-button
                  size="small"
                  :disabled="!remoteFilesParentPath"
                  @click="goToRemoteParent"
                  :icon="remoteActionIcon('up')"
              >
                Up
              </el-button>

              <el-dropdown
                  :loading="quickJumpLoading || remotePinnedJumpLoading"
                  @command="jumpToPath"
              >
                <el-button size="small" :icon="remoteActionIcon('quick_jump')">
                  Quick Jump
                </el-button>

                <template #dropdown>
                  <el-dropdown-menu>
                    <RemoteSystemJumpItems />

                    <el-dropdown-item
                        v-for="(item, index) in remotePinnedJumpItems"
                        :key="`pinned-jump-${item.display_name}-${item.path}`"
                        :divided="index === 0"
                        :command="{
                        type: 'pinned_jump',
                        display_name: item.display_name,
                        path: item.path,
                      }"
                      :icon="remoteActionIcon('pinned_jump')"
                  >
                      {{ item.display_name }}
                    </el-dropdown-item>

                    <el-dropdown-item divided command="input_navigate" :icon="remoteActionIcon('input_navigate')">
                      Go to Folder
                    </el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </div>

            <span class="remote-toolbar-divider"></span>

            <div class="remote-toolbar-group">
              <el-button size="small" @click="createRemoteDirectory" :icon="remoteActionIcon('new_folder')">
                New Folder
              </el-button>

              <el-button
                  size="small"
                  :loading="remoteUploadLoading"
                  :disabled="dragUploadLoading"
                  @click="triggerRemoteUpload"
                  :icon="remoteActionIcon('upload')"
              >
                Upload
              </el-button>

              <el-button
                  size="small"
                  type="primary"
                  :disabled="!hasRemoteSelection"
                  :loading="remoteZipDownloading"
                  @click="downloadSelectedRemoteEntries"
                  :icon="remoteActionIcon('download')"
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
                  :icon="remoteActionIcon('delete')"
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
                <el-button size="small" :icon="remoteActionIcon('more')">More</el-button>

                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item command="drag_upload" :disabled="remoteUploadLoading || dragUploadLoading || !remoteFilesCurrentPath" :icon="remoteActionIcon('drag_upload')">Drag Upload</el-dropdown-item>
                    <el-dropdown-item command="set_cwd" :disabled="!remoteFilesCurrentPath" :icon="remoteActionIcon('set_cwd')">Set as CWD</el-dropdown-item>
                  <el-dropdown-item command="open_pty" :disabled="!remoteFilesCurrentPath" :icon="remoteActionIcon('open_pty')">Open PTY Here</el-dropdown-item>
                    <el-dropdown-item command="toggle_pin" :icon="remoteActionIcon(remotePinButtonText === 'Unpin' ? 'unpin' : 'toggle_pin')">
                      {{ remotePinButtonText }}
                    </el-dropdown-item>

                    <el-dropdown-item
                        command="copy"
                        :disabled="!hasRemoteSelection"
                        divided
                        :icon="remoteActionIcon('copy')"
                    >
                      Copy
                      <span v-if="remoteSelectedPaths.length">
                        ({{ remoteSelectedPaths.length }})
                      </span>
                    </el-dropdown-item>

                    <el-dropdown-item
                        command="cut"
                        :disabled="!hasRemoteSelection"
                        :icon="remoteActionIcon('cut')"
                    >
                      Cut
                      <span v-if="remoteSelectedPaths.length">
                        ({{ remoteSelectedPaths.length }})
                      </span>
                    </el-dropdown-item>

                    <el-dropdown-item command="copy_to_selected" :disabled="!hasRemoteSelection" :icon="remoteActionIcon('copy_to_selected')">Copy To</el-dropdown-item>
                    <el-dropdown-item command="move_to_selected" :disabled="!hasRemoteSelection" :icon="remoteActionIcon('move_to_selected')">Move To</el-dropdown-item>

                    <el-dropdown-item
                        command="create_zip"
                        :disabled="!hasRemoteSelection || remoteZipCreating"
                        :icon="remoteActionIcon('create_zip')"
                    >
                      Create ZIP
                      <span v-if="remoteSelectedPaths.length">
                        ({{ remoteSelectedPaths.length }})
                      </span>
                    </el-dropdown-item>

                    <el-dropdown-item
                        command="paste"
                        :disabled="!hasRemoteClipboard"
                        :icon="remoteActionIcon('paste')"
                    >
                      Paste
                      <span v-if="hasRemoteClipboard">
                        ({{ remoteClipboardPaths.length }})
                      </span>
                    </el-dropdown-item>

                    <el-dropdown-item
                        command="clear_clipboard"
                        :disabled="!hasRemoteClipboard"
                        :icon="remoteActionIcon('clear_clipboard')"
                    >
                      Clear Clipboard
                    </el-dropdown-item>

                    <el-dropdown-item
                        v-if="!isRemoteCurrentPageAllSelected"
                        command="toggle_select_all"
                        divided
                        :disabled="!visibleRemoteSelectablePaths.length"
                        :icon="remoteActionIcon('toggle_select_all')"
                    >
                      Select All
                    </el-dropdown-item>

                    <el-dropdown-item
                        :divided="isRemoteCurrentPageAllSelected"
                        command="clear_selection"
                        :disabled="!hasRemoteSelection"
                        :icon="remoteActionIcon('clear_selection')"
                    >
                      Clear Selection
                    </el-dropdown-item>

                    <el-dropdown-item command="toggle_hidden" :icon="remoteActionIcon(showHiddenFiles ? 'hide_hidden' : 'toggle_hidden')">
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
                    v-model="remoteSearchRecursiveModel"
                    size="small"
                    @change="handleRemoteSearchRecursiveChange"
                />
              </div>
              <el-input
                  v-model="remoteSearchKeywordModel"
                  clearable
                  size="small"
                  class="remote-toolbar-search-input"
                  placeholder="Search"
                  @input="scheduleRemoteSearch"
                  @clear="applyRemoteSearch"
                  @keyup.enter="applyRemoteSearch">
                  <template #prefix><Search :size="14" aria-hidden="true" /></template>
                </el-input>

            </div>
          </div>
        </div>
      </div>
</template>

<script>
import { remoteActionIcon } from '../utils/remoteFileIcons.js'
import RemoteSystemJumpItems from './RemoteSystemJumpItems.vue'
import RemoteFileNavigation from './RemoteFileNavigation.vue'
import { Ellipsis, Search, Check } from '@lucide/vue'
export default {
  name: 'RemoteFilesToolbar',
  props: {
    remoteBreadcrumbItems: { type: Array, required: true },
    remoteFilesParentPath: { type: String, required: true },
    remoteFilesCurrentPath: { type: String, required: true },
    remoteUploadLoading: { type: Boolean, required: true },
    dragUploadLoading: { type: Boolean, required: true },
    remotePinButtonText: { type: String, required: true },
    quickJumpLoading: { type: Boolean, required: true },
    remotePinnedJumpLoading: { type: Boolean, required: true },
    hasPinnedQuickJumps: { type: Boolean, required: true },
    remotePinnedJumpItems: { type: Array, required: true },
    hasRemoteSelection: { type: Boolean, required: true },
    remoteZipDownloading: { type: Boolean, required: true },
    remoteSelectedPaths: { type: Array, required: true },
    remoteZipCreating: { type: Boolean, required: true },
    hasRemoteClipboard: { type: Boolean, required: true },
    isRemoteCurrentPageAllSelected: { type: Boolean, required: true },
    visibleRemoteSelectablePaths: { type: Array, required: true },
    remoteMobileViewMode: { type: String, required: true },
    remoteSearchRecursive: { type: Boolean, required: true },
    showHiddenFiles: { type: Boolean, required: true },
    remoteSearchKeyword: { type: String, required: true },
    remoteClipboardPaths: { type: Array, required: true },
  },
  emits: ['navigate-breadcrumb', 'mobile-command', 'schedule-search', 'apply-search', 'refresh', 'up', 'quick-jump', 'new-folder', 'upload', 'download', 'delete', 'more-command', 'recursive-change', 'update:remoteSearchKeyword', 'update:remoteSearchRecursive'],
  computed: {
    remoteSearchKeywordModel: { get() { return this.remoteSearchKeyword }, set(value) { this.$emit('update:remoteSearchKeyword', value) } },
    remoteSearchRecursiveModel: { get() { return this.remoteSearchRecursive }, set(value) { this.$emit('update:remoteSearchRecursive', value) } },
  },
  methods: {
    remoteActionIcon,
    goToRemoteBreadcrumb(...args) { this.$emit('navigate-breadcrumb', ...args) },
    handleRemoteMobileToolsCommand(...args) { this.$emit('mobile-command', ...args) },
    scheduleRemoteSearch(...args) { this.$emit('schedule-search', ...args) },
    applyRemoteSearch(...args) { this.$emit('apply-search', ...args) },
    refreshRemoteDirectory(...args) { this.$emit('refresh', ...args) },
    goToRemoteParent(...args) { this.$emit('up', ...args) },
    jumpToPath(...args) { this.$emit('quick-jump', ...args) },
    createRemoteDirectory(...args) { this.$emit('new-folder', ...args) },
    triggerRemoteUpload(...args) { this.$emit('upload', ...args) },
    downloadSelectedRemoteEntries(...args) { this.$emit('download', ...args) },
    deleteSelectedRemoteEntries(...args) { this.$emit('delete', ...args) },
    handleRemoteToolbarMoreCommand(...args) { this.$emit('more-command', ...args) },
    handleRemoteSearchRecursiveChange(...args) { this.$emit('recursive-change', ...args) },
  },
  components: { RemoteSystemJumpItems, RemoteFileNavigation, Ellipsis, Search, Check },
}
</script>
