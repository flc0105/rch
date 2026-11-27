<template>
  <el-dialog
    :model-value="visible" @update:model-value="$emit('update:visible', $event)"
    :title="title"
    width="760px"
    top="8vh"
    class="fixed-dialog"
  >
    <div class="file-info-body">
      <template v-if="hasInfo">
        <div
          v-for="section in sections"
          :key="section.key"
          class="file-info-section"
        >
          <div class="file-info-title">
            {{ section.title }}
          </div>

          <div
            v-for="item in section.items"
            :key="section.key + '-' + item.key"
            class="file-info-row"
          >
            <div class="file-info-label">
              {{ item.label }}
            </div>

            <div class="file-info-value" :class="{ 'file-info-monospace': monospaceValues }">
              {{ item.value }}
            </div>
          </div>
        </div>
      </template>

      <el-empty
        v-else
        :description="emptyDescription"
      />
    </div>
  </el-dialog>
</template>

<script>

export default {
  name: 'FileInfoDialog',
  props: {
    visible: { type: Boolean, required: true },
    title: { type: String, required: true },
    hasInfo: { type: Boolean, required: true },
    sections: { type: Array, required: true },
    emptyDescription: { type: String, required: true },
    monospaceValues: { type: Boolean, required: true },
  },
  emits: ['update:visible'],
}
</script>
<style scoped>
.file-info-body {
  max-height: 65vh;
  overflow: auto;
}

.file-info-section {
  margin-bottom: 20px;
}

.file-info-title {
  font-weight: 600;
  font-size: 14px;
  margin-bottom: 10px;
}

.file-info-row {
  display: grid;
  grid-template-columns: 180px 1fr;
  gap: 12px;
  padding: 8px 0;
  border-bottom: 1px solid #ebeef5;
}

.file-info-label {
  color: #606266;
  font-weight: 500;
}

.file-info-value {
  word-break: break-word;
}
.file-info-monospace {
  white-space: pre-wrap;
  font-family: Monaco, Menlo, "Ubuntu Mono", Consolas, monospace;
  font-size: 12px;
  line-height: 1.5;
}
</style>
