import { ElMessage, ElMessageBox } from 'element-plus'
import { inspectSharedUpload, uploadSharedBatch } from '../api/artifactsApi.js'
import { flattenUploadAttachments } from '../utils/browserFileEntries.js'
import { expectData, resolveConflictPolicies } from '../utils/fileConflictDecisions.js'

export default {
  data() {
    return {
      sharedFileUploading: false,
      sharedUploadStage: '',
      sharedUploadProgress: null,
      sharedUploadCanCancel: false,
      sharedUploadAbort: null,
      sharedFileUploadDialogVisible: false,
    }
  },
  methods: {
    async createSharedFilePrompt() {
      if (!this.isSharedFilesTab) return
      const folderId = this.selectedFolderId

      try {
        const { value } = await ElMessageBox.prompt(
          'Enter the new shared file name',
          'Create File',
          {
            confirmButtonText: 'Create',
            cancelButtonText: 'Cancel',
            inputValue: 'new_file.txt',
            inputPlaceholder: 'new_file.txt',
          }
        )

        const filename = String(value || 'new_file.txt').trim()
        if (!filename) {
          ElMessage.warning('File name is required')
          return
        }

        this.$emit('open-new-shared-file-editor', filename, folderId)
      } catch (e) {
        if (e === 'cancel' || e === 'close') return
      }
    },

    triggerSharedFileUpload() {
      if (!this.isSharedFilesTab) return
      this.sharedFileUploadDialogVisible = true
    },

    async uploadSharedFiles(attachments) {
      if (!this.isSharedFilesTab || this.sharedFileUploading) return
      let plan
      try {
        plan = flattenUploadAttachments(attachments)
      } catch (error) {
        ElMessage.error(error.message || 'Invalid upload selection')
        return
      }
      if (!plan.files.length && !plan.directories.length) return

      const folderId = this.selectedFolderId || ''
      const paths = plan.files.map(item => item.relativePath)
      this.sharedFileUploading = true
      const controller = new AbortController()
      this.sharedUploadAbort = controller
      this.sharedUploadCanCancel = true
      this.sharedUploadStage = 'Checking conflicts…'
      this.sharedUploadProgress = null
      try {
        const preview = await expectData(await inspectSharedUpload({ folder_id: folderId, paths, directories: plan.directories }), 'Conflict inspection')
        if (controller.signal.aborted) { ElMessage.info?.('Upload cancelled'); return }
        const policies = await resolveConflictPolicies(preview.conflicts, paths.length)
        if (policies === false || controller.signal.aborted) { ElMessage.info?.('Upload cancelled'); return }
        const formData = new FormData()
        formData.append('folder_id', folderId)
        formData.append('directories', JSON.stringify(plan.directories))
        formData.append('paths', JSON.stringify(paths))
        formData.append('conflict_policies', JSON.stringify(policies))
        for (const entry of plan.files) formData.append('files', entry.file, entry.file.name)
        this.sharedUploadStage = 'Uploading to Server…'
        const json = await uploadSharedBatch(formData, this.buildJsonHeaders(), {
          signal: controller.signal,
          onProgress: (loaded, total) => {
            if (!this.sharedUploadCanCancel) return
            this.sharedUploadProgress = total ? Math.min(100, Math.round(100 * loaded / total)) : null
            if (total !== null && loaded >= total) {
              this.sharedUploadCanCancel = false
              this.sharedUploadStage = 'Saving files…'
              this.sharedUploadProgress = null
            }
          },
          onBodySent: () => {
            this.sharedUploadCanCancel = false
            this.sharedUploadStage = 'Saving files…'
            this.sharedUploadProgress = null
          },
        })
        const result = json.data || {}
        ElMessage.success(`Uploaded ${result.files_uploaded || 0} file(s), ${result.folders_created || 0} folder(s)${result.files_skipped ? `, ${result.files_skipped} skipped` : ''}`)
        this.sharedFileUploadDialogVisible = false
      } catch (error) {
        if (error?.name === 'AbortError') ElMessage.info?.('Upload cancelled; check Shared Files for any saved files.')
        else ElMessage.error(error.message || 'Upload failed')
      } finally {
        this.sharedFileUploading = false
        this.sharedUploadCanCancel = false
        this.sharedUploadAbort = null
        this.sharedUploadProgress = null
        this.sharedUploadStage = ''
        await this.loadArtifacts()
      }
    },

  },
}
