import { ElMessage, ElMessageBox } from 'element-plus'
import { sendArtifactToClient } from '../api/artifactsApi.js'
import { prepareUploadConflict } from '../utils/remoteFileConflicts.js'
import { createTerminalOperation, operationHeaders } from '../utils/terminalOperation.js'
import { formatTerminalCommandFinishedLine } from './terminalMarkers.js'
import { setRemoteClipboardArtifactFile } from '../api/clipboardApi.js'

export default {
  methods: {
    async sendArtifactToCurrentDeviceClipboard(row) {
      if (this.standaloneMode) return
      if (!row || !row.artifact_id || !this.isSharedFileItem(row)) {
        ElMessage.warning('Invalid shared file')
        return
      }

      const clientId = String(this.selectedId || this.currentConnection?.client_id || '').trim()
      if (!clientId) {
        ElMessage.warning('Please select a device')
        return
      }

      try {
        await setRemoteClipboardArtifactFile(clientId, row.artifact_id, this.buildJsonHeaders())
        ElMessage.success(`Sent to clipboard: ${this.formatArtifactName(row)}`)
      } catch (e) {
        ElMessage.error(e.message || 'Failed to send file to target clipboard')
      }
    },

    async sendArtifactToCurrentDevice(row) {
      if (this.standaloneMode) return
      if (!row || !row.artifact_id) {
        ElMessage.warning('Invalid artifact')
        return
      }

      const clientId = String(this.selectedId || this.currentConnection?.client_id || '').trim()
      if (!clientId) {
        ElMessage.warning('Please select a device')
        return
      }

      const displayName = this.formatArtifactName(row)
      const deviceLabel = this.formatCurrentDeviceLabel()
      const targetCwd = this.getCurrentDeviceCwd()
      const targetCwdLabel = this.formatCurrentDeviceCwd()

      try {
        await ElMessageBox.confirm(
          `Send "${displayName}" to ${deviceLabel} directory: ${targetCwdLabel}?`,
          'Send to Current Device',
          {
            confirmButtonText: 'Send',
            cancelButtonText: 'Cancel',
            type: 'warning',
          }
        )
      } catch (e) {
        if (this.isDialogCancel(e)) return
        return
      }

      if (this.standaloneMode) return
      let operation = null
      try {
        const conflictPolicy = await prepareUploadConflict(clientId, targetCwd || '.', displayName)
        if (conflictPolicy === false || this.standaloneMode ||
            String(this.selectedId || this.currentConnection?.client_id || '').trim() !== clientId ||
            this.getCurrentDeviceCwd() !== targetCwd) return
        operation = createTerminalOperation({ kind: 'transfer', action: 'upload_files', clientId,
          invocation: { source: 'artifact_send', artifact_id: row.artifact_id, destination: targetCwd }, replay: null })
        this.$emit(
          'append-output', clientId,
          `> [Artifact Send] ${displayName} -> ${deviceLabel} :: ${targetCwdLabel}`, 'command',
          { operation },
        )
        const res = await sendArtifactToClient(
          row.artifact_id, clientId, targetCwd, operationHeaders(operation, this.buildJsonHeaders({ 'Content-Type': 'application/json' })), conflictPolicy,
        )
        const json = await res.json()

        if (!res.ok || json.code !== 0) {
          throw new Error(json.message || 'Send failed')
        }

        const taskId = json.data && json.data.task_id
        this.$emit('set-active-task', clientId, taskId || '', '', '', operation.operation_id)
        ElMessage.success(`Send started: ${displayName}`)
      } catch (e) {
        const failedDuringPreflight = !operation
        const title = `[Artifact Send] ${displayName} -> ${deviceLabel} :: ${targetCwdLabel}`
        if (failedDuringPreflight) {
          operation = createTerminalOperation({ kind: 'transfer', action: 'upload_files', clientId,
            invocation: { source: 'artifact_send', artifact_id: row.artifact_id, destination: targetCwd }, replay: null })
          this.$emit('append-output', clientId, `> ${title}`, 'command', { operation })
        }
        this.$emit('append-output', clientId, `[Artifact send failed] ${e.message || 'unknown error'}`,
          'error', { operation_id: operation.operation_id, event_type: 'submission_error' })
        if (failedDuringPreflight) {
          this.$emit('append-output', clientId, formatTerminalCommandFinishedLine(title, 'Failed'),
            'error', { operation_id: operation.operation_id, event_type: 'completed', execution_status: 'failed', execution_success: false })
        }
        ElMessage.error(e.message || 'Send failed')
      }
    },

  },
}
