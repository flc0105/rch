import { ElMessage } from 'element-plus'
import { listRemoteDirectory, makeRemoteDirectory } from '../api/remoteFilesApi.js'
import { uploadRemoteFileToClient, startBrowserUploadBatch, finalizeBrowserUploadBatch, isBrowserUploadBatchCancelled } from '../api/transferApi.js'
import { createTerminalOperation } from '../utils/terminalOperation.js'
import { formatTerminalCommandFinishedLine, TERMINAL_REMOTE_UPLOAD_PREFIX } from './terminalMarkers.js'
import { flattenUploadAttachments } from '../utils/browserFileEntries.js'
import { joinRemotePath } from '../utils/remotePaths.js'
import { prepareRemoteUploadPlan } from '../utils/remoteFileConflicts.js'
import { showTransferStartedToast } from '../utils/transferStartedToast.js'

export default {
  data() {
    return {
      dragUploadVisible: false,
      dragUploadLoading: false,
      dragUploadStage: '',
      dragUploadProgress: null,
    }
  },
  methods: {
    triggerRemoteUpload() {
      if (this.dragUploadLoading) return
      if (!this.remoteFilesClientId) {
        ElMessage.warning('Please select a device')
        return
      }

      if (!this.remoteFilesCurrentPath) {
        ElMessage.warning('Current directory is empty')
        return
      }

      this.$emit('request-upload')
    },
    triggerDragUpload() {
      if (!this.remoteFilesClientId) return ElMessage.warning('Please select a device')
      if (!this.remoteFilesCurrentPath) return ElMessage.warning('Current directory is empty')
      this.dragUploadVisible = true
    },
    async ensureUploadRemoteDirectory(clientId, path, reuse) {
      const response = reuse ? await listRemoteDirectory(clientId, { path, page: 1, pageSize: 1 }) : await makeRemoteDirectory(clientId, path)
      const result = await response.json()
      if (!response.ok || result.code !== 0 || (reuse && !result.data?.current_path)) {
        throw new Error(result.message || `Cannot prepare directory: ${path}`)
      }
    },
    async handleDragUpload(attachments) {
      if (this.dragUploadLoading || this.remoteUploadLoading) return
      let plan
      try {
        plan = flattenUploadAttachments(attachments)
      } catch (error) {
        return ElMessage.error(error.message || 'Invalid upload selection')
      }
      if (!plan.directories.length && !plan.files.length) return

      const context = this.captureRemoteFilesContext()
      const root = this.remoteFilesCurrentPath
      if (!context.clientId || !root) return
      const stillActive = () => this.visible && this.isRemoteFilesContextActive(context) && this.remoteFilesCurrentPath === root

      // A lone file uses the original Upload workflow, not a Batch parent.
      if (plan.directories.length === 0 && plan.files.length === 1) {
        const uploaded = await this.uploadSelectedFile(plan.files[0].file)
        if (uploaded && stillActive()) {
          this.dragUploadVisible = false
          await this.refreshRemoteDirectory()
        }
        return
      }

      const operation = createTerminalOperation({ kind: 'transfer', action: 'upload_files',
        clientId: context.clientId })
      const batchId = operation.operation_id
      const headers = { ...this.getTabScopedHeaders(), 'X-RCH-Origin': 'web_ui',
        'X-RCH-Feature': 'remote_files' }
      let started = 0
      let batchError = ''
      let batchStarted = false
      let readyFolders = 0
      let queue = []
      this.dragUploadLoading = true
      this.dragUploadStage = 'Checking conflicts…'
      this.dragUploadProgress = null
      try {
        if (plan.files.length > 1000 || plan.directories.length > 10000) throw new Error('Invalid upload batch size')
        // Inspect existing destinations before creating folders or starting transfers.
        const prepared = await prepareRemoteUploadPlan(context.clientId, root, plan, stillActive)
        if (prepared === false) { ElMessage.info?.('Upload cancelled'); return }
        queue = prepared.files.map(entry => {
          const parent = entry.relativePath.split('/').slice(0, -1).join('/')
          return { ...entry, destinationDir: parent ? joinRemotePath(root, parent) : root }
        })
        if (!queue.length && !prepared.directories.length) {
          if (stillActive()) {
            this.dragUploadVisible = false
            ElMessage.info(`Skipped ${plan.files.length} file(s)`)
          }
          return
        }
        await startBrowserUploadBatch({ clientId: context.clientId, batchId, destinationPath: root,
          files: queue.map(({ file, relativePath, policy }) => ({ relative_path: relativePath, size: file.size, conflict_policy: policy })),
          directories: prepared.directories }, headers)
        batchStarted = true
        this.$emit('append-output', context.clientId,
          `> ${TERMINAL_REMOTE_UPLOAD_PREFIX} ${queue.length} file(s) -> ${root}`, 'command', { operation })
        this.dragUploadStage = 'Preparing folders…'
        for (const dir of prepared.directories) {
          if (isBrowserUploadBatchCancelled(batchId)) throw new Error('Remote upload stopped')
          await this.ensureUploadRemoteDirectory(context.clientId, joinRemotePath(root, dir), prepared.reused.has(dir))
          readyFolders++
          this.dragUploadProgress = Math.round(100 * readyFolders / prepared.directories.length)
        }
        this.dragUploadStage = 'Submitting files…'
        this.dragUploadProgress = queue.length ? 0 : null
        for (const [index, { file, destinationDir, policy }] of queue.entries()) {
          if (isBrowserUploadBatchCancelled(batchId)) throw new Error('Browser upload was cancelled')
          await uploadRemoteFileToClient({
            file, clientId: context.clientId, destinationPath: destinationDir,
            conflictPolicy: policy, headers, batchId, batchTotal: queue.length, batchIndex: index,
            onStarted: () => {
              if (index === 0) showTransferStartedToast(
                `Upload started: ${queue.length} file(s)`, this.openTransferCenterFromToast)
            },
          })
          started++
          this.dragUploadProgress = Math.round(100 * started / queue.length)
        }
        if (stillActive()) {
          this.dragUploadVisible = false
          await this.refreshRemoteDirectory()
          ElMessage.success(`Started ${started} file transfer(s), ${readyFolders} folder(s) ready${plan.files.length > queue.length ? `, ${plan.files.length - queue.length} skipped` : ''}`)
        }
      } catch (error) {
        batchError = error.message || 'Upload failed'
        if (!batchStarted) {
          const title = `${TERMINAL_REMOTE_UPLOAD_PREFIX} ${plan.files.length} file(s) -> ${root}`
          this.$emit('append-output', context.clientId, `> ${title}`, 'command', { operation })
          this.$emit('append-output', context.clientId,
            formatTerminalCommandFinishedLine(title, `Failed: ${batchError}`), 'error', {
              operation_id: operation.operation_id, event_type: 'completed',
              execution_status: 'failed', execution_success: false,
            })
        }
        if (stillActive()) ElMessage.error(`${batchError} (${started}/${queue.length || plan.files.length} started)`)
      } finally {
        if (batchStarted) {
          try {
            await finalizeBrowserUploadBatch({
              clientId: context.clientId, batchId, folderCount: readyFolders,
              error: batchError || (started < queue.length ? 'Incomplete upload batch' : ''),
            }, headers)
          } catch (error) {
            if (stillActive()) ElMessage.error(error.message || 'Failed to finalize upload batch')
          }
        }
        this.dragUploadLoading = false
        this.dragUploadStage = ''
        this.dragUploadProgress = null
      }
    },
    async handleUploadChange(event) {
      const file = event?.target?.files?.[0]
      if (event?.target) event.target.value = ''
      if (file) return this.uploadSelectedFile(file)
    },
    async uploadSelectedFile(file) {
      return this.submitRemoteFile(file, 'remote_files')
    },
  },
}
