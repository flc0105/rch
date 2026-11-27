<template>
  <FolderUp v-if="entry.is_parent_entry" :size="size" class="remote-entry-icon remote-entry-folder" aria-hidden="true" />
  <Folder v-else-if="entry.is_dir" :size="size" class="remote-entry-icon remote-entry-folder" aria-hidden="true" />
  <FileArchive v-else-if="isZipEntry(entry)" :size="size" class="remote-entry-icon" aria-hidden="true" />
  <File v-else :size="size" class="remote-entry-icon" aria-hidden="true" />
</template>

<script>
import { File, FileArchive, Folder, FolderUp } from '@lucide/vue'
import { isZipEntry } from '../utils/remotePaths.js'

export default {
  name: 'RemoteFileEntryIcon',
  components: { File, FileArchive, Folder, FolderUp },
  props: {
    entry: { type: Object, required: true },
    size: { type: Number, default: 16 },
  },
  methods: { isZipEntry },
}
</script>

<style scoped>
.remote-entry-icon { flex: 0 0 auto; vertical-align: middle; color: var(--el-text-color-secondary); }
.remote-entry-folder { color: var(--el-color-warning); }
</style>
