<template>
  <el-dialog
    v-model="visible"
    :title="archiveName ? `Peek ZIP · ${archiveName}` : 'Peek ZIP'"
    width="1080px"
    top="5vh"
    append-to-body
    class="remote-zip-peek-dialog"
    @closed="resetState"
  >
    <ArchivePreviewPanel
      ref="archivePanelRef" :inspect="inspectArchive" :read-entry="readArchiveEntry"
      entry-actions @download-entry="downloadEntry" @extract-entry="extractEntry"
    />
    <RemoteZipEntryActions ref="archiveActionsRef" :selected-id="archiveClientId" :archive-path="archivePath" />
    <template #footer><el-button size="small" @click="visible = false">Close</el-button></template>
  </el-dialog>
</template>

<script>
import ArchivePreviewPanel from './ArchivePreviewPanel.vue'
import RemoteZipEntryActions from './RemoteZipEntryActions.vue'
import { inspectRemoteZip, readRemoteZipEntry } from '../api/remoteFilesApi.js'

export default {
  name: 'RemoteZipPeekDialog',
  components: { ArchivePreviewPanel, RemoteZipEntryActions },
  props: { selectedId: { type: String, default: '' } },
  data() { return { visible: false, archivePath: '', archiveName: '', archiveClientId: '' } },
  methods: {
    resetState() {
      this.$refs.archivePanelRef?.resetState()
      this.$refs.archiveActionsRef?.cancelSelection()
    },
    downloadEntry(entry) { this.$refs.archiveActionsRef?.downloadEntry(entry) },
    extractEntry(entry) { this.$refs.archiveActionsRef?.extractEntry(entry) },
    inspectArchive() { return inspectRemoteZip(this.archiveClientId, this.archivePath) },
    readArchiveEntry(entryName) { return readRemoteZipEntry(this.archiveClientId, this.archivePath, entryName) },
    async open(row) {
      if (!this.selectedId || !row?.path) return
      this.archiveClientId = String(this.selectedId)
      this.archivePath = String(row.path).trim()
      this.archiveName = String(row.name || '').trim() || 'archive.zip'
      this.visible = true
      await this.$nextTick()
      await this.$refs.archivePanelRef?.loadArchive()
    },
  },
}
</script>
