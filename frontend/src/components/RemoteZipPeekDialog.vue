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
    <ArchivePreviewPanel ref="archivePanelRef" :inspect="inspectArchive" :read-entry="readArchiveEntry" />
    <template #footer><el-button size="small" @click="visible = false">Close</el-button></template>
  </el-dialog>
</template>

<script>
import ArchivePreviewPanel from './ArchivePreviewPanel.vue'
import { inspectRemoteZip, readRemoteZipEntry } from '../api/remoteFilesApi.js'

export default {
  name: 'RemoteZipPeekDialog',
  components: { ArchivePreviewPanel },
  props: { selectedId: { type: String, default: '' } },
  data() { return { visible: false, archivePath: '', archiveName: '' } },
  methods: {
    resetState() { this.$refs.archivePanelRef?.resetState() },
    inspectArchive() { return inspectRemoteZip(this.selectedId, this.archivePath) },
    readArchiveEntry(entryName) { return readRemoteZipEntry(this.selectedId, this.archivePath, entryName) },
    async open(row) {
      if (!this.selectedId || !row?.path) return
      this.archivePath = String(row.path).trim()
      this.archiveName = String(row.name || '').trim() || 'archive.zip'
      this.visible = true
      await this.$nextTick()
      await this.$refs.archivePanelRef?.loadArchive()
    },
  },
}
</script>
