<template>
  <aside class="artifact-folder-sidebar">
    <div class="artifact-folder-heading">
      <span>Folders</span>
      <el-button v-if="isSharedFilesTab" size="small" text type="primary" @click="$emit('create-folder')">New Folder</el-button>
    </div>
    <el-tree
      :key="artifactActiveTab"
      :data="folderTreeNodes"
      node-key="folder_id"
      :props="{ label: 'name', children: 'children' }"
      :default-expand-all="true"
      highlight-current
      :current-node-key="selectedFolderId || ARTIFACT_FOLDER_ALL"
      @node-click="$emit('select-folder', $event)"
    >
      <template #default="{ data }">
        <span class="artifact-tree-entry">
          <FolderOpen v-if="data.folder_id === ARTIFACT_FOLDER_ALL" :size="15" aria-hidden="true" />
          <Folder v-else :size="15" aria-hidden="true" />
          <span class="ellipsis">{{ data.name }}</span>
        </span>
      </template>
    </el-tree>
  </aside>
</template>

<script>
import { Folder, FolderOpen } from '@lucide/vue'
import { ARTIFACT_FOLDER_ALL } from '../data/artifactConstants.js'
export default {
  name: 'ArtifactFolderTree',
  props: {
    artifactActiveTab: { type: String, required: true },
    folderTreeNodes: { type: Array, required: true },
    selectedFolderId: { type: String, required: true },
    isSharedFilesTab: { type: Boolean, required: true },
  },
  emits: ['create-folder', 'select-folder'],
  components: { Folder, FolderOpen },
  data: () => ({ ARTIFACT_FOLDER_ALL }),
}
</script>
