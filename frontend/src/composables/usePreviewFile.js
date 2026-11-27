import { ElMessage } from 'element-plus'
import { previewArtifact, inspectArtifactZip, readArtifactZipEntry, savePreviewToSaved } from '../api/artifactsApi.js'
import { inspectRemoteZip, readRemoteZipEntry } from '../api/remoteFilesApi.js'
import { previewBackgroundJobFile } from '../api/backgroundJobsApi.js'
import { formatBytes } from '../utils/formatters.js'
import { PREVIEW_SOURCE_OPERATIONS } from '../utils/previewSources.js'

export default {
  methods: {
    downloadArchiveEntry(entry) {
      this.$refs.archiveActionsRef?.downloadEntry(entry)
    },

    extractArchiveEntry(entry) {
      this.$refs.archiveActionsRef?.extractEntry(entry)
    },

    editRemoteEntry(row) {
      return this.previewRemoteEntry(row, { editImmediately: true })
    },

    async previewRemoteEntry(row, { editImmediately = false } = {}) {
      if (!row || !row.path || row.is_dir || row.is_parent_entry) {
        ElMessage.warning('Please select a file')
        return
      }

      const clientId = String(row.client_id || this.selectedId || '').trim()
      if (!clientId) {
        ElMessage.warning('Please select a device')
        return
      }

      if (!editImmediately && /\.zip$/i.test(String(row.name || row.path))) {
        const path = row.path
        const seq = this.startPreviewSession({ source: 'remote_file', path, remoteClientId: clientId })
        this.previewTitle = row.name || 'ZIP Preview'
        this.previewType = 'archive'
        this.archiveInspect = () => inspectRemoteZip(clientId, path)
        this.archiveReadEntry = entryName => readRemoteZipEntry(clientId, path, entryName)
        this.previewDialogVisible = true
        await this.$nextTick()
        if (this.isPreviewSessionCurrent(seq)) await this.$refs.archivePreviewRef?.loadArchive()
        return
      }

      // 记录文件路径和对应设备，避免全局选择变化后写到其他 Client。
      const path = row.path
      const seq = this.startPreviewSession({ source: 'remote_file', path, remoteClientId: clientId })

      await this.loadPreviewPayload(
          () => fetch(`/api/connections/${encodeURIComponent(clientId)}/remote-files/preview`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json', ...(this.getTabScopedHeaders?.() || {})},
            body: JSON.stringify({path}),
          }),
          row.name || 'File Preview',
          { editImmediately, seq },
      )

      // Remote Files Browser 仍从只读预览开始，由 loadPreviewPayload 设置编辑状态。
    },

    async previewArtifact(row) {
      if (!row || !row.artifact_id) {
        ElMessage.warning('Invalid artifact')
        return
      }

      const artifactId = row.artifact_id
      // Artifact identity is stable across every entry point.
      const seq = this.startPreviewSession({ source: 'artifact', path: artifactId, artifactInfo: row })

      await this.loadPreviewPayload(
          () => previewArtifact(artifactId),
          row.original_name || row.stored_name || 'Artifact Preview',
          { seq },
      )
    },

    async previewBackgroundJobFile(file) {
      if (!file) {
        ElMessage.warning('No preview available')
        return
      }

      if (file.artifact_id) {
        await this.previewArtifact({ ...file, original_name: file.original_name || file.stored_name || 'Job File Preview' })
        return
      }

      if (!file.preview_url) {
        ElMessage.warning('No preview available')
        return
      }

      const url = file.preview_url
      const seq = this.startPreviewSession({ source: 'job_attachment' })
      await this.loadPreviewPayload(
          () => previewBackgroundJobFile(url),
          file.original_name || file.stored_name || 'Job File Preview',
          { seq },
      )
    },

    async saveRemotePreviewToSaved() {
      if (!this.previewCacheArtifactId || this.previewSaving) return
      const seq = this.previewLoadSeq
      this.previewSaving = true
      try {
        const response = await savePreviewToSaved(this.previewCacheArtifactId)
        const json = await response.json()
        if (!response.ok || json.code !== 0) throw new Error(json.message || 'Failed to save preview')
        ElMessage.success('Saved to Saved Files / Downloads')
        this.$emit('artifacts-maybe-changed')
      } catch (error) {
        ElMessage.error(error.message || 'Failed to save preview')
      } finally {
        if (this.isPreviewSessionCurrent(seq)) this.previewSaving = false
      }
    },

    async loadPreviewPayload(fetcher, fallbackTitle = 'File Preview', { editImmediately = false, seq } = {}) {
      // Terminal edit validates the complete editable payload before showing a new dialog.
      if (!editImmediately) this.previewDialogVisible = true
      this.previewLoading = true

      try {
        const res = await fetcher()
        const json = await res.json()
        if (!this.isPreviewSessionCurrent(seq)) return

        if (!res.ok || json.code !== 0) {
          throw new Error(json.message || 'Preview failed')
        }

        const data = json.data || {}
        this.previewCacheArtifactId = this.previewRemoteClientId ? String(data.artifact_id || '') : ''
        if (editImmediately) {
          if (data.truncated) throw new Error('File exceeds the editable preview size limit')
          if (data.type !== 'text') throw new Error('Only text files can be edited')
          if (data.editable !== true) throw new Error('This text file cannot be edited')
          this.previewDialogVisible = true
        }
        this.previewType = data.type || 'unsupported'
        this.previewTitle = data.name || fallbackTitle
        this.previewImageInfo = data.image_info || null

        if (this.previewType === 'image') {
          this.previewUrl = data.url || ''
        } else if (this.previewType === 'archive') {
          const artifactId = String(data.artifact_id || '')
          if (!artifactId) throw new Error('Archive artifact is missing')
          this.archiveInspect = () => inspectArtifactZip(artifactId)
          this.archiveReadEntry = entryName => readArtifactZipEntry(artifactId, entryName)
          await this.$nextTick()
          if (this.isPreviewSessionCurrent(seq)) await this.$refs.archivePreviewRef?.loadArchive()
        } else if (this.previewType === 'text') {
          this.previewText = data.content || ''
          this.previewTruncated = data.truncated || false
          this.previewEditable = data.editable === true && !this.previewTruncated && typeof PREVIEW_SOURCE_OPERATIONS[this.previewSource]?.save === 'function'
          this.previewEditMode = editImmediately
          this.previewFileCodec = data.encoding || 'unknown'
          this.previewOriginalContent = this.previewText
          this.previewFileSize = formatBytes(data.size || this.previewText.length)
          this.previewFileEncoding = this.getEncodingDisplayName(this.previewFileCodec)
          this.previewDetectedLanguage = this.getLanguageDisplayName(this.getLanguageFromFilename(this.previewTitle))

          // 等待 DOM 渲染完成后初始化编辑器
          this.$nextTick(() => {
            if (this.isPreviewSessionCurrent(seq)) this.initMonacoEditor()
          })
        }
      } catch (e) {
        if (this.isPreviewSessionCurrent(seq)) {
          this.previewDialogVisible = false
          ElMessage.error(e.message || 'Preview failed')
        }
      } finally {
        if (this.isPreviewSessionCurrent(seq)) this.previewLoading = false
      }
    },

    getEncodingDisplayName(codec) {
      const names = {
        'utf-8': 'UTF-8',
        'utf-8-sig': 'UTF-8 with BOM',
        'utf-16-le': 'UTF-16 LE with BOM',
        'utf-16-be': 'UTF-16 BE with BOM',
        'unknown': 'Unknown encoding',
      }
      return names[codec] || 'Unknown encoding'
    },


    openPreviewImageInfoDialog() {
      if (!this.previewImageInfo) {
        ElMessage.warning('No image info available')
        return
      }
      this.previewImageInfoDialogVisible = true
    },

    openPreviewOriginal() {
      if (!this.previewUrl) {
        ElMessage.warning('No image available')
        return
      }
      window.open(this.previewUrl, '_blank')
    },

  },
}
