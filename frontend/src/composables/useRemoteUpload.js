import { ElMessage } from 'element-plus'
import { createTerminalOperation, operationHeaders } from '../utils/terminalOperation.js'
import { formatTerminalCommandFinishedLine, TERMINAL_REMOTE_UPLOAD_PREFIX } from './terminalMarkers.js'
import { uploadRemoteFileToClient } from '../api/transferApi.js'
import { prepareUploadConflict } from '../utils/remoteFileConflicts.js'
import { showTransferStartedToast } from '../utils/transferStartedToast.js'

export default {
  data() { return { remoteUploadLoading: false, remoteUploadSequence: 0 } },
  methods: {
    async submitRemoteFile(file, source) {
      if (this.remoteUploadLoading) return false
      const context = this.captureRemoteFilesContext()
      const clientId = String(context.clientId || '').trim()
      if (!clientId) {
        ElMessage.warning('Please select a device')
        return
      }

      if (!this.remoteFilesCurrentPath) {
        ElMessage.warning('Current directory is empty')
        return
      }

      if (!this.visible || !this.isRemoteFilesContextActive(context)) return false
      const targetPath = this.remoteFilesCurrentPath
      const uploadSeq = ++this.remoteUploadSequence
      this.remoteUploadLoading = true

      let operation = null
      try {
        const conflictPolicy = await prepareUploadConflict(clientId, targetPath, file.name)
        if (conflictPolicy === false || !this.isRemoteFilesContextActive(context) || this.remoteFilesCurrentPath !== targetPath) return false
        operation = createTerminalOperation({ kind: 'transfer', action: 'upload_files', clientId,
          invocation: { source, filename: file.name, destination: targetPath }, replay: null })
        this.$emit('append-output', clientId, `> ${TERMINAL_REMOTE_UPLOAD_PREFIX} ${file.name} -> ${targetPath}`,
          'command', { operation })
        const result = await uploadRemoteFileToClient({
          file, clientId, destinationPath: targetPath, conflictPolicy,
          headers: operationHeaders(operation, {...this.getTabScopedHeaders?.(), 'X-RCH-Origin': 'web_ui', 'X-RCH-Feature': source}),
          onStarted: () => {
            showTransferStartedToast(`Upload started: ${file.name}`, this.openTransferCenterFromToast)
          },
        })
        const taskId = result.task_id

        this.$emit('set-active-task', clientId, taskId || '', '', '', operation.operation_id)
        this.$emit('upload-started', {
          source,
          taskId: taskId || '',
          clientId,
          path: targetPath || '',
        })
        return true

      } catch (e) {
        if (e?.name === 'AbortError' && operation) {
          this.$emit('append-output', clientId, `[Upload cancelled] ${file.name}`, 'info', {
            operation_id: operation.operation_id,
            event_type: 'completed', execution_status: 'cancelled', execution_success: false,
          })
          ElMessage.info('Upload cancelled')
          return false
        }
        const failedDuringPreflight = !operation
        const title = `${TERMINAL_REMOTE_UPLOAD_PREFIX} ${file.name} -> ${targetPath}`
        if (failedDuringPreflight) {
          operation = createTerminalOperation({ kind: 'transfer', action: 'upload_files', clientId,
            invocation: { source, filename: file.name, destination: targetPath }, replay: null })
          this.$emit('append-output', clientId, `> ${title}`, 'command', { operation })
        }
        this.$emit('append-output', clientId, `[Upload failed] ${e.message || 'unknown error'}`,
          'error', { operation_id: operation.operation_id, event_type: 'submission_error' })
        if (failedDuringPreflight) {
          this.$emit('append-output', clientId, formatTerminalCommandFinishedLine(title, 'Failed'),
            'error', { operation_id: operation.operation_id, event_type: 'completed', execution_status: 'failed', execution_success: false })
        }

        ElMessage.error(e.message || 'Upload failed')
        return false
      } finally {
        if (uploadSeq === this.remoteUploadSequence) this.remoteUploadLoading = false
      }
    },
  },
}
