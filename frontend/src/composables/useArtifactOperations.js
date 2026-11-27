import { ElMessage, ElMessageBox } from 'element-plus'
import { getArtifactDetail, renameArtifact as requestRenameArtifact, deleteArtifact as deleteArtifactRequest, clearArtifacts } from '../api/artifactsApi.js'
import { ARTIFACT_TYPE } from '../data/artifactConstants.js'
import { formatArtifactInfoSections } from '../utils/artifactPresentation.js'

export default {
  data() {
    return {
      artifactClearing: false,
      artifactBulkDeleting: false,
      artifactInfoDialogVisible: false,
      artifactInfoItem: null,
      artifactInfoSeq: 0,
    }
  },
  computed: {
    formattedArtifactInfoSections() {
      return formatArtifactInfoSections(this.artifactInfoItem)
    },
  },
  methods: {
    async requestArtifactMutation(request, fallback) {
      const response = await request
      const json = await response.json()
      if (!response.ok || json.code !== 0) throw new Error(json.message || fallback)
      await this.loadArtifacts()
      return json.data || {}
    },

    async openArtifactInfoDialog(row) {
      if (!row || !row.artifact_id) {
        ElMessage.warning('Invalid artifact')
        return
      }
      const seq = ++this.artifactInfoSeq
      try {
        const res = await getArtifactDetail(row.artifact_id)
        const json = await res.json()
        if (!res.ok || json.code !== 0) throw new Error(json.message || 'Failed to load artifact')
        if (seq !== this.artifactInfoSeq || !this.visible) return
        this.artifactInfoItem = json.data || null
        this.artifactInfoDialogVisible = true
      } catch (error) {
        if (seq === this.artifactInfoSeq && this.visible) ElMessage.error(error.message || 'Failed to load artifact')
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
      if (this.artifactClearing) return
      const scope = this.artifactActiveTab
      const folderId = this.selectedFolderId
      const machineId = this.isSharedFilesTab ? '' : this.artifactMachineIdFilter
      this.artifactClearing = true
      try {
        const where = folderId ? ` in ${this.folderNameForArtifact({ folder_id: folderId })}` : ''
        const device = machineId ? ' for selected device' : ''
        const message = scope === ARTIFACT_TYPE.SHARED
          ? `Clear all Shared files and subfolders${where}?${folderId ? ' This folder will be kept.' : ''}`
          : `Clear all ${scope} files${where}${device}?`
        await ElMessageBox.confirm(message,
          'Clear Artifacts', { type: 'warning', confirmButtonText: 'Clear', cancelButtonText: 'Cancel' })
        const result = await this.requestArtifactMutation(clearArtifacts(scope, machineId, folderId), 'Clear failed')
        ElMessage.success(scope === ARTIFACT_TYPE.SHARED
          ? `Cleared ${result.deleted_count || 0} file(s), ${result.deleted_folder_count || 0} folder(s)`
          : `Cleared ${result.deleted_count || 0} item(s)`)
      } catch (error) {
        if (!this.isDialogCancel(error)) {
          ElMessage.error(error.message || 'Clear failed')
          await this.loadArtifacts()
        }
      } finally {
        this.artifactClearing = false
      }
    },
  },
}
