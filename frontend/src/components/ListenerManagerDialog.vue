<template>
  <el-dialog v-model="visible" title="Listeners" width="1080px" class="fixed-dialog listener-manager-dialog"
             :close-on-click-modal="true">
    <div class="listener-manager-content" v-loading="loading">
      <div class="listener-manager-table">
        <el-table :data="listeners" size="default" table-layout="fixed" empty-text="No listeners" stripe>
          <el-table-column prop="name" label="Name" min-width="160" show-overflow-tooltip />
          <el-table-column label="Protocol" width="112">
            <template #default="{ row }">{{ row.protocol_label }}</template>
          </el-table-column>
          <el-table-column label="Bind" min-width="185" show-overflow-tooltip>
            <template #default="{ row }"><span class="listener-bind">{{ row.host || '0.0.0.0' }}:{{ row.port }}</span></template>
          </el-table-column>
          <el-table-column label="Status" width="122">
            <template #default="{ row }"><el-tag :type="row.status === 'listening' ? 'success' : (row.status === 'error' ? 'danger' : 'info')" size="small" :title="row.last_error || ''">{{ row.status }}</el-tag></template>
          </el-table-column>
          <el-table-column label="Devices" prop="connections" width="84" align="center" />
          <el-table-column label="Actions" width="184" align="center">
            <template #default="{ row }">
              <div class="listener-actions">
                <el-button size="small" plain @click="toggle(row)">{{ row.status === 'listening' ? 'Stop' : 'Start' }}</el-button>
                <el-button v-if="row.id !== 'tcp-default'" size="small" type="danger" plain @click="remove(row)">Delete</el-button>
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
            <el-button v-if="row.id !== 'tcp-default'" size="small" type="danger" plain @click="remove(row)">Delete</el-button>
          </div>
        </div>
      </div>

      <el-divider content-position="left">Add listener</el-divider>
      <el-form :model="form" label-position="top" class="listener-manager-form" @submit.prevent="create">
        <el-form-item label="Name"><el-input v-model="form.name" maxlength="60" placeholder="e.g. Public TLS" /></el-form-item>
        <el-form-item label="Protocol">
          <el-select v-model="form.protocol" style="width:100%">
            <el-option v-for="protocol in protocols" :key="protocol.id" :label="protocol.label" :value="protocol.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="Bind address"><el-input v-model="form.host" placeholder="0.0.0.0 (all interfaces)" /></el-form-item>
        <el-form-item label="Port"><el-input v-model.number="form.port" type="number" min="1" max="65535" /></el-form-item>
      </el-form>
      <el-alert v-if="selectedProtocol?.notice" type="info" :closable="false" show-icon :title="selectedProtocol.notice" />
    </div>
    <template #footer>
      <el-button @click="visible = false">Close</el-button>
      <el-button @click="load" :loading="loading">Refresh</el-button>
      <el-button type="primary" :loading="saving" @click="create">Add Listener</el-button>
    </template>
  </el-dialog>
</template>

<script>
import { ElMessage, ElMessageBox } from 'element-plus'
import { listListeners, listListenerProtocols, createListener, removeListener, setListenerEnabled } from '../api/listenersApi.js'

export default {
  name: 'ListenerManagerDialog',
  data() { return { visible: false, loading: false, saving: false, listeners: [], protocols: [],
    form: { name: '', protocol: 'tcp', host: '0.0.0.0', port: 9443 } } },
  computed: {
    selectedProtocol() { return this.protocols.find(item => item.id === this.form.protocol) },
  },
  methods: {
    async open() { this.visible = true; await this.load() },
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
      }
      catch (error) { ElMessage.error(error.message) }
      finally { this.loading = false }
    },
    async create() {
      if (!this.form.name.trim() || !this.form.port) { ElMessage.warning('Enter a name and port'); return }
      this.saving = true
      try {
        await this.requestResponse(createListener(this.form))
        this.form.name = ''
        ElMessage.success('Listener added')
        await this.load()
      } catch (error) { ElMessage.error(error.message) }
      finally { this.saving = false }
    },
    async toggle(row) {
      try { await this.requestResponse(setListenerEnabled(row.id, row.status !== 'listening')); await this.load() }
      catch (error) { ElMessage.error(error.message) }
    },
    async remove(row) {
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
  display: flex;
  flex-direction: column;
}
.listener-manager-dialog .el-dialog__body {
  min-height: 0;
  overflow-y: auto;
}
.listener-manager-table { min-width: 0; }
.listener-manager-dialog .el-table { width: 100%; }
.listener-manager-dialog .el-table .cell { padding: 0 10px; }
.listener-bind { white-space: nowrap; }
.listener-actions { display: flex; justify-content: center; align-items: center; gap: 7px; white-space: nowrap; }
.listener-actions .el-button + .el-button { margin-left: 0; }
.listener-actions .el-button { min-width: 63px; }
.listener-manager-form { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 24px; }
.listener-manager-form .el-form-item { min-width: 0; }
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
  .listener-manager-dialog .el-dialog__header { flex: 0 0 auto; padding: 16px 16px 12px; }
  .listener-manager-dialog .el-dialog__body { flex: 1 1 auto; padding: 12px 16px; }
  .listener-manager-dialog .el-dialog__footer { flex: 0 0 auto; padding: 12px 16px max(12px, env(safe-area-inset-bottom)); }
  .listener-manager-dialog .el-dialog__footer .el-button { margin-left: 4px; padding: 8px 12px; }
  .listener-manager-table { display: none; }
  .listener-manager-mobile-list { display: grid; gap: 10px; }
  .listener-manager-mobile-card { border: 1px solid var(--el-border-color-light); border-radius: 10px; padding: 12px; }
  .listener-manager-mobile-top { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
  .listener-manager-mobile-meta { margin: 9px 0; font-size: 12px; color: var(--el-text-color-secondary); overflow-wrap: anywhere; }
  .listener-manager-mobile-card .listener-actions { justify-content: flex-start; }
  .listener-manager-form { grid-template-columns: minmax(0, 1fr); gap: 0; }
  .listener-manager-empty { padding: 16px; text-align: center; color: var(--el-text-color-secondary); }
}
</style>
