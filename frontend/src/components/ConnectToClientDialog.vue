<template>
  <el-dialog v-model="visible" title="Connect to Client" width="560px" class="fixed-dialog bind-connect-dialog" append-to-body>
    <el-tabs v-model="activeTab" class="bind-connect-tabs">
      <el-tab-pane label="Manual" name="manual">
        <el-form :model="form" label-position="top" class="bind-connect-form" @submit.prevent="connect">
          <el-form-item label="Connection name (optional)">
            <el-input v-model="form.name" placeholder="Name this connection" autocomplete="off" />
          </el-form-item>
          <el-form-item label="Host">
            <el-input v-model="form.host" placeholder="Client IP or hostname" autocomplete="off" />
          </el-form-item>
          <el-form-item label="Port">
            <el-input v-model.number="form.port" type="number" min="1" max="65535" />
          </el-form-item>
          <el-form-item label="Transport">
            <el-select v-model="form.transport" style="width:100%">
              <el-option label="TCP" value="tcp" />
              <el-option label="mTLS/TCP" value="mtls_tcp" />
            </el-select>
          </el-form-item>
          <el-form-item label="Server Web URL">
            <el-input v-model="form.serverWebBaseUrl" placeholder="http://server:8085" autocomplete="off" />
          </el-form-item>
        </el-form>
      </el-tab-pane>
      <el-tab-pane label="Discovery" name="discovery">
        <div class="bind-discovery-panel">
          <div class="bind-discovery-controls">
            <div class="bind-discovery-interface">
              <span class="bind-discovery-label">Network interface</span>
              <el-select v-model="interfaceAddress" placeholder="Select a network interface" style="width:100%" @change="onInterfaceChange">
                <el-option v-for="item in interfaces" :key="item.address" :label="`${item.name} · ${item.address}`" :value="item.address" />
              </el-select>
            </div>
            <el-button :loading="scanning" :disabled="!interfaceAddress || connecting" @click="scan">Scan</el-button>
          </div>
          <div class="bind-discovery-meta">{{ devices.length }} devices discovered</div>
          <div class="bind-discovery-results" role="radiogroup" aria-label="Discovered Bind Clients">
            <button v-for="device in devices" :key="deviceKey(device)" type="button"
              class="bind-discovery-device" :class="{ 'is-selected': selectedDeviceKey === deviceKey(device) }"
              role="radio" :aria-checked="selectedDeviceKey === deviceKey(device)" @click="selectDevice(device)">
              <span class="bind-discovery-radio" aria-hidden="true"></span>
              <span class="bind-discovery-device-main">
                <strong>{{ device.hostname || device.host }}</strong>
                <span class="bind-discovery-details">{{ device.host }}:{{ device.port }} · {{ device.os || 'Unknown' }}</span>
                <span class="bind-discovery-transport">{{ device.transport === 'mtls_tcp' ? 'mTLS/TCP' : 'TCP' }}</span>
              </span>
              <el-tag size="small" :type="device.available ? 'success' : 'info'" effect="plain">
                {{ device.available ? 'Available' : 'Busy' }}
              </el-tag>
            </button>
            <el-empty v-if="!scanning && !devices.length" :description="hasScanned ? 'No Bind Clients discovered' : 'Click Scan to find Bind Clients'" :image-size="70" />
          </div>
          <div class="bind-discovery-web-url">
            <span class="bind-discovery-label">Server Web URL</span>
            <el-input v-model="form.serverWebBaseUrl" placeholder="http://server:8085" autocomplete="off" />
          </div>
        </div>
      </el-tab-pane>
    </el-tabs>
    <template #footer>
      <el-button @click="visible = false">Cancel</el-button>
      <el-button :loading="connecting" :disabled="activeTab === 'discovery' && !selectedDeviceKey" @click="save">Save</el-button>
      <el-button type="primary" :loading="connecting" :disabled="activeTab === 'discovery' && !selectedDeviceKey" @click="connect">Connect</el-button>
    </template>
  </el-dialog>
</template>

<script>
import { ElMessage } from 'element-plus'
import { connectToClient, discoverBindClients, getBindConnectionSettings, getBindDiscoveryInterfaces, saveBindTarget } from '../api/connectionsApi.js'

export default {
  name: 'ConnectToClientDialog',
  emits: ['connected', 'saved'],
  data() {
    return {
      visible: false, connecting: false, scanning: false, hasScanned: false, activeTab: 'manual',
      interfaceAddress: '', interfaces: [], devices: [], selectedDeviceKey: '', targetId: '',
      form: { host: '', port: 9443, serverWebBaseUrl: '', name: '', transport: 'tcp' },
    }
  },
  methods: {
    onInterfaceChange() {
      this.devices = []
      this.selectedDeviceKey = ''
    },
    deviceKey(device) {
      return `${device.host}:${device.port}:${device.transport}`
    },
    selectDevice(device) {
      this.selectedDeviceKey = this.deviceKey(device)
      this.form.host = device.host
      this.form.port = device.port
      this.form.transport = device.transport
      this.form.name = device.hostname || ''
      this.targetId = ''
    },
    async scan() {
      if (!this.interfaceAddress || this.scanning) return
      this.scanning = true
      this.hasScanned = true
      const interfaceAddress = this.interfaceAddress
      this.devices = []
      this.selectedDeviceKey = ''
      try {
        const result = await discoverBindClients(interfaceAddress)
        if (this.interfaceAddress === interfaceAddress) this.devices = result.devices || []
      } catch (error) {
        ElMessage.error(error.message || 'Unable to discover Bind Clients')
      } finally {
        this.scanning = false
      }
    },
    async open(target = null) {
      this.visible = true
      this.targetId = String(target?.target_id || '')
      this.activeTab = target ? 'manual' : 'discovery'
      this.devices = []
      this.selectedDeviceKey = ''
      this.hasScanned = false
      this.form = {
        host: String(target?.host || ''),
        port: Number(target?.port || 9443),
        serverWebBaseUrl: String(target?.server_web_base_url || ''),
        name: String(target?.name || ''),
        transport: String(target?.transport || 'tcp'),
      }
      if (target) return
      try {
        const result = await getBindDiscoveryInterfaces()
        this.interfaces = result.interfaces || []
        if (!this.interfaces.some(item => item.address === this.interfaceAddress)) {
          this.interfaceAddress = this.interfaces[0]?.address || ''
        }
      } catch (error) {
        this.interfaces = []
        ElMessage.error(error.message || 'Unable to load network interfaces')
      }
      try {
        const settings = await getBindConnectionSettings()
        this.form.serverWebBaseUrl = String(settings.server_web_base_url || '')
      } catch (error) {
        ElMessage.error(error.message || 'Unable to load Server Web URL')
      }
    },
    getValidatedFields() {
      const host = this.form.host.trim()
      const port = Number(this.form.port)
      if (!host || !Number.isInteger(port) || port < 1 || port > 65535) {
        ElMessage.warning('Enter a Client address and valid port')
        return null
      }
      const serverWebBaseUrl = this.form.serverWebBaseUrl.trim()
      if (!/^https?:\/\/[^/\s]+\/?$/.test(serverWebBaseUrl)) {
        ElMessage.warning('Enter a valid Server Web URL')
        return null
      }
      return { host, port, serverWebBaseUrl }
    },
    async save() {
      const values = this.getValidatedFields()
      if (!values) return
      this.connecting = true
      try {
        await saveBindTarget(values.host, values.port, values.serverWebBaseUrl,
          this.form.name.trim(), this.targetId, this.form.transport)
        this.visible = false
        ElMessage.success('Connection saved')
        this.$emit('saved')
      } catch (error) {
        ElMessage.error(error.message || 'Unable to save connection')
      } finally {
        this.connecting = false
      }
    },
    async connect() {
      const host = this.form.host.trim()
      const port = Number(this.form.port)
      if (!host || !Number.isInteger(port) || port < 1 || port > 65535) {
        ElMessage.warning('Enter a Client address and valid port')
        return
      }
      const serverWebBaseUrl = this.form.serverWebBaseUrl.trim()
      if (!/^https?:\/\/[^/\s]+\/?$/.test(serverWebBaseUrl)) {
        ElMessage.warning('Enter a valid Server Web URL')
        return
      }
      this.connecting = true
      try {
        const result = await connectToClient(host, port, serverWebBaseUrl, this.form.name?.trim() || '', this.form.transport)
        this.visible = false
        if (result.status === 'already_connected') {
          ElMessage.info('Client already connected')
        } else {
          ElMessage.success('Client connected')
          this.$emit('connected', result.client_id)
        }
      } catch (error) {
        ElMessage.error(error.message || 'Unable to connect to Client')
      } finally {
        this.connecting = false
      }
    },
  },
}
</script>

<style>
.bind-connect-dialog.el-dialog {
  max-width: calc(100vw - 32px);
  max-height: calc(100dvh - 32px);
  display: flex;
  flex-direction: column;
}
.bind-connect-dialog .el-dialog__body { min-height: 0; display: flex; overflow: hidden; }
.bind-connect-dialog .el-dialog__footer { flex: none; }
.bind-connect-tabs { display: flex; flex-direction: column; flex: 1; min-height: 0; }
.bind-connect-tabs > .el-tabs__header { flex: none; margin-bottom: 12px; }
.bind-connect-tabs > .el-tabs__content { min-height: 0; max-height: calc(100dvh - 192px); overflow-y: auto; }
.bind-connect-form { padding: 8px 4px 4px; }
.bind-connect-form .el-form-item { margin-bottom: 16px; }
.bind-connect-form .el-form-item__label { height: auto; line-height: 20px; margin-bottom: 4px; padding: 0; }
.bind-connect-dialog .el-form-item__label { white-space: nowrap; }
.bind-discovery-panel { display: flex; flex-direction: column; gap: 12px; padding: 4px; }
.bind-discovery-controls { display: flex; align-items: end; gap: 12px; }
.bind-discovery-interface { flex: 1; min-width: 0; }
.bind-discovery-label { display: block; font-size: 12px; margin-bottom: 6px; color: var(--el-text-color-secondary); }
.bind-discovery-meta { color: var(--el-text-color-secondary); font-size: 12px; }
.bind-discovery-results { display: flex; flex-direction: column; gap: 8px; max-height: 240px; overflow-y: auto; }
.bind-discovery-device { font: inherit; text-align: left; display: flex; align-items: center; gap: 12px; width: 100%; padding: 12px; background: var(--el-fill-color-blank); color: var(--el-text-color-primary); border: 1px solid var(--el-border-color); border-radius: 8px; cursor: pointer; }
.bind-discovery-device:hover { border-color: var(--el-color-primary-light-5); }
.bind-discovery-device.is-selected { border-color: var(--el-color-primary); box-shadow: inset 0 0 0 1px var(--el-color-primary); }
.bind-discovery-radio { width: 14px; height: 14px; border: 1px solid var(--el-border-color-darker); border-radius: 50%; flex: none; }
.bind-discovery-device.is-selected .bind-discovery-radio { border: 4px solid var(--el-color-primary); }
.bind-discovery-device-main { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 4px; }
.bind-discovery-device-main strong { overflow-wrap: anywhere; font-size: 13px; }
.bind-discovery-details, .bind-discovery-transport { color: var(--el-text-color-secondary); font-size: 12px; overflow-wrap: anywhere; }
.bind-discovery-web-url { padding-top: 4px; }
@media (max-width: 960px) {
  .bind-connect-dialog.el-dialog { width: 100vw !important; max-width: 100vw !important; height: 100dvh !important; max-height: 100dvh !important; margin: 0 !important; border-radius: 0 !important; }
  .bind-connect-dialog .el-dialog__body { flex: 1; }
  .bind-connect-tabs > .el-tabs__content { flex: 1; max-height: none; }
}
</style>
