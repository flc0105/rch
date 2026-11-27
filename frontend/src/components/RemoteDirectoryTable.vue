<template>
  <el-table
    ref="tableRef"
    :data="entries"
    v-loading="loading"
    stripe
    width="100%"
    height="100%"
    :empty-text="emptyText"
    table-layout="fixed"
    @row-dblclick="(...args) => $emit('row-dblclick', ...args)"
    @selection-change="$emit('selection-change', $event)"
    @row-click="(...args) => $emit('row-click', ...args)"
  >
    <slot name="selection" />
    <el-table-column label="Name" :min-width="nameWidth" show-overflow-tooltip>
      <template #default="{ row }">
        <div class="file-cell remote-file-name-cell">
          <RemoteFileEntryIcon :entry="row" />
          <span class="file-cell-text remote-file-name-text">{{ row.is_parent_entry ? '..' : row.name }}</span>
          <el-tag v-if="row.is_parent_entry" size="small" type="info">Parent</el-tag>
          <el-tag v-else-if="row.is_symlink" size="small" type="info">Link</el-tag>
          <slot name="name-badges" :row="row" />
        </div>
      </template>
    </el-table-column>
    <slot name="after-name" />
    <el-table-column label="Type" :width="typeWidth" align="center">
      <template #default="{ row }">
        {{ row.is_parent_entry ? 'Parent' : (row.is_dir ? 'Folder' : 'File') }}
      </template>
    </el-table-column>
    <el-table-column label="Size" :width="sizeWidth" align="center">
      <template #default="{ row }">{{ row.is_dir ? '-' : formatBytes(row.size) }}</template>
    </el-table-column>
    <slot name="after-size" />
    <slot name="actions" />
  </el-table>
</template>

<script>
import RemoteFileEntryIcon from './RemoteFileEntryIcon.vue'
import { formatBytes } from '../utils/formatters.js'

export default {
  components: { RemoteFileEntryIcon },
  name: 'RemoteDirectoryTable',
  props: {
    entries: { type: Array, required: true },
    loading: { type: Boolean, required: true },
    emptyText: { type: String, required: true },
    nameWidth: { type: Number, required: true },
    typeWidth: { type: Number, required: true },
    sizeWidth: { type: Number, required: true },
  },
  emits: ['row-dblclick', 'row-click', 'selection-change'],
  methods: {
    formatBytes,
    clearSelection() { this.$refs.tableRef?.clearSelection() },
    toggleRowSelection(row, selected) { this.$refs.tableRef?.toggleRowSelection(row, selected) },
  },
}
</script>

<style scoped>
.remote-file-name-cell {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.remote-file-name-text {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
