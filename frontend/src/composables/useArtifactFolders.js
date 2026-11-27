import { ElMessage, ElMessageBox } from 'element-plus'
import { createArtifactFolder, renameArtifactFolder, deleteArtifactFolder, moveArtifactToFolder } from '../api/artifactsApi.js'
import { ARTIFACT_TYPE } from '../data/artifactConstants.js'

export default {
  data() {
    return {
      moveDialogVisible: false,
      moveArtifactItem: null,
      moveTargetFolderId: '',
    }
  },
  computed: {
    moveFolderOptions() {
      return (this.artifactFolders || []).filter(folder =>
        folder.artifact_type === ARTIFACT_TYPE.SHARED &&
        this.moveArtifactItem?.artifact_type === ARTIFACT_TYPE.SHARED)
    },

  },
  methods: {
    async createFolderPrompt() {
      if (!this.isSharedFilesTab) return
      const parentId = this.selectedFolderId
      try {
        const { value } = await ElMessageBox.prompt('Folder name', 'New Folder', {
          inputPattern: /\S/, inputErrorMessage: 'Folder name is required',
        })
        await this.requestArtifactMutation(createArtifactFolder(ARTIFACT_TYPE.SHARED,
          String(value || '').trim(), parentId), 'Failed to create folder')
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
      const folderId = this.selectedFolderId
      try {
        await ElMessageBox.confirm('Delete this folder and all its files and subfolders?', 'Delete Folder', { type: 'warning' })
        await this.requestArtifactMutation(deleteArtifactFolder(folderId), 'Failed to delete folder')
      } catch (error) {
        if (!this.isDialogCancel(error)) {
          ElMessage.error(error.message || 'Failed to delete folder')
          await this.loadArtifacts()
        }
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

  },
}
