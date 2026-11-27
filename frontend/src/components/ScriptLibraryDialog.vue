<template>
  <el-dialog
    v-model="visible"
    title="Script Library"
    width="1180px"
    top="6vh"
    class="fixed-dialog script-library-dialog"
    modal-class="script-library-overlay"
    @closed="handleClosed"
  >
    <div
      class="fixed-dialog-body script-library-body"
      v-loading="loading"
    >
      <div class="script-library-toolbar">
        <div class="script-library-toolbar-left">
          <el-button
            size="small"
            class="toolbar-btn"
            type="primary"
            plain
            @click="createRemoteScriptPrompt"
          >
            <Plus class="script-library-action-icon" :size="14" aria-hidden="true" />
            New
          </el-button>

          <el-button
            size="small"
            class="toolbar-btn"
            :loading="uploadLoading"
            @click="triggerScriptUpload"
          >
            <Upload class="script-library-action-icon" :size="14" aria-hidden="true" />
            Upload
          </el-button>

          <el-button
            size="small"
            class="toolbar-btn"
            @click="createRemoteScriptFolderPrompt"
          >
            <FolderPlus class="script-library-action-icon" :size="14" aria-hidden="true" />
            New Folder
          </el-button>

          <el-button
            size="small"
            class="toolbar-btn"
            :disabled="!selectedDirectory"
            @click="renameRemoteScriptFolder"
          >
            <Pencil class="script-library-action-icon" :size="14" aria-hidden="true" />
            Rename Folder
          </el-button>

          <el-button
            size="small"
            class="toolbar-btn"
            type="danger"
            plain
            :disabled="!selectedDirectory"
            @click="deleteRemoteScriptFolder"
          >
            <Trash2 class="script-library-action-icon" :size="14" aria-hidden="true" />
            Delete Folder
          </el-button>

          <el-button
            size="small"
            class="toolbar-btn"
            :loading="loading"
            @click="loadScriptCatalog"
          >
            <RefreshCw class="script-library-action-icon" :size="14" aria-hidden="true" />
            Refresh
          </el-button>

          <input
            ref="serverScriptUploadInputRef"
            type="file"
            accept=".py,text/x-python"
            class="hidden-file-input"
            @change="handleServerScriptUpload"
          />
        </div>

        <div class="script-library-toolbar-right">
<!--          <span class="script-library-upload-target-text mono">-->
<!--            Upload Target: {{ selectedDirectory || 'root' }}-->
<!--          </span>-->

          <el-input
            v-model="scriptSearchText"
            size="small"
            clearable
            class="script-library-filter-control script-library-search"
            placeholder="Search scripts"
          >
            <template #prefix>
              <Search :size="15" aria-hidden="true" />
            </template>
          </el-input>
        </div>
      </div>

      <div class="script-library-shell" :class="{ 'script-library-tree-collapsed': !scriptTreeVisible }">
        <div v-show="scriptTreeVisible" class="script-library-tree panel-lite">
          <div class="background-jobs-section-title script-library-tree-title">
            <Folder :size="16" aria-hidden="true" />
            Folders
          </div>

          <div class="script-library-pane-scroll">
            <el-tree
              :key="scriptTreeRenderKey"
              ref="scriptDirectoryTreeRef"
              :data="scriptDirectoryTreeData"
              node-key="key"
              :default-expand-all="false"
              :default-expanded-keys="scriptTreeExpandedKeys"
              :current-node-key="selectedScriptDirectoryTreeKey"
              highlight-current
              :expand-on-click-node="true"
              class="script-library-tree-view"
              @node-click="handleScriptTreeNodeClick"
              @node-expand="handleScriptTreeNodeExpand"
              @node-collapse="handleScriptTreeNodeCollapse"
            >
              <template #default="{ data }">
                <span class="script-tree-node">
                  <FolderOpen v-if="data.key === selectedScriptDirectoryTreeKey" class="script-tree-icon" :size="16" aria-hidden="true" />
                  <Folder v-else class="script-tree-icon" :size="16" aria-hidden="true" />
                  <span class="script-tree-node-label">
                    {{ data.label }}
                  </span>
                </span>
              </template>
            </el-tree>
          </div>
        </div>

        <div class="script-library-directory panel-lite">
          <div class="script-library-directory-top">
            <button
              type="button"
              class="script-library-tree-toggle"
              :class="{ 'is-open': scriptTreeVisible }"
              :aria-expanded="scriptTreeVisible"
              :aria-label="scriptTreeVisible ? 'Hide folder tree' : 'Show folder tree'"
              :title="scriptTreeVisible ? 'Hide folder tree' : 'Show folder tree'"
              @click="scriptTreeVisible = !scriptTreeVisible"
            >
              <PanelLeftClose v-if="scriptTreeVisible" :size="17" aria-hidden="true" />
              <PanelLeftOpen v-else :size="17" aria-hidden="true" />
              <span>{{ scriptTreeVisible ? 'Hide tree' : 'Show tree' }}</span>
            </button>
            <div class="script-library-directory-title-block">
              <nav ref="scriptBreadcrumb" class="script-library-breadcrumb" aria-label="Script directory">
                <template v-for="(crumb, index) in scriptDirectoryBreadcrumb" :key="crumb.path">
                  <ChevronRight v-if="index" :size="14" class="script-library-breadcrumb-separator" aria-hidden="true" />
                  <button
                    type="button"
                    class="script-library-breadcrumb-item"
                    :class="{ 'is-current': crumb.path === selectedDirectory }"
                    :aria-current="crumb.path === selectedDirectory ? 'location' : undefined"
                    :disabled="crumb.path === selectedDirectory"
                    :title="crumb.path || 'root'"
                    @click="navigateScriptDirectory(crumb.path)"
                  >
                    <Folder v-if="!index" :size="15" aria-hidden="true" />
                    <span>{{ crumb.label }}</span>
                  </button>
                </template>
              </nav>
            </div>
          </div>

          <div ref="scriptDirectoryPane" class="script-library-pane-scroll">
            <div v-if="!hasScriptSearch && (selectedDirectory || currentScriptDirectoryFolders.length)" class="script-library-folder-list">
              <button
                v-if="selectedDirectory"
                type="button"
                class="script-library-folder-row script-library-parent-row"
                @click="navigateScriptDirectory(getParentScriptDirectory(selectedDirectory))"
              >
                <ArrowUp :size="17" aria-hidden="true" />
                <span class="script-library-folder-name">Up one level</span>
              </button>
              <button
                v-for="folder in currentScriptDirectoryFolders"
                :key="folder.key"
                type="button"
                class="script-library-folder-row"
                :title="folder.path"
                @click="navigateScriptDirectory(folder.path)"
              >
                <span class="script-library-card-main">
                  <span class="script-library-card-icon-tile"><Folder :size="19" aria-hidden="true" /></span>
                  <span class="script-library-card-heading">
                    <span class="script-library-card-title">{{ folder.label }}</span>
                  </span>
                  <span class="script-library-card-description">{{ folder.scriptCount }} {{ folder.scriptCount === 1 ? 'script' : 'scripts' }}</span>
                </span>
                <span class="script-library-card-actions script-library-folder-enter">
                  Open <ChevronRight :size="16" aria-hidden="true" />
                </span>
              </button>
            </div>
            <div
              v-if="filteredCurrentScriptDirectoryItems.length"
              class="script-library-card-list script-library-card-list-single"
            >
              <div
                v-for="item in filteredCurrentScriptDirectoryItems"
                :key="item.script_name"
                class="script-library-card"
              >
                <div class="script-library-card-main">
                  <span class="script-library-card-icon-tile">
                    <FileCode2 class="script-library-card-icon" :size="19" aria-hidden="true" />
                  </span>
                  <div class="script-library-card-heading">
                    <div
                      class="script-library-card-title"
                      :title="[item.display_name, item.path || item.script_name].filter(Boolean).join(' — ')"
                    >
                      {{ item.display_name || item.script_name }}
                    </div>
                    <div class="script-tags script-library-card-tags">
                      <el-tag
                        size="small"
                        :type="isScriptSupportedForCurrentConnection(item) ? 'info' : 'danger'"
                        :title="formatScriptPlatformLabel(item)"
                      >
                        {{ formatScriptPlatformLabel(item) }}
                      </el-tag>

                      <el-tag
                        v-if="scriptHasParams(item)"
                        size="small"
                        type="warning"
                      >
                        <SlidersHorizontal class="script-library-tag-icon" :size="12" aria-hidden="true" />
                        Params
                      </el-tag>
                    </div>
                  </div>

                  <div
                    class="script-library-card-description"
                    :title="item.description || ''"
                  >
                    {{ item.description || 'No description' }}
                  </div>
                </div>

                <div class="script-library-card-actions">
                  <el-button
                    size="small"
                    type="primary"
                    plain
                    :disabled="!isScriptSupportedForCurrentConnection(item)"
                    @click="openScriptRunDialog(item)"
                  >
                    <Play class="script-library-action-icon" :size="14" aria-hidden="true" />
                    Run
                  </el-button>

                  <el-button
                    size="small"
                    plain
                    @click="openRemoteScriptEditor(item.script_name)"
                  >
                    <Pencil class="script-library-action-icon" :size="14" aria-hidden="true" />
                    Edit
                  </el-button>

                  <el-dropdown
                    trigger="click"
                    @command="handleScriptMoreCommand(item, $event)"
                  >
                    <el-button
                      size="small"
                      plain
                    >
                      <Ellipsis class="script-library-action-icon" :size="14" aria-hidden="true" />
                      More
                    </el-button>

                    <template #dropdown>
                      <el-dropdown-menu>
                        <el-dropdown-item command="rename">
                          <Pencil class="script-library-action-icon" :size="14" aria-hidden="true" />
                          Rename
                        </el-dropdown-item>

                        <el-dropdown-item command="delete">
                          <Trash2 class="script-library-action-icon" :size="14" aria-hidden="true" />
                          Delete
                        </el-dropdown-item>
                      </el-dropdown-menu>
                    </template>
                  </el-dropdown>
                </div>
              </div>
            </div>

            <div
              v-else-if="hasScriptSearch || !currentScriptDirectoryFolders.length"
              class="empty-state script-library-empty"
            >
              {{ hasScriptSearch ? 'No matching scripts' : 'No scripts in this folder' }}
            </div>
          </div>
        </div>
      </div>
    </div>
  </el-dialog>

  <ScriptRunDialog
    ref="scriptRunDialogRef"
    v-model:visible="scriptRunDialogVisible"
    :item="pendingRunScriptItem"
    :param-specs="pendingRunScriptParamSpecs"
    :param-form="scriptParamForm"
    :mode-options="scriptModeOptions"
    :run-modes="scriptRunModes"
    :modes-loading="scriptModesLoading"
    :mode-error="scriptModesError"
    @update-mode="updateScriptMode"
    :machine-id="currentConnection?.machine_id || ''"
    :submitting="scriptRunSubmitting"
    :selected-id="selectedId"
    :get-tab-scoped-headers="getTabScopedHeaders"
    :is-script-supported-for-current-connection="isScriptSupportedForCurrentConnection"
    :format-script-platform-label="formatScriptPlatformLabel"
    @update-param="updateScriptParam"
    @apply-param-values="applyScriptParamValues"
    @append-output="forwardAppendOutput"
    @set-active-task="forwardSetActiveTask"
    @upload-started="$emit('upload-started', $event)"
    @cancel="closeScriptRunDialog"
    @confirm="confirmRunScript"
  />

  <el-dialog
    v-model="resultVisible"
    :title="activeRun.displayName || 'Script Result'"
    width="760px"
    class="rch-result-detail-fullscreen"
    append-to-body
  >
    <div class="script-result-meta">
      <el-tag :type="resultStatusType" size="small">
        {{ activeRun.status || 'Running' }}
      </el-tag>
      <code class="script-result-path" :title="activeRun.scriptPath">{{ activeRun.scriptPath }}</code>
      <el-button v-if="resultJsonText" size="small" class="script-result-json-button" @click="viewResultJson">View JSON</el-button>
    </div>
    <pre class="script-result-output">{{ activeRun.output || (activeRun.complete ? '(no output)' : 'Running…') }}</pre>
    <template #footer>
      <el-button v-if="!activeRun.complete && activeRun.cancelSupported" type="danger" :disabled="!activeRun.taskId || activeRun.cancelSending" :loading="activeRun.cancelSending" @click="cancelScriptRun">Cancel</el-button>
      <el-button :disabled="!activeRun.output" @click="copyResult">Copy</el-button>
      <el-button @click="resultVisible = false">Close</el-button>
    </template>
  </el-dialog>
</template>

<script>
import { cancelTask } from '../api/tasksApi.js'
import { createTerminalOperation, operationHeaders } from '../utils/terminalOperation.js'
import { ElMessage, ElMessageBox } from 'element-plus'
import { FileCode2, Plus, Upload, FolderPlus, Pencil, Trash2, RefreshCw, Play, Ellipsis, Search, Folder, FolderOpen, SlidersHorizontal, ArrowUp, ChevronRight, PanelLeftClose, PanelLeftOpen } from '@lucide/vue'
import {
  getScriptCatalog, getScriptRunOptions, runLibraryScript, createScriptFolder, renameScriptFolder,
  deleteScriptFolder, renameLibraryScript, uploadLibraryScript, deleteLibraryScript,
} from '../api/scriptLibraryApi.js'
import ScriptRunDialog from './ScriptRunDialog.vue'
import { findJsonOutput, selectJsonViewResult } from '../utils/terminalJson.js'
import { TERMINAL_RUN_SCRIPT_PREFIX } from '../composables/terminalMarkers.js'
import { cloneParamValue, normalizeParamSpecs, normalizeParamType } from '../utils/parameterSchema.js'

function emptyScriptRun() {
  return {
    runId: '',
    clientId: '',
    displayName: '',
    scriptPath: '',
    operation: null,
    output: '',
    jsonText: '',
    view: null,
    outputChunks: 0,
    status: '',
    complete: false,
    success: false,
    taskId: '',
    cancelSupported: false,
    cancelSending: false,
  }
}

export default {
  name: 'ScriptLibraryDialog',

  components: {
    FileCode2, Plus, Upload, FolderPlus, Pencil, Trash2, RefreshCw, Play, Ellipsis, Search, Folder, FolderOpen, SlidersHorizontal, ArrowUp, ChevronRight, PanelLeftClose, PanelLeftOpen,
    ScriptRunDialog,
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

    getTabScopedHeaders: {
      type: Function,
      default: null,
    },

    openScriptEditor: {
      type: Function,
      default: null,
    },

    openNewScriptEditor: {
      type: Function,
      default: null,
    },
  },

  emits: [
    'append-output',
    'set-active-task',
    'upload-started',
    'open-json',
  ],

  data() {
    return {
      visible: false,
      loading: false,
      uploadLoading: false,
      scriptCatalogItems: [],
      scriptCatalogDirectories: [],
      selectedDirectory: '',
      scriptSearchText: '',
      scriptTreeVisible: true,
      scriptTreeRenderKey: 0,
      scriptTreeExpandedKeys: [],
      scriptDirectorySelectionContextKey: '',
      scriptRunDialogVisible: false,
      scriptRunSubmitting: false,
      scriptModeOptions: {},
      scriptRunModes: {},
      scriptModesLoading: false,
      scriptModesError: '',
      scriptModeRequest: 0,
      pendingRunScriptName: '',
      scriptParamForm: {},
      resultVisible: false,
      activeRun: emptyScriptRun(),
    }
  },

  computed: {
    scriptDirectoryTreeData() {
      const ensureNode = (children, key, label, path) => {
        const existing = children.find(node => node.key === key)
        if (existing) return existing

        const node = { key, label, path, children: [] }
        children.push(node)
        return node
      }

      const rootNode = { key: 'dir:.', label: 'root', path: '', children: [] }
      const scriptCounts = new Map()
      for (const item of this.scriptCatalogItems || []) {
        // Count the complete subtree, independently of the current search.
        let path = this.getScriptItemDirectory(item)
        while (true) {
          scriptCounts.set(path, (scriptCounts.get(path) || 0) + 1)
          if (!path) break
          path = this.getParentScriptDirectory(path)
        }
      }
      rootNode.scriptCount = scriptCounts.get('') || 0

      const directories = Array.isArray(this.scriptCatalogDirectories) && this.scriptCatalogDirectories.length
        ? this.scriptCatalogDirectories
        : [{ key: 'dir:.', label: 'root', path: '' }]

      directories.forEach((directory) => {
        const path = this.normalizeScriptDirectoryPath(directory?.path || '')
        const parts = path.split('/').filter(Boolean)
        let currentChildren = rootNode.children
        let currentPath = ''

        if (!parts.length) return

        parts.forEach((part) => {
          currentPath = currentPath ? `${currentPath}/${part}` : part
          const node = ensureNode(currentChildren, `dir:${currentPath}`, part, currentPath)
          node.scriptCount = scriptCounts.get(currentPath) || 0
          currentChildren = node.children
        })
      })

      const sortNodes = (nodes) => {
        nodes.sort((a, b) => String(a.label || '').localeCompare(String(b.label || '')))
        nodes.forEach(node => sortNodes(node.children || []))
        return nodes
      }

      sortNodes(rootNode.children)
      return [rootNode]
    },

    selectedScriptDirectoryTreeKey() {
      return this.getScriptDirectoryTreeKey(this.selectedDirectory)
    },

    scriptDirectoryBreadcrumb() {
      const items = [{ label: 'root', path: '' }]
      let path = ''
      for (const part of this.normalizeScriptDirectoryPath(this.selectedDirectory).split('/').filter(Boolean)) {
        path = path ? `${path}/${part}` : part
        items.push({ label: part, path })
      }
      return items
    },

    currentScriptDirectoryFolders() {
      // Both panes use the same sorted tree, including empty folders.
      let node = this.scriptDirectoryTreeData[0]
      for (const part of this.normalizeScriptDirectoryPath(this.selectedDirectory).split('/').filter(Boolean)) {
        node = node?.children.find(child => child.label === part)
        if (!node) return []
      }
      return node?.children || []
    },

    currentScriptDirectoryItems() {
      const currentDir = String(this.selectedDirectory || '').trim()
      const items = (this.scriptCatalogItems || []).filter(item => this.getScriptItemDirectory(item) === currentDir)

      return this.sortScriptItems(items)
    },

    currentScriptDirectoryRecursiveItems() {
      const currentDir = String(this.selectedDirectory || '').trim()

      const items = (this.scriptCatalogItems || []).filter(item => {
        const dirPath = this.getScriptItemDirectory(item)

        if (!currentDir) return true

        // 搜索只递归当前选中目录及其子目录。
        return dirPath === currentDir || dirPath.startsWith(`${currentDir}/`)
      })

      return this.sortScriptItems(items)
    },

    filteredCurrentScriptDirectoryItems() {
      const keyword = String(this.scriptSearchText || '').trim().toLowerCase()
      if (!keyword) return this.currentScriptDirectoryItems

      return this.currentScriptDirectoryRecursiveItems.filter(item => {

        const values = [
          item.display_name,
          item.script_name,
          item.path,
          item.description,
        ].map(value => String(value || '').toLowerCase())

        return values.some(value => value.includes(keyword))
      })
    },

    hasScriptSearch() {
      return !!String(this.scriptSearchText || '').trim()
    },

    currentConnectionPlatform() {
      return this.resolveCurrentConnectionPlatform()
    },

    pendingRunScriptItem() {
      const target = String(this.pendingRunScriptName || '').trim()
      return (this.scriptCatalogItems || []).find(item => String(item.script_name || '').trim() === target) || null
    },

    pendingRunScriptMetadata() {
      const item = this.pendingRunScriptItem
      if (!item) {
        return { name: '', display_name: '', description: '', platforms: [], params: [], category: '', tags: [] }
      }

      return this.normalizeScriptMetadata(item.metadata || {})
    },

    pendingRunScriptParamSpecs() {
      return Array.isArray(this.pendingRunScriptMetadata.params) ? this.pendingRunScriptMetadata.params : []
    },

    resultJsonText() { return this.activeRun.jsonText || findJsonOutput(this.activeRun.output) },
    resultStatusType() {
      if (!this.activeRun.complete) return 'info'
      return this.activeRun.status === 'Partial' ? 'warning' : (this.activeRun.success ? 'success' : 'danger')
    },
  },

  watch: {
    scriptTreeVisible(value) {
      if (value) this.syncScriptTreeSelection()
    },
    selectedId() { if (this.scriptRunDialogVisible) this.closeScriptRunDialog() },
    scriptRunDialogVisible(value) {
      if (!value) this.closeScriptRunDialog()
    },
  },

  methods: {
    viewResultJson() {
      if (!this.resultJsonText) return
      this.$emit('open-json', {
        jsonText: this.resultJsonText,
        jsonView: this.activeRun.view || {},
        clientId: this.activeRun.clientId,
        jsonCommandInfo: {
          blockType: 'script',
          is_script: true,
          script_path: this.activeRun.scriptPath,
          script_name: this.activeRun.operation?.replay?.script_name || '',
          operation: this.activeRun.operation,
        },
      })
    },
    forwardAppendOutput(clientId, line, kind, meta) {
      this.$emit('append-output', clientId, line, kind, meta)
    },

    forwardSetActiveTask(clientId, taskId, cancelPolicy = '', historyEntryId = '', operationId = '') {
      this.$emit('set-active-task', clientId, taskId, cancelPolicy, historyEntryId, operationId)
    },

    refreshRemoteFilePickerDirectory(path = '') {
      return this.$refs.scriptRunDialogRef?.loadRemoteFilePickerDirectory(path || '')
    },

    async open() {
      if (!this.selectedId) {
        ElMessage.warning('Please select a device')
        return
      }

      this.visible = true
      // await this.loadScriptCatalog()
      await this.loadScriptCatalog({ selectForConnection: true })
    },

    async openRunForScript(scriptName) {
      if (!this.selectedId) {
        ElMessage.warning('Please select a device')
        return
      }
      this.scriptCatalogItems = []
      await this.loadScriptCatalog()
      const target = String(scriptName || '').trim()
      const item = this.scriptCatalogItems.find(row => row.script_name === target)
      if (!item) {
        ElMessage.warning('Script is unavailable')
        return
      }
      this.openScriptRunDialog(item)
    },

    isOpen() {
      return this.visible
    },

    async refreshIfOpen() {
      if (!this.visible) return
      await this.loadScriptCatalog()
    },

    handleClosed() {
      this.closeScriptRunDialog()
    },

    buildJsonHeaders(extra = {}) {
      if (typeof this.getTabScopedHeaders === 'function') {
        return this.getTabScopedHeaders(extra)
      }

      return extra
    },

    normalizeScriptDirectoryPath(directory) {
      return String(directory || '').trim().replace(/\\/g, '/').replace(/^\/+/, '').replace(/\/+$/, '')
    },

    getScriptDirectoryTreeKey(directory) {
      const normalized = this.normalizeScriptDirectoryPath(directory)
      return normalized ? `dir:${normalized}` : 'dir:.'
    },

    getScriptDirectorySelectionContextKey() {
      const connection = this.currentConnection || {}
      return String(connection.machine_id || connection.client_id || this.selectedId || '').trim()
    },

    getScriptDirectoryPathFromTreeKey(key) {
      const value = String(key || '').trim()
      if (value === 'dir:.') return ''
      if (!value.startsWith('dir:')) return ''
      return this.normalizeScriptDirectoryPath(value.slice(4))
    },

    normalizeScriptTreeExpandedKeys(keys) {
      const result = []
      const seen = new Set()

      for (const key of keys || []) {
        const normalized = String(key || '').trim()
        if (!normalized || seen.has(normalized)) continue

        seen.add(normalized)
        result.push(normalized)
      }

      return result
    },

    includeScriptTreeAncestorKeys(keys) {
      const result = [...this.normalizeScriptTreeExpandedKeys(keys)]

      for (const key of result) {
        const path = this.getScriptDirectoryPathFromTreeKey(key)
        const parts = path.split('/').filter(Boolean)

        if (!parts.length) continue

        result.push('dir:.')

        let currentPath = ''
        for (let i = 0; i < parts.length - 1; i += 1) {
          currentPath = currentPath ? `${currentPath}/${parts[i]}` : parts[i]
          result.push(this.getScriptDirectoryTreeKey(currentPath))
        }
      }

      return this.normalizeScriptTreeExpandedKeys(result)
    },

    getScriptTreeDirectoryKeySet() {
      const keys = new Set(['dir:.'])

      for (const directory of this.scriptCatalogDirectories || []) {
        const path = this.normalizeScriptDirectoryPath(directory?.path || '')
        const parts = path.split('/').filter(Boolean)

        let currentPath = ''
        for (const part of parts) {
          currentPath = currentPath ? `${currentPath}/${part}` : part
          keys.add(this.getScriptDirectoryTreeKey(currentPath))
        }
      }

      return keys
    },

    filterExistingScriptTreeExpandedKeys(keys) {
      const validKeys = this.getScriptTreeDirectoryKeySet()
      return this.normalizeScriptTreeExpandedKeys(keys).filter(key => validKeys.has(key))
    },

    mapScriptTreeExpandedKeysForRename(keys, oldDirectory, newDirectory) {
      const oldKey = this.getScriptDirectoryTreeKey(oldDirectory)
      const newKey = this.getScriptDirectoryTreeKey(newDirectory)

      if (oldKey === newKey) {
        return this.normalizeScriptTreeExpandedKeys(keys)
      }

      const mappedKeys = (keys || []).map((key) => {
        const currentKey = String(key || '').trim()

        if (currentKey === oldKey) return newKey
        if (oldKey !== 'dir:.' && currentKey.startsWith(`${oldKey}/`)) {
          return `${newKey}${currentKey.slice(oldKey.length)}`
        }

        return currentKey
      })

      return this.includeScriptTreeAncestorKeys(mappedKeys)
    },

    filterScriptTreeExpandedKeysAfterDelete(keys, deletedDirectory) {
      const deletedKey = this.getScriptDirectoryTreeKey(deletedDirectory)

      if (deletedKey === 'dir:.') return []

      return this.normalizeScriptTreeExpandedKeys(keys).filter((key) => {
        const currentKey = String(key || '').trim()
        return currentKey !== deletedKey && !currentKey.startsWith(`${deletedKey}/`)
      })
    },

    handleScriptTreeNodeExpand(node) {
      const key = String(node?.key || '').trim()
      if (!key) return

      this.scriptTreeExpandedKeys = this.includeScriptTreeAncestorKeys([
        ...this.scriptTreeExpandedKeys,
        key,
      ])
    },

    handleScriptTreeNodeCollapse(node) {
      const key = String(node?.key || '').trim()
      if (!key) return

      if (key === 'dir:.') {
        this.scriptTreeExpandedKeys = []
        return
      }

      this.scriptTreeExpandedKeys = this.normalizeScriptTreeExpandedKeys(this.scriptTreeExpandedKeys).filter((item) => {
        const currentKey = String(item || '').trim()
        return currentKey !== key && !currentKey.startsWith(`${key}/`)
      })
    },

    getScriptItemDirectory(item) {
      const path = this.normalizeScriptDirectoryPath(item?.path || `${item?.script_name || ''}.py`)
      const parts = path.split('/').filter(Boolean)
      return parts.slice(0, -1).join('/')
    },

    sortScriptItems(items) {
      return [...(items || [])].sort((a, b) => {
        const da = String(a.display_name || a.script_name || '').toLowerCase()
        const db = String(b.display_name || b.script_name || '').toLowerCase()
        return da.localeCompare(db)
      })
    },

    normalizeServerScriptFilename(scriptName, fallbackName = 'new_script.py') {
      let normalized = String(scriptName || '').trim().replace(/\\/g, '/').replace(/^\/+/, '')
      if (!normalized) normalized = fallbackName
      if (!/\.py$/i.test(normalized)) normalized = `${normalized}.py`
      return normalized
    },

    async loadScriptCatalog(options = {}) {
      this.loading = true

      try {
        const res = await getScriptCatalog()
        const json = await res.json()
        if (!res.ok || json.code !== 0) {
          throw new Error(json.message || 'Failed to load script catalog')
        }

        const catalog = json.data || {}
        this.scriptCatalogItems = Array.isArray(catalog.items) ? catalog.items : []
        this.scriptCatalogDirectories = Array.isArray(catalog.directories) ? catalog.directories : [{ key: 'dir:.', label: 'root', path: '' }]

        if (options?.selectForConnection) {
          const contextKey = this.getScriptDirectorySelectionContextKey()
          const currentDirectory = this.normalizeScriptDirectoryPath(this.selectedDirectory)
          const directoryExists = this.scriptCatalogDirectories.some(item =>
            this.normalizeScriptDirectoryPath(item?.path || '') === currentDirectory)
          if (contextKey !== this.scriptDirectorySelectionContextKey || !directoryExists) {
            this.selectedDirectory = this.getDefaultScriptDirectory()
          }
          this.scriptDirectorySelectionContextKey = contextKey
          this.scriptTreeExpandedKeys = this.selectedDirectory
            ? this.includeScriptTreeAncestorKeys([
              this.getScriptDirectoryTreeKey(this.selectedDirectory),
            ]) : []
        } else if (!this.scriptCatalogDirectories.some(item =>
          this.normalizeScriptDirectoryPath(item?.path || '') === this.selectedDirectory)) {
          this.selectedDirectory = this.getDefaultScriptDirectory()
        }

        this.scriptTreeExpandedKeys = this.filterExistingScriptTreeExpandedKeys(this.scriptTreeExpandedKeys)
        this.scriptTreeRenderKey += 1
        this.syncScriptTreeSelection()
      } catch (e) {
        ElMessage.error(e.message || 'Failed to load script catalog')
      } finally {
        this.loading = false
      }
    },

    getFirstAvailableScriptDirectory() {
      const dirs = (this.scriptCatalogDirectories || []).map(item => this.normalizeScriptDirectoryPath(item?.path || ''))
      return dirs.length ? dirs.sort()[0] : ''
    },

    getDefaultScriptDirectory() {
      const dirs = new Set((this.scriptCatalogDirectories || [])
        .map(item => this.normalizeScriptDirectoryPath(item?.path || '')))
      return dirs.has('common') ? 'common' : dirs.has('') ? '' : this.getFirstAvailableScriptDirectory()
    },

    getParentScriptDirectory(directory) {
      const normalized = this.normalizeScriptDirectoryPath(directory)
      if (!normalized) return ''

      const parts = normalized.split('/').filter(Boolean)
      return parts.slice(0, -1).join('/')
    },

    selectScriptDirectory(directory) {
      this.selectedDirectory = this.normalizeScriptDirectoryPath(directory)
      this.$nextTick(() => {
        const pane = this.$refs.scriptDirectoryPane
        if (pane) pane.scrollTop = 0
        const breadcrumb = this.$refs.scriptBreadcrumb
        if (breadcrumb) breadcrumb.scrollLeft = breadcrumb.scrollWidth
      })
    },

    syncScriptTreeSelection() {
      // Apply the selection after Vue has updated the tree and its expanded keys.
      const key = this.selectedScriptDirectoryTreeKey
      this.scriptTreeExpandedKeys = this.includeScriptTreeAncestorKeys([
        ...this.scriptTreeExpandedKeys,
        key,
      ])
      this.$nextTick(() => {
        if (key !== this.selectedScriptDirectoryTreeKey) return
        const tree = this.$refs.scriptDirectoryTreeRef
        if (!tree) return
        tree.setCurrentKey(key, true)
      })
    },

    handleScriptTreeNodeClick(node) {
      if (!node) return
      this.selectScriptDirectory(node.path)
    },

    navigateScriptDirectory(directory) {
      this.selectScriptDirectory(directory)
      this.syncScriptTreeSelection()
    },

    handleScriptMoreCommand(item, command) {
      if (!item) return

      if (command === 'rename') {
        this.renameServerScript(item.script_name)
        return
      }

      if (command === 'delete') {
        this.deleteServerScript(item.script_name)
      }
    },

    normalizeScriptMetadata(metadata = {}) {
      if (!metadata || typeof metadata !== 'object' || Array.isArray(metadata)) {
        return { name: '', display_name: '', description: '', platforms: [], params: [], category: '', tags: [] }
      }

      return {
        ...metadata,
        name: String(metadata.name || '').trim(),
        display_name: String(metadata.display_name || '').trim(),
        description: String(metadata.description || '').trim(),
        category: String(metadata.category || '').trim(),
        tags: Array.isArray(metadata.tags) ? metadata.tags : [],
        platforms: this.normalizeScriptPlatforms(metadata.platforms),
        params: normalizeParamSpecs(metadata.params),
      }
    },

    normalizeScriptPlatforms(platforms) {
      const source = Array.isArray(platforms)
        ? platforms
        : (typeof platforms === 'string' && platforms.trim() ? [platforms] : [])

      const result = []
      const seen = new Set()

      for (const item of source) {
        const normalized = this.normalizeScriptPlatform(item)
        if (!normalized || seen.has(normalized)) continue

        seen.add(normalized)
        result.push(normalized)
      }

      return result
    },

    normalizeScriptPlatform(platform) {
      const value = String(platform || '').trim().toLowerCase()
      if (!value) return ''
      if (['*', 'all', 'any', 'common'].includes(value)) return '*'
      if (['darwin', 'mac', 'macos', 'osx'].includes(value)) return 'mac'
      if (['windows', 'win', 'win32', 'nt'].includes(value)) return 'win'
      if (['linux', 'ubuntu', 'debian', 'centos', 'fedora', 'redhat', 'rhel', 'alpine', 'arch'].includes(value)) return 'linux'
      return value
    },

    resolveCurrentConnectionPlatform() {
      return this.currentConnection?.os_alias || ''
    },

    formatScriptPlatformLabel(item) {
      const metadata = this.normalizeScriptMetadata(item?.metadata || {})
      const platforms = metadata.platforms || []

      if (!platforms.length || platforms.includes('*')) {
        return 'All OS'
      }

      const labels = platforms.map(platform => {
        if (platform === 'mac') return 'macOS'
        if (platform === 'win') return 'Windows'
        if (platform === 'linux') return 'Linux'
        if (platform === 'ios') return 'iOS'
        return platform
      })

      return labels.join(' / ')
    },

    isScriptSupportedForCurrentConnection(item) {
      const metadata = this.normalizeScriptMetadata(item?.metadata || {})
      const platforms = metadata.platforms || []
      if (!platforms.length || platforms.includes('*')) return true

      const current = this.currentConnectionPlatform
      if (!current) return true

      return platforms.includes(current)
    },

    scriptHasParams(item) {
      const metadata = this.normalizeScriptMetadata(item?.metadata || {})
      return Array.isArray(metadata.params) && metadata.params.length > 0
    },

    buildScriptParamDefaults(item) {
      const metadata = this.normalizeScriptMetadata(item?.metadata || {})
      const result = {}

      for (const param of metadata.params || []) {
        const type = normalizeParamType(param.type)
        const hasDefault = Object.prototype.hasOwnProperty.call(param, 'default') && param.default !== null && param.default !== undefined
        if (hasDefault) {
          if (['remote_files', 'remote_folders', 'path_list'].includes(type)) {
            result[param.name] = Array.isArray(param.default) ? cloneParamValue(param.default) : []
          } else if (type === 'boolean') {
            result[param.name] = param.default === true || String(param.default).toLowerCase() === 'true'
          } else {
            result[param.name] = cloneParamValue(param.default)
          }
        } else if (['remote_files', 'remote_folders', 'path_list'].includes(type)) {
          result[param.name] = []
        } else if (type === 'boolean') {
          result[param.name] = false
        } else {
          result[param.name] = ''
        }
      }

      return result
    },

    updateScriptParam(name, value) {
      if (!name) return

      this.scriptParamForm = {
        ...this.scriptParamForm,
        [name]: value,
      }
    },

    applyScriptParamValues(values) {
      if (!values || typeof values !== 'object' || Array.isArray(values)) return
      this.scriptParamForm = {
        ...this.scriptParamForm,
        ...values,
      }
    },

    coerceScriptParamValue(param, rawValue) {
      const type = normalizeParamType(param?.type)
      if (type === 'boolean') return !!rawValue
      if (type === 'path_list') {
        if (!Array.isArray(rawValue)) throw new Error(`Param "${param.name}" must be a path list`)
        return rawValue.map((entry, index) => {
          if (!entry || typeof entry !== 'object' || Array.isArray(entry) || typeof entry.path !== 'string') {
            throw new Error(`Invalid path at row ${index + 1} of "${param.name}"`)
          }
          return { path: entry.path.trim(), enabled: entry.enabled !== false }
        })
      }


      if (['remote_files', 'remote_folders'].includes(type)) {
        if (!Array.isArray(rawValue)) throw new Error(`Param "${param.name}" must be a path list`)
        return rawValue.map(item => String(item || '').trim()).filter(Boolean)
      }

      if (['remote_file', 'remote_folder'].includes(type)) {
        if (Array.isArray(rawValue)) throw new Error(`Param "${param.name}" must be a single path`)
        return String(rawValue || '').trim()
      }

      if (type === 'textarea') {
        return rawValue === null || rawValue === undefined ? '' : String(rawValue)
      }

      const value = rawValue === null || rawValue === undefined ? '' : String(rawValue).trim()
      if (type === 'integer') {
        if (!/^-?\d+$/.test(value)) throw new Error(`Param "${param.name}" must be an integer`)

        const parsed = parseInt(value, 10)
        if (param.min !== undefined && parsed < Number(param.min)) throw new Error(`Param "${param.name}" must be >= ${param.min}`)
        if (param.max !== undefined && parsed > Number(param.max)) throw new Error(`Param "${param.name}" must be <= ${param.max}`)
        return parsed
      }

      if (type === 'number') {
        const parsed = Number(value)
        if (Number.isNaN(parsed)) throw new Error(`Param "${param.name}" must be a number`)
        if (param.min !== undefined && parsed < Number(param.min)) throw new Error(`Param "${param.name}" must be >= ${param.min}`)
        if (param.max !== undefined && parsed > Number(param.max)) throw new Error(`Param "${param.name}" must be <= ${param.max}`)
        return parsed
      }

      if (type === 'select') {
        if (Array.isArray(param.options) && param.options.length && !param.options.map(String).includes(value)) {
          throw new Error(`Param "${param.name}" has invalid option`)
        }
        return value
      }

      return value
    },

    buildScriptRunParams(item) {
      const metadata = this.normalizeScriptMetadata(item?.metadata || {})
      const params = {}

      for (const param of metadata.params || []) {
        const rawValue = this.scriptParamForm[param.name]
        const type = normalizeParamType(param.type)
        // An empty editable list is intentional (all rows deleted), not a request for defaults.
        if (type === 'path_list') {
          params[param.name] = this.coerceScriptParamValue(param, rawValue)
          continue
        }
        const hasRemoteMultiValue = ['remote_files', 'remote_folders'].includes(type) && Array.isArray(rawValue) && rawValue.length > 0
        const textValue = type === 'boolean' ? rawValue : String(rawValue === null || rawValue === undefined ? '' : rawValue).trim()

        if ((!hasRemoteMultiValue && type !== 'boolean' && !textValue) || (type === 'boolean' && rawValue === undefined)) {
          if (param.required && (param.default === undefined || param.default === null || String(param.default).trim() === '')) {
            throw new Error(`Missing required param: ${param.name}`)
          }

          if (param.default !== undefined && param.default !== null && String(param.default).trim() !== '') {
            params[param.name] = this.coerceScriptParamValue(param, param.default)
          }
          continue
        }

        params[param.name] = this.coerceScriptParamValue(param, rawValue)
      }

      return params
    },

    async openScriptRunDialog(item) {
      if (!item) return

      if (!this.selectedId) {
        ElMessage.warning('Please select a device')
        return
      }

      if (!this.isScriptSupportedForCurrentConnection(item)) {
        ElMessage.warning(`${item.display_name || item.script_name} only supports: ${this.formatScriptPlatformLabel(item)}`)
        return
      }

      this.pendingRunScriptName = String(item.script_name || '').trim()
      this.scriptParamForm = this.buildScriptParamDefaults(item)
      this.scriptModeOptions = {}
      this.scriptRunModes = {}
      this.scriptModesError = ''
      this.scriptModesLoading = true
      this.scriptRunDialogVisible = true
      const request = ++this.scriptModeRequest
      const clientId = this.selectedId
      try {
        const options = await getScriptRunOptions(clientId, item.script_name)
        if (request !== this.scriptModeRequest || String(clientId) !== String(this.selectedId)) return
        this.scriptModeOptions = options
        this.scriptRunModes = Object.fromEntries(Object.entries(options).map(([key, spec]) => [key, spec.default]))
        if (Object.values(options).some(spec => !spec.allowed.length)) this.scriptModesError = 'No supported run modes for this Client.'
      } catch (e) {
        if (request === this.scriptModeRequest) this.scriptModesError = e.message || 'Unable to load Script run options'
      } finally {
        if (request === this.scriptModeRequest) this.scriptModesLoading = false
      }
    },

    updateScriptMode(key, value) {
      if (this.scriptModeOptions[key]?.allowed?.includes(value)) this.scriptRunModes[key] = value
    },

    async cancelScriptRun() {
      const run = this.activeRun
      if (!run.taskId || !run.cancelSupported || run.complete || run.cancelSending) return
      run.cancelSending = true
      try {
        await cancelTask(run.taskId)
        if (!run.complete) run.status = 'Cancelling'
      } catch (e) {
        ElMessage.error(e.message || 'Unable to cancel Script')
      } finally {
        run.cancelSending = false
      }
    },

    closeScriptRunDialog() {
      this.scriptRunDialogVisible = false
      this.scriptRunSubmitting = false
      this.pendingRunScriptName = ''
      this.scriptParamForm = {}
      this.scriptModeRequest++
      this.scriptModesLoading = false
    },

    createRunId() {
      if (globalThis.crypto && typeof globalThis.crypto.randomUUID === 'function') {
        return globalThis.crypto.randomUUID()
      }
      return `script-run-${Date.now()}-${Math.random().toString(16).slice(2)}`
    },

    handleCommandResult(payload = {}) {
      const metadata = payload.metadata && typeof payload.metadata === 'object' ? payload.metadata : {}
      if (metadata.script_run !== true || metadata.script_run_presentation !== 'dialog') return false
      if (String(metadata.script_run_id || '') !== this.activeRun.runId ||
          String(payload.client_id || '') !== this.activeRun.clientId) return true

      if (!this.resultVisible) this.resultVisible = true
      if (payload.result?.data !== undefined) {
        const selected = selectJsonViewResult(this.activeRun.jsonText
          ? { jsonText: this.activeRun.jsonText, view: this.activeRun.view } : null, payload.result)
        this.activeRun.jsonText = selected.jsonText
        this.activeRun.view = selected.view
      }
      const chunk = String(payload.text ?? '').replace(/\r\n/g, '\n').replace(/\r/g, '\n')
      if (metadata.output_mode === 'stream') {
        this.activeRun.output += (this.activeRun.outputChunks++ ? '\n' : '') + chunk
      } else if (chunk) {
        const output = this.activeRun.output
        const separator = output && !output.endsWith('\n') && !chunk.startsWith('\n') ? '\n' : ''
        this.activeRun.output = `${output}${separator}${chunk}`
      }
      return true
    },

    handleCommandComplete(payload = {}) {
      const metadata = payload.metadata && typeof payload.metadata === 'object' ? payload.metadata : {}
      if (metadata.script_run !== true || metadata.script_run_presentation !== 'dialog') return false
      if (String(metadata.script_run_id || '') !== this.activeRun.runId ||
          String(payload.client_id || '') !== this.activeRun.clientId) return true

      this.activeRun.complete = true
      const status = String(payload.status || '').trim()
      this.activeRun.success = status ? status === 'success' : payload.success === true
      this.activeRun.status = status === 'cancelled' || (!status && payload.cancelled) ? 'Cancelled'
        : status === 'partial' ? 'Partial'
        : status === 'timed_out' ? 'Timed out'
        : status === 'interrupted' ? 'Interrupted'
        : this.activeRun.success ? 'Success' : 'Failed' 
      return true
    },

    async copyResult() {
      const text = String(this.activeRun.output || '')
      if (!text) return
      try {
        if (window.isSecureContext && navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
          await navigator.clipboard.writeText(text)
        } else {
          const textarea = document.createElement('textarea')
          textarea.value = text
          textarea.style.position = 'fixed'
          textarea.style.opacity = '0'
          document.body.appendChild(textarea)
          textarea.focus()
          textarea.select()
          document.execCommand('copy')
          document.body.removeChild(textarea)
        }
        ElMessage.success('Result copied')
      } catch (e) {
        ElMessage.error(e.message || 'Copy failed')
      }
    },

    async runScriptFromTerminalBlock(payload = {}) {
      const scriptName = String(payload.script_name || '').trim()
      const params = payload.params && typeof payload.params === 'object' && !Array.isArray(payload.params)
        ? { ...payload.params }
        : {}
      const displayName = String(payload.script_display_name || scriptName).trim()
      const scriptPath = String(payload.script_path || `${scriptName}.py`).trim()
      const modes = Object.fromEntries(['execution_mode', 'output_mode'].filter(key => payload[key]).map(key => [key, payload[key]]))

      if (!this.selectedId || (payload.clientId && String(this.selectedId) !== String(payload.clientId))) {
        ElMessage.warning('The target device has changed')
        return ''
      }
      if (!scriptName) {
        ElMessage.warning('Missing script name')
        return ''
      }
      let operation = null
      try {
        operation = payload.operation || createTerminalOperation({ kind: 'script', action: 'run', clientId: this.selectedId,
          invocation: { script_name: scriptName, params, ...modes },
          replay: { type: 'script', script_name: scriptName, script_path: scriptPath,
            script_display_name: displayName || scriptName, params, ...modes } })
        const commandText = `> ${TERMINAL_RUN_SCRIPT_PREFIX} ${displayName || scriptName}`
        this.$emit('append-output', this.selectedId, commandText, 'command', {
          operation,
          script_name: scriptName,
          script_path: scriptPath,
          script_display_name: displayName || scriptName,
          params: { ...params },
        })
        const res = await runLibraryScript(this.selectedId,
          { script_name: scriptName, params, ...modes, presentation: 'terminal' },
          operationHeaders(operation, this.buildJsonHeaders({ 'Content-Type': 'application/json' })))
        const json = await res.json()
        if (!res.ok || json.code !== 0) throw new Error(json.message || 'Failed to run script')
        const taskId = String(json.data?.task_id || '')
        this.$emit('set-active-task', this.selectedId, taskId, modes.execution_mode === 'subprocess_pipe' ? 'process' : (modes.execution_mode === 'inproc' ? 'none' : ''), '', operation.operation_id)
        ElMessage.success(`Run request submitted: ${displayName || scriptName}`)
        return taskId
      } catch (e) {
        this.$emit('append-output', this.selectedId, `Script failed: ${e.message || 'unknown error'}`, 'error',
          { operation_id: operation?.operation_id, event_type: 'submission_error' })
        ElMessage.error(e.message || 'Failed to run script')
        return ''
      }
    },

    async confirmRunScript(presentation = 'dialog') {
      const item = this.pendingRunScriptItem
      if (!item) {
        this.closeScriptRunDialog()
        return
      }

      if (!this.selectedId) {
        ElMessage.warning('Please select a device')
        return
      }
      if (this.scriptRunSubmitting || this.scriptModesLoading || this.scriptModesError) return
      const modes = { ...this.scriptRunModes }
      if (!['execution_mode', 'output_mode'].every(key => this.scriptModeOptions[key]?.allowed?.includes(modes[key]))) return

      let runId = ''
      let operation = null
      try {
        const params = this.buildScriptRunParams(item)
        this.scriptRunSubmitting = true
        const displayName = item.display_name || item.script_name
        const replay = { type: 'script', script_name: item.script_name,
          script_path: item.path || '', script_display_name: displayName, params, ...modes }

        if (presentation === 'dialog') {
          runId = this.createRunId()
          this.activeRun = {
            ...emptyScriptRun(),
            runId,
            clientId: String(this.selectedId),
            displayName,
            scriptPath: item.path || `${item.script_name}.py`,
            operation: createTerminalOperation({ kind: 'script', action: 'run', clientId: this.selectedId,
              invocation: { script_name: item.script_name, params, ...modes }, replay, presentation: 'dialog' }),
            status: 'Running',
            cancelSupported: modes.execution_mode === 'subprocess_pipe',
          }
          this.resultVisible = true
        } else {
          // Terminal output keeps its original command block and re-run metadata.
          operation = createTerminalOperation({ kind: 'script', action: 'run', clientId: this.selectedId,
            invocation: { script_name: item.script_name, params, ...modes },
            replay })
          const commandText = `> ${TERMINAL_RUN_SCRIPT_PREFIX} ${displayName}`
          this.$emit('append-output', this.selectedId, commandText, 'command', {
            operation,
            script_name: item.script_name || '',
            script_path: item.path || `${item.script_name || ''}.py`,
            script_display_name: displayName,
            params: { ...params },
          })
        }

        const res = await runLibraryScript(this.selectedId,
          { script_name: item.script_name, params, ...modes, presentation, run_id: runId },
          operation ? operationHeaders(operation, this.buildJsonHeaders({ 'Content-Type': 'application/json' }))
            : this.buildJsonHeaders({ 'Content-Type': 'application/json' }))
        const json = await res.json()
        if (!res.ok || json.code !== 0) throw new Error(json.message || 'Failed to run script')

        const taskId = json.data && json.data.task_id
        if (runId && this.activeRun.runId === runId) this.activeRun.taskId = taskId || ''
        this.$emit('set-active-task', this.selectedId, taskId || '', modes.execution_mode === 'subprocess_pipe' ? 'process' : 'none', '', operation?.operation_id || '')
        ElMessage.success(`Run request submitted: ${displayName}`)
        this.closeScriptRunDialog()
      } catch (e) {
        if (presentation === 'dialog' && this.activeRun.runId === runId && runId) {
          this.activeRun.complete = true
          this.activeRun.success = false
          this.activeRun.status = 'Failed'
          this.activeRun.output += `${this.activeRun.output ? '\n' : ''}${e.message || 'Failed to run script'}`
        }
        if (presentation === 'terminal' && operation) {
          this.$emit('append-output', this.selectedId, `Script failed: ${e.message || 'unknown error'}`, 'error',
            { operation_id: operation.operation_id, event_type: 'submission_error' })
        }
        ElMessage.error(e.message || 'Failed to run script')
      } finally {
        this.scriptRunSubmitting = false
      }
    },

    async openRemoteScriptEditor(scriptName) {
      if (typeof this.openScriptEditor === 'function') {
        await this.openScriptEditor(scriptName)
      }
    },

    async createRemoteScriptPrompt() {
      if (!this.selectedId) {
        ElMessage.warning('Please select a device')
        return
      }

      try {
        const baseDir = this.selectedDirectory ? `${this.selectedDirectory}/` : ''
        const { value } = await ElMessageBox.prompt(
          'Enter the new script filename',
          'New Script',
          {
            confirmButtonText: 'Create',
            cancelButtonText: 'Cancel',
            inputValue: `${baseDir}new_script.py`,
            inputPlaceholder: 'folder/new_script.py',
          }
        )

        if (typeof this.openNewScriptEditor === 'function') {
          await this.openNewScriptEditor(value || `${baseDir}new_script.py`)
        }
      } catch (e) {
        if (e === 'cancel' || e === 'close') return
      }
    },

    async createRemoteScriptFolderPrompt() {
      if (!this.selectedId) {
        ElMessage.warning('Please select a device')
        return
      }

      try {
        const baseDir = this.selectedDirectory ? `${this.selectedDirectory}/` : ''
        const { value } = await ElMessageBox.prompt(
          'Enter the new folder path',
          'New Folder',
          {
            confirmButtonText: 'Create',
            cancelButtonText: 'Cancel',
            inputValue: `${baseDir}new_folder`,
            inputPlaceholder: 'folder/subfolder',
          }
        )

        const directory = this.normalizeScriptDirectoryPath(value)
        if (!directory) {
          ElMessage.warning('Folder path is required')
          return
        }

        const res = await createScriptFolder(directory)
        const json = await res.json()
        if (!res.ok || json.code !== 0) throw new Error(json.message || 'Failed to create folder')

        this.selectedDirectory = directory
        ElMessage.success(`Folder created: ${directory}`)
        await this.loadScriptCatalog()
      } catch (e) {
        if (e === 'cancel' || e === 'close') return
        ElMessage.error(e.message || 'Failed to create folder')
      }
    },

    async renameRemoteScriptFolder() {
      const currentDirectory = this.normalizeScriptDirectoryPath(this.selectedDirectory)
      if (!currentDirectory) {
        ElMessage.warning('Root folder cannot be renamed')
        return
      }

      try {
        const expandedKeysBeforeRename = [...this.scriptTreeExpandedKeys]
        const { value } = await ElMessageBox.prompt(
          'Enter the new folder path',
          'Rename Folder',
          {
            confirmButtonText: 'Rename',
            cancelButtonText: 'Cancel',
            inputValue: currentDirectory,
            inputPlaceholder: 'folder/subfolder',
          }
        )

        const newDirectory = this.normalizeScriptDirectoryPath(value)
        if (!newDirectory) {
          ElMessage.warning('New folder path is required')
          return
        }

        const res = await renameScriptFolder(currentDirectory, newDirectory)
        const json = await res.json()
        if (!res.ok || json.code !== 0) throw new Error(json.message || 'Failed to rename folder')

        this.selectedDirectory = newDirectory
        this.scriptTreeExpandedKeys = this.mapScriptTreeExpandedKeysForRename(expandedKeysBeforeRename, currentDirectory, newDirectory)

        ElMessage.success(`Folder renamed: ${newDirectory}`)
        await this.loadScriptCatalog()
      } catch (e) {
        if (e === 'cancel' || e === 'close') return
        ElMessage.error(e.message || 'Failed to rename folder')
      }
    },

    async deleteRemoteScriptFolder() {
      const currentDirectory = this.normalizeScriptDirectoryPath(this.selectedDirectory)
      if (!currentDirectory) {
        ElMessage.warning('Root folder cannot be deleted')
        return
      }

      try {
        const expandedKeysBeforeDelete = [...this.scriptTreeExpandedKeys]

        await ElMessageBox.confirm(
          `Delete folder "${currentDirectory}" and all files/subfolders in it? This action cannot be undone.`,
          'Delete Folder',
          {
            type: 'warning',
            confirmButtonText: 'Delete',
            cancelButtonText: 'Cancel',
          }
        )

        const parentDirectory = this.getParentScriptDirectory(currentDirectory)

        const res = await deleteScriptFolder(currentDirectory)
        const json = await res.json()
        if (!res.ok || json.code !== 0) throw new Error(json.message || 'Failed to delete folder')

        this.selectedDirectory = parentDirectory
        this.scriptTreeExpandedKeys = this.filterScriptTreeExpandedKeysAfterDelete(expandedKeysBeforeDelete, currentDirectory)

        ElMessage.success(`Folder deleted: ${currentDirectory}`)
        await this.loadScriptCatalog()
      } catch (e) {
        if (e === 'cancel' || e === 'close') return
        ElMessage.error(e.message || 'Failed to delete folder')
      }
    },

    async renameServerScript(scriptName) {
      const normalized = String(scriptName || '').trim().replace(/\\/g, '/').replace(/^\/+/, '')
      if (!normalized) {
        ElMessage.warning('Invalid script name')
        return
      }

      try {
        const { value } = await ElMessageBox.prompt(
          'Enter the new file name (.py path)',
          'Rename Script',
          {
            confirmButtonText: 'Rename',
            cancelButtonText: 'Cancel',
            inputValue: `${normalized}.py`,
            inputPlaceholder: 'folder/new_name.py',
          }
        )

        const newName = String(value || '').trim().replace(/\\/g, '/').replace(/^\/+/, '')
        if (!newName) {
          ElMessage.warning('New file name is required')
          return
        }

        const res = await renameLibraryScript(normalized, newName)
        const json = await res.json()
        if (!res.ok || json.code !== 0) throw new Error(json.message || 'Failed to rename script')

        const renamedName = this.normalizeServerScriptFilename(json.data?.name || newName)
        ElMessage.success(`Script renamed: ${renamedName}`)
        await this.loadScriptCatalog()
      } catch (e) {
        if (e === 'cancel' || e === 'close') return
        ElMessage.error(e.message || 'Failed to rename script')
      }
    },

    triggerScriptUpload() {
      if (!this.selectedId) {
        ElMessage.warning('Please select a device')
        return
      }

      const input = this.$refs.serverScriptUploadInputRef
      if (input) {
        input.value = ''
        input.click()
      }
    },

    async handleServerScriptUpload(event) {
      const input = event && event.target
      const file = input && input.files && input.files[0]
      if (!file) return

      if (!/\.py$/i.test(file.name || '')) {
        ElMessage.warning('Only .py files are supported')
        input.value = ''
        return
      }

      this.uploadLoading = true

      try {
        const formData = new FormData()
        formData.append('file', file, file.name)
        formData.append('directory', this.selectedDirectory || '')

        const res = await uploadLibraryScript(formData)

        const json = await res.json()
        if (!res.ok || json.code !== 0) {
          throw new Error(json.message || 'Failed to upload script')
        }

        const uploadedName = this.normalizeServerScriptFilename(json.data?.name || file.name)
        ElMessage.success(`Script uploaded: ${uploadedName}`)

        await this.loadScriptCatalog()
        await this.openRemoteScriptEditor(uploadedName)
      } catch (e) {
        ElMessage.error(e.message || 'Failed to upload script')
      } finally {
        this.uploadLoading = false
        if (input) input.value = ''
      }
    },

    async deleteServerScript(scriptName) {
      const normalized = String(scriptName || '').trim().replace(/\\/g, '/').replace(/^\/+/, '').replace(/\.py$/i, '')
      if (!normalized) {
        ElMessage.warning('Invalid script name')
        return
      }

      try {
        await ElMessageBox.confirm(`Delete "${normalized}.py"? This action cannot be undone.`, 'Delete Script', {
          type: 'warning',
          confirmButtonText: 'Delete',
          cancelButtonText: 'Cancel',
        })

        const res = await deleteLibraryScript(normalized)
        const json = await res.json()
        if (!res.ok || json.code !== 0) throw new Error(json.message || 'Failed to delete script')

        ElMessage.success(`Deleted: ${normalized}.py`)
        await this.loadScriptCatalog()
      } catch (e) {
        if (e === 'cancel' || e === 'close') return
        ElMessage.error(e.message || 'Failed to delete script')
      }
    },
  },
}
</script>

<style scoped>
.script-library-body {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  overflow: hidden;
}

.script-library-toolbar {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}

.script-library-toolbar-left,
.script-library-toolbar-right {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  min-width: 0;
}

.script-library-toolbar-left :deep(.el-button),
.script-library-card-actions :deep(.el-button) {
  margin: 0;
}

.script-library-toolbar :deep(.el-button.toolbar-btn) {
  height: 32px;
  min-height: 32px;
  padding: 0 12px;
  border-radius: 10px;
}

.script-library-toolbar-right {
  justify-content: flex-end;
}

.script-library-upload-target-text {
  max-width: 260px;
  min-width: 0;
  color: #667085;
  font-size: 12px;
  line-height: 32px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.script-library-filter-control {
  width: 180px;
}

.script-library-search {
  width: 220px;
}

.script-library-filter-control :deep(.el-input__wrapper),
.script-library-filter-control :deep(.el-select__wrapper) {
  min-height: 32px;
  border-radius: 10px;
}

.script-library-shell {
  display: grid;
  grid-template-columns: 280px minmax(0, 1fr);
  gap: 14px;
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
}

.script-library-tree,
.script-library-directory {
  min-height: 0;
  height: 100%;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.script-library-pane-scroll {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
  overflow-x: hidden;
  padding-right: 4px;
}

/* Match the Device Sidebar's translucent, lightweight scrollbar. */
.script-library-pane-scroll,
:global(.script-library-overlay > .el-overlay-dialog > .script-library-dialog > .el-dialog__body) {
  scrollbar-width: thin;
  scrollbar-color: rgba(148, 163, 184, 0.35) transparent;
}

.script-library-pane-scroll::-webkit-scrollbar,
:global(.script-library-overlay > .el-overlay-dialog > .script-library-dialog > .el-dialog__body::-webkit-scrollbar) {
  width: 8px;
  height: 8px;
}

.script-library-pane-scroll::-webkit-scrollbar-track,
:global(.script-library-overlay > .el-overlay-dialog > .script-library-dialog > .el-dialog__body::-webkit-scrollbar-track) {
  background: transparent;
}

.script-library-pane-scroll::-webkit-scrollbar-thumb,
:global(.script-library-overlay > .el-overlay-dialog > .script-library-dialog > .el-dialog__body::-webkit-scrollbar-thumb) {
  background: rgba(148, 163, 184, 0.38);
  border-radius: 999px;
  border: 2px solid transparent;
  background-clip: padding-box;
}

.script-library-pane-scroll::-webkit-scrollbar-thumb:hover,
:global(.script-library-overlay > .el-overlay-dialog > .script-library-dialog > .el-dialog__body::-webkit-scrollbar-thumb:hover) {
  background-color: rgba(148, 163, 184, 0.58);
}

.script-library-tree {
  background: #f8fafc;
  border-color: #e8edf3;
}

.script-library-directory {
  border-color: transparent;
}

.script-library-tree-title {
  display: flex;
  align-items: center;
  gap: 8px;
}

.script-library-tree-title > svg {
  color: var(--muted);
  flex: 0 0 auto;
}

.script-library-breadcrumb {
  display: flex;
  align-items: center;
  gap: 3px;
  min-width: 0;
  max-width: 100%;
  overflow-x: auto;
  scrollbar-width: thin;
  scrollbar-color: rgba(148, 163, 184, 0.35) transparent;
}

.script-library-breadcrumb-item {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  flex: 0 0 auto;
  max-width: 180px;
  min-height: 30px;
  padding: 3px 6px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--muted);
  font: inherit;
  font-size: 13px;
  cursor: pointer;
}

.script-library-breadcrumb-item > span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.script-library-breadcrumb-item > svg,
.script-library-breadcrumb-separator { flex: 0 0 auto; color: var(--muted); }
.script-library-breadcrumb-item:hover:not(:disabled),
.script-library-breadcrumb-item:focus-visible { background: #eef2f7; color: var(--primary); }
.script-library-breadcrumb-item.is-current { color: var(--text); font-weight: 650; cursor: default; }

.script-library-tree-view {
  min-height: 0;
  background: transparent;
  --el-tree-node-hover-bg-color: #eef2f7;
}

.script-library-tree-view :deep(.el-tree-node.is-current > .el-tree-node__content) {
  background: #e8f0ff;
  color: var(--primary);
  font-weight: 600;
}

.script-library-tree-view :deep(.el-tree-node__content) {
  min-width: 0;
  height: 30px;
  border-radius: 6px;
}

.script-tree-node {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  min-width: 0;
}

.script-tree-icon {
  flex: 0 0 auto;
  color: var(--muted);
}

.script-library-tree-view :deep(.el-tree-node.is-current > .el-tree-node__content) .script-tree-icon {
  color: var(--primary);
}

.script-tree-node-label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.script-library-directory-top {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  align-items: center;
  margin-bottom: 8px;
}

.script-library-directory-title-block {
  flex: 1 1 0;
  min-width: 0;
}

/* Folder and script cards use the same grid, spacing and icon dimensions. */
.script-library-folder-row {
  width: 100%;
  font: inherit;
  color: var(--text);
  text-align: left;
  cursor: pointer;
}

.script-library-folder-row .script-library-card-icon-tile {
  background: linear-gradient(150deg, #fffbf2, #fff0d9);
  box-shadow: inset 0 0 0 1px rgba(161, 98, 7, 0.10);
  color: #a16207;
}

.script-library-folder-name {
  min-width: 0;
  overflow-wrap: anywhere;
  font-weight: 600;
}

.script-library-parent-row {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 36px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: var(--muted);
  padding: 5px 8px;
}

.script-library-parent-row:hover,
.script-library-parent-row:focus-visible {
  background: #f8fafc;
}

.script-library-tree-toggle {
  flex: 0 0 auto;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  min-height: 32px;
  padding: 0 9px;
  border: 0;
  border-radius: 7px;
  background: transparent;
  color: var(--muted);
  font: inherit;
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
  cursor: pointer;
  transition: color 150ms ease, background-color 150ms ease;
}

.script-library-tree-toggle.is-open {
  color: var(--primary);
  background: #eef4ff;
}

.script-library-tree-toggle:hover {
  color: var(--primary);
  background: #e8f0ff;
}

.script-library-tree-toggle:focus-visible {
  outline: 2px solid var(--primary);
  outline-offset: 2px;
}

.script-library-tree-toggle > svg {
  flex: 0 0 auto;
}

.script-library-folder-list,
.script-library-card-list {
  display: grid;
  gap: 12px;
  padding: 2px 5px 8px 2px;
}

.script-library-card-list-single {
  grid-template-columns: 1fr;
}

.script-library-card,
.script-library-folder-row:not(.script-library-parent-row) {
  container-type: inline-size;
  min-width: 0;
  padding: 12px 14px;
  border: 1px solid rgba(148, 163, 184, 0.26);
  border-radius: 13px;
  background: var(--bg-card);
  box-shadow: 0 2px 5px rgba(15, 23, 42, 0.035), 0 6px 16px rgba(15, 23, 42, 0.035);
  transition: border-color 150ms ease, box-shadow 150ms ease;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 16px;
  align-items: center;
}

.script-library-card:hover,
.script-library-card:focus-within,
.script-library-folder-row:not(.script-library-parent-row):hover,
.script-library-folder-row:not(.script-library-parent-row):focus-visible {
  border-color: rgba(37, 99, 235, 0.32);
  box-shadow: 0 2px 6px rgba(15, 23, 42, 0.045), 0 7px 20px rgba(37, 99, 235, 0.07);
}

.script-library-card-main {
  min-width: 0;
  display: grid;
  grid-template-columns: 42px minmax(0, 1fr);
  column-gap: 13px;
  row-gap: 5px;
}

.script-library-card-main > :not(.script-library-card-icon-tile) {
  grid-column: 2;
}

.script-library-card-icon-tile {
  grid-column: 1;
  grid-row: 1 / span 2;
  align-self: center;
  width: 42px;
  height: 42px;
  display: grid;
  place-items: center;
  border-radius: 11px;
  background: linear-gradient(150deg, #f7faff, #eaf1ff);
  box-shadow: inset 0 0 0 1px rgba(37, 99, 235, 0.10);
  color: var(--primary);
}

.script-library-card-heading {
  display: flex;
  align-items: center;
  flex-wrap: nowrap;
  gap: 6px;
  min-width: 0;
}

.script-library-card-icon {
  flex: 0 0 auto;
}

.script-library-action-icon,
.script-library-tag-icon {
  flex: 0 0 auto;
  vertical-align: middle;
  margin-right: 5px;
}

.script-library-tag-icon {
  margin-right: 3px;
}

.script-library-card-title {
  min-width: 0;
  margin: 0;
  font-size: 15px;
  line-height: 22px;
  font-weight: 650;
  letter-spacing: -0.015em;
  color: var(--text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.script-library-card-description {
  min-width: 0;
  margin: 0;
  font-size: 13px;
  line-height: 19px;
  color: var(--muted);
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.script-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: flex-start;
  align-content: flex-start;
  min-height: 0;
  margin: auto 0 0;
}

.script-library-card-tags {
  margin: 0;
  align-items: center;
  flex: 0 1 auto;
  flex-wrap: nowrap;
  min-width: 0;
  max-width: 62%;
  gap: 5px;
}

.script-library-card-tags :deep(.el-tag) {
  border-radius: 999px;
  font-size: 11px;
  padding-inline: 7px;
  min-width: 0;
}

.script-library-card-tags :deep(.el-tag__content) {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.script-library-card-tags :deep(.el-tag--warning) {
  flex-shrink: 0;
}

.script-library-card-actions {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  flex-wrap: nowrap;
  white-space: nowrap;
  padding-left: 14px;
  border-left: 1px solid rgba(148, 163, 184, 0.18);
}

.script-library-folder-enter {
  min-height: 32px;
  justify-content: flex-end;
  color: var(--muted);
  font-size: 13px;
  font-weight: 500;
}

.script-library-empty {
  min-height: 120px;
}

.script-result-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
  margin-bottom: 12px;
}

.script-result-json-button {
  margin-left: auto;
  flex: 0 0 auto;
}

.script-result-path {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
  color: var(--el-text-color-regular);
}

.script-result-output {
  min-height: 220px;
  max-height: calc(100dvh - 190px);
  overflow: auto;
  margin: 0;
  padding: 14px;
  border: 1px solid var(--el-border-color);
  border-radius: 6px;
  background: var(--el-fill-color-light);
  white-space: pre-wrap;
  word-break: break-word;
  font-family: var(--el-font-family-monospace, ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace);
}

@media (max-width: 1024px) {
  .script-library-shell {
    grid-template-columns: 220px minmax(0, 1fr);
  }
}

.script-library-shell.script-library-tree-collapsed {
  grid-template-columns: minmax(0, 1fr);
}

@media (max-width: 760px) {
  .script-library-shell {
    grid-template-columns: minmax(0, 1fr);
    grid-template-rows: minmax(120px, 28%) minmax(0, 1fr);
  }

  .script-library-tree,
  .script-library-directory {
    height: auto;
    min-width: 0;
    width: 100%;
    box-sizing: border-box;
  }

  .script-library-directory { padding: 0; border: 0; }
  .script-library-directory .script-library-pane-scroll { padding-right: 0; }
  .script-library-folder-list,
  .script-library-card-list { padding: 2px 0 8px; }
  .script-library-directory-top { gap: 6px; }

  .script-library-shell.script-library-tree-collapsed { grid-template-rows: minmax(0, 1fr); }
}

@media (max-width: 768px), (max-height: 720px) {
  .script-library-toolbar,
  .script-library-toolbar-left,
  .script-library-toolbar-right {
    align-items: stretch;
  }

  .script-library-toolbar-left,
  .script-library-toolbar-right,
  .script-library-filter-control,
  .script-library-search,
  .script-library-upload-target-text {
    width: 100%;
    max-width: none;
  }
}
.script-library-card-actions :deep(.el-button) {
  height: 32px;
  border-radius: 8px;
  padding-inline: 10px;
  justify-content: center;
}

.script-library-card-actions :deep(.el-button--primary.is-plain) {
  font-weight: 600;
  background: var(--primary);
  border-color: var(--primary);
  color: #fff;
}

.script-library-card-actions :deep(.el-button--primary.is-plain:hover),
.script-library-card-actions :deep(.el-button--primary.is-plain:focus-visible) {
  background: #1d4ed8;
  border-color: #1d4ed8;
  color: #fff;
}

.script-library-card-actions :deep(.el-button--primary.is-disabled),
.script-library-card-actions :deep(.el-button--primary.is-disabled:hover) {
  background: var(--el-disabled-bg-color);
  border-color: var(--el-disabled-border-color);
  color: var(--el-disabled-text-color);
}

.script-library-card-actions :deep(.el-button.is-plain:not(.el-button--primary)) {
  border-color: transparent;
  background: transparent;
}

.script-library-card-actions :deep(.el-button.is-plain:not(.el-button--primary):hover),
.script-library-card-actions :deep(.el-button.is-plain:not(.el-button--primary):focus-visible) {
  background: #f1f5f9;
  border-color: #e8edf3;
}

.script-library-card-actions :deep(.el-dropdown) { flex: 0 0 auto; }

/* Keep the compact desktop actions beside the text until the card needs a second row. */
@container (width < 520px) {
  .script-library-card-main { grid-column: 1 / -1; }
  .script-library-card-actions {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    grid-column: 1 / -1;
    width: 100%;
    gap: 8px;
    align-items: stretch;
    padding: 10px 0 0;
    border-left: 0;
    border-top: 1px solid rgba(148, 163, 184, 0.18);
  }
  .script-library-card-actions :deep(.el-button),
  .script-library-card-actions :deep(.el-dropdown) { width: 100%; min-width: 0; }
  .script-library-folder-enter {
    display: flex;
    min-height: 43px;
  }
}

/* Keep all three actions together on narrow cards, with touch-friendly targets. */
@container (width < 420px) {
  .script-library-card-actions { gap: 5px; }
  .script-library-card-actions :deep(.el-button) { height: 32px; padding: 0 5px; }
  .script-library-card-main { grid-template-columns: 30px minmax(0, 1fr); column-gap: 8px; }
  .script-library-card-icon-tile { width: 30px; height: 30px; }
}

@media (max-width: 640px) {
  .script-library-toolbar-left {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 6px;
  }
  .script-library-toolbar :deep(.el-button.toolbar-btn) {
    width: 100%;
    min-width: 0;
    padding: 0 5px;
  }
  .script-library-card,
  .script-library-folder-row:not(.script-library-parent-row) { padding: 10px; gap: 10px; }
  .script-library-toolbar-right .script-library-search {
    flex: 1 1 120px;
    width: auto;
    min-width: 0;
  }
  .script-library-toolbar-right { justify-content: flex-start; }
  .script-library-breadcrumb-item { max-width: 112px; }
}
</style>

<style>
/* ScriptLibraryDialog: 固定弹窗高度，树和脚本列表各自滚动。 */
.script-library-overlay .el-overlay-dialog {
  overflow: hidden !important;
}

.script-library-overlay .el-dialog {
  height: 72vh !important;
  max-height: 72vh !important;
  margin-top: 6vh !important;
  display: flex !important;
  flex-direction: column !important;
  overflow: hidden !important;
}

.script-library-overlay .el-dialog__header {
  flex: 0 0 auto !important;
}

.script-library-overlay .el-dialog__body {
  display: flex !important;
  flex: 1 1 auto !important;
  min-height: 0 !important;
  height: auto !important;
  overflow: hidden !important;
  padding-top: 8px !important;
  padding-bottom: 12px !important;
}

.script-library-overlay .script-library-body {
  flex: 1 1 auto !important;
  min-height: 0 !important;
  height: auto !important;
  overflow: hidden !important;
}

@media (max-width: 768px) {
  .script-library-overlay .el-dialog {
    width: 100vw !important;
    max-width: 100vw !important;
    height: 100dvh !important;
    max-height: 100dvh !important;
    margin: 0 !important;
    border-radius: 0 !important;
  }

  .script-library-overlay .el-dialog__header {
    padding: 14px 16px 10px !important;
  }

  .script-library-overlay .el-dialog__body {
    padding: 10px 12px 12px !important;
  }
}
</style>
<style>
@media (max-width: 640px) {
  .script-library-overlay .el-dialog__body {
    overflow-y: auto !important;
    overscroll-behavior: contain;
  }
  .script-library-overlay .script-library-body {
    height: auto !important;
    flex: 1 1 auto !important;
    overflow: visible !important;
    min-width: 0;
  }
  .script-library-overlay .script-library-shell {
    max-width: 100%;
    /* Retain the original single-column grid and its width constraints. */
    grid-template-columns: minmax(0, 1fr);
    grid-template-rows: 226px auto;
    height: auto !important;
    flex: 0 0 auto !important;
    overflow: visible !important;
    min-width: 0;
  }
  .script-library-overlay .script-library-tree {
    height: 226px !important;
    min-height: 0 !important;
    overflow: hidden !important;
    min-width: 0;
  }
  .script-library-overlay .script-library-shell.script-library-tree-collapsed {
    grid-template-rows: auto;
  }
  .script-library-overlay .script-library-directory {
    max-width: 100%;
    height: auto !important;
    min-width: 0;
    overflow: visible !important;
  }
  .script-library-overlay .script-library-directory .script-library-pane-scroll {
    overflow: visible !important;
  }
}
</style>
