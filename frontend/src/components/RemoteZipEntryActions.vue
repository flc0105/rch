<template>
  <RemoteFilePicker
    v-model:visible="folderPickerVisible"
    :selected-id="selectedId"
    :initial-path="pickerInitialPath"
    selection-mode="folder"
    :allow-current-folder="true"
    :append-to-body="true"
    @select="extractToFolder"
  />
</template>

<script>
import { ElMessage, ElMessageBox } from 'element-plus'
import RemoteFilePicker from './RemoteFilePicker.vue'
import { downloadRemoteZipEntry, extractRemoteZip } from '../api/remoteFilesApi.js'
import { prepareExtractConflict } from '../utils/remoteFileConflicts.js'

export default {
  name: 'RemoteZipEntryActions',
  components: { RemoteFilePicker },
  props: {
    selectedId: { type: String, default: '' },
    archivePath: { type: String, default: '' },
  },
  emits: ['artifacts-maybe-changed', 'remote-directory-maybe-changed'],
  data() {
    return {
      folderPickerVisible: false,
      pickerInitialPath: '',
      pendingEntry: null,
      downloading: false,
      extracting: false,
    }
  },
  watch: {
    selectedId() { this.cancelSelection() },
    archivePath() { this.cancelSelection() },
  },
  methods: {
    cancelSelection() {
      this.folderPickerVisible = false
      this.pendingEntry = null
    },
    async downloadEntry(entry) {
      const clientId = String(this.selectedId || '').trim()
      const archivePath = String(this.archivePath || '').trim()
      if (!clientId || !archivePath || !entry?.path || entry.is_dir || this.downloading) return
      this.downloading = true
      try {
        ElMessage.success({ message: `Download started: ${entry.name || 'file'}`, duration: 1800 })
        const response = await downloadRemoteZipEntry(clientId, archivePath, entry.entry_name || entry.path)
        const json = await response.json()
        if (!response.ok || json.code !== 0) throw new Error(json.message || 'ZIP entry download failed')
        const artifact = json.data?.artifact || json.data?.file
        if (!artifact?.artifact_id) throw new Error('Download finished, but artifact was not found')
        window.open(artifact.download_url || `/api/artifacts/${encodeURIComponent(artifact.artifact_id)}/download`, '_blank')
        ElMessage.success(`Downloaded: ${entry.name}`)
        this.$emit('artifacts-maybe-changed')
      } catch (error) {
        ElMessage.error(error?.message || 'ZIP entry download failed')
      } finally {
        this.downloading = false
      }
    },
    extractEntry(entry) {
      if (!this.selectedId || !this.archivePath || !entry?.path || this.extracting) return
      this.pendingEntry = { path: entry.path, name: entry.name || entry.path, is_dir: !!entry.is_dir }
      // Starting near the archive directory makes choosing a destination quicker.
      const parentPath = String(this.archivePath).replace(/[\\/][^\\/]+$/, '')
      this.pickerInitialPath = /^[A-Za-z]:$/.test(parentPath) ? `${parentPath}\\` : (parentPath || '/')
      this.folderPickerVisible = true
    },
    async extractToFolder(destinationDir) {
      const entry = this.pendingEntry
      this.pendingEntry = null
      const clientId = String(this.selectedId || '').trim()
      const archivePath = String(this.archivePath || '').trim()
      if (!clientId || !archivePath || !entry?.path || !destinationDir || this.extracting) return
      try {
        await this.$nextTick()
        await ElMessageBox.confirm(
          `Extract "${entry.name}" to "${destinationDir}"?`,
          'Extract ZIP Entry',
          { type: 'warning', confirmButtonText: 'Extract', cancelButtonText: 'Cancel' },
        )
      } catch (_) {
        return
      }
      // The confirmation may remain open while the selected client/archive changes.
      if (String(this.selectedId || '').trim() !== clientId ||
          String(this.archivePath || '').trim() !== archivePath) return
      this.extracting = true
      try {
        const request = { path: archivePath, destination_dir: destinationDir, entry_name: entry.path }
        const conflicts = await prepareExtractConflict(clientId, request)
        if (conflicts === false || String(this.selectedId || '').trim() !== clientId || String(this.archivePath || '').trim() !== archivePath) return
        const response = await extractRemoteZip(clientId, { ...request, ...(conflicts || {}) })
        const json = await response.json()
        if (!response.ok || json.code !== 0) throw new Error(json.message || 'ZIP entry extraction failed')
        ElMessage.success(`Extracted to: ${json.data?.extracted_to || destinationDir}`)
        this.$emit('remote-directory-maybe-changed')
      } catch (error) {
        ElMessage.error(error?.message || 'ZIP entry extraction failed')
      } finally {
        this.extracting = false
      }
    },
  },
}
</script>
