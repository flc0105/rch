<template>
  <el-dialog v-model="visible" title="Tunnel Manager" width="880px" top="6vh" class="fixed-dialog tunnel-manager-dialog" append-to-body @closed="onClosed">
    <div class="tunnel-manager-content">
      <div class="tunnel-manager-toolbar">
      <el-select v-model="targetId" filterable placeholder="Select Client" class="tunnel-target" @change="refresh">
        <el-option v-for="device in deviceOptions" :key="device.value" :label="device.label" :value="device.value" />
      </el-select>
      <el-input v-model="query" clearable placeholder="Search tunnels..." class="tunnel-search" />
      <el-button :loading="loading" @click="refresh">Refresh</el-button>
      <el-button type="primary" :disabled="!targetId || busy" @click="openCreate">New Tunnel</el-button>
    </div>
    <div v-if="snapshot.streams || snapshot.last_error" class="tunnel-summary">
      <span v-if="snapshot.streams">Active streams: {{ snapshot.streams }}</span>
      <span v-if="snapshot.last_error" class="tunnel-last-error">{{ snapshot.last_error }}</span>
    </div>
    <div v-loading="loading" class="tunnel-instance-list">
      <div v-for="item in filteredInstances" :key="item.name" class="tunnel-instance-row">
        <div class="tunnel-instance-body">
          <div class="tunnel-instance-title">
            <strong>{{ item.name }}</strong>
            <el-tag :type="statusColor(item.status)" size="small" effect="plain">{{ statusLabel(item.status) }}</el-tag>
          </div>
          <div class="tunnel-instance-path">
            {{ item.expose_on === 'server' ? 'Server' : 'Client' }} {{ item.listen_host }}:{{ item.listen_port }}
            <span aria-hidden="true">→</span>
            {{ item.expose_on === 'server' ? 'Client' : 'Server' }} {{ item.target_host }}:{{ item.target_port }}
          </div>
        </div>
        <div class="tunnel-instance-actions">
          <el-button v-if="item.status === 'stopped'" size="small" type="primary" :loading="busyName === item.name" :disabled="busy" @click="operate(item, 'start')">Start</el-button>
          <template v-else>
            <el-button size="small" :loading="busyName === item.name" :disabled="busy" @click="operate(item, 'restart')">Restart</el-button>
            <el-button size="small" :disabled="busy" @click="operate(item, 'stop')">Stop</el-button>
          </template>
          <el-dropdown trigger="click" :disabled="busy" @command="onMore($event, item)">
            <el-button size="small">More</el-button>
            <template #dropdown><el-dropdown-menu>
              <el-dropdown-item command="details">Details</el-dropdown-item>
              <el-dropdown-item command="copy">Copy address</el-dropdown-item>
              <el-dropdown-item command="edit" :disabled="item.status !== 'stopped'">Edit</el-dropdown-item>
              <el-dropdown-item command="delete" :disabled="item.status !== 'stopped'" divided>Delete</el-dropdown-item>
            </el-dropdown-menu></template>
          </el-dropdown>
        </div>
      </div>
      <el-empty v-if="!loading && !filteredInstances.length" :description="query ? 'No matching tunnels' : 'No tunnel instances'" />
    </div>
    </div>
  </el-dialog>

  <el-dialog v-model="formVisible" :title="editing ? 'Edit Tunnel' : 'New Tunnel'" width="520px" append-to-body class="tunnel-edit-dialog">
    <el-form label-position="top" class="tunnel-instance-form" @submit.prevent="save(false)">
      <el-form-item label="Name">
        <el-input v-model="form.name" :disabled="editing" maxlength="32" placeholder="rch-web" />
      </el-form-item>
      <el-form-item label="Expose on">
        <el-select v-model="form.expose_on" style="width: 100%">
          <el-option label="Client" value="client" />
          <el-option label="Server" value="server" />
        </el-select>
      </el-form-item>
      <div class="tunnel-form-grid">
        <el-form-item :label="`${form.expose_on === 'server' ? 'Server' : 'Client'} Listen Host`"><el-input v-model="form.listen_host" placeholder="127.0.0.1" /></el-form-item>
        <el-form-item :label="`${form.expose_on === 'server' ? 'Server' : 'Client'} Listen Port`"><el-input-number v-model="form.listen_port" :min="1" :max="65535" controls-position="right" /></el-form-item>
        <el-form-item :label="`${form.expose_on === 'server' ? 'Client' : 'Server'} Target Host`"><el-input v-model="form.target_host" placeholder="127.0.0.1" /></el-form-item>
        <el-form-item :label="`${form.expose_on === 'server' ? 'Client' : 'Server'} Target Port`"><el-input-number v-model="form.target_port" :min="1" :max="65535" controls-position="right" /></el-form-item>
      </div>
      <p v-if="form.listen_host === '0.0.0.0'" class="tunnel-form-note">The forwarded port is accessible from networks that can reach the exposed device.</p>
    </el-form>
    <template #footer>
      <el-button @click="formVisible = false">Cancel</el-button>
      <el-button :loading="busy" @click="save(false)">Save</el-button>
      <el-button v-if="!editing" type="primary" :loading="busy" @click="save(true)">Save &amp; Start</el-button>
    </template>
  </el-dialog>

  <el-dialog v-model="detailsVisible" title="Tunnel Details" width="520px" append-to-body>
    <el-descriptions v-if="details" :column="1" border>
      <el-descriptions-item label="Name">{{ details.name }}</el-descriptions-item>
      <el-descriptions-item label="Status">{{ statusLabel(details.status) }}</el-descriptions-item>
      <el-descriptions-item label="Expose on">{{ details.expose_on === 'server' ? 'Server' : 'Client' }}</el-descriptions-item>
      <el-descriptions-item :label="`${details.expose_on === 'server' ? 'Server' : 'Client'} Listen`">{{ details.listen_host }}:{{ details.listen_port }}</el-descriptions-item>
      <el-descriptions-item :label="`${details.expose_on === 'server' ? 'Client' : 'Server'} Target`">{{ details.target_host }}:{{ details.target_port }}</el-descriptions-item>
    </el-descriptions>
  </el-dialog>
</template>

<script>
import { ElMessage, ElMessageBox } from 'element-plus'
import { copyTextFallback } from '../utils/clipboard.js'
import { listTunnelInstances, createTunnelInstance, editTunnelInstance, removeTunnelInstance, runTunnelInstance } from '../api/tunnelsApi.js'

const emptyForm = () => ({ name: '', expose_on: 'client', listen_host: '127.0.0.1', listen_port: 18085,
  target_host: '127.0.0.1', target_port: 8085 })

export default {
  name: 'TunnelManagerDialog',
  props: {
    selectedId: { type: String, default: '' },
    connections: { type: Array, default: () => [] },
  },
  data() {
    return { visible: false, targetId: '', query: '', loading: false, busy: false, busyName: '',
      snapshot: { instances: [], connected: false },
      formVisible: false, editing: false, form: emptyForm(), detailsVisible: false, details: null,
      pollTimer: null, requestSerial: 0 }
  },
  computed: {
    deviceOptions() {
      const seen = new Set()
      const items = []
      for (const device of this.connections || []) {
        const value = String(device?.client_id || '').trim()
        if (!value || seen.has(value)) continue
        seen.add(value)
        items.push({ value, label: device?.hostname || device?.display_name || value })
      }
      if (this.targetId && !seen.has(this.targetId)) items.unshift({ value: this.targetId, label: this.targetId })
      return items
    },
    filteredInstances() {
      const text = this.query.trim().toLowerCase()
      return (this.snapshot.instances || []).filter(item => !text || [item.name, item.listen_host, item.target_host, String(item.listen_port), String(item.target_port)]
        .some(value => value.toLowerCase().includes(text)))
    },
  },
  beforeUnmount() { this.onClosed() },
  methods: {
    isOpen() { return this.visible },
    open() {
      if (this.visible) return
      this.targetId = this.selectedId || this.deviceOptions[0]?.value || ''
      this.visible = true
      this.refresh()
      this.pollTimer = window.setInterval(() => { if (!this.busy && !this.loading) void this.refresh(true) }, 5000)
    },
    onClosed() {
      if (this.pollTimer !== null) window.clearInterval(this.pollTimer)
      this.pollTimer = null
      this.requestSerial++
    },
    async refresh(silent = false) {
      const clientId = this.targetId
      const requestId = ++this.requestSerial
      if (!clientId) { this.snapshot = { instances: [], connected: false }; return }
      if (!silent) this.loading = true
      try {
        const response = await listTunnelInstances(clientId)
        if (requestId === this.requestSerial && this.targetId === clientId) this.snapshot = response
      } catch (error) {
        if (!silent && requestId === this.requestSerial) ElMessage.error(error.message || 'Unable to load tunnels')
      } finally {
        if (!silent && requestId === this.requestSerial) this.loading = false
      }
    },
    statusLabel(status) { return { running: 'Running', stopped: 'Stopped', error: 'Error' }[status] || status },
    statusColor(status) { return { running: 'success', stopped: 'info', error: 'danger' }[status] || 'info' },
    openCreate() {
      this.editing = false
      this.form = emptyForm()
      this.formVisible = true
    },
    openEdit(item) { this.editing = true; this.form = { ...item }; this.formVisible = true },
    async save(andStart) {
      if (this.busy || !this.targetId) return
      this.busy = true
      const clientId = this.targetId
      try {
        const { name, expose_on, listen_host, listen_port, target_host, target_port } = this.form
        const config = { expose_on, listen_host, listen_port, target_host, target_port }
        if (this.editing) await editTunnelInstance(clientId, name, config)
        else await createTunnelInstance(clientId, { name, ...config })
        // Once saved, keep it saved even when starting the remote listener fails.
        this.formVisible = false
        if (andStart) await runTunnelInstance(clientId, name, 'start')
        ElMessage.success(andStart ? 'Tunnel started' : 'Tunnel saved')
      } catch (error) { ElMessage.error(error.message || 'Unable to save tunnel') }
      finally { this.busy = false; await this.refresh() }
    },
    async operate(item, action) {
      if (this.busy) return
      this.busy = true; this.busyName = item.name
      const clientId = this.targetId
      try {
        await runTunnelInstance(clientId, item.name, action)
        ElMessage.success(`Tunnel ${action === 'restart' ? 'restarted' : action === 'start' ? 'started' : 'stopped'}`)
      } catch (error) { ElMessage.error(error.message || `Unable to ${action} tunnel`) }
      finally { this.busy = false; this.busyName = ''; await this.refresh() }
    },
    async onMore(action, item) {
      if (action === 'details') { this.details = item; this.detailsVisible = true; return }
      if (action === 'copy') {
        try {
          const address = `${item.listen_host}:${item.listen_port}`
          if (window.isSecureContext && navigator.clipboard?.writeText) await navigator.clipboard.writeText(address)
          else copyTextFallback(address)
          ElMessage.success('Address copied')
        } catch (_) { ElMessage.warning('Unable to copy address') }
        return
      }
      if (action === 'edit') { this.openEdit(item); return }
      if (action !== 'delete') return
      try { await ElMessageBox.confirm(`Delete tunnel "${item.name}"?`, 'Delete Tunnel', { type: 'warning' }) }
      catch (_) { return }
      if (this.busy) return
      const clientId = this.targetId
      this.busy = true
      try { await removeTunnelInstance(clientId, item.name); ElMessage.success('Tunnel deleted') }
      catch (error) { ElMessage.error(error.message || 'Unable to delete tunnel') }
      finally { this.busy = false; await this.refresh() }
    },
  },
}
</script>

<style scoped>
.tunnel-manager-content { display: flex; flex-direction: column; height: 100%; min-height: 0; }
.tunnel-manager-toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-bottom: 12px; }
.tunnel-target { width: 210px; max-width: 100%; }
.tunnel-search { flex: 1 1 150px; min-width: 130px; }
.tunnel-summary { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; margin-bottom: 14px; font-size: 12px; color: var(--el-text-color-secondary); }
.tunnel-last-error { color: var(--el-color-danger); overflow-wrap: anywhere; }
.tunnel-instance-list { flex: 1 1 auto; min-height: 0; overflow-y: auto; }
.tunnel-instance-row { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px; padding: 14px 6px; border-bottom: 1px solid var(--el-border-color-lighter); }
.tunnel-instance-body { min-width: 0; flex: 1 1 280px; }
.tunnel-instance-title { display: flex; align-items: center; gap: 9px; margin-bottom: 7px; }
.tunnel-instance-path { font-size: 13px; overflow-wrap: anywhere; }
.tunnel-instance-path span { margin: 0 6px; }
.tunnel-instance-actions { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.tunnel-instance-actions :deep(.el-button + .el-button) { margin-left: 0; }
.tunnel-form-grid { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 0 14px; }
.tunnel-form-note { color: var(--el-color-warning); font-size: 12px; }
@media (max-width: 640px) {
  :global(.tunnel-edit-dialog.el-dialog) { width: calc(100vw - 16px) !important; max-width: calc(100vw - 16px); }
  .tunnel-manager-toolbar > * { flex: 1 1 100%; }
  .tunnel-target { width: 100%; }
  .tunnel-form-grid { grid-template-columns: 1fr; }
  .tunnel-instance-actions { width: 100%; }
}
</style>

<style>
.tunnel-manager-dialog.el-dialog {
  width: 880px;
  max-width: calc(100vw - 32px);
  height: min(660px, 88dvh);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.tunnel-manager-dialog .el-dialog__header { flex: 0 0 auto; }
.tunnel-manager-dialog .el-dialog__body { flex: 1 1 auto; min-height: 0; overflow: hidden; }
@media (max-width: 640px) {
  .tunnel-manager-dialog.el-dialog {
    width: 100vw !important; max-width: 100vw !important;
    height: 100dvh !important; margin: 0 !important; border-radius: 0;
  }
  .tunnel-manager-dialog .el-dialog__body { max-height: none !important; overflow: hidden !important; }
}
</style>
