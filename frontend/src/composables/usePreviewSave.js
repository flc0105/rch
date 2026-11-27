import { ElMessage } from 'element-plus'
import { uploadArtifact, saveArtifactContent } from '../api/artifactsApi.js'
import { saveServerJob } from '../api/backgroundJobsApi.js'
import { formatBytes } from '../utils/formatters.js'
import * as externalToolsApi from '../api/externalToolsApi.js'
import { PREVIEW_SOURCE_OPERATIONS } from '../utils/previewSources.js'

export default {
  methods: {
    applySavedPreviewContent(seq, content) {
      if (!this.isPreviewSessionCurrent(seq)) return false
      // Saving an earlier snapshot must not discard typing during the request.
      const currentContent = this.getMonacoEditorContent()
      this.previewOriginalContent = content
      this.previewText = currentContent
      this.previewEditMode = currentContent !== content
      this.setMonacoEditorReadOnly(!this.previewEditMode)
      return true
    },

    async saveEditedContent() {
      if (this.previewSaving || this.previewReloading || this.previewLoading || !this.previewEditMode) return
      const source = PREVIEW_SOURCE_OPERATIONS[this.previewSource]
      if (source?.requiresCompleteContent && (this.previewTruncated || !this.previewEditable)) {
        ElMessage.warning('Editing is disabled for this file')
        return
      }
      if (!source?.save) {
        ElMessage.warning('Unknown preview source')
        return
      }
      await source.save(this, this.getMonacoEditorContent())
    },

    async saveToExternalToolMeta(content) {
      if (!this.previewFilePath) {
        ElMessage.warning('Invalid external tool id')
        return
      }

      const seq = this.previewLoadSeq
      this.previewSaving = true

      try {
        const data = await externalToolsApi.saveExternalToolMetaContent(this.previewFilePath, content)

        ElMessage.success('External tool meta saved successfully')

        const applied = this.applySavedPreviewContent(seq, content)

        if (applied && data && data.size != null) {
          this.previewFileSize = formatBytes(data.size)
        }

        this.$emit('external-tools-maybe-changed')
      } catch (e) {
        ElMessage.error(e.message || 'Failed to save external tool meta')
      } finally {
        if (this.isPreviewSessionCurrent(seq)) this.previewSaving = false
      }
    },

    async saveToServerScript(content) {
      if (!this.previewFilePath) {
        ElMessage.warning('Invalid script name')
        return
      }

      const seq = this.previewLoadSeq
      this.previewSaving = true

      try {
        const res = await fetch('/api/scripts/save', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            name: this.previewFilePath,
            content,
          }),
        })

        const json = await res.json()
        if (!res.ok || json.code !== 0) {
          throw new Error(json.message || 'Failed to save script')
        }

        ElMessage.success('Script saved successfully')

        this.applySavedPreviewContent(seq, content)

        this.$emit('scripts-maybe-changed')
      } catch (e) {
        ElMessage.error(e.message || 'Failed to save script')
      } finally {
        if (this.isPreviewSessionCurrent(seq)) this.previewSaving = false
      }
    },

    async saveToBackgroundJob(content) {
      if (!this.previewFilePath) {
        ElMessage.warning('Invalid job name')
        return
      }

      const seq = this.previewLoadSeq
      this.previewSaving = true

      try {
        const res = await saveServerJob(this.previewFilePath, content)

        const json = await res.json()
        if (!res.ok || json.code !== 0) {
          throw new Error(json.message || 'Failed to save job')
        }

        ElMessage.success('Job saved successfully')

        this.applySavedPreviewContent(seq, content)

        // 刷新 Jobs 列表
        this.$emit('background-job-modules-maybe-changed')
      } catch (e) {
        ElMessage.error(e.message || 'Failed to save job')
      } finally {
        if (this.isPreviewSessionCurrent(seq)) this.previewSaving = false
      }
    },

    async saveToRemoteFile(content) {
      const clientId = String(this.previewRemoteClientId || '').trim()
      if (!clientId || !this.previewFilePath) {
        ElMessage.warning('Invalid file path')
        return
      }

      const seq = this.previewLoadSeq
      this.previewSaving = true

      try {
        const res = await fetch(`/api/connections/${encodeURIComponent(clientId)}/remote-files/save`, {
          method: 'POST',
          headers: {'Content-Type': 'application/json', 'X-RCH-Origin': 'web_ui'},
          body: JSON.stringify({
            path: this.previewFilePath,
            content,
            encoding: this.previewFileCodec,
          }),
        })

        const json = await res.json()
        if (!res.ok || json.code !== 0) {
          throw new Error(json.message || 'Failed to save file')
        }

        ElMessage.success('File saved successfully')

        this.applySavedPreviewContent(seq, content)

        if (this.remoteFilesDialogVisible) {
          this.$emit('remote-directory-maybe-changed')
        }
      } catch (e) {
        ElMessage.error(e.message || 'Failed to save file')
      } finally {
        if (this.isPreviewSessionCurrent(seq)) this.previewSaving = false
      }
    },

    async saveToNewSharedFile(content) {
      const filename = this.normalizeSharedArtifactFilename(this.previewFilePath)
      if (!filename) {
        ElMessage.warning('Invalid file name')
        return
      }

      const seq = this.previewLoadSeq
      this.previewSaving = true

      try {
        const formData = new FormData()
        const blob = new Blob([content == null ? '' : String(content)], {
          type: 'text/plain;charset=utf-8',
        })

        // 复用现有 upload artifact 逻辑，不新建/销毁 Monaco 组件。
        if (typeof File === 'function') {
          formData.append('file', new File([blob], filename, {type: blob.type}))
        } else {
          formData.append('file', blob, filename)
        }
        formData.append('artifact_type', 'shared')
        if (this.sharedCreateFolderId) formData.append('folder_id', this.sharedCreateFolderId)
        formData.append('extra', JSON.stringify({
          saved_from: 'artifact_dialog_create_file',
        }))

        const res = await uploadArtifact(formData)

        const json = await res.json()
        if (!res.ok || json.code !== 0) {
          throw new Error(json.message || 'Failed to create artifact')
        }

        const artifact = json.data || {}
        ElMessage.success('Artifact created successfully')

        const applied = this.applySavedPreviewContent(seq, content)
        if (applied) this.previewFileSize = formatBytes(artifact.size ?? String(content || '').length)

        if (applied && artifact.artifact_id) {
          this.previewSource = 'artifact'
          this.previewFilePath = artifact.artifact_id
          this.previewArtifactInfo = artifact
          this.previewTitle = artifact.original_name || artifact.stored_name || filename
        }

        this.$emit('artifacts-maybe-changed')
      } catch (e) {
        ElMessage.error(e.message || 'Failed to create artifact')
      } finally {
        if (this.isPreviewSessionCurrent(seq)) this.previewSaving = false
      }
    },

    async saveToArtifact(content) {
      if (!this.previewFilePath) {
        ElMessage.warning('Invalid artifact')
        return
      }

      const seq = this.previewLoadSeq
      this.previewSaving = true

      try {
        const res = await saveArtifactContent(this.previewFilePath, content, this.previewFileCodec)

        const json = await res.json()
        if (!res.ok || json.code !== 0) {
          throw new Error(json.message || 'Failed to save artifact')
        }

        ElMessage.success('Artifact saved successfully')

        // 更新本地内容
        const applied = this.applySavedPreviewContent(seq, content)

        // 更新文件大小显示
        if (applied && json.data && json.data.size != null) {
          this.previewFileSize = formatBytes(json.data.size)
        }

        // 刷新 Artifact 列表
        this.$emit('artifacts-maybe-changed')

        // 触发 artifact_created 事件，通知其他组件
        if (applied && this.previewArtifactInfo) {
          // 更新本地 artifact 信息
          this.previewArtifactInfo.size = json.data?.size ?? this.previewArtifactInfo.size
        }
      } catch (e) {
        ElMessage.error(e.message || 'Failed to save artifact')
      } finally {
        if (this.isPreviewSessionCurrent(seq)) this.previewSaving = false
      }
    },

  },
}
