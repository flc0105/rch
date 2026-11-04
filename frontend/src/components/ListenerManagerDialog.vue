<template>
    <el-dialog v-model="visible" title="Listeners" width="1080px" class="fixed-dialog listener-manager-dialog"
               :close-on-click-modal="true">
      <div class="listener-manager-content" v-loading="loading">
        <div class="listener-manager-toolbar">
          <el-button size="small" :loading="loading" @click="load">Refresh</el-button>
          <el-button size="small" type="primary" plain @click="openAdd">Add</el-button>
        </div>
        <div class="listener-manager-table">
          <el-table :data="listeners" height="100%" size="default" table-layout="fixed" empty-text="No listeners" stripe>
            <el-table-column prop="name" label="Name" min-width="135" show-overflow-tooltip />
            <el-table-column label="Protocol" width="110">
              <template #default="{ row }">{{ row.protocol_label }}</template>
            </el-table-column>
            <el-table-column label="Bind" min-width="165" show-overflow-tooltip>
              <template #default="{ row }"><span class="listener-bind">{{ row.host || '0.0.0.0' }}:{{ row.port }}</span></template>
            </el-table-column>
            <el-table-column label="Status" width="120">
              <template #default="{ row }"><el-tag :type="row.status === 'listening' ? 'success' : (row.status === 'error' ? 'danger' : 'info')" size="small" :title="row.last_error || ''">{{ row.status }}</el-tag></template>
            </el-table-column>
            <el-table-column label="Devices" prop="connections" width="80" align="center" />
            <el-table-column label="Actions" width="164" align="center">
              <template #default="{ row }">
                <div class="listener-actions">
                  <el-button size="small" plain @click="toggle(row)">{{ row.status === 'listening' ? 'Stop' : 'Start' }}</el-button>
                  <el-button size="small" type="danger" plain :disabled="row.id === 'tcp-default'" @click="remove(row)">Delete</el-button>
                </div>
              </template>
            </el-table-column>
          </el-table>
        </div>
        <div class="listener-manager-mobile-list">
          <div v-if="!listeners.length" class="listener-manager-empty">No listeners</div>
          <div v-for="row in listeners" :key="row.id" class="listener-manager-mobile-card">
            <div class="listener-manager-mobile-top">
              <strong>{{ row.name }}</strong>
              <el-tag :type="row.status === 'listening' ? 'success' : (row.status === 'error' ? 'danger' : 'info')" size="small" :title="row.last_error || ''">{{ row.status }}</el-tag>
            </div>
            <div class="listener-manager-mobile-meta">{{ row.protocol_label }} · {{ row.host || '0.0.0.0' }}:{{ row.port }} · {{ row.connections }} devices</div>
            <div class="listener-actions">
              <el-button size="small" plain @click="toggle(row)">{{ row.status === 'listening' ? 'Stop' : 'Start' }}</el-button>
              <el-button size="small" type="danger" plain :disabled="row.id === 'tcp-default'" @click="remove(row)">Delete</el-button>
            </div>
          </div>
        </div>
      </div>
    </el-dialog>
    <AddListenerDialog ref="addDialog" :protocols="protocols" @created="load" />
</template>

<script>
import { ElMessage, ElMessageBox } from 'element-plus'
import { listListeners, listListenerProtocols, removeListener, setListenerEnabled } from '../api/listenersApi.js'
import AddListenerDialog from './AddListenerDialog.vue'

export default {
  name: 'ListenerManagerDialog',
  components: { AddListenerDialog },
  data() { return { visible: false, loading: false, listeners: [], protocols: [] } },
  methods: {
    async open() { this.visible = true; await this.load() },
    openAdd() { this.$refs.addDialog.open() },
    async requestResponse(request) {
      const response = await request
      const result = await response.json()
      if (!response.ok || result.code !== 0) throw new Error(result.message || 'Listener operation failed')
      return result.data
    },
    async load() {
      this.loading = true
      try {
        this.protocols = await this.requestResponse(listListenerProtocols()) || []
        this.listeners = await this.requestResponse(listListeners()) || []
      } catch (error) { ElMessage.error(error.message) }
      finally { this.loading = false }
    },
    async toggle(row) {
      try { await this.requestResponse(setListenerEnabled(row.id, row.status !== 'listening')); await this.load() }
      catch (error) { ElMessage.error(error.message) }
    },
    async remove(row) {
      if (row.id === 'tcp-default') return
      try { await ElMessageBox.confirm(`Delete listener "${row.name}"? Existing sessions will remain connected.`, 'Delete listener', { type: 'warning' }) }
      catch { return }
      try { await this.requestResponse(removeListener(row.id)); ElMessage.success('Listener removed'); await this.load() }
      catch (error) { ElMessage.error(error.message) }
    },
  },
}
</script>

<style>
.listener-manager-dialog.el-dialog {
  max-width: calc(100vw - 32px);
  height: min(520px, calc(100dvh - 80px));
  display: flex;
  flex-direction: column;
}
.listener-manager-dialog .el-dialog__header { flex: 0 0 auto; }
.listener-manager-toolbar { flex: 0 0 auto; display: flex; align-items: center; gap: 8px; margin-bottom: 12px; }
.listener-manager-toolbar .el-button { height: 32px; min-height: 32px; padding: 0 12px; border-radius: 10px; margin: 0; }
.listener-manager-dialog .el-dialog__body { flex: 1 1 auto; min-height: 0; display: flex; overflow: hidden; }
.listener-manager-content { flex: 1; min-width: 0; min-height: 0; display: flex; flex-direction: column; }
.listener-manager-table { flex: 1; min-height: 0; min-width: 0; }
.listener-manager-dialog .el-table { width: 100%; }
.listener-manager-dialog .el-table .cell { padding: 0 8px; }
.listener-bind { white-space: nowrap; }
.listener-actions { display: flex; justify-content: center; align-items: center; gap: 7px; white-space: nowrap; }
.listener-actions .el-button + .el-button { margin-left: 0; }
.listener-actions .el-button { width: 58px; min-width: 58px; padding-left: 6px; padding-right: 6px; }
.listener-manager-mobile-list { display: none; }
@media (max-width: 960px) {
  .listener-manager-dialog.el-dialog {
    width: 100vw !important;
    max-width: 100vw !important;
    height: 100dvh !important;
    max-height: 100dvh !important;
    margin: 0 !important;
    border-radius: 0 !important;
  }
  .listener-manager-dialog .el-dialog__header { padding: 16px 16px 12px; }
  .listener-manager-dialog .el-dialog__body { padding: 12px 16px max(12px, env(safe-area-inset-bottom)); }
  .listener-manager-table { display: none; }
  .listener-manager-mobile-list { display: flex; flex-direction: column; flex: 1; overflow-y: auto; gap: 10px; min-height: 0; }
  .listener-manager-mobile-card { border: 1px solid var(--el-border-color-light); border-radius: 10px; padding: 12px; }
  .listener-manager-mobile-top { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
  .listener-manager-mobile-meta { margin: 9px 0; font-size: 12px; color: var(--el-text-color-secondary); overflow-wrap: anywhere; }
  .listener-manager-mobile-card .listener-actions { justify-content: flex-start; }
  .listener-manager-empty { padding: 16px; text-align: center; color: var(--el-text-color-secondary); }
}
</style>
