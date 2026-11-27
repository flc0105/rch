import { ElMessage } from 'element-plus'
import { normalizeServerJobFilename } from '../utils/jobFilename.js'
import { downloadServerJob } from '../api/backgroundJobsApi.js'
import { formatBytes } from '../utils/formatters.js'
import * as externalToolsApi from '../api/externalToolsApi.js'

export default {
  methods: {
    showResourceEditor(seq, { title, content, size = content.length, language }) {
      if (!this.isPreviewSessionCurrent(seq)) return
      this.previewTitle = title
      this.previewText = content
      this.previewOriginalContent = content
      this.previewType = 'text'
      this.previewTruncated = false
      this.previewFileSize = formatBytes(size)
      this.previewFileEncoding = 'UTF-8'
      this.previewFileCodec = 'utf-8'
      this.previewEditable = true
      this.previewDetectedLanguage = language || this.getLanguageDisplayName(this.getLanguageFromFilename(title))
      this.previewEditMode = true
      this.previewDialogVisible = true
      this.$nextTick(() => {
        if (this.isPreviewSessionCurrent(seq)) this.initMonacoEditor()
      })
    },
    buildServerScriptTemplate(scriptName = 'new_script.py') {
      const normalizedScriptName = String(scriptName || 'new_script.py').trim().replace(/\\/g, '/').replace(/^\/+/, '') || 'new_script.py'
      const classBaseName = normalizedScriptName
          .replace(/\.py$/i, '')
          .split('/')
          .pop()
          .split(/[^a-zA-Z0-9]+/)
          .filter(Boolean)
          .map(part => part.charAt(0).toUpperCase() + part.slice(1))
          .join('') || 'NewScript'

      return `SCRIPT_METADATA = {
    "name": "${normalizedScriptName.replace(/\.py$/i, '')}",
    "display_name": "${classBaseName}",
    "description": "Describe what this script does",
    "platforms": ["common"],
    "category": "General",
    "params": [
        {
            "name": "example",
            "type": "string",
            "required": False,
            "default": "",
            "description": "Example parameter"
        }
    ]
}

value = kwargs.get('example', '')
print(value)

# kwargs will be injected by the script runner.
# Example:
# value = kwargs.get('example', '')
`
    },

    normalizeSharedArtifactFilename(filename, fallbackName = 'new_file.txt') {
      let normalized = String(filename || '').trim().replace(/\\/g, '/').replace(/^\/+/, '')
      if (!normalized) {
        normalized = fallbackName
      }
      return normalized
    },

    openNewSharedFileEditor(filename = 'new_file.txt', folderId = '') {
      const normalizedFilename = this.normalizeSharedArtifactFilename(filename)
      if (!normalizedFilename) {
        ElMessage.warning('Invalid file name')
        return
      }

      const seq = this.startPreviewSession({ source: 'new_shared_file', path: normalizedFilename })
      this.sharedCreateFolderId = String(folderId || '')
      this.showResourceEditor(seq, { title: normalizedFilename, content: '' })
    },


    buildServerJobTemplate(scriptName = 'new_job.py') {
      const normalizedScriptName = normalizeServerJobFilename(scriptName)
      const classBaseName = normalizedScriptName
          .replace(/\.py$/i, '')
          .split('/')
          .pop()
          .split(/[^a-zA-Z0-9]+/)
          .filter(Boolean)
          .map(part => part.charAt(0).toUpperCase() + part.slice(1))
          .join('') || 'NewBackgroundJob'

      return `JOB_METADATA = {\n    "name": "${normalizedScriptName.replace(/\.py$/i, '')}",\n    "display_name": "${classBaseName}",\n    "description": "Describe what this job does",\n    "platforms": ["mac"],\n    "params": [\n        {\n            "name": "interval_seconds",\n            "type": "integer",\n            "required": False,\n            "default": 10,\n            "min": 1,\n            "description": "Loop interval in seconds"\n        }\n    ]\n}\n\nimport time\n\nfrom client.jobs.core.job import Job\n\n\nclass ${classBaseName}(Job):\n    def __init__(self):\n        super().__init__()\n        self.interval = 10\n\n    def on_context_bound(self):\n        self.interval = int(self.get_job_param("interval_seconds", 10) or 10)\n\n    def run(self):\n        self.mark_running()\n        self.send_to_server(1, "${normalizedScriptName} started")\n\n        try:\n            while not self.stop_event.is_set():\n                self.send_to_server(1, f"heartbeat: {time.strftime('%Y-%m-%d %H:%M:%S')}")\n                time.sleep(self.interval)\n        finally:\n            self.send_to_server(1, "${normalizedScriptName} stopped")\n            self.mark_stopped()\n\n    def stop(self, notify=True):\n        self.request_stop(notify=notify)\n`
    },

    async openExternalToolMetaEditor(toolId) {
      const normalizedToolId = String(toolId || '').trim()
      if (!normalizedToolId) {
        ElMessage.warning('Invalid external tool id')
        return
      }

      const seq = this.startPreviewSession({ source: 'external_tool_meta', path: normalizedToolId })
      this.previewLoading = true
      try {
        const data = await externalToolsApi.loadExternalToolMetaContent(normalizedToolId)
        const content = data.content || ''

        this.showResourceEditor(seq, { title: data.name || `${normalizedToolId}.json`, content, size: data.size || content.length, language: 'JSON' })
      } catch (e) {
        if (this.isPreviewSessionCurrent(seq)) ElMessage.error(e.message || 'Failed to load external tool meta')
      } finally {
        if (this.isPreviewSessionCurrent(seq)) this.previewLoading = false
      }
    },

    openNewRemoteScriptEditor(scriptName = 'new_script.py') {
      if (!this.selectedId) {
        ElMessage.warning('Please select a device')
        return
      }

      let normalizedScriptName = String(scriptName || '').trim().replace(/\\/g, '/').replace(/^\/+/, '')
      if (!normalizedScriptName) {
        normalizedScriptName = 'new_script.py'
      }
      if (!/\.py$/i.test(normalizedScriptName)) {
        normalizedScriptName = `${normalizedScriptName}.py`
      }

      const content = this.buildServerScriptTemplate(normalizedScriptName)

      const seq = this.startPreviewSession({ source: 'server_script', path: normalizedScriptName })
      this.showResourceEditor(seq, { title: normalizedScriptName, content })
    },

    openNewRemoteJobEditor(scriptName = 'new_job.py') {
      if (!this.selectedId) {
        ElMessage.warning('Please select a device')
        return
      }

      const normalizedScriptName = normalizeServerJobFilename(scriptName)
      const content = this.buildServerJobTemplate(normalizedScriptName)

      const seq = this.startPreviewSession({ source: 'background_job', path: normalizedScriptName })
      this.showResourceEditor(seq, { title: normalizedScriptName, content })
    },

    async openRemoteScriptEditorInternal(scriptName) {
      if (!this.selectedId) {
        ElMessage.warning('Please select a device')
        return
      }

      let normalizedScriptName = String(scriptName || '').trim().replace(/\\/g, '/').replace(/^\/+/, '')
      if (!normalizedScriptName) {
        ElMessage.warning('Invalid script name')
        return
      }
      if (!/\.py$/i.test(normalizedScriptName)) {
        normalizedScriptName = `${normalizedScriptName}.py`
      }

      const seq = this.startPreviewSession({ source: 'server_script', path: normalizedScriptName })
      this.previewLoading = true
      try {
        const res = await fetch(`/api/scripts/download?name=${encodeURIComponent(normalizedScriptName)}`)
        if (!res.ok) {
          throw new Error(`Failed to load script: ${res.statusText}`)
        }
        const content = await res.text()

        this.showResourceEditor(seq, { title: normalizedScriptName, content })
      } catch (e) {
        if (this.isPreviewSessionCurrent(seq)) ElMessage.error(e.message || 'Failed to load script')
      } finally {
        if (this.isPreviewSessionCurrent(seq)) this.previewLoading = false
      }
    },

    async openRemoteJobEditor(scriptName) {
      if (!this.selectedId) {
        ElMessage.warning('Please select a device')
        return
      }

      let normalizedScriptName = normalizeServerJobFilename(scriptName, 'new_job.py')
      if (!normalizedScriptName) {
        ElMessage.warning('Invalid script name')
        return
      }

      const seq = this.startPreviewSession({ source: 'background_job', path: normalizedScriptName })
      this.previewLoading = true
      try {
        const res = await downloadServerJob(normalizedScriptName)
        if (!res.ok) {
          throw new Error(`Failed to load job: ${res.statusText}`)
        }
        const content = await res.text()

        this.showResourceEditor(seq, { title: normalizedScriptName, content })
      } catch (e) {
        if (this.isPreviewSessionCurrent(seq)) ElMessage.error(e.message || 'Failed to load job')
      } finally {
        if (this.isPreviewSessionCurrent(seq)) this.previewLoading = false
      }
    },

    handleBackgroundJobDeleted(normalizedName) {
      if (
          this.previewDialogVisible &&
          this.previewSource === 'background_job'
      ) {
        const currentPreviewName = normalizeServerJobFilename(this.previewFilePath || this.previewTitle || '')

        if (currentPreviewName === normalizedName) {
          this.previewDialogVisible = false
        }
      }
    },


  },
}
