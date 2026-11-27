<template>
  <div class="artifact-dialog-toolbar" role="toolbar" aria-label="Artifact actions">
    <div class="artifact-toolbar-group">
      <el-button class="toolbar-btn" size="small" @click="$emit('refresh')">Refresh</el-button>
      <el-button v-if="isSharedFilesTab" class="toolbar-btn" size="small" @click="$emit('create-file')">Create File</el-button>
      <el-button v-if="isSharedFilesTab" class="toolbar-btn" size="small" :loading="sharedFileUploading" @click="$emit('upload')">Upload</el-button>
      <span class="artifact-toolbar-divider" aria-hidden="true"></span>
      <el-button v-if="isSharedFilesTab" class="toolbar-btn" size="small" :disabled="!canEditSelectedFolder" @click="$emit('rename-folder')">Rename Folder</el-button>
      <el-button v-if="isSharedFilesTab" class="toolbar-btn" size="small" :disabled="!canEditSelectedFolder" @click="$emit('delete-folder')">Delete Folder</el-button>
      <el-button class="toolbar-btn" size="small" type="danger" plain :disabled="!selectedArtifactIds.length"
                 :loading="artifactBulkDeleting" @click="$emit('delete-selected')">
        Delete {{ selectedArtifactIds.length ? ` (${selectedArtifactIds.length})` : '' }}
      </el-button>
      <el-button class="toolbar-btn" size="small" type="danger" :loading="artifactClearing"
                 @click="$emit('clear')">Clear</el-button>
    </div>
    <div class="artifact-toolbar-filters">
      <el-input :model-value="artifactKeyword" @update:model-value="$emit('update:artifactKeyword', $event)" class="artifact-toolbar-search" clearable size="small" placeholder="Search" />
      <el-select v-if="showArtifactMachineFilter" :model-value="artifactMachineIdFilter" @update:model-value="$emit('update:artifactMachineIdFilter', $event || '')"
                 class="artifact-toolbar-device" clearable filterable size="small"
                 placeholder="Filter by device" @change="$emit('machine-filter-change')">
        <el-option v-for="item in artifactMachineOptions" :key="item.machine_id"
                   :label="item.label" :value="item.machine_id" />
      </el-select>
    </div>
  </div>
</template>

<script>

export default {
  name: 'ArtifactToolbar',
  props: {
    isSharedFilesTab: { type: Boolean, required: true },
    sharedFileUploading: { type: Boolean, required: true },
    canEditSelectedFolder: { type: Boolean, required: true },
    selectedArtifactIds: { type: Array, required: true },
    artifactBulkDeleting: { type: Boolean, required: true },
    artifactClearing: { type: Boolean, required: true },
    artifactKeyword: { type: String, required: true },
    showArtifactMachineFilter: { type: Boolean, required: true },
    artifactMachineIdFilter: { type: String, required: true },
    artifactMachineOptions: { type: Array, required: true },
  },
  emits: ['refresh', 'create-file', 'upload', 'rename-folder', 'delete-folder', 'delete-selected', 'clear', 'update:artifactKeyword', 'update:artifactMachineIdFilter', 'machine-filter-change'],
}
</script>
