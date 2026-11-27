import { ElMessage } from 'element-plus'
import { promptCreateRemoteFolder } from '../utils/remoteFolderCreation.js'

export default {
  data() { return { remoteCreatingFolder: false } },
  methods: {
    async createRemoteDirectory() {
      if (this.remoteCreatingFolder) return
      const context = this.captureRemoteFilesContext()
      if (!context.clientId) {
        ElMessage.warning('Please select a device')
        return
      }
      const parentPath = this.remoteFilesCurrentPath
      if (!parentPath) {
        ElMessage.warning('Current directory is empty')
        return
      }
      const isActive = () => this.isRemoteFilesContextActive(context) && this.remoteFilesCurrentPath === parentPath && !this.remoteFilesLoading
      this.remoteCreatingFolder = true
      try {
        if (await promptCreateRemoteFolder(context.clientId, parentPath, isActive)) {
          if (!isActive()) return
          ElMessage.success('Directory created')
          await this.refreshRemoteDirectory()
        }
      } catch (e) {
        if (!isActive() || e === 'cancel' || e === 'close' || e?.toString?.().includes('cancel')) return
        ElMessage.error(e.message || 'Create directory failed')
      } finally {
        if (this.isRemoteFilesContextActive(context)) this.remoteCreatingFolder = false
      }
    },
  },
}
