import { ElMessage } from 'element-plus'
import { previewArtifact } from '../api/artifactsApi.js'
import { downloadServerJob } from '../api/backgroundJobsApi.js'
import * as externalToolsApi from '../api/externalToolsApi.js'
import { PREVIEW_SOURCE_OPERATIONS } from '../utils/previewSources.js'

export default {
  methods: {
    async reloadPreviewContent() {
      if (this.previewType !== 'text') {
        ElMessage.warning('Only text content can be reloaded')
        return
      }

      if (!this.previewEditMode) {
        ElMessage.warning('Please enter edit mode first')
        return
      }

      if (this.previewReloading || this.previewSaving) return

      const seq = this.previewLoadSeq
      this.previewReloading = true

      try {
        const data = await this.fetchLatestPreviewTextPayload()
        if (!this.isPreviewSessionCurrent(seq)) return
        const content = data.content || ''

        this.applyReloadedPreviewText({
          content,
          name: data.name,
          size: data.size,
          truncated: data.truncated,
          encoding: data.encoding,
          editable: data.editable,
        })

        ElMessage.success('File reloaded')
      } catch (e) {
        if (this.isPreviewSessionCurrent(seq)) ElMessage.error(e.message || 'Failed to reload file')
      } finally {
        if (this.isPreviewSessionCurrent(seq)) this.previewReloading = false
      }
    },

    async fetchLatestPreviewTextPayload() {
      const source = PREVIEW_SOURCE_OPERATIONS[this.previewSource]
      if (!source?.reload) throw new Error('Unknown preview source')
      return source.reload(this)
    },

    async fetchLatestRemoteFileTextPayload() {
      const clientId = String(this.previewRemoteClientId || '').trim()
      if (!clientId || !this.previewFilePath) {
        throw new Error('Invalid remote file path')
      }

      const res = await fetch(`/api/connections/${encodeURIComponent(clientId)}/remote-files/preview`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json', ...(this.getTabScopedHeaders?.() || {})},
        body: JSON.stringify({path: this.previewFilePath}),
      })

      return await this.parsePreviewTextResponse(res, 'Failed to reload remote file')
    },

    async fetchLatestArtifactTextPayload() {
      if (!this.previewFilePath) {
        throw new Error('Invalid artifact')
      }

      const res = await previewArtifact(this.previewFilePath)

      return await this.parsePreviewTextResponse(res, 'Failed to reload artifact')
    },

    async fetchLatestServerScriptTextPayload() {
      if (!this.previewFilePath) {
        throw new Error('Invalid script name')
      }

      const res = await fetch(`/api/scripts/download?name=${encodeURIComponent(this.previewFilePath)}`)

      if (!res.ok) {
        throw new Error(`Failed to reload script: ${res.statusText}`)
      }

      const content = await res.text()

      return {
        content,
        name: this.previewTitle || this.previewFilePath,
        size: content.length,
        truncated: false,
        encoding: 'utf-8',
        editable: true,
      }
    },

    async fetchLatestBackgroundJobTextPayload() {
      if (!this.previewFilePath) {
        throw new Error('Invalid job name')
      }

      const res = await downloadServerJob(this.previewFilePath)

      if (!res.ok) {
        throw new Error(`Failed to reload job: ${res.statusText}`)
      }

      const content = await res.text()

      return {
        content,
        name: this.previewTitle || this.previewFilePath,
        size: content.length,
        truncated: false,
        encoding: 'utf-8',
        editable: true,
      }
    },

    async fetchLatestExternalToolMetaTextPayload() {
      if (!this.previewFilePath) {
        throw new Error('Invalid external tool id')
      }

      const data = await externalToolsApi.loadExternalToolMetaContent(this.previewFilePath)
      const content = data.content || ''

      return {
        content,
        name: data.name || this.previewTitle || `${this.previewFilePath}.json`,
        size: data.size || content.length,
        truncated: false,
        encoding: 'utf-8',
        editable: true,
      }
    },


    async parsePreviewTextResponse(res, fallbackMessage = 'Failed to reload file') {
      const json = await res.json()

      if (!res.ok || json.code !== 0) {
        throw new Error(json.message || fallbackMessage)
      }

      const data = json.data || {}

      if (data.type && data.type !== 'text') {
        throw new Error('Reloaded file is not text content')
      }

      return {
        content: data.content || '',
        name: data.name || this.previewTitle,
        size: data.size,
        truncated: data.truncated || false,
        encoding: data.encoding || 'unknown',
        editable: data.editable === true,
      }
    },

  },
}
