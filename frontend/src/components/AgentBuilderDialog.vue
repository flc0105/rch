<template>
  <el-dialog
      v-model="visible"
      title="Build Agent"
      width="720px"
      top="8vh"
      class="fixed-dialog agent-builder-dialog"
      modal-class="agent-builder-overlay"
  >
    <div
        class="fixed-dialog-body agent-builder-body"
        v-loading="platformLoading"
    >
      <el-form
          :model="agentForm"
          label-width="110px"
          class="agent-builder-form"
          @submit.prevent="buildAgent"
      >
        <el-form-item label="Server IP" required>
          <el-input
              v-model="agentForm.server_host"
              placeholder="e.g., 192.168.1.100"
          />
        </el-form-item>

        <el-form-item label="Server Port" required>
          <el-input
              v-model.number="agentForm.server_port"
              type="number"
              placeholder="8000"
          />
        </el-form-item>

        <el-form-item label="Web Port" required>
          <el-input
              v-model.number="agentForm.web_port"
              type="number"
              placeholder="8000"
          />
        </el-form-item>

        <el-form-item label="Target OS">
          <el-radio-group
              v-model="agentForm.target_os"
              :disabled="isAgentTargetOsDisabled"
              class="agent-builder-radio-group"
          >
            <el-radio label="mac">macOS</el-radio>
            <el-radio label="win">Windows</el-radio>
            <el-radio label="linux">Linux</el-radio>
          </el-radio-group>
        </el-form-item>

        <el-form-item label="Builder">
          <el-radio-group
              v-model="agentForm.builder"
              class="agent-builder-radio-group"
          >
            <el-radio label="bundle">Bundle</el-radio>
            <el-radio label="pyinstaller">PyInstaller</el-radio>
            <el-radio label="go">Go (Simple)</el-radio>
            <el-radio label="go_loader">Go (Loader)</el-radio>
          </el-radio-group>
        </el-form-item>

        <el-form-item label="Target Arch">
          <el-radio-group
              v-model="agentForm.target_arch"
              :disabled="isAgentTargetArchDisabled"
              class="agent-builder-radio-group"
          >
            <el-radio label="amd64">amd64</el-radio>
            <el-radio label="arm64">arm64</el-radio>
          </el-radio-group>
        </el-form-item>

        <el-alert
            type="info"
            :closable="false"
            show-icon
        >
          <template #default>
            <div class="agent-builder-alert-text">
              {{ agentBuilderAlertText }}
            </div>
          </template>
        </el-alert>
      </el-form>
    </div>

    <template #footer>
      <div class="agent-builder-footer">
        <el-button @click="visible = false">
          Cancel
        </el-button>

        <el-button
            type="primary"
            :loading="agentBuilding"
            @click="buildAgent"
        >
          Build & Download
        </el-button>
      </div>
    </template>
  </el-dialog>
</template>

<script>
import {ElMessage} from 'element-plus'

export default {
  name: 'AgentBuilderDialog',

  emits: [
    'built',
  ],

  data() {
    return {
      visible: false,
      platformLoading: false,
      agentBuilding: false,
      agentServerTargetOs: 'mac',
      agentForm: {
        server_host: window.location.hostname || '127.0.0.1',
        server_port: 9999,
        web_port: 8085,
        target_os: 'mac',
        builder: 'bundle',
        target_arch: 'arm64',
      },
    }
  },

  computed: {
    agentBuilderAlertText() {
      if (this.agentForm.builder === 'pyinstaller') {
        return `Standalone executable. Can only build for the same OS as the current server (${this.describeAgentTargetOs(this.agentServerTargetOs)}).`
      }

      if (this.agentForm.builder === 'bundle') {
        return 'Source ZIP package. Includes the Python client source files.'
        // return 'Source ZIP package. Includes the Python client source files.\nOne-liner: python3 -c "import requests; exec(requests.post(\'http://' + this.agentForm.server_host + ':' + this.agentForm.web_port + '/api/agent/bootstrap\', json={\'server_host\':\'' + this.agentForm.server_host + '\',\'server_port\':' + this.agentForm.server_port + ',\'web_port\':' + this.agentForm.web_port + '}).text)"'
      }

      if (this.agentForm.builder === 'go_loader') {
        return 'Downloads the bundle and runs it with Python.'
      }

      return 'Lightweight Go client for basic commands.'
    },

    isBundleBuilder() {
      return this.agentForm.builder === 'bundle'
    },

    isPyInstallerBuilder() {
      return this.agentForm.builder === 'pyinstaller'
    },

    isAgentTargetOsDisabled() {
      return this.isBundleBuilder || this.isPyInstallerBuilder
    },

    isAgentTargetArchDisabled() {
      return this.isBundleBuilder || this.isPyInstallerBuilder
    },
  },

  watch: {
    'agentForm.builder'() {
      this.applyAgentBuilderRules()
    },

    'agentForm.target_os'() {
      this.applyAgentBuilderRules()
    },
  },

  methods: {
    async open() {
      this.visible = true
      this.agentForm.server_host = window.location.hostname || '127.0.0.1'
      this.agentForm.server_port = 9999
      this.agentForm.web_port = 8085

      this.platformLoading = true
      try {
        await this.loadAgentServerPlatform()
      } finally {
        this.platformLoading = false
      }

      this.applyAgentBuilderRules()
    },

    describeAgentTargetOs(targetOs) {
      const mapping = {
        win: 'Windows',
        mac: 'macOS',
        linux: 'Linux',
        bundle: 'Bundle',
      }

      return mapping[targetOs] || targetOs || 'macOS'
    },

    getDefaultAgentTargetArch(targetOs) {
      const normalizedTargetOs = String(targetOs || '').trim().toLowerCase()

      if (normalizedTargetOs === 'win') return 'amd64'
      if (normalizedTargetOs === 'mac') return 'arm64'

      return 'amd64'
    },

    async loadAgentServerPlatform() {
      try {
        const res = await fetch('/api/agent/platform')
        const json = await res.json()

        if (!res.ok || json.code !== 0) {
          throw new Error(json.message || 'Failed to load server platform')
        }

        const targetOs = String(json.data?.target_os || 'mac').trim() || 'mac'
        this.agentServerTargetOs = targetOs

        const socketPort = Number(json.data?.socket_port || 0)
        const webPort = Number(json.data?.web_port || 0)
        if (socketPort > 0) {
          this.agentForm.server_port = socketPort
        }
        if (webPort > 0) {
          this.agentForm.web_port = webPort
        }
      } catch (_error) {
        this.agentServerTargetOs = 'mac'
      }
    },

    applyAgentBuilderRules() {
      if (this.agentForm.builder === 'bundle') {
        this.agentForm.target_os = 'mac'
        this.agentForm.target_arch = 'arm64'
        return
      }

      if (this.agentForm.builder === 'pyinstaller') {
        this.agentForm.target_os = this.agentServerTargetOs || 'mac'
        this.agentForm.target_arch = this.getDefaultAgentTargetArch(this.agentForm.target_os)
        return
      }

      this.agentForm.target_arch = this.getDefaultAgentTargetArch(this.agentForm.target_os)
    },

    buildAgentPayload() {
      const payload = {
        ...this.agentForm,
        source: 'manual',
        server_web_scheme: window.location.protocol.replace(':', '') || 'http',
        server_web_host: this.agentForm.server_host,
      }

      if (this.agentForm.builder === 'bundle') {
        payload.target_os = 'bundle'
        payload.target_arch = ''
      } else if (this.agentForm.builder === 'pyinstaller') {
        payload.target_os = this.agentServerTargetOs || this.agentForm.target_os || 'mac'
        payload.target_arch = ''
      }

      return payload
    },

    async buildAgent() {
      if (this.agentBuilding) return

      if (!this.agentForm.server_host) {
        ElMessage.warning('Please enter server IP')
        return
      }

      if (!this.agentForm.server_port) {
        ElMessage.warning('Please enter server port')
        return
      }

      if (!this.agentForm.web_port) {
        ElMessage.warning('Please enter web port')
        return
      }

      this.agentBuilding = true

      try {
        const res = await fetch('/api/agent/build', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(this.buildAgentPayload()),
        })

        const json = await res.json()

        if (!res.ok || json.code !== 0) {
          throw new Error(json.message || 'Build failed')
        }

        const data = json.data || {}
        const downloadUrl = data.download_url || `/api/agent/download/${encodeURIComponent(data.file_name)}`

        ElMessage.success('Build completed. Downloading...')

        const a = document.createElement('a')
        a.href = downloadUrl
        a.download = data.file_name
        document.body.appendChild(a)
        a.click()
        document.body.removeChild(a)

        this.visible = false
        this.$emit('built', data)
      } catch (e) {
        ElMessage.error(e.message || 'Build failed')
      } finally {
        this.agentBuilding = false
      }
    },
  },
}
</script>

<style scoped>
.agent-builder-body {
  width: 100%;
  min-width: 0;
  max-height: calc(82vh - 132px);
  overflow-y: auto;
  overflow-x: hidden;
  padding-right: 4px;
  box-sizing: border-box;
}

.agent-builder-form {
  display: flex;
  flex-direction: column;
  width: 100%;
  min-width: 0;
  box-sizing: border-box;
}

.agent-builder-form :deep(.el-form-item:last-of-type) {
  margin-bottom: 14px;
}

.agent-builder-radio-group {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 16px;
}

.agent-builder-alert-text {
  white-space: pre-line;
  line-height: 1.7;
  font-size: 12px;
}

.agent-builder-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

@media (max-width: 768px) {
  .agent-builder-body {
    max-height: none;
    padding-right: 0;
  }

  .agent-builder-form :deep(.el-form-item) {
    display: block;
  }

  .agent-builder-form :deep(.el-form-item__label) {
    justify-content: flex-start;
    width: auto !important;
    margin-bottom: 4px;
  }

  .agent-builder-form :deep(.el-form-item__content) {
    margin-left: 0 !important;
  }
}
</style>

<style>
/* AgentBuilderDialog: 构建表单滚动放在组件内部。 */
.agent-builder-overlay .el-dialog {
  max-height: 82vh !important;
  overflow: hidden !important;
}

.agent-builder-overlay .el-dialog__body {
  overflow: hidden !important;
}

@media (max-width: 768px) {
  .agent-builder-overlay .el-dialog {
    width: 100vw !important;
    max-width: 100vw !important;
    height: 100dvh !important;
    max-height: 100dvh !important;
    margin: 0 !important;
    border-radius: 0 !important;
    display: flex !important;
    flex-direction: column !important;
  }

  .agent-builder-overlay .el-dialog__header {
    flex: 0 0 auto !important;
    padding: 14px 16px 10px !important;
  }

  .agent-builder-overlay .el-dialog__body {
    display: flex !important;
    flex: 1 1 auto !important;
    min-height: 0 !important;
    padding: 10px 12px 12px !important;
    overflow-y: auto !important;
    overflow-x: hidden !important;
  }

  .agent-builder-overlay .el-dialog__footer {
    flex: 0 0 auto !important;
  }
}


@media (min-width: 769px) {
  .agent-builder-overlay .el-dialog {
    width: 720px !important;
    max-width: calc(100vw - 32px) !important;
    height: auto !important;
    max-height: 82vh !important;
    margin: 8vh auto 0 !important;
    border-radius: var(--el-border-radius-small) !important;
    display: flex !important;
    flex-direction: column !important;
    overflow: hidden !important;
  }

  .agent-builder-overlay .el-dialog__body {
    display: block !important;
    flex: 0 1 auto !important;
    width: 100% !important;
    min-width: 0 !important;
    overflow: hidden !important;
    box-sizing: border-box !important;
  }

  .agent-builder-overlay .el-dialog__footer {
    flex: 0 0 auto !important;
  }
}
</style>