<template>
  <el-dialog v-model="visible" title="Listeners" width="680px" class="fixed-dialog" :close-on-click-modal="false">
    <div v-loading="loading">
      <el-table :data="listeners" size="small" empty-text="No listeners">
        <el-table-column prop="name" label="Name" min-width="120" />
        <el-table-column label="Protocol" width="110">
          <template #default="{ row }">{{ row.protocol === 'tls_tcp' ? 'TLS/TCP' : 'TCP' }}</template>
        </el-table-column>
        <el-table-column label="Bind" min-width="155">
          <template #default="{ row }">{{ row.host || '0.0.0.0' }}:{{ row.port }}</template>
        </el-table-column>
        <el-table-column label="Status" width="100">
          <template #default="{ row }"><el-tag :type="row.status === 'listening' ? 'success' : (row.status === 'error' ? 'danger' : 'info')" size="small" :title="row.last_error || ''">{{ row.status }}</el-tag></template>
        </el-table-column>
        <el-table-column label="Devices" prop="connections" width="78" />
        <el-table-column width="140" label="Actions">
          <template #default="{ row }">
            <el-button size="small" text @click="toggle(row)">{{ row.status === 'listening' ? 'Stop' : 'Start' }}</el-button>
            <el-button v-if="row.id !== 'tcp-default'" size="small" text type="danger" @click="remove(row)">Delete</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-divider content-position="left">Add listener</el-divider>
      <el-form :model="form" label-width="100px" @submit.prevent="create">
        <el-form-item label="Name"><el-input v-model="form.name" maxlength="60" placeholder="e.g. Public TLS" /></el-form-item>
        <el-form-item label="Protocol">
          <el-select v-model="form.protocol" style="width:100%">
            <el-option label="TCP" value="tcp" />
            <el-option label="TLS/TCP" value="tls_tcp" />
          </el-select>
        </el-form-item>
        <el-form-item label="Bind address"><el-input v-model="form.host" placeholder="0.0.0.0 (all interfaces)" /></el-form-item>
        <el-form-item label="Port"><el-input v-model.number="form.port" type="number" min="1" max="65535" /></el-form-item>
      </el-form>
      <el-alert v-if="form.protocol === 'tls_tcp'" type="info" :closable="false" show-icon
                title="A self-signed certificate is generated once. Bundle agents pin its fingerprint." />
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
import { listListeners, createListener, removeListener, setListenerEnabled } from '../api/listenersApi.js'

export default {
  name: 'ListenerManagerDialog',
  data() { return { visible: false, loading: false, saving: false, listeners: [],
    form: { name: '', protocol: 'tcp', host: '0.0.0.0', port: 9443 } } },
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
      try { this.listeners = await this.requestResponse(listListeners()) || [] }
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
