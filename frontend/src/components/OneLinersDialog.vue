<template>
  <el-dialog
    v-model="visible"
    title="One-liners"
    width="860px"
    top="7vh"
    class="fixed-dialog one-liners-dialog"
    modal-class="one-liners-overlay"
  >
    <div class="fixed-dialog-body one-liners-body">
      <div class="one-liners-intro">
        <div class="one-liners-intro-title">Quick command snippets</div>
        <div class="one-liners-intro-text">
          Edit the server values below.
        </div>
      </div>

      <div class="one-liners-config-row">
        <label class="one-liners-config-field">
          <span>Server IP</span>
          <el-input
            v-model="serverForm.serverHost"
            size="small"
            placeholder="Server IP"
          />
        </label>

        <label class="one-liners-config-field">
          <span>Server port</span>
          <el-input
            v-model="serverForm.serverPort"
            size="small"
            placeholder="9999"
          />
        </label>

        <label class="one-liners-config-field">
          <span>Web port</span>
          <el-input
            v-model="serverForm.webPort"
            size="small"
            placeholder="8085"
          />
        </label>
      </div>

      <div
        v-if="!normalizedOneLiners.length"
        class="empty-state"
      >
        No one-liners configured
      </div>

      <div
        v-else
        class="one-liners-list"
      >
        <div
          v-for="item in normalizedOneLiners"
          :key="item.id"
          class="one-liner-card"
        >
          <div class="one-liner-label">
            {{ item.label }}
          </div>

          <div class="one-liner-code-row">
            <pre
              class="one-liner-code"
              contenteditable="true"
              spellcheck="false"
              :aria-label="`${item.label} command`"
              @blur="saveOneLinerEdit(item, $event)"
            ><code>{{ item.code }}</code></pre>

            <el-button
              size="small"
              class="one-liner-copy-button"
              type="primary"
              plain
              @click="copyOneLiner(item)"
            >
              Copy
            </el-button>
          </div>
        </div>
      </div>
    </div>
  </el-dialog>
</template>

<script>
import { ElMessage } from 'element-plus'
import { terminalOneLiners } from '../data/terminalOneLiners.js'

export default {
  name: 'OneLinersDialog',

  data() {
    return {
      visible: false,
      oneLiners: terminalOneLiners,
      oneLinerOverrides: {},
      serverForm: this.getDefaultServerForm(),
    }
  },

  computed: {
    normalizedOneLiners() {
      return this.oneLiners
        .map((item, index) => {
          const id = item.id || `${index}-${item.label || 'one-liner'}`
          const renderedCode = this.renderOneLinerCode(item.code)
          const hasOverride = Object.prototype.hasOwnProperty.call(this.oneLinerOverrides, id)
          return {
            id,
            label: String(item.label || '').trim(),
            code: hasOverride ? this.oneLinerOverrides[id] : renderedCode,
          }
        })
        .filter(item => item.label)
    },
  },

  methods: {
    async open() {
      this.oneLinerOverrides = {}
      this.serverForm = this.getDefaultServerForm()
      this.visible = true
      await this.loadServerPlatform()
    },

    close() {
      this.visible = false
    },

    getDefaultServerForm() {
      const location = typeof window !== 'undefined' ? window.location : null

      return {
        serverHost: location?.hostname || 'localhost',
        serverPort: '9999',
        webPort: '8085',
      }
    },

    async loadServerPlatform() {
      try {
        const res = await fetch('/api/agent/platform')
        const json = await res.json()

        if (!res.ok || json.code !== 0) {
          throw new Error(json.message || 'Failed to load server platform')
        }

        const webPort = Number(json.data?.web_port || 0)
        const socketPort = Number(json.data?.socket_port || 0)

        if (webPort > 0) {
          this.serverForm.webPort = String(webPort)
        }
        if (socketPort > 0) {
          this.serverForm.serverPort = String(socketPort)
        }
      } catch (_error) {
        // 保留本地默认值，避免平台信息读取失败时阻断 one-liner 使用。
      }
    },

    renderOneLinerCode(code) {
      const replacements = {
        server_host: String(this.serverForm.serverHost || '').trim(),
        server_port: String(this.serverForm.serverPort || '').trim(),
        web_port: String(this.serverForm.webPort || '').trim(),
      }

      return String(code || '')
        .replace(/{{\s*server_host\s*}}/g, replacements.server_host)
        .replace(/{{\s*server_port\s*}}/g, replacements.server_port)
        .replace(/{{\s*web_port\s*}}/g, replacements.web_port)
        .trim()
    },

    saveOneLinerEdit(item, event) {
      const itemId = String(item?.id || '').trim()
      if (!itemId) return

      const text = String(event?.currentTarget?.innerText ?? '')
        .replace(/\r\n/g, '\n')
        .replace(/\u00a0/g, ' ')

      this.oneLinerOverrides = {
        ...this.oneLinerOverrides,
        [itemId]: text,
      }
    },

    async copyOneLiner(item) {
      if (!item?.code) {
        ElMessage.warning('No command to copy')
        return
      }

      try {
        await this.copyTextToClipboard(item.code)
        ElMessage.success('Command copied')
      } catch (e) {
        ElMessage.error(e.message || 'Failed to copy command')
      }
    },

    async copyTextToClipboard(text) {
      if (
        typeof navigator !== 'undefined' &&
        navigator.clipboard &&
        typeof navigator.clipboard.writeText === 'function'
      ) {
        await navigator.clipboard.writeText(text)
        return
      }

      const textarea = document.createElement('textarea')
      textarea.value = text
      textarea.setAttribute('readonly', 'readonly')
      textarea.style.position = 'fixed'
      textarea.style.left = '-9999px'
      textarea.style.top = '-9999px'
      document.body.appendChild(textarea)
      textarea.select()

      const ok = document.execCommand('copy')
      document.body.removeChild(textarea)

      if (!ok) {
        throw new Error('Fallback copy failed')
      }
    },
  },
}
</script>

<style scoped>
.one-liners-body {
  gap: 12px;
}

.one-liners-intro {
  flex: 0 0 auto;
  padding: 12px 14px;
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 14px;
  background: linear-gradient(135deg, rgba(37, 99, 235, 0.07), rgba(15, 23, 42, 0.03));
}

.one-liners-intro-title {
  color: #0f172a;
  font-size: 14px;
  font-weight: 750;
  line-height: 1.35;
}

.one-liners-intro-text {
  margin-top: 3px;
  color: #64748b;
  font-size: 12px;
  line-height: 1.5;
}

.one-liners-config-row {
  flex: 0 0 auto;
  display: grid;
  grid-template-columns: minmax(0, 1.25fr) repeat(2, minmax(100px, 0.75fr));
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 14px;
  background: rgba(248, 250, 252, 0.95);
}

.one-liners-config-field {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.one-liners-config-field span {
  color: #475569;
  font-size: 11px;
  font-weight: 700;
  line-height: 1.2;
}

.one-liners-list {
  min-height: 0;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding-right: 2px;
}

.one-liner-card {
  padding: 12px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.88);
  box-shadow: 0 8px 20px rgba(15, 23, 42, 0.04);
}

.one-liner-label {
  margin-bottom: 8px;
  color: #0f172a;
  font-size: 13px;
  font-weight: 700;
  line-height: 1.35;
}

.one-liner-code-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 10px;
  align-items: stretch;
}

.one-liner-code {
  min-width: 0;
  margin: 0;
  padding: 10px 12px;
  border: 1px solid rgba(148, 163, 184, 0.16);
  border-radius: 12px;
  background: #0f172a;
  color: #dbeafe;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 12px;
  line-height: 1.55;
  white-space: pre-wrap;
  word-break: break-word;
  cursor: text;
  outline: none;
}

.one-liner-code:focus {
  border-color: rgba(96, 165, 250, 0.72);
  box-shadow: inset 0 0 0 1px rgba(96, 165, 250, 0.22);
}

.one-liner-copy-button.el-button {
  align-self: stretch;
  min-height: 36px;
  margin: 0;
  border-radius: 12px;
}

@media (max-width: 720px) {
  .one-liners-config-row {
    grid-template-columns: minmax(0, 1fr);
  }

  .one-liner-code-row {
    grid-template-columns: minmax(0, 1fr);
  }

  .one-liner-copy-button.el-button {
    justify-self: end;
    align-self: auto;
  }
}
</style>
