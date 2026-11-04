<template>
  <el-dialog v-model="visible" title="Add listener" width="640px" top="8vh"
             class="fixed-dialog listener-add-dialog" append-to-body :close-on-click-modal="true">
    <div class="fixed-dialog-body listener-add-body">
      <el-form :model="form" label-width="120px" class="listener-add-form" @submit.prevent="create">
        <el-form-item label="Name">
          <el-input v-model="form.name" maxlength="60" placeholder="e.g. Public TLS" />
        </el-form-item>
        <el-form-item label="Protocol">
          <el-select v-model="form.protocol" style="width:100%">
            <el-option v-for="protocol in protocols" :key="protocol.id" :label="protocol.label" :value="protocol.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="Bind address">
          <el-input v-model="form.host" placeholder="0.0.0.0 (all interfaces)" />
        </el-form-item>
        <el-form-item label="Port">
          <el-input v-model.number="form.port" type="number" min="1" max="65535" />
        </el-form-item>
      </el-form>
      <el-alert v-if="selectedProtocol?.notice" type="info" :closable="false" show-icon :title="selectedProtocol.notice" />
    </div>
    <template #footer>
      <el-button @click="visible = false">Cancel</el-button>
      <el-button type="primary" :loading="saving" @click="create">Add Listener</el-button>
    </template>
  </el-dialog>
</template>

<script>
import { ElMessage } from 'element-plus'
import { createListener } from '../api/listenersApi.js'

export default {
  name: 'AddListenerDialog',
  props: { protocols: { type: Array, default: () => [] } },
  emits: ['created'],
  data() { return { visible: false, saving: false,
    form: { name: '', protocol: 'tcp', host: '0.0.0.0', port: 9443 } } },
  computed: {
    selectedProtocol() { return this.protocols.find(item => item.id === this.form.protocol) },
  },
  methods: {
    open() {
      this.form = { name: '', protocol: 'tcp', host: '0.0.0.0', port: 9443 }
      this.visible = true
    },
    async create() {
      if (!this.form.name.trim() || !Number.isInteger(Number(this.form.port)) || Number(this.form.port) < 1 || Number(this.form.port) > 65535) {
        ElMessage.warning('Enter a name and port')
        return
      }
      this.saving = true
      try {
        const response = await createListener(this.form)
        const result = await response.json()
        if (!response.ok || result.code !== 0) throw new Error(result.message || 'Listener operation failed')
        this.visible = false
        ElMessage.success('Listener added')
        this.$emit('created')
      } catch (error) { ElMessage.error(error.message) }
      finally { this.saving = false }
    },
  },
}
</script>

<style>
.listener-add-dialog.el-dialog { max-width: calc(100vw - 32px); display: flex; flex-direction: column; }
.listener-add-dialog .el-dialog__body { min-height: 0; overflow-y: auto; }
.listener-add-form { width: 100%; min-width: 0; }
.listener-add-form .el-form-item { min-width: 0; }
@media (max-width: 960px) {
  .listener-add-dialog.el-dialog {
    width: 100vw !important;
    max-width: 100vw !important;
    height: 100dvh !important;
    margin: 0 !important;
    border-radius: 0 !important;
  }
  .listener-add-dialog .el-dialog__header { flex: 0 0 auto; padding: 16px 16px 12px; }
  .listener-add-dialog .el-dialog__body { flex: 1 1 auto; padding: 12px 16px; }
  .listener-add-dialog .el-dialog__footer { flex: 0 0 auto; padding: 12px 16px max(12px, env(safe-area-inset-bottom)); }
  .listener-add-form .el-form-item { display: block; }
  .listener-add-form .el-form-item__label { justify-content: flex-start; width: auto !important; }
  .listener-add-form .el-form-item__content { margin-left: 0 !important; }
}
</style>
