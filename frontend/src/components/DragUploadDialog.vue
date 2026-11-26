<template>
  <el-dialog
    :model-value="modelValue"
    :title="title"
    width="560px"
    class="drag-upload-dialog"
    :close-on-click-modal="!loading"
    :close-on-press-escape="!loading"
    :show-close="!loading"
    @update:model-value="handleVisibleChange"
  >
    <div
      class="drag-upload-dropzone"
      :class="{ 'is-dragging': dragging, 'is-loading': loading || scanning }"
      role="button"
      tabindex="0"
      @click="openFilePicker"
      @keydown.enter.prevent="openFilePicker"
      @keydown.space.prevent="openFilePicker"
      @dragenter.prevent="handleDragEnter"
      @dragover.prevent="handleDragOver"
      @dragleave.prevent="handleDragLeave"
      @drop.prevent="handleDrop"
    >
      <div class="drag-upload-icon">⬆</div>
      <div class="drag-upload-title">Drop files here or click to choose</div>
      <div class="drag-upload-desc">{{ helperText }}</div>
    </div>

    <input
      ref="fileInputRef"
      type="file"
      class="drag-upload-input"
      :accept="accept"
      :multiple="multiple"
      @change="handleInputChange"
    />

    <div
      v-if="selectedItems.length"
      class="drag-upload-file-panel"
    >
      <div class="drag-upload-file-header">
        <span>Selected items</span>
        <span>{{ selectedItems.length }}</span>
      </div>

      <div class="drag-upload-file-list">
        <div
          v-for="(file, index) in selectedItems"
          :key="selectedItemKey(file, index)"
          class="drag-upload-file-row"
        >
          <div class="drag-upload-file-main">
            <div class="drag-upload-file-name">{{ file.name }}</div>
            <div class="drag-upload-file-size">{{ file.kind === 'directory' ? `Folder · ${file.files.length} files` : formatFileSize(file.file?.size) }}</div>
          </div>

          <el-button
            size="small"
            link
            type="danger"
            :disabled="loading"
            @click.stop="removeSelectedItem(index)"
          >
            Remove
          </el-button>
        </div>
      </div>
    </div>

    <template #footer>
      <el-button :disabled="loading" @click="closeDialog">Cancel</el-button>
      <el-button
        :disabled="!selectedItems.length || loading || scanning"
        @click="clearSelectedItems"
      >
        Clear
      </el-button>
      <el-button
        type="primary"
        :disabled="!selectedItems.length || scanning"
        :loading="loading"
        @click="submitUpload"
      >
        {{ buttonText }}
      </el-button>
    </template>
  </el-dialog>
</template>

<script>
import { formatBytesHuman } from '../utils/formatters.js'
import { collectTransferAttachments } from '../utils/browserFileEntries.js'
import { ElMessage } from 'element-plus'
export default {
  name: 'DragUploadDialog',

  props: {
    modelValue: { type: Boolean, default: false },
    title: { type: String, default: 'Upload Files' },
    helperText: { type: String, default: 'Only files are supported.' },
    buttonText: { type: String, default: 'Upload' },
    accept: { type: String, default: '' },
    multiple: { type: Boolean, default: false },
    allowDirectories: { type: Boolean, default: false },
    loading: { type: Boolean, default: false },
  },

  emits: ['update:modelValue', 'upload'],

  data() {
    return {
      dragging: false,
      dragDepth: 0,
      scanning: false,
      scanSeq: 0,
      selectedItems: [],
    }
  },

  watch: {
    modelValue(value) {
      if (!value) {
        this.resetAllState()
      }
    },
  },

  methods: {
    handleVisibleChange(value) {
      if (this.loading && !value) return
      this.$emit('update:modelValue', value)
      if (!value) {
        this.resetAllState()
      }
    },

    closeDialog() {
      this.handleVisibleChange(false)
    },

    openFilePicker() {
      if (this.loading || this.scanning) return
      const input = this.$refs.fileInputRef
      if (!input) return
      input.value = ''
      input.click()
    },

    handleDragEnter() {
      if (this.loading) return
      this.dragDepth += 1
      this.dragging = true
    },

    handleDragOver() {
      if (this.loading) return
      this.dragging = true
    },

    handleDragLeave() {
      if (this.loading) return
      this.dragDepth = Math.max(this.dragDepth - 1, 0)
      if (this.dragDepth === 0) {
        this.dragging = false
      }
    },

    async handleDrop(event) {
      if (this.loading || this.scanning) return
      this.resetDragState()
      this.scanning = true
      const scanSeq = this.scanSeq
      try {
        const attachments = this.allowDirectories
          ? await collectTransferAttachments(event?.dataTransfer)
          : Array.from(event?.dataTransfer?.files || []).map(file => ({ kind: 'file', name: file.name, file }))
        if (this.modelValue && scanSeq === this.scanSeq) this.addSelectedItems(attachments)
      } catch (error) {
        if (this.modelValue && scanSeq === this.scanSeq) {
          ElMessage.error(error.message || 'Failed to read dropped files')
        }
      } finally {
        if (scanSeq === this.scanSeq) this.scanning = false
      }
    },

    handleInputChange(event) {
      const files = Array.from(event?.target?.files || [])
      this.addSelectedItems(files.map(file => ({ kind: 'file', name: file.name, file })))
      if (event?.target) event.target.value = ''
    },

    addSelectedItems(files) {
      const validFiles = files.filter(file => file && typeof file.name === 'string')
      if (!validFiles.length) return

      if (!this.multiple) {
        this.selectedItems = [validFiles[0]]
        return
      }

      const nextFiles = [...this.selectedItems, ...validFiles]
      const fileMap = new Map()

      nextFiles.forEach(file => {
        fileMap.set(this.selectedItemKey(file), file)
      })

      this.selectedItems = Array.from(fileMap.values())
    },

    submitUpload() {
      if (!this.selectedItems.length || this.loading) return
      this.$emit('upload', [...this.selectedItems])
    },

    removeSelectedItem(index) {
      if (this.loading) return
      this.selectedItems = this.selectedItems.filter((_, fileIndex) => fileIndex !== index)
    },

    clearSelectedItems() {
      if (this.loading) return
      this.selectedItems = []
    },

    selectedItemKey(file, index = '') {
      return [file?.kind || 'file', file?.name || '', file?.file?.size || 0, file?.file?.lastModified || 0, index].join('-')
    },

    formatFileSize(value) {
      return formatBytesHuman(value, { precision: 'one', maxUnit: 'TB', invalid: '0 B', nonPositiveAsZero: true })
    },

    resetDragState() {
      this.dragging = false
      this.dragDepth = 0
    },

    resetAllState() {
      this.scanSeq += 1
      this.scanning = false
      this.resetDragState()
      this.selectedItems = []
    },
  },
}
</script>

<style scoped>
.drag-upload-dropzone {
  min-height: 190px;
  border: 1px dashed rgba(148, 163, 184, 0.75);
  border-radius: 18px;
  background: rgba(248, 250, 252, 0.72);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 28px 24px;
  cursor: pointer;
  text-align: center;
  transition: border-color 0.16s ease, background 0.16s ease, box-shadow 0.16s ease;
}

.drag-upload-dropzone:hover,
.drag-upload-dropzone.is-dragging {
  border-color: var(--el-color-primary);
  background: rgba(64, 158, 255, 0.08);
  box-shadow: 0 8px 24px rgba(15, 23, 42, 0.08);
}

.drag-upload-dropzone.is-loading {
  cursor: wait;
  opacity: 0.72;
}

.drag-upload-icon {
  width: 46px;
  height: 46px;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: rgba(64, 158, 255, 0.12);
  color: var(--el-color-primary);
  font-size: 24px;
  line-height: 1;
}

.drag-upload-title {
  font-size: 16px;
  font-weight: 700;
  color: var(--text, #0f172a);
}

.drag-upload-desc {
  font-size: 13px;
  color: var(--muted-2, #64748b);
  line-height: 1.5;
}

.drag-upload-input {
  display: none;
}

.drag-upload-file-panel {
  margin-top: 14px;
  border: 1px solid rgba(226, 232, 240, 0.95);
  border-radius: 14px;
  background: #fff;
  overflow: hidden;
}

.drag-upload-file-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
  background: rgba(248, 250, 252, 0.95);
  color: var(--muted, #475569);
  font-size: 12px;
  font-weight: 700;
}

.drag-upload-file-list {
  max-height: 180px;
  overflow-y: auto;
}

.drag-upload-file-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 14px;
  border-top: 1px solid rgba(226, 232, 240, 0.75);
}

.drag-upload-file-main {
  min-width: 0;
}

.drag-upload-file-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text, #0f172a);
  font-size: 13px;
  font-weight: 600;
}

.drag-upload-file-size {
  margin-top: 2px;
  color: var(--muted-2, #64748b);
  font-size: 12px;
}
</style>
