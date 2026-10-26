<template>
  <el-dialog
    :model-value="modelValue"
    title="Manage Pinned Paths"
    width="760px"
    top="6vh"
    class="fixed-dialog remote-pins-dialog"
    modal-class="remote-pins-overlay"
    @update:model-value="emitVisibleChange"
  >
    <div class="fixed-dialog-body remote-pins-body">
      <div class="remote-pins-toolbar">
        <el-button size="small" type="primary" :disabled="!selectedId || createSaving" @click="openCreatePicker">Create</el-button>
      </div>
      <div class="dialog-table-shell remote-pins-table-shell">
        <el-table
          :data="items"
          stripe
          width="100%"
          height="100%"
          empty-text="No pinned paths"
          table-layout="fixed"
        >
          <el-table-column
            prop="display_name"
            label="Display Name"
            min-width="180"
            show-overflow-tooltip
          />

          <el-table-column
            prop="path"
            label="Path"
            min-width="360"
            show-overflow-tooltip
          />

          <el-table-column
            label="Actions"
            width="160"
            align="center"
            fixed="right"
          >
            <template #default="{ row }">
              <div class="table-actions table-actions-links">
                <el-button
                  size="small"
                  link
                  type="primary"
                  @click="promptEditPinnedQuickJump(row)"
                >
                  Edit
                </el-button>

                <el-button
                  size="small"
                  link
                  type="danger"
                  @click="deletePinnedQuickJump(row)"
                >
                  Delete
                </el-button>
              </div>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>
  </el-dialog>

  <RemoteFilePicker
    v-model:visible="createPickerVisible"
    :selected-id="selectedId"
    selection-mode="folder"
    :multiple="false"
    @select="createPinnedPathFromSelection"
  />
</template>

<script>
import { ElMessage, ElMessageBox } from 'element-plus'
import RemoteFilePicker from './RemoteFilePicker.vue'

export default {
  name: 'RemotePinsDialog',
  components: { RemoteFilePicker },

  props: {
    modelValue: {
      type: Boolean,
      default: false,
    },

    selectedId: {
      type: String,
      default: '',
    },

    items: {
      type: Array,
      default: () => [],
    },
  },

  emits: [
    'update:modelValue',
    'updated',
  ],

  data() {
    return { createPickerVisible: false, createSaving: false }
  },

  watch: {
    modelValue(value) {
      if (!value) this.createPickerVisible = false
    },
  },

  methods: {
    openCreatePicker() {
      if (!this.selectedId || this.createSaving) return
      this.createPickerVisible = true
    },

    async createPinnedPathFromSelection(selectedPath) {
      const clientId = String(this.selectedId || '').trim()
      const path = String(selectedPath || '').trim()
      if (!clientId || !path || !this.modelValue || this.createSaving) return
      const defaultName = path.replace(/[\\/]+$/, '').split(/[\\/]/).filter(Boolean).pop() || 'Pinned Path'

      try {
        const { value } = await ElMessageBox.prompt(
          `Selected folder:<br><span style="word-break: break-all; color: var(--muted);">${this.escapeRemoteHtml(path)}</span>`,
          'Pin Path',
          {
            confirmButtonText: 'Create',
            cancelButtonText: 'Cancel',
            dangerouslyUseHTMLString: true,
            inputValue: defaultName,
            inputPattern: /\S/,
            inputErrorMessage: 'Display name is required',
          },
        )
        if (clientId !== String(this.selectedId || '').trim() || !this.modelValue) return
        const displayName = String(value || '').trim()
        if (!displayName) return

        // POST updates existing names; creating from the manager must not silently replace a Pin.
        const latestRes = await fetch(`/api/connections/${encodeURIComponent(clientId)}/pinned_paths`)
        const latestJson = await latestRes.json()
        if (!latestRes.ok || latestJson.code !== 0) {
          throw new Error(latestJson.message || 'Failed to check pinned paths')
        }
        if (clientId !== String(this.selectedId || '').trim() || !this.modelValue) return
        const existing = Array.isArray(latestJson.data?.items) ? latestJson.data.items : []
        if (existing.some(item => String(item?.display_name || '').toLowerCase() === displayName.toLowerCase())) {
          ElMessage.warning('A pinned path with this name already exists')
          return
        }

        const res = await fetch(`/api/connections/${encodeURIComponent(clientId)}/pinned_paths`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ display_name: displayName, path }),
        })
        const json = await res.json()
        if (clientId !== String(this.selectedId || '').trim() || !this.modelValue) return
        if (!res.ok || json.code !== 0) throw new Error(json.message || 'Failed to save pinned path')
        this.$emit('updated', Array.isArray(json.data?.items) ? json.data.items : [])
        ElMessage.success(json.data?.message || 'Pinned path saved')
      } catch (e) {
        if (this.isDialogCancel(e)) return
        ElMessage.error(e.message || 'Failed to save pinned path')
      } finally {
        this.createSaving = false
      }
    },

    emitVisibleChange(value) {
      this.$emit('update:modelValue', value)
    },

    async promptEditPinnedQuickJump(item) {
      if (!this.selectedId || !item?.display_name) return

      try {
        const { value: displayNameValue } = await ElMessageBox.prompt(
          `Edit display name for:<br><span style="word-break: break-all; color: var(--muted);">${this.escapeRemoteHtml(item.path || '')}</span>`,
          'Edit Pinned Path',
          {
            confirmButtonText: 'Next',
            cancelButtonText: 'Cancel',
            dangerouslyUseHTMLString: true,
            inputValue: item.display_name || '',
            inputPattern: /.+/,
            inputErrorMessage: 'Display name is required',
          }
        )

        const displayName = String(displayNameValue || '').trim()
        if (!displayName) return

        const { value: pathValue } = await ElMessageBox.prompt(
          'Edit target path',
          'Edit Pinned Path',
          {
            confirmButtonText: 'Save',
            cancelButtonText: 'Cancel',
            inputValue: item.path || '',
            inputPattern: /.+/,
            inputErrorMessage: 'Path is required',
          }
        )

        const path = String(pathValue || '').trim()
        if (!path) return

        const res = await fetch(`/api/connections/${encodeURIComponent(this.selectedId)}/pinned_paths`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            original_display_name: item.display_name,
            display_name: displayName,
            path,
          }),
        })

        const json = await res.json()

        if (!res.ok || json.code !== 0) {
          throw new Error(json.message || 'Failed to update pinned path')
        }

        const nextItems = Array.isArray(json.data?.items)
          ? json.data.items
          : []

        this.$emit('updated', nextItems)
        ElMessage.success(json.data?.message || 'Pinned path updated')
      } catch (e) {
        if (this.isDialogCancel(e)) return
        ElMessage.error(e.message || 'Failed to update pinned path')
      }
    },

    async deletePinnedQuickJump(item) {
      if (!this.selectedId || !item?.display_name) return

      try {
        await ElMessageBox.confirm(
          `Remove pinned path "${this.escapeRemoteHtml(item.display_name)}"?`,
          'Delete Pinned Path',
          {
            confirmButtonText: 'Delete',
            cancelButtonText: 'Cancel',
            type: 'warning',
            dangerouslyUseHTMLString: true,
          }
        )

        const res = await fetch(`/api/connections/${encodeURIComponent(this.selectedId)}/pinned_paths`, {
          method: 'DELETE',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ display_name: item.display_name }),
        })

        const json = await res.json()

        if (!res.ok || json.code !== 0) {
          throw new Error(json.message || 'Failed to delete pinned path')
        }

        const nextItems = Array.isArray(json.data?.items)
          ? json.data.items
          : []

        this.$emit('updated', nextItems)
        ElMessage.success(json.data?.message || 'Pinned path removed')
      } catch (e) {
        if (this.isDialogCancel(e)) return
        ElMessage.error(e.message || 'Failed to delete pinned path')
      }
    },

    escapeRemoteHtml(text) {
      return String(text || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;')
    },

    isDialogCancel(e) {
      return e === 'cancel' || e === 'close' || e?.toString?.().includes('cancel')
    },
  },
}
</script>

<style scoped>
.remote-pins-toolbar {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  justify-content: flex-start;
  padding-bottom: 12px;
}

.remote-pins-body {
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.remote-pins-table-shell {
  flex: 1 1 auto;
  min-height: 0;
  height: auto;
  overflow: hidden;
}
</style>

<style>
.remote-pins-overlay .el-overlay-dialog {
  overflow: hidden !important;
}

.remote-pins-overlay .el-dialog {
  width: 760px !important;
  max-width: calc(100vw - 32px) !important;
  height: 560px !important;
  max-height: calc(100vh - 12vh) !important;
  margin-top: 6vh !important;
  display: flex !important;
  flex-direction: column !important;
  overflow: hidden !important;
}

.remote-pins-overlay .el-dialog__header {
  flex: 0 0 auto !important;
}

.remote-pins-overlay .el-dialog__body {
  flex: 1 1 auto !important;
  min-height: 0 !important;
  overflow: hidden !important;
  padding-top: 12px !important;
  padding-bottom: 12px !important;
}

.remote-pins-overlay .fixed-dialog-body {
  height: 100% !important;
  min-height: 0 !important;
  display: flex !important;
  flex-direction: column !important;
  overflow: hidden !important;
}

.remote-pins-overlay .dialog-table-shell {
  flex: 1 1 auto !important;
  height: auto !important;
  min-height: 0 !important;
  max-height: none !important;
  overflow: hidden !important;
}

.remote-pins-overlay .dialog-table-shell .el-table,
.remote-pins-overlay .dialog-table-shell .el-table__inner-wrapper,
.remote-pins-overlay .dialog-table-shell .el-scrollbar,
.remote-pins-overlay .dialog-table-shell .el-scrollbar__wrap {
  height: 100% !important;
}

.remote-pins-overlay .dialog-table-shell .el-scrollbar__wrap {
  overflow-y: auto !important;
  overflow-x: auto !important;
}

@media (max-width: 768px), (max-height: 720px) {
  .remote-pins-overlay .el-dialog {
    width: 100vw !important;
    max-width: 100vw !important;
    height: 100vh !important;
    max-height: 100vh !important;
    margin: 0 !important;
    border-radius: 0 !important;
  }
}
</style>