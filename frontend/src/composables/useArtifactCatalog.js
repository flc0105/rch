import { ElMessage } from 'element-plus'
import { listArtifacts } from '../api/artifactsApi.js'
import { ARTIFACT_TYPE, ARTIFACT_FOLDER_ALL } from '../data/artifactConstants.js'
import { formatArtifactName, isSharedFileItem, useArtifactMoreMenu } from '../utils/artifactPresentation.js'

export default {
  data() {
    return {
      artifactLoading: false,
      artifactItems: [],
      artifactMachines: [],
      artifactActiveTab: ARTIFACT_TYPE.SAVED,
      artifactFolders: [],
      selectedFolderId: '',
      artifactMachineIdFilter: '',
      artifactKeyword: '',
      selectedArtifactIds: [],
      artifactLoadSeq: 0,
    }
  },
  computed: {
    isSharedFilesTab() {
      return this.artifactActiveTab === ARTIFACT_TYPE.SHARED
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
        .filter(folder => folder.artifact_type === this.artifactActiveTab)
      const nodes = folders.map(folder => ({ ...folder, children: [] }))
      const byId = Object.fromEntries(nodes.map(node => [node.folder_id, node]))
      const roots = []
      nodes.forEach(node => {
        if (node.parent_id && byId[node.parent_id]) byId[node.parent_id].children.push(node)
        else roots.push(node)
      })
      return [{ folder_id: ARTIFACT_FOLDER_ALL, name: 'All Files', children: [] }, ...roots]
    },

    canEditSelectedFolder() {
      const folder = (this.artifactFolders || []).find(item => item.folder_id === this.selectedFolderId)
      return Boolean(this.isSharedFilesTab && folder && !folder.is_preset)
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
        if (item.artifact_type !== this.artifactActiveTab) return false
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
        if (!Object.prototype.hasOwnProperty.call(counts, item.artifact_type)) return
        if (item.artifact_type === ARTIFACT_TYPE.SAVED && machineId && this.normalizeMachineId(item.machine_id) !== machineId) return
        counts[item.artifact_type] += 1
      })
      return counts
    },

  },
  methods: {
    formatArtifactName, isSharedFileItem, useArtifactMoreMenu,
    folderNameForArtifact(item) {
      return (this.artifactFolders || []).find(folder => folder.folder_id === item?.folder_id)?.name || 'Unfiled'
    },

    handleFolderSelect(node) {
      this.selectedFolderId = node.folder_id === ARTIFACT_FOLDER_ALL ? '' : node.folder_id
      this.selectedArtifactIds = []
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

    handleArtifactSelectionChange(rows) {
      this.selectedArtifactIds = (rows || [])
        .map(item => String(item?.artifact_id || '').trim())
        .filter(Boolean)
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
      this.artifactActiveTab = tabName || ARTIFACT_TYPE.SAVED
      this.selectedFolderId = ''
      this.selectedArtifactIds = []
      await this.loadArtifacts()
    },

    handleMachineFilterChange() {
      this.selectedArtifactIds = []
    },

    async loadArtifacts() {
      const seq = ++this.artifactLoadSeq
      this.artifactLoading = true

      try {
        const res = await listArtifacts()
        const json = await res.json()

        if (!res.ok || json.code !== 0) {
          throw new Error(json.message || 'Failed to load artifacts')
        }

        if (seq !== this.artifactLoadSeq) return
        const data = json.data || {}
        this.artifactItems = Array.isArray(data.items) ? data.items : []
        this.artifactMachines = Array.isArray(data.machines) ? data.machines : []
        this.artifactFolders = Array.isArray(data.folders) ? data.folders : []
        if (this.isSharedFilesTab && this.selectedFolderId && !this.artifactFolders.some(folder => folder.folder_id === this.selectedFolderId)) {
          this.selectedFolderId = ''
        }
        this.pruneArtifactSelection()
      } catch (e) {
        if (seq !== this.artifactLoadSeq) return
        this.artifactItems = []
        this.artifactMachines = []
        this.artifactFolders = []
        ElMessage.error(e.message || 'Failed to load artifacts')
      } finally {
        if (seq === this.artifactLoadSeq) this.artifactLoading = false
      }
    },

    pruneArtifactSelection() {
      const available = new Set(
        (this.artifactItems || [])
          .map(item => String(item?.artifact_id || '').trim())
          .filter(Boolean)
      )
      this.selectedArtifactIds = this.selectedArtifactIds.filter(item => available.has(item))
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
}
