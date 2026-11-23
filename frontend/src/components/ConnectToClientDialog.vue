<template>
  <el-dialog v-model="visible" title="Connect to Client" width="560px" class="fixed-dialog bind-connect-dialog" append-to-body>
    <el-form :model="form" label-position="top" class="bind-connect-form" @submit.prevent="connect">
      <el-form-item label="Host">
        <el-input v-model="form.host" placeholder="Client IP or hostname" autocomplete="off" />
      </el-form-item>
      <el-form-item label="Port">
        <el-input v-model.number="form.port" type="number" min="1" max="65535" />
      </el-form-item>
      <el-form-item label="Server Web URL">
        <el-input v-model="form.serverWebBaseUrl" placeholder="http://server:8085" autocomplete="off" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="visible = false">Cancel</el-button>
      <el-button type="primary" :loading="connecting" @click="connect">Connect</el-button>
    </template>
  </el-dialog>
</template>

<script>
import { ElMessage } from 'element-plus'
import { connectToClient, getBindConnectionSettings } from '../api/connectionsApi.js'

export default {
  name: 'ConnectToClientDialog',
  emits: ['connected'],
  data() {
    return { visible: false, connecting: false, form: { host: '', port: 9443, serverWebBaseUrl: '' } }
  },
  methods: {
    async open() {
      this.visible = true
      try {
        const settings = await getBindConnectionSettings()
        this.form.serverWebBaseUrl = String(settings.server_web_base_url || '')
      } catch (error) {
        ElMessage.error(error.message || 'Unable to load Server Web URL')
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
        const result = await connectToClient(host, port, serverWebBaseUrl)
        this.visible = false
        ElMessage.success('Client connected')
        this.$emit('connected', result.client_id)
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
.bind-connect-dialog .bind-connect-form { padding: 8px 4px 4px; }
.bind-connect-dialog .bind-connect-form .el-form-item { margin-bottom: 16px; }
.bind-connect-dialog .bind-connect-form .el-form-item__label { height: auto; line-height: 20px; margin-bottom: 4px; padding: 0; }
.bind-connect-dialog.el-dialog { max-width: calc(100vw - 32px); }
.bind-connect-dialog .el-form-item__label { white-space: nowrap; }
@media (max-width: 960px) {
  .bind-connect-dialog.el-dialog {
    width: 100vw !important;
    max-width: 100vw !important;
    height: 100dvh !important;
    margin: 0 !important;
    border-radius: 0 !important;
    display: flex;
    flex-direction: column;
  }
  .bind-connect-dialog .el-dialog__body { flex: 1; overflow-y: auto; }
}
</style>
