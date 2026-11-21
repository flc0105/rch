<template>
  <el-dialog v-model="visible" title="Connect to Client" width="480px" class="fixed-dialog bind-connect-dialog" append-to-body>
    <el-form :model="form" label-width="80px" @submit.prevent="connect">
      <el-form-item label="Host">
        <el-input v-model="form.host" placeholder="Client IP or hostname" autocomplete="off" />
      </el-form-item>
      <el-form-item label="Port">
        <el-input v-model.number="form.port" type="number" min="1" max="65535" />
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
import { connectToClient } from '../api/connectionsApi.js'

export default {
  name: 'ConnectToClientDialog',
  emits: ['connected'],
  data() {
    return { visible: false, connecting: false, form: { host: '', port: 9443 } }
  },
  methods: {
    open() { this.visible = true },
    async connect() {
      const host = this.form.host.trim()
      const port = Number(this.form.port)
      if (!host || !Number.isInteger(port) || port < 1 || port > 65535) {
        ElMessage.warning('Enter a Client address and valid port')
        return
      }
      this.connecting = true
      try {
        const result = await connectToClient(host, port)
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
.bind-connect-dialog.el-dialog { max-width: calc(100vw - 32px); }
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
