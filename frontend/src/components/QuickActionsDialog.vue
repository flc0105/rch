<template>
  <el-dialog
    v-model="visible"
    title="Quick Actions"
    width="920px"
    top="6vh"
    class="fixed-dialog quick-actions-dialog"
    modal-class="quick-actions-overlay"
    destroy-on-close
  >
    <div class="fixed-dialog-body quick-actions-body">
      <div class="quick-actions-toolbar">
        <div class="quick-actions-toolbar-left">
          <el-select v-model="filterPlatform" class="platform-filter" :disabled="loading">
            <el-option label="Current" value="current" />
            <el-option
              v-for="platform in supportedPlatforms"
              :key="platform"
              :label="platformLabel(platform)"
              :value="platform"
            />
          </el-select>

          <el-input
            v-model="searchText"
            clearable
            class="quick-actions-search"
            placeholder="Filter alias or command"
          />
        </div>

        <el-button type="primary" @click="openCreateDialog">
          New Action
        </el-button>
      </div>

      <div class="quick-actions-table-shell">
        <el-table
          v-loading="loading"
          :data="filteredItems"
          empty-text="No Quick Actions"
          class="quick-actions-table"
          height="100%"
          table-layout="fixed"
        >
          <el-table-column label="Action" min-width="165">
            <template #default="{ row }">
              <div class="action-cell">
                <span class="action-name">{{ row.alias }}</span>
                <el-tag
                  v-if="showCommonTag(row)"
                  size="small"
                  type="info"
                  effect="plain"
                  class="common-origin-tag"
                  :title="commonTagTitle(row)"
                >
                  Common
                </el-tag>
              </div>
            </template>
          </el-table-column>

          <el-table-column label="Command" min-width="360">
            <template #default="{ row }">
              <el-tooltip
                :content="row.command"
                placement="top"
                :show-after="250"
                :disabled="!isOverflowing(commandOverflowKey(row))"
                popper-class="quick-actions-command-tooltip"
              >
                <code v-overflow-state="commandOverflowKey(row)" class="command-cell">{{ row.command }}</code>
              </el-tooltip>
            </template>
          </el-table-column>

          <el-table-column label="Run" width="120" align="center">
            <template #default="{ row }">
              <el-dropdown
                split-button
                size="small"
                type="primary"
                :disabled="runSubmitting"
                @click="requestRun(row, 'dialog')"
                @command="command => handleRunCommand(row, command)"
              >
                Run
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item command="terminal">
                      Run in Terminal
                    </el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </template>
          </el-table-column>

          <el-table-column label="Manage" width="145" align="right">
            <template #default="{ row }">
              <el-button size="small" @click="openEditDialog(row)">
                Edit
              </el-button>
              <el-button size="small" type="danger" plain @click="deleteItem(row)">
                Delete
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>

    <template #footer>
      <el-button @click="visible = false">Close</el-button>
    </template>
  </el-dialog>

  <el-dialog
    v-model="editorVisible"
    :title="editorMode === 'create' ? 'New Quick Action' : 'Edit Quick Action'"
    width="620px"
    append-to-body
  >
    <el-form label-position="top">
      <el-form-item label="Platform">
        <el-select v-model="editorForm.platform" style="width: 100%">
          <el-option
            v-for="platform in supportedPlatforms"
            :key="platform"
            :label="platformLabel(platform)"
            :value="platform"
          />
        </el-select>
      </el-form-item>

      <el-form-item label="Action name">
        <el-input
          v-model="editorForm.alias"
          placeholder="e.g. logs"
          @keyup.enter="saveEditor"
        />
      </el-form-item>

      <el-form-item label="Command">
        <el-input
          v-model="editorForm.command"
          type="textarea"
          :rows="4"
          placeholder="Use <parameter> placeholders to render a run form"
        />
      </el-form-item>
    </el-form>

    <template #footer>
      <el-button @click="editorVisible = false">Cancel</el-button>
      <el-button type="primary" :loading="saving" @click="saveEditor">Save</el-button>
    </template>
  </el-dialog>

  <el-dialog
    v-model="parameterVisible"
    :title="`Run ${pendingRunItem?.alias || 'Quick Action'}`"
    width="560px"
    append-to-body
  >
    <el-form label-position="top" @submit.prevent>
      <el-form-item
        v-for="(parameter, index) in pendingRunParameters"
        :key="`${parameter.position}-${parameter.placeholder}`"
        :label="parameterLabel(parameter, index)"
      >
        <el-input
          v-model="parameterValues[index]"
          :placeholder="parameter.placeholder"
          @keyup.enter="submitParameterRun"
        />
      </el-form-item>
    </el-form>

    <template #footer>
      <div class="quick-action-parameter-actions">
        <el-button @click="parameterVisible = false">Cancel</el-button>
        <el-dropdown
          split-button
          type="primary"
          :disabled="runSubmitting"
          @click="submitParameterRun"
          @command="handleParameterRunCommand"
        >
          {{ pendingRunPresentation === 'terminal' ? 'Run in Terminal' : 'Run' }}
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item :command="pendingRunPresentation === 'terminal' ? 'dialog' : 'terminal'">
                {{ pendingRunPresentation === 'terminal' ? 'Run with Result Dialog' : 'Run in Terminal' }}
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </template>
  </el-dialog>

  <el-dialog
    v-model="resultVisible"
    :title="resultTitle"
    width="760px"
    append-to-body
  >
    <div class="quick-action-result-meta">
      <el-tag :type="resultStatusType" size="small" class="quick-action-result-status">
        {{ activeRun.status || 'Running' }}
      </el-tag>
      <div v-if="activeRun.resolvedCommand" class="quick-action-result-command-shell">
        <el-tooltip
          :content="activeRun.resolvedCommand"
          placement="top"
          :show-after="250"
          :disabled="!isOverflowing('result-command')"
          popper-class="quick-actions-command-tooltip"
        >
          <code v-overflow-state="'result-command'" class="quick-action-result-command">
            {{ activeRun.resolvedCommand }}
          </code>
        </el-tooltip>
      </div>
    </div>

    <pre class="quick-action-result-output">{{ activeRun.output || (activeRun.complete ? '(no output)' : 'Running…') }}</pre>

    <template #footer>
      <el-button :disabled="!activeRun.output" @click="copyResult">Copy</el-button>
      <el-button @click="resultVisible = false">Close</el-button>
    </template>
  </el-dialog>
</template>

<script>
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  createQuickAction,
  deleteQuickAction,
  executeQuickAction,
  listQuickActions,
  updateQuickAction,
} from '../api/quickActionsApi.js'

const PLATFORM_LABELS = {
  common: 'Common',
  win: 'Windows',
  mac: 'macOS',
  linux: 'Linux',
  ios: 'iOS',
}

function configureOverflowState(el, binding) {
  el.__quickActionOverflowInstance = binding.instance
  el.__quickActionOverflowKey = String(binding.value || '')

  const apply = () => {
    const overflowing = el.scrollWidth > el.clientWidth + 1
    el.classList.toggle('is-overflowing', overflowing)
    el.__quickActionOverflowInstance?.setOverflowState?.(el.__quickActionOverflowKey, overflowing)
  }

  el.__quickActionOverflowApply = apply
  requestAnimationFrame(apply)
}

const overflowStateDirective = {
  mounted(el, binding) {
    configureOverflowState(el, binding)
    if (typeof ResizeObserver === 'function') {
      el.__quickActionOverflowObserver = new ResizeObserver(() => {
        el.__quickActionOverflowApply?.()
      })
      el.__quickActionOverflowObserver.observe(el)
    }
  },
  updated(el, binding) {
    configureOverflowState(el, binding)
  },
  unmounted(el) {
    el.__quickActionOverflowInstance?.setOverflowState?.(el.__quickActionOverflowKey, false)
    el.__quickActionOverflowObserver?.disconnect()
    delete el.__quickActionOverflowObserver
    delete el.__quickActionOverflowApply
    delete el.__quickActionOverflowInstance
    delete el.__quickActionOverflowKey
  },
}

function emptyRun() {
  return {
    runId: '',
    taskId: '',
    alias: '',
    platform: '',
    displayCommand: '',
    resolvedCommand: '',
    output: '',
    status: '',
    complete: false,
    success: false,
  }
}

export default {
  name: 'QuickActionsDialog',

  directives: {
    overflowState: overflowStateDirective,
  },

  props: {
    selectedId: {
      type: [String, Number],
      default: '',
    },
    currentConnection: {
      type: Object,
      default: null,
    },
    getTabScopedHeaders: {
      type: Function,
      default: null,
    },
  },

  emits: ['append-output', 'set-active-task'],

  data() {
    return {
      visible: false,
      loading: false,
      saving: false,
      runSubmitting: false,
      supportedPlatforms: [],
      currentPlatform: 'common',
      defaultPlatforms: ['common'],
      items: [],
      filterPlatform: 'current',
      searchText: '',

      editorVisible: false,
      editorMode: 'create',
      editorOriginal: null,
      editorForm: {
        platform: 'common',
        alias: '',
        command: '',
      },

      parameterVisible: false,
      pendingRunItem: null,
      pendingRunPresentation: 'dialog',
      parameterValues: [],

      resultVisible: false,
      activeRun: emptyRun(),
      overflowStates: {},
    }
  },

  computed: {
    filteredItems() {
      const keyword = String(this.searchText || '').trim().toLowerCase()
      const defaultSet = new Set(this.defaultPlatforms || ['common'])

      return (this.items || []).filter((item) => {
        let platformMatches = true
        if (this.filterPlatform === 'current') {
          platformMatches = defaultSet.has(item.platform)
        } else {
          platformMatches = item.platform === this.filterPlatform
        }
        if (!platformMatches) return false
        if (!keyword) return true
        return `${item.alias || ''} ${item.command || ''}`.toLowerCase().includes(keyword)
      })
    },
    pendingRunParameters() {
      return Array.isArray(this.pendingRunItem?.parameters) ? this.pendingRunItem.parameters : []
    },
    resultTitle() {
      const alias = this.activeRun.alias || 'Quick Action'
      const platform = this.activeRun.platform ? ` · ${this.platformLabel(this.activeRun.platform)}` : ''
      return `${alias}${platform}`
    },
    resultStatusType() {
      if (!this.activeRun.complete) return 'info'
      return this.activeRun.success ? 'success' : 'danger'
    },
  },

  methods: {
    platformLabel(platform) {
      return PLATFORM_LABELS[String(platform || '').trim().toLowerCase()] || String(platform || 'Unknown')
    },
    showCommonTag(row) {
      return this.filterPlatform === 'current' && row?.platform === 'common'
    },
    commonTagTitle(row) {
      if (row?.overridden && this.currentPlatform && this.currentPlatform !== 'common') {
        return `Common definition · overridden by ${this.platformLabel(this.currentPlatform)} for normal alias resolution`
      }
      return 'Common definition'
    },
    commandOverflowKey(row) {
      return `table-command:${JSON.stringify([row?.platform || '', row?.alias || ''])}`
    },
    setOverflowState(key, overflowing) {
      if (!key) return
      this.overflowStates[key] = overflowing === true
    },
    isOverflowing(key) {
      return this.overflowStates[key] === true
    },
    open() {
      if (!this.selectedId) {
        ElMessage.warning('Please select a device')
        return
      }
      this.filterPlatform = 'current'
      this.searchText = ''
      this.loading = true
      this.visible = true

      // Render the dialog/loading state first, then start the remote list request.
      // This keeps opening responsive even when alias reload/listing takes longer.
      this.$nextTick(() => {
        requestAnimationFrame(() => {
          if (!this.visible) {
            this.loading = false
            return
          }
          void this.loadItems()
        })
      })
    },
    async loadItems() {
      if (!this.selectedId) return
      this.loading = true
      try {
        const data = await listQuickActions(this.selectedId)
        this.supportedPlatforms = Array.isArray(data.supported_platforms) ? data.supported_platforms : []
        this.currentPlatform = String(data.current_platform || 'common')
        this.defaultPlatforms = Array.isArray(data.default_platforms) && data.default_platforms.length
          ? data.default_platforms
          : ['common']
        this.items = Array.isArray(data.items) ? data.items : []
      } catch (e) {
        ElMessage.error(e.message || 'Failed to load Quick Actions')
      } finally {
        this.loading = false
      }
    },
    openCreateDialog() {
      this.editorMode = 'create'
      this.editorOriginal = null
      this.editorForm = {
        platform: this.currentPlatform || 'common',
        alias: '',
        command: '',
      }
      this.editorVisible = true
    },
    openEditDialog(row) {
      this.editorMode = 'edit'
      this.editorOriginal = {
        platform: row.platform,
        alias: row.alias,
      }
      this.editorForm = {
        platform: row.platform,
        alias: row.alias,
        command: row.command,
      }
      this.editorVisible = true
    },
    validateEditor() {
      const alias = String(this.editorForm.alias || '').trim()
      const command = String(this.editorForm.command || '').trim()
      if (!alias) throw new Error('Action name is required')
      if (/\s/.test(alias)) throw new Error('Action name cannot contain whitespace')
      if (!command) throw new Error('Command is required')
      if (!this.editorForm.platform) throw new Error('Platform is required')
      return { alias, command }
    },
    async saveEditor() {
      if (this.saving || !this.selectedId) return
      let normalized
      try {
        normalized = this.validateEditor()
      } catch (e) {
        ElMessage.warning(e.message)
        return
      }

      this.saving = true
      try {
        if (this.editorMode === 'create') {
          await createQuickAction(this.selectedId, {
            platform: this.editorForm.platform,
            alias: normalized.alias,
            command: normalized.command,
          })
          ElMessage.success('Quick Action created')
        } else {
          await updateQuickAction(this.selectedId, {
            original_platform: this.editorOriginal?.platform,
            original_alias: this.editorOriginal?.alias,
            platform: this.editorForm.platform,
            alias: normalized.alias,
            command: normalized.command,
          })
          ElMessage.success('Quick Action updated')
        }
        this.editorVisible = false
        await this.loadItems()
      } catch (e) {
        ElMessage.error(e.message || 'Failed to save Quick Action')
      } finally {
        this.saving = false
      }
    },
    async deleteItem(row) {
      try {
        await ElMessageBox.confirm(
          `Delete Quick Action "${row.alias}" from ${this.platformLabel(row.platform)}?`,
          'Delete Quick Action',
          { type: 'warning', confirmButtonText: 'Delete', cancelButtonText: 'Cancel' },
        )
        await deleteQuickAction(this.selectedId, {
          platform: row.platform,
          alias: row.alias,
        })
        ElMessage.success('Quick Action deleted')
        await this.loadItems()
      } catch (e) {
        if (e === 'cancel' || e === 'close' || e?.message === 'cancel') return
        ElMessage.error(e.message || 'Failed to delete Quick Action')
      }
    },
    handleRunCommand(row, command) {
      if (command === 'terminal') this.requestRun(row, 'terminal')
    },
    requestRun(row, presentation = 'dialog') {
      const parameters = Array.isArray(row.parameters) ? row.parameters : []
      if (parameters.length > 0) {
        this.pendingRunItem = row
        this.pendingRunPresentation = presentation
        this.parameterValues = parameters.map(() => '')
        this.parameterVisible = true
        return
      }
      this.executeItem(row, [], presentation)
    },
    parameterLabel(parameter, index) {
      const duplicatesBefore = this.pendingRunParameters
        .slice(0, index)
        .filter(item => item.name === parameter.name).length
      return duplicatesBefore > 0 ? `${parameter.name} (${duplicatesBefore + 1})` : parameter.name
    },
    submitParameterRun() {
      this.executePendingParameterRun(this.pendingRunPresentation || 'dialog')
    },
    handleParameterRunCommand(command) {
      if (command === 'terminal' || command === 'dialog') this.executePendingParameterRun(command)
    },
    executePendingParameterRun(presentation) {
      if (!this.pendingRunItem) return
      const values = this.parameterValues.map(value => String(value ?? ''))
      const row = this.pendingRunItem
      this.parameterVisible = false
      this.executeItem(row, values, presentation)
    },
    createRunId() {
      if (globalThis.crypto && typeof globalThis.crypto.randomUUID === 'function') {
        return globalThis.crypto.randomUUID()
      }
      return `quick-action-${Date.now()}-${Math.random().toString(16).slice(2)}`
    },
    quoteDisplayArg(value) {
      const text = String(value ?? '')
      if (!text || /\s|["']/.test(text)) return JSON.stringify(text)
      return text
    },
    buildDisplayCommand(row, values) {
      const args = values.map(value => this.quoteDisplayArg(value))
      return [row.alias, ...args].join(' ')
    },
    async executeItem(row, values, presentation) {
      if (this.runSubmitting || !this.selectedId) return
      const runId = this.createRunId()
      const displayCommand = this.buildDisplayCommand(row, values)

      if (presentation === 'dialog') {
        this.activeRun = {
          ...emptyRun(),
          runId,
          alias: row.alias,
          platform: row.platform,
          displayCommand,
          status: 'Running',
        }
        this.resultVisible = true
      } else {
        this.$emit('append-output', this.selectedId, `> ${displayCommand}`, 'command')
      }

      this.runSubmitting = true
      try {
        const data = await executeQuickAction(
          this.selectedId,
          {
            platform: row.platform,
            alias: row.alias,
            arguments: values,
            presentation,
            run_id: runId,
          },
          this.getTabScopedHeaders ? this.getTabScopedHeaders() : {},
        )
        this.$emit('set-active-task', this.selectedId, data.task_id || '')

        if (presentation === 'dialog' && this.activeRun.runId === runId) {
          this.activeRun.taskId = data.task_id || ''
          this.activeRun.displayCommand = data.display_command || displayCommand
          this.activeRun.resolvedCommand = data.resolved_command || ''
        }
      } catch (e) {
        if (presentation === 'dialog' && this.activeRun.runId === runId) {
          this.activeRun.complete = true
          this.activeRun.success = false
          this.activeRun.status = 'Failed'
          this.activeRun.output += `${this.activeRun.output ? '\n' : ''}${e.message || 'Quick Action failed'}`
        } else {
          this.$emit('append-output', this.selectedId, `Quick Action failed: ${e.message || 'unknown error'}`, 'error')
        }
        ElMessage.error(e.message || 'Quick Action failed')
      } finally {
        this.runSubmitting = false
      }
    },
    handleCommandResult(payload = {}) {
      const metadata = payload.metadata && typeof payload.metadata === 'object' ? payload.metadata : {}
      if (!metadata.quick_action || metadata.quick_action_presentation !== 'dialog') return false
      if (String(metadata.quick_action_run_id || '') !== String(this.activeRun.runId || '')) return true

      if (!this.resultVisible) this.resultVisible = true
      if (!this.activeRun.resolvedCommand) {
        this.activeRun.resolvedCommand = String(metadata.quick_action_resolved_command || '')
      }
      this.appendResultChunk(payload.text)
      return true
    },
    appendResultChunk(text) {
      const chunk = String(text ?? '').replace(/\r\n/g, '\n').replace(/\r/g, '\n')
      if (!chunk) return

      const current = String(this.activeRun.output || '')
      if (!current) {
        this.activeRun.output = chunk
        return
      }

      const separator = current.endsWith('\n') || chunk.startsWith('\n') ? '' : '\n'
      this.activeRun.output = `${current}${separator}${chunk}`
    },
    handleCommandComplete(payload = {}) {
      const metadata = payload.metadata && typeof payload.metadata === 'object' ? payload.metadata : {}
      if (!metadata.quick_action || metadata.quick_action_presentation !== 'dialog') return false
      if (String(metadata.quick_action_run_id || '') !== String(this.activeRun.runId || '')) return true

      this.activeRun.complete = true
      this.activeRun.success = payload.success === true
      const status = String(payload.status || '').trim()
      this.activeRun.status = status === 'cancelled'
        ? 'Cancelled'
        : (payload.success ? 'Success' : 'Failed')
      return true
    },
    async copyResult() {
      const text = String(this.activeRun.output || '')
      if (!text) return
      try {
        if (window.isSecureContext && navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
          await navigator.clipboard.writeText(text)
        } else {
          const textarea = document.createElement('textarea')
          textarea.value = text
          textarea.style.position = 'fixed'
          textarea.style.opacity = '0'
          document.body.appendChild(textarea)
          textarea.focus()
          textarea.select()
          document.execCommand('copy')
          document.body.removeChild(textarea)
        }
        ElMessage.success('Result copied')
      } catch (e) {
        ElMessage.error(e.message || 'Copy failed')
      }
    },
  },
}
</script>

<style scoped>
.quick-actions-body {
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.quick-actions-toolbar {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}

.quick-actions-toolbar-left {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
  flex: 1 1 auto;
}

.platform-filter {
  flex: 0 0 145px;
  width: 145px;
}

.quick-actions-search {
  flex: 1 1 auto;
  min-width: 180px;
  max-width: none;
}

.quick-actions-table-shell {
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
}

.action-cell {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 7px;
}

.action-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.common-origin-tag {
  flex: 0 0 auto;
  opacity: 0.72;
}

.quick-action-parameter-actions {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 12px;
}

.command-cell,
.quick-action-result-command {
  font-family: var(--el-font-family-monospace, ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace);
}

.command-cell.is-overflowing,
.quick-action-result-command.is-overflowing {
  cursor: help;
}

.command-cell {
  display: block;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  cursor: default;
  color: var(--el-text-color-regular);
  font-size: 12px;
  line-height: 1.5;
}

.quick-action-result-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
  margin-bottom: 12px;
}

.quick-action-result-status {
  flex: 0 0 auto;
}

.quick-action-result-command-shell {
  flex: 1 1 auto;
  min-width: 0;
}

.quick-action-result-command {
  display: block;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  cursor: default;
  color: var(--el-text-color-regular);
  font-size: 12px;
  line-height: 1.5;
}

.quick-action-result-output {
  min-height: 220px;
  max-height: 52vh;
  overflow: auto;
  margin: 0;
  padding: 14px;
  border: 1px solid var(--el-border-color);
  border-radius: 6px;
  background: var(--el-fill-color-light);
  white-space: pre-wrap;
  word-break: break-word;
  font-family: var(--el-font-family-monospace, ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace);
}
</style>


<style>
.quick-actions-overlay .el-overlay-dialog {
  overflow: hidden !important;
}

.quick-actions-overlay .el-dialog {
  width: 920px !important;
  max-width: calc(100vw - 32px) !important;
  height: 640px !important;
  max-height: calc(100vh - 12vh) !important;
  margin-top: 6vh !important;
  display: flex !important;
  flex-direction: column !important;
  overflow: hidden !important;
}

.quick-actions-overlay .el-dialog__header,
.quick-actions-overlay .el-dialog__footer {
  flex: 0 0 auto !important;
}

.quick-actions-overlay .el-dialog__body {
  flex: 1 1 auto !important;
  min-height: 0 !important;
  overflow: hidden !important;
  padding-top: 12px !important;
  padding-bottom: 12px !important;
}

.quick-actions-overlay .fixed-dialog-body,
.quick-actions-overlay .quick-actions-table-shell,
.quick-actions-overlay .quick-actions-table,
.quick-actions-overlay .quick-actions-table .el-table__inner-wrapper,
.quick-actions-overlay .quick-actions-table .el-scrollbar,
.quick-actions-overlay .quick-actions-table .el-scrollbar__wrap {
  min-height: 0 !important;
}

.quick-actions-overlay .quick-actions-table,
.quick-actions-overlay .quick-actions-table .el-table__inner-wrapper,
.quick-actions-overlay .quick-actions-table .el-scrollbar,
.quick-actions-overlay .quick-actions-table .el-scrollbar__wrap {
  height: 100% !important;
}

.quick-actions-overlay .quick-actions-table .el-scrollbar__wrap {
  overflow-y: auto !important;
  overflow-x: auto !important;
}

.quick-actions-command-tooltip {
  max-width: min(680px, calc(100vw - 48px));
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  font-family: var(--el-font-family-monospace, ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace);
}

@media (max-width: 768px), (max-height: 720px) {
  .quick-actions-overlay .el-dialog {
    width: 100vw !important;
    max-width: 100vw !important;
    height: 100vh !important;
    max-height: 100vh !important;
    margin: 0 !important;
    border-radius: 0 !important;
  }
}
</style>
