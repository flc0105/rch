import { ElMessage, ElMessageBox } from 'element-plus'
import { pasteRemoteFiles, createRemoteZip, extractRemoteZip, renameRemoteFile, downloadRemoteFile, downloadRemoteZip, deleteRemoteEntries } from '../api/remoteFilesApi.js'
import { copyTextFallback } from '../utils/clipboard.js'
import { showTransferStartedToast } from '../utils/transferStartedToast.js'
import { preparePasteConflicts, prepareExtractConflict } from '../utils/remoteFileConflicts.js'
import { sendCommand } from '../api/connectionsApi.js'
import { createTerminalOperation, operationHeaders } from '../utils/terminalOperation.js'

import { isZipEntry } from '../utils/remotePaths.js'

export default {
  data() {
    return {
      remoteZipDownloading: false,
      remoteZipCreating: false,
      remoteZipExtracting: false,
      destinationPickerVisible: false,
      destinationPickerInitialPath: '',
      destinationRequest: null,
      remoteClipboardPaths: [],
      remoteClipboardMode: '',
      remoteClipboardSourcePath: '',
    }
  },
  computed: {
    hasRemoteClipboard() {
      return this.remoteClipboardPaths.length > 0 && !!this.remoteClipboardMode
    },
    remoteClipboardActionText() {
      return this.remoteClipboardMode === 'move' ? 'Cut' : 'Copy'
    },
  },
  methods: {
    // async copyRemotePath(row) {
    //   if (!row || !row.path || row.is_parent_entry) {
    //     ElMessage.warning('Invalid path')
    //     return
    //   }
    //
    //   try {
    //     await navigator.clipboard.writeText(row.path)
    //     ElMessage.success('Path copied')
    //   } catch (e) {
    //     ElMessage.error('Failed to copy path')
    //   }
    // },

    async copyRemotePath(row) {
      if (!row || !row.path || row.is_parent_entry) {
        ElMessage.warning('Invalid path')
        return
      }

      const text = String(row.path)

      try {
        if (
            window.isSecureContext &&
            navigator.clipboard &&
            typeof navigator.clipboard.writeText === 'function'
        ) {
          await navigator.clipboard.writeText(text)
          ElMessage.success('Path copied')
          return
        }

        copyTextFallback(text)
        ElMessage.success('Path copied')
      } catch (e) {
        try {
          copyTextFallback(text)
          ElMessage.success('Path copied')
        } catch (fallbackError) {
          ElMessage.error('Failed to copy path')
        }
      }
    },
    cacheRemoteClipboard(mode) {
      const paths = [...this.remoteSelectedPaths]

      if (!paths.length) {
        ElMessage.warning('Please select at least one file or folder')
        return
      }

      this.remoteClipboardPaths = paths
      this.remoteClipboardMode = mode === 'move' ? 'move' : 'copy'
      this.remoteClipboardSourcePath = this.remoteFilesCurrentPath || ''

      const actionText = this.remoteClipboardMode === 'move' ? 'Cut' : 'Copied'
      ElMessage.success(`${actionText} ${paths.length} item(s)`)
    },
    copySelectedRemoteEntries() {
      this.cacheRemoteClipboard('copy')
    },
    cutSelectedRemoteEntries() {
      this.cacheRemoteClipboard('move')
    },
    copySingleRemoteEntry(row) {
      if (!row?.path) return
      this.remoteSelectedPaths = [row.path]
      this.copySelectedRemoteEntries()
    },
    cutSingleRemoteEntry(row) {
      if (!row?.path) return
      this.remoteSelectedPaths = [row.path]
      this.cutSelectedRemoteEntries()
    },
    clearRemoteClipboard() {
      this.remoteClipboardPaths = []
      this.remoteClipboardMode = ''
      this.remoteClipboardSourcePath = ''
    },
    openDestinationPicker(row, operation) {
      if (!row?.path || row.is_parent_entry) return
      this.openDestinationPickerForPaths([row.path], operation)
    },
    openDestinationPickerForPaths(paths, operation) {
      const context = this.captureRemoteFilesContext()
      if (!this.isRemoteFilesContextActive(context) || !paths.length || !['copy', 'move'].includes(operation)) return
      this.destinationRequest = { context, paths: [...paths], operation }
      this.destinationPickerInitialPath = this.remoteFilesCurrentPath
      this.destinationPickerVisible = true
    },
    handleDestinationPickerUploadStarted(payload) {
      this.$emit('upload-started', { ...payload, source: 'remote_files_destination_picker' })
    },
    async refreshDestinationPickerDirectory(clientId, path) {
      if (String(clientId) !== this.remoteFilesClientId) return
      const picker = this.$refs.destinationPickerRef
      if (this.destinationPickerVisible && picker?.remoteFilesCurrentPath === path) await picker.refreshRemoteDirectory()
      if (this.visible && this.remoteFilesCurrentPath === path) await this.refreshRemoteDirectory()
    },
    async handleDestinationSelected(destinationDir) {
      const pending = this.destinationRequest
      this.destinationRequest = null
      if (!pending || !destinationDir || !this.isRemoteFilesContextActive(pending.context)) return
      await this.executeRemotePaste(pending.context, {
        paths: pending.paths, destination_dir: destinationDir, operation: pending.operation,
      })
    },
    async pasteRemoteClipboard() {
      const context = this.captureRemoteFilesContext()
      if (!context.clientId) {
        ElMessage.warning('Please select a device')
        return
      }
      if (!this.remoteFilesCurrentPath) {
        ElMessage.warning('Current directory is empty')
        return
      }
      const paths = [...this.remoteClipboardPaths]
      const operation = this.remoteClipboardMode
      if (!paths.length || !operation) {
        ElMessage.warning('Clipboard is empty')
        return
      }
      const result = await this.executeRemotePaste(context, { paths, destination_dir: this.remoteFilesCurrentPath, operation })
      if (result && operation === 'move' && result.failed === 0 && this.isRemoteFilesContextActive(context) &&
          this.remoteClipboardMode === operation && JSON.stringify(this.remoteClipboardPaths) === JSON.stringify(paths)) {
        this.clearRemoteClipboard()
      }
    },
    async executeRemotePaste(context, request) {
      const { paths, operation } = request
      try {
        const conflicts = await preparePasteConflicts(context.clientId, request)
        if (conflicts === false || !this.isRemoteFilesContextActive(context)) return null
        const res = await pasteRemoteFiles(context.clientId, { ...request, ...(conflicts || {}) })
        const json = await res.json()
        if (!this.isRemoteFilesContextActive(context)) return null
        if (!res.ok || json.code !== 0) throw new Error(json.message || 'Paste failed')
        const actionText = operation === 'move' ? 'Moved' : 'Copied'
        const message = json.data?.message || `${actionText} ${paths.length} item(s)`
        const failed = Number(json.data?.failed || 0)
        if (failed > 0) ElMessage.warning(`${actionText} ${json.data?.succeeded || 0} of ${paths.length} item(s). ${failed} failed.`)
        else ElMessage.success(`${actionText} ${paths.length} item(s)`)
        await this.refreshRemoteDirectory()
        if (message && !message.startsWith(`${actionText} ${paths.length} item(s)`)) ElMessage.info(message)
        return { failed }
      } catch (e) {
        if (this.isRemoteFilesContextActive(context)) ElMessage.error(e.message || 'Paste failed')
        return null
      }
    },
    async setRemoteDirectoryAsCwd(path) {
      const context = this.captureRemoteFilesContext()
      const targetPath = String(path || '').trim()
      if (!context.clientId || !targetPath || /[\r\n]/.test(targetPath)) return

      try {
        // Register the same operation identity as a terminal-submitted command.
        const command = `cd ${targetPath}`
        const operation = createTerminalOperation({ kind: 'command', action: 'invoke', clientId: context.clientId,
          invocation: { input: command }, replay: { type: 'command', command } })
        this.$emit('append-output', context.clientId, `> ${command}`, 'command', { operation })
        const result = await sendCommand(context.clientId, command, operationHeaders(operation, this.getTabScopedHeaders()))
        if (!this.isRemoteFilesContextActive(context)) return
        const taskId = result?.task_id || ''
        this.$emit('set-active-task', context.clientId, taskId, '', result?.history_entry_id || '', operation.operation_id)
        ElMessage.success('CWD change submitted')
      } catch (e) {
        if (!this.isRemoteFilesContextActive(context)) return
        ElMessage.error(e.message || 'Failed to set CWD')
      }
    },
    openRemotePtyHere(path) {
      const directory = String(path || '').trim()
      if (directory && this.remoteFilesClientId === String(this.selectedId || '')) {
        this.$emit('open-pty', directory)
      }
    },
    handleRemoteMoreAction(command, row) {
      if (!row || row.is_parent_entry) return
      if (command === 'set_cwd' && row.is_dir) return this.setRemoteDirectoryAsCwd(row.path)
      if (command === 'open_pty' && row.is_dir) return this.openRemotePtyHere(row.path)

      if (command === 'rename') {
        this.renameRemoteEntry(row)
        return
      }

      if (command === 'copy_to' || command === 'move_to') {
        this.openDestinationPicker(row, command === 'move_to' ? 'move' : 'copy')
        return
      }

      if (command === 'copy_path') {
        this.copyRemotePath(row)
        return
      }

      if (command === 'copy') {
        this.copySingleRemoteEntry(row)
        return
      }

      if (command === 'cut') {
        this.cutSingleRemoteEntry(row)
        return
      }

      if (command === 'extract') {
        this.extractRemoteZip(row)
        return
      }

      if (command === 'delete') {
        this.deleteRemoteEntry(row)
      }
    },
    remotePathBaseName(path) {
      const normalized = String(path || '').replace(/[\\/]+$/, '')
      const parts = normalized.split(/[\\/]/)
      return parts[parts.length - 1] || 'archive'
    },
    buildRemoteZipDefaultName() {
      const paths = [...this.remoteSelectedPaths]
      if (paths.length === 1) {
        const baseName = this.remotePathBaseName(paths[0])
        const stem = baseName.replace(/\.[^.]+$/, '') || baseName || 'archive'
        return baseName.toLowerCase().endsWith('.zip') ? `${stem}_archive.zip` : `${stem}.zip`
      }

      const now = new Date()
      const pad = value => String(value).padStart(2, '0')
      const stamp = `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}_${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`
      return `bundle_${stamp}.zip`
    },
    async createSelectedRemoteZip() {
      const context = this.captureRemoteFilesContext()
      const clientId = context.clientId
      if (!clientId) {
        ElMessage.warning('Please select a device')
        return
      }

      const paths = [...this.remoteSelectedPaths]
      if (!paths.length) {
        ElMessage.warning('Please select at least one file or folder')
        return
      }
      if (!this.remoteFilesCurrentPath) {
        ElMessage.warning('Current directory is empty')
        return
      }

      try {
        const {value} = await ElMessageBox.prompt(
            'The ZIP archive will be created in the current remote directory.',
            'Create ZIP',
            {
              confirmButtonText: 'Create',
              cancelButtonText: 'Cancel',
              inputValue: this.buildRemoteZipDefaultName(),
              inputPattern: /.+/,
              inputErrorMessage: 'ZIP name is required',
            }
        )

        let archiveName = String(value || '').trim()
        if (!archiveName) return
        if (!archiveName.toLowerCase().endsWith('.zip')) archiveName += '.zip'
        if (!this.isRemoteFilesContextActive(context)) return

        this.remoteZipCreating = true
        const res = await createRemoteZip(clientId, { paths, destination_dir: this.remoteFilesCurrentPath, archive_name: archiveName })
        const json = await res.json()

        if (!this.isRemoteFilesContextActive(context)) return
        if (!res.ok || json.code !== 0) {
          throw new Error(json.message || 'Create ZIP failed')
        }

        const data = json.data || {}
        ElMessage.success(`ZIP created: ${data.archive_name || archiveName}`)
        await this.refreshRemoteDirectory()
      } catch (e) {
        if (!this.isRemoteFilesContextActive(context)) return
        if (this.isDialogCancel(e)) return
        ElMessage.error(e.message || 'Create ZIP failed')
      } finally {
        if (this.isRemoteFilesContextActive(context)) this.remoteZipCreating = false
      }
    },
    async extractRemoteZip(row) {
      const context = this.captureRemoteFilesContext()
      const clientId = context.clientId
      if (!clientId) {
        ElMessage.warning('Please select a device')
        return
      }
      if (!isZipEntry(row) || !row.path) {
        ElMessage.warning('Please select a ZIP file')
        return
      }
      if (!this.remoteFilesCurrentPath) {
        ElMessage.warning('Current directory is empty')
        return
      }

      try {
        await ElMessageBox.confirm(
            `Extract "${row.name}" into the current directory?`,
            'Extract ZIP',
            {
              type: 'warning',
              confirmButtonText: 'Extract',
              cancelButtonText: 'Cancel',
            }
        )

        if (!this.isRemoteFilesContextActive(context)) return
        this.remoteZipExtracting = true
        const request = { path: row.path, destination_dir: this.remoteFilesCurrentPath }
        const conflicts = await prepareExtractConflict(clientId, request)
        if (conflicts === false || !this.isRemoteFilesContextActive(context)) return
        const res = await extractRemoteZip(clientId, { ...request, ...(conflicts || {}) })
        const json = await res.json()

        if (!this.isRemoteFilesContextActive(context)) return
        if (!res.ok || json.code !== 0) {
          throw new Error(json.message || 'Extract ZIP failed')
        }

        const data = json.data || {}
        ElMessage.success(`Extracted to: ${data.extracted_to || this.remoteFilesCurrentPath}`)
        await this.refreshRemoteDirectory()
      } catch (e) {
        if (!this.isRemoteFilesContextActive(context)) return
        if (this.isDialogCancel(e)) return
        ElMessage.error(e.message || 'Extract ZIP failed')
      } finally {
        if (this.isRemoteFilesContextActive(context)) this.remoteZipExtracting = false
      }
    },
    async renameRemoteEntry(row) {
      const context = this.captureRemoteFilesContext()
      const clientId = context.clientId
      if (!clientId) {
        ElMessage.warning('Please select a device')
        return
      }
      if (!row || !row.path || row.is_parent_entry) {
        ElMessage.warning('Invalid path')
        return
      }

      try {
        const {value} = await ElMessageBox.prompt(
            'Enter the new name',
            'Rename',
            {
              confirmButtonText: 'Rename',
              cancelButtonText: 'Cancel',
              inputValue: row.name || '',
              inputPattern: /.+/,
              inputErrorMessage: 'New name is required',
            }
        )

        const newName = String(value || '').trim()
        if (!newName || newName === row.name || !this.isRemoteFilesContextActive(context)) return

        const res = await renameRemoteFile(clientId, row.path, newName)

        const json = await res.json()

        if (!this.isRemoteFilesContextActive(context)) return
        if (!res.ok || json.code !== 0) {
          throw new Error(json.message || 'Rename failed')
        }

        ElMessage.success('Renamed')
        await this.refreshRemoteDirectory()
      } catch (e) {
        if (!this.isRemoteFilesContextActive(context)) return
        if (this.isDialogCancel(e)) return
        ElMessage.error(e.message || 'Rename failed')
      }
    },
    async downloadRemoteEntry(row) {
      const context = this.captureRemoteFilesContext()
      const clientId = context.clientId
      if (!clientId) {
        ElMessage.warning('Please select a device')
        return
      }
      if (!row || !row.path || row.is_dir || row.is_parent_entry) {
        ElMessage.warning('Please select a file')
        return
      }

      try {
        showTransferStartedToast(`Download started: ${row.name || 'file'}`, this.openTransferCenterFromToast)

        const res = await downloadRemoteFile(clientId, row.path, this.getTabScopedHeaders())
        const json = await res.json()

        if (!this.isRemoteFilesContextActive(context)) return
        if (!res.ok || json.code !== 0) {
          throw new Error(json.message || 'Download failed')
        }

        const file = (json.data && (json.data.file || json.data.artifact)) || null

        if (!file || !file.artifact_id) {
          throw new Error('Download finished, but artifact was not found')
        }

        const downloadUrl = file.download_url || `/api/artifacts/${encodeURIComponent(file.artifact_id)}/download`
        window.open(downloadUrl, '_blank')

        ElMessage.success(`Downloaded: ${row.name}`)
        this.$emit('artifacts-maybe-changed')
      } catch (e) {
        if (!this.isRemoteFilesContextActive(context)) return
        ElMessage.error(e.message || 'Download failed')
      }
    },
    async downloadSelectedRemoteEntries() {
      const context = this.captureRemoteFilesContext()
      const clientId = context.clientId
      if (!clientId) {
        ElMessage.warning('Please select a device')
        return
      }

      const paths = [...this.remoteSelectedPaths]

      if (!paths.length) {
        ElMessage.warning('Please select at least one file or folder')
        return
      }

      this.remoteZipDownloading = true

      try {
        showTransferStartedToast(`Download started: ${paths.length} selected item(s)`, this.openTransferCenterFromToast)

        const res = await downloadRemoteZip(clientId, paths, this.getTabScopedHeaders())

        const json = await res.json()

        if (!this.isRemoteFilesContextActive(context)) return
        if (!res.ok || json.code !== 0) {
          throw new Error(json.message || 'ZIP download failed')
        }

        const file = (json.data && (json.data.file || json.data.artifact)) || null

        if (!file || !file.artifact_id) {
          throw new Error('ZIP download finished, but artifact was not found')
        }

        const downloadUrl = file.download_url || `/api/artifacts/${encodeURIComponent(file.artifact_id)}/download`
        window.open(downloadUrl, '_blank')

        ElMessage.success(`ZIP ready: ${file.original_name || file.stored_name}`)
        this.$emit('artifacts-maybe-changed')
      } catch (e) {
        if (!this.isRemoteFilesContextActive(context)) return
        ElMessage.error(e.message || 'ZIP download failed')
      } finally {
        if (this.isRemoteFilesContextActive(context)) this.remoteZipDownloading = false
      }
    },
    async deleteRemoteEntry(row) {
      const context = this.captureRemoteFilesContext()
      const clientId = context.clientId
      if (!clientId) {
        ElMessage.warning('Please select a device')
        return
      }
      if (!row || !row.path || row.is_parent_entry) {
        ElMessage.warning('Invalid path')
        return
      }

      try {
        await ElMessageBox.confirm(
            `Delete "${row.name}"?${row.is_dir ? ' All nested contents will be removed as well.' : ''}`,
            'Delete Confirmation',
            {
              type: 'warning',
              confirmButtonText: 'Delete',
              cancelButtonText: 'Cancel',
            }
        )

        if (!this.isRemoteFilesContextActive(context)) return
        const res = await deleteRemoteEntries(clientId, [row.path])
        const json = await res.json()

        if (!this.isRemoteFilesContextActive(context)) return
        if (!res.ok || json.code !== 0) {
          throw new Error(json.message || 'Delete failed')
        }

        ElMessage.success('Deleted')
        await this.refreshRemoteDirectory()
      } catch (e) {
        if (!this.isRemoteFilesContextActive(context)) return
        if (this.isDialogCancel(e)) return
        ElMessage.error(e.message || 'Delete failed')
      }
    },
    async deleteSelectedRemoteEntries() {
      const context = this.captureRemoteFilesContext()
      const clientId = context.clientId
      if (!clientId) {
        ElMessage.warning('Please select a device')
        return
      }

      const paths = [...this.remoteSelectedPaths]

      if (!paths.length) {
        ElMessage.warning('Please select at least one file or folder to delete')
        return
      }

      try {
        await ElMessageBox.confirm(
            `Delete ${paths.length} selected item(s)?`,
            'Delete Multiple Items',
            {
              type: 'warning',
              confirmButtonText: 'Delete',
              cancelButtonText: 'Cancel',
              confirmButtonClass: 'el-button--danger',
              dangerouslyUseHTMLString: false,
            }
        )

        if (!this.isRemoteFilesContextActive(context)) return
        const res = await deleteRemoteEntries(clientId, paths)

        const json = await res.json()

        if (!this.isRemoteFilesContextActive(context)) return
        if (!res.ok || json.code !== 0) {
          throw new Error(json.message || 'Batch delete failed')
        }

        const message = json.data?.message || 'Delete completed'

        ElMessage.success(`Deleted ${paths.length} item(s)`)
        await this.refreshRemoteDirectory()
        this.clearRemoteSelection()

        if (message && message !== 'Delete completed') {
          ElMessage.info(message)
        }
      } catch (e) {
        if (!this.isRemoteFilesContextActive(context)) return
        if (this.isDialogCancel(e)) return
        ElMessage.error(e.message || 'Batch delete failed')
      }
    },
    previewRow(row) {
      if (!row || row.is_dir || row.is_parent_entry) return
      this.$emit('preview', {
        ...row,
        client_id: this.remoteFilesClientId,
      })
    },
    escapeRemoteHtml(text) {
      return String(text || '')
          .replace(/&/g, '&amp;')
          .replace(/</g, '&lt;')
          .replace(/>/g, '&gt;')
          .replace(/"/g, '&quot;')
          .replace(/'/g, '&#39;')
    },
    isDialogCancel(e) {
      return e === 'cancel' || e === 'close' || e?.toString?.().includes('cancel')
    },
  },
}
