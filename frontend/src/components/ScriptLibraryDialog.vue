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
            New
          </el-button>

          <el-button
            size="small"
            class="toolbar-btn"
            :loading="uploadLoading"
            @click="triggerScriptUpload"
          >
            Upload
          </el-button>

          <el-button
            size="small"
            class="toolbar-btn"
            @click="createRemoteScriptFolderPrompt"
          >
            New Folder
          </el-button>

          <el-button
            size="small"
            class="toolbar-btn"
            :disabled="!selectedDirectory"
            @click="renameRemoteScriptFolder"
          >
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
            Delete Folder
          </el-button>

          <el-button
            size="small"
            class="toolbar-btn"
            :loading="loading"
            @click="loadScriptCatalog"
          >
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
          />
        </div>
      </div>

      <div class="script-library-shell">
        <div class="script-library-tree panel-lite">
          <div class="background-jobs-section-title">Folders</div>

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
            <div class="script-library-directory-title-block">
              <div class="background-jobs-section-title">
                {{ selectedDirectory || 'Scripts' }}
              </div>

              <div class="background-job-module-key mono">
                {{ scriptDirectoryItemCountText }}
              </div>
            </div>
          </div>

          <div class="script-library-pane-scroll">
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
                  <div
                    class="script-library-card-title"
                    :title="item.display_name || item.script_name"
                  >
                    {{ item.display_name || item.script_name }}
                  </div>

                  <div
                    class="script-library-card-path mono"
                    :title="item.path || item.script_name"
                  >
                    {{ item.path || item.script_name }}
                  </div>

                  <div
                    class="script-library-card-description"
                    :title="item.description || ''"
                  >
                    {{ item.description || 'No description' }}
                  </div>

                  <div class="script-tags script-library-card-tags">
                    <el-tag
                      size="small"
                      :type="isScriptSupportedForCurrentConnection(item) ? 'info' : 'danger'"
                    >
                      {{ formatScriptPlatformLabel(item) }}
                    </el-tag>

                    <el-tag
                      v-if="scriptHasParams(item)"
                      size="small"
                      type="warning"
                    >
                      Params
                    </el-tag>
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
                    Run
                  </el-button>

                  <el-button
                    size="small"
                    plain
                    @click="openRemoteScriptEditor(item.script_name)"
                  >
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
                      More
                    </el-button>

                    <template #dropdown>
                      <el-dropdown-menu>
                        <el-dropdown-item command="rename">
                          Rename
                        </el-dropdown-item>

                        <el-dropdown-item command="delete">
                          Delete
                        </el-dropdown-item>
                      </el-dropdown-menu>
                    </template>
                  </el-dropdown>
                </div>
              </div>
            </div>

            <div
              v-else
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
    :submitting="scriptRunSubmitting"
    :selected-id="selectedId"
    :get-tab-scoped-headers="getTabScopedHeaders"
    :is-script-supported-for-current-connection="isScriptSupportedForCurrentConnection"
    :format-script-platform-label="formatScriptPlatformLabel"
    @update-param="updateScriptParam"
    @append-output="forwardAppendOutput"
    @set-active-task="forwardSetActiveTask"
    @upload-started="$emit('upload-started', $event)"
    @cancel="closeScriptRunDialog"
    @confirm="confirmRunScript"
  />
</template>

<script>
import { ElMessage, ElMessageBox } from 'element-plus'
import ScriptRunDialog from './ScriptRunDialog.vue'
import { TERMINAL_RUN_SCRIPT_PREFIX } from '../composables/terminalMarkers.js'
import { cloneParamValue, normalizeParamSpecs, normalizeParamType } from '../utils/parameterSchema.js'

export default {
  name: 'ScriptLibraryDialog',

  components: {
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
      scriptTreeRenderKey: 0,
      scriptTreeExpandedKeys: [],
      scriptDirectorySelectionContextKey: '',
      scriptRunDialogVisible: false,
      scriptRunSubmitting: false,
      pendingRunScriptName: '',
      scriptParamForm: {},
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
      const sourceItems = keyword
        ? this.currentScriptDirectoryRecursiveItems
        : this.currentScriptDirectoryItems

      const items = sourceItems.filter(item => {
        if (!keyword) return true

        const values = [
          item.display_name,
          item.script_name,
          item.path,
          item.description,
        ].map(value => String(value || '').toLowerCase())

        return values.some(value => value.includes(keyword))
      })

      return this.sortScriptItems(items)
    },

    hasScriptSearch() {
      return !!String(this.scriptSearchText || '').trim()
    },

    scriptDirectoryItemCountText() {
      const total = this.hasScriptSearch
        ? this.currentScriptDirectoryRecursiveItems.length
        : this.currentScriptDirectoryItems.length

      const visible = this.filteredCurrentScriptDirectoryItems.length
      const suffix = total === 1 ? 'script' : 'scripts'

      if (this.hasScriptSearch) {
        return `${visible} / ${total} ${suffix}`
      }

      return `${total} ${suffix}`
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
  },

  watch: {
    scriptRunDialogVisible(value) {
      if (!value) this.closeScriptRunDialog()
    },
  },

  methods: {
    forwardAppendOutput(clientId, line, kind) {
      this.$emit('append-output', clientId, line, kind)
    },

    forwardSetActiveTask(clientId, taskId) {
      this.$emit('set-active-task', clientId, taskId)
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
  const machineId = String(
    connection.machine_id
    || connection.client_id
    || this.selectedId
    || ''
  ).trim()

  const platform = String(this.resolvePreferredScriptDirectoryPlatform() || '').trim()

  return `${machineId}::${platform}`
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
        const res = await fetch('/api/scripts/catalog')
        const json = await res.json()
        if (!res.ok || json.code !== 0) {
          throw new Error(json.message || 'Failed to load script catalog')
        }

        const catalog = json.data || {}
        this.scriptCatalogItems = Array.isArray(catalog.items) ? catalog.items : []
        this.scriptCatalogDirectories = Array.isArray(catalog.directories) ? catalog.directories : [{ key: 'dir:.', label: 'root', path: '' }]

        // if (!this.selectedDirectory) {
        //   this.selectedDirectory = this.getFirstAvailableScriptDirectory()
        // } else {
        //   const hasCurrentDir = this.scriptCatalogDirectories.some(item => this.normalizeScriptDirectoryPath(item?.path || '') === this.selectedDirectory)
        //   if (!hasCurrentDir) this.selectedDirectory = this.getFirstAvailableScriptDirectory()
        // }

//         if (options?.selectForConnection) {
//   const preferredDirectory = this.getPreferredScriptDirectoryForCurrentConnection()
//   this.selectedDirectory = preferredDirectory || this.getFirstAvailableScriptDirectory()
//
//   if (this.selectedDirectory) {
//     this.scriptTreeExpandedKeys = this.includeScriptTreeAncestorKeys([
//       ...this.scriptTreeExpandedKeys,
//       this.getScriptDirectoryTreeKey(this.selectedDirectory),
//     ])
//   }
// } else if (!this.selectedDirectory) {

//         if (options?.selectForConnection) {
//   const preferredDirectory = this.getPreferredScriptDirectoryForCurrentConnection()
//   this.selectedDirectory = preferredDirectory || this.getFirstAvailableScriptDirectory()
//
//   // 打开弹窗时只展开当前设备对应目录路径，不沿用上次手动展开状态。
//   this.scriptTreeExpandedKeys = this.selectedDirectory
//     ? this.includeScriptTreeAncestorKeys([
//       this.getScriptDirectoryTreeKey(this.selectedDirectory),
//     ])
//     : []
// } else if (!this.selectedDirectory) {
//   this.selectedDirectory = this.getFirstAvailableScriptDirectory()
// } else {
//   const hasCurrentDir = this.scriptCatalogDirectories.some(item => this.normalizeScriptDirectoryPath(item?.path || '') === this.selectedDirectory)
//   if (!hasCurrentDir) this.selectedDirectory = this.getFirstAvailableScriptDirectory()
// }

        if (options?.selectForConnection) {
  const selectionContextKey = this.getScriptDirectorySelectionContextKey()
  const currentDirectory = this.normalizeScriptDirectoryPath(this.selectedDirectory)

  const hasCurrentDir = this.scriptCatalogDirectories.some(item => {
    return this.normalizeScriptDirectoryPath(item?.path || '') === currentDirectory
  })

  if (
    selectionContextKey
    && selectionContextKey === this.scriptDirectorySelectionContextKey
    && hasCurrentDir
  ) {
    // 同一台机器 + 同一 platform：保留上次操作目录。
    this.selectedDirectory = currentDirectory
  } else {
    // 切换机器或 platform：回到当前 platform 的目录。
    const preferredDirectory = this.getPreferredScriptDirectoryForCurrentConnection()
    this.selectedDirectory = preferredDirectory || this.getFirstAvailableScriptDirectory()
  }

  this.scriptDirectorySelectionContextKey = selectionContextKey

  this.scriptTreeExpandedKeys = this.selectedDirectory
    ? this.includeScriptTreeAncestorKeys([
      this.getScriptDirectoryTreeKey(this.selectedDirectory),
    ])
    : []
} else if (!this.selectedDirectory) {
  this.selectedDirectory = this.getFirstAvailableScriptDirectory()
} else {
  const hasCurrentDir = this.scriptCatalogDirectories.some(item => this.normalizeScriptDirectoryPath(item?.path || '') === this.selectedDirectory)
  if (!hasCurrentDir) this.selectedDirectory = this.getFirstAvailableScriptDirectory()
}

        this.scriptTreeExpandedKeys = this.filterExistingScriptTreeExpandedKeys(this.scriptTreeExpandedKeys)
        this.scriptTreeRenderKey += 1
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

    resolvePreferredScriptDirectoryPlatform() {
  const connection = this.currentConnection || {}
  const candidates = [
    this.currentConnectionPlatform,
    connection.os_alias,
    connection.os_type,
    connection.type,
    connection.platform,
    connection.system,
    connection.os,
    connection.os_name,
  ]

  for (const candidate of candidates) {
    const text = String(candidate || '').trim().toLowerCase()
    if (!text) continue

    if (text.includes('ios') || text.includes('iphone') || text.includes('ipad')) {
      return 'ios'
    }

    const normalized = this.normalizeClientPlatform(text)
    if (normalized) return normalized
  }

  return ''
},
//
// getPreferredScriptDirectoryForCurrentConnection() {
//   const platform = this.resolvePreferredScriptDirectoryPlatform()
//   const platformAliases = {
//     mac: ['mac', 'macos', 'darwin', 'osx'],
//     win: ['win', 'windows', 'win32', 'nt'],
//     linux: ['linux', 'ubuntu', 'debian', 'centos', 'fedora', 'redhat', 'rhel', 'alpine', 'arch'],
//     ios: ['ios', 'iphone', 'ipad', 'iphoneos', 'ipados'],
//   }
//
//   const aliases = platformAliases[platform] || (platform ? [platform] : [])
//   const aliasSet = new Set(aliases.map(item => String(item || '').toLowerCase()))
//
//   if (!aliasSet.size) return ''
//
//   const directories = (this.scriptCatalogDirectories || [])
//     .map(item => this.normalizeScriptDirectoryPath(item?.path || ''))
//     .filter(Boolean)
//     .sort((a, b) => a.localeCompare(b))
//
//   const matchesPlatformRoot = (directory) => {
//     const root = String(directory || '').split('/').filter(Boolean)[0]?.toLowerCase() || ''
//     return aliasSet.has(root)
//   }
//
//   const hasDirectScripts = (directory) => {
//     return (this.scriptCatalogItems || []).some(item => this.getScriptItemDirectory(item) === directory)
//   }
//
//   const exactDirectory = directories.find(directory => aliasSet.has(directory.toLowerCase()))
//
//   if (exactDirectory && hasDirectScripts(exactDirectory)) {
//     return exactDirectory
//   }
//
//   const scriptDirectory = directories.find(directory => matchesPlatformRoot(directory) && hasDirectScripts(directory))
//   if (scriptDirectory) return scriptDirectory
//
//   return exactDirectory || directories.find(matchesPlatformRoot) || ''
// },



getPreferredScriptDirectoryForCurrentConnection() {
  const platform = this.resolvePreferredScriptDirectoryPlatform()
  const platformAliases = {
    mac: ['mac', 'macos', 'darwin', 'osx'],
    win: ['win', 'windows', 'win32', 'nt'],
    linux: ['linux', 'ubuntu', 'debian', 'centos', 'fedora', 'redhat', 'rhel', 'alpine', 'arch'],
    ios: ['ios', 'iphone', 'ipad', 'iphoneos', 'ipados'],
  }

  const aliases = platformAliases[platform] || (platform ? [platform] : [])
  const aliasSet = new Set(aliases.map(item => String(item || '').toLowerCase()))

  if (!aliasSet.size) return ''

  const directories = (this.scriptCatalogDirectories || [])
    .map(item => this.normalizeScriptDirectoryPath(item?.path || ''))
    .filter(Boolean)
    .sort((a, b) => a.localeCompare(b))

  const matchesPlatformRoot = (directory) => {
    const root = String(directory || '').split('/').filter(Boolean)[0]?.toLowerCase() || ''
    return aliasSet.has(root)
  }

  // 只选 platform 当前目录，不再找“第一个有脚本内容的目录”。
  const exactDirectory = directories.find(directory => aliasSet.has(directory.toLowerCase()))
  if (exactDirectory) return exactDirectory

  return directories.find(matchesPlatformRoot) || ''
},


    getParentScriptDirectory(directory) {
      const normalized = this.normalizeScriptDirectoryPath(directory)
      if (!normalized) return ''

      const parts = normalized.split('/').filter(Boolean)
      return parts.slice(0, -1).join('/')
    },

    handleScriptTreeNodeClick(node) {
      if (!node) return
      this.selectedDirectory = this.normalizeScriptDirectoryPath(node.path || '')
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

    normalizeClientPlatform(osType = '') {
      const value = String(osType || '').trim().toLowerCase()
      if (!value) return ''
      if (value.includes('darwin') || value.includes('mac')) return 'mac'
      if (value.includes('win')) return 'win'
      if (value.includes('linux')) return 'linux'
      if (/(ubuntu|debian|centos|fedora|redhat|rhel|alpine|arch)/.test(value)) return 'linux'
      return this.normalizeScriptPlatform(value)
    },

    resolveCurrentConnectionPlatform() {
      const conn = this.currentConnection || {}
      const candidates = [
        conn.os_alias,
        conn.os_type,
        conn.platform,
        conn.system,
        conn.os,
        conn.os_name,
      ]

      for (const candidate of candidates) {
        const normalized = this.normalizeClientPlatform(candidate)
        if (['mac', 'win', 'linux', 'ios'].includes(normalized)) return normalized
      }

      for (const candidate of candidates) {
        const normalized = this.normalizeClientPlatform(candidate)
        if (normalized) return normalized
      }

      return ''
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
          if (['remote_files', 'remote_folders'].includes(type)) {
            result[param.name] = Array.isArray(param.default) ? cloneParamValue(param.default) : []
          } else if (type === 'boolean') {
            result[param.name] = param.default === true || String(param.default).toLowerCase() === 'true'
          } else {
            result[param.name] = cloneParamValue(param.default)
          }
        } else if (['remote_files', 'remote_folders'].includes(type)) {
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

    coerceScriptParamValue(param, rawValue) {
      const type = normalizeParamType(param?.type)
      if (type === 'boolean') return !!rawValue

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

    openScriptRunDialog(item) {
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
      this.scriptRunDialogVisible = true
    },

    closeScriptRunDialog() {
      this.scriptRunDialogVisible = false
      this.scriptRunSubmitting = false
      this.pendingRunScriptName = ''
      this.scriptParamForm = {}
    },


    async runScriptFromTerminalBlock(payload = {}) {
  const scriptName = String(payload.script_name || '').trim()
  const params = payload.params && typeof payload.params === 'object' && !Array.isArray(payload.params)
    ? { ...payload.params }
    : {}
  const displayName = String(payload.script_display_name || scriptName).trim()
  const scriptPath = String(payload.script_path || `${scriptName}.py`).trim()

  if (!this.selectedId) {
    ElMessage.warning('Please select a device')
    return
  }

  if (!scriptName) {
    ElMessage.warning('Missing script name')
    return
  }

  try {
    const commandText = `> ${TERMINAL_RUN_SCRIPT_PREFIX} ${displayName || scriptName}`
    this.$emit('append-output', this.selectedId, commandText, 'command', {
      terminal_block_type: 'script',
      script_name: scriptName,
      script_path: scriptPath,
      script_display_name: displayName || scriptName,
      params: { ...params },
    })

    const res = await fetch(`/api/connections/${encodeURIComponent(this.selectedId)}/scripts/run`, {
      method: 'POST',
      headers: this.buildJsonHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ script_name: scriptName, params }),
    })
    const json = await res.json()
    if (!res.ok || json.code !== 0) throw new Error(json.message || 'Failed to run script')

    const taskId = json.data && json.data.task_id
    this.$emit('set-active-task', this.selectedId, taskId || '')
    ElMessage.success(`Run request submitted: ${displayName || scriptName}`)
  } catch (e) {
    ElMessage.error(e.message || 'Failed to run script')
  }
},




    async confirmRunScript() {
      const item = this.pendingRunScriptItem
      if (!item) {
        this.closeScriptRunDialog()
        return
      }

      if (!this.selectedId) {
        ElMessage.warning('Please select a device')
        return
      }

      try {
        this.scriptRunSubmitting = true
        const params = this.buildScriptRunParams(item)

        const commandText = `> ${TERMINAL_RUN_SCRIPT_PREFIX} ${item.display_name || item.script_name}`
        this.$emit('append-output', this.selectedId, commandText, 'command', {
          terminal_block_type: 'script',
          script_name: item.script_name || '',
          script_path: item.path || `${item.script_name || ''}.py`,
          script_display_name: item.display_name || item.script_name || '',
          params: { ...params },
        })

        const res = await fetch(`/api/connections/${encodeURIComponent(this.selectedId)}/scripts/run`, {
          method: 'POST',
          headers: this.buildJsonHeaders({ 'Content-Type': 'application/json' }),
          body: JSON.stringify({ script_name: item.script_name, params }),
        })
        const json = await res.json()
        if (!res.ok || json.code !== 0) throw new Error(json.message || 'Failed to run script')

        const taskId = json.data && json.data.task_id
        this.$emit('set-active-task', this.selectedId, taskId || '')
        ElMessage.success(`Run request submitted: ${item.display_name || item.script_name}`)
        this.closeScriptRunDialog()
      } catch (e) {
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

        const res = await fetch('/api/scripts/folders', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ directory }),
        })
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

        const res = await fetch('/api/scripts/folders/rename', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            directory: currentDirectory,
            new_directory: newDirectory,
          }),
        })
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

        const res = await fetch('/api/scripts/folders', {
          method: 'DELETE',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ directory: currentDirectory }),
        })
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

        const res = await fetch('/api/scripts/rename', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name: normalized, new_name: newName }),
        })
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

        const res = await fetch('/api/scripts/upload', {
          method: 'POST',
          body: formData,
        })

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

        const res = await fetch('/api/scripts/delete', {
          method: 'DELETE',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name: normalized }),
        })
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

.script-library-tree-view {
  min-height: 0;
}

.script-library-tree-view :deep(.el-tree-node__content) {
  min-width: 0;
  height: 30px;
  border-radius: 8px;
}

.script-tree-node {
  display: inline-flex;
  align-items: center;
  min-width: 0;
}

.script-tree-node-label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.script-library-directory-top {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
  margin-bottom: 12px;
}

.script-library-directory-title-block {
  min-width: 0;
}

.script-library-card-list {
  display: grid;
  gap: 12px;
}

.script-library-card-list-single {
  grid-template-columns: 1fr;
}

.script-library-card {
  min-width: 0;
  padding: 14px 16px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 18px;
  background: #fff;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 16px;
  align-items: center;
}

.script-library-card-main {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.script-library-card-title {
  min-width: 0;
  margin: 0;
  font-size: 15px;
  line-height: 22px;
  font-weight: 600;
  color: var(--text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.script-library-card-path {
  min-width: 0;
  margin: 0;
  font-size: 12px;
  line-height: 18px;
  color: var(--muted);
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
  word-break: break-word;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
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
  margin-top: 2px;
}

.script-library-card-actions {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  flex-wrap: nowrap;
  white-space: nowrap;
}

.script-library-empty {
  min-height: 120px;
}

@media (max-width: 1024px) {
  .script-library-shell {
    grid-template-columns: 220px minmax(0, 1fr);
  }

  .script-library-card {
    grid-template-columns: 1fr;
    align-items: flex-start;
  }

  .script-library-card-actions {
    justify-content: flex-end;
    width: 100%;
    flex-wrap: wrap;
  }
}

@media (max-width: 760px) {
  .script-library-shell {
    grid-template-columns: 1fr;
    grid-template-rows: minmax(120px, 28%) minmax(0, 1fr);
  }

  .script-library-tree,
  .script-library-directory {
    height: auto;
  }
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

@media (max-width: 768px), (max-height: 720px) {
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