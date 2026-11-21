<template>
  <el-dialog
    v-model="visible"
    :title="title"
    append-to-body
    width="980px"
    top="8vh"
    class="fixed-dialog terminal-json-dialog rch-result-detail-fullscreen"
  >
    <div class="terminal-json-wrap">
      <div class="terminal-json-toolbar">
        <div class="terminal-json-toolbar-left">
          <el-button
            size="small"
            @click="copyTerminalJsonRaw"
          >
            Copy Raw
          </el-button>



          <el-button
            v-if="canRunAgain"
            size="small"
            :loading="refreshRunning"
            :disabled="!!actionRun"
            @click="runAgain"
          >
            Run Again
          </el-button>

          <el-button
            v-if="hasTerminalJsonRenderView"
            size="small"
            @click="toggleTerminalJsonViewMode"
          >
            {{ isTerminalJsonRawView ? 'Render View' : 'Raw View' }}
          </el-button>

                  <el-button
            v-if="displayMode === 'table' && !isTerminalJsonRawView"
            size="small"
            @click="tableViewMode = tableViewMode === 'card' ? 'table' : 'card'"
          >
            {{ tableViewMode === 'card' ? 'Table View' : 'Card View' }}
          </el-button>

          <el-button
            size="small"
            type="primary"
            :loading="savingJsonArtifact"
            @click="saveTerminalJsonToArtifact"
          >
            Save to Artifact
          </el-button>
        </div>

        <div class="terminal-json-toolbar-right">
          <template v-if="displayMode === 'table' && !isTerminalJsonRawView">
            <el-input
              v-model="tableSearchText"
              class="terminal-json-search"
              size="small"
              clearable
              placeholder="Search text"
            />

            <el-tag
              size="small"
              type="info"
            >
              {{ filteredTableRows.length }} / {{ tableRows.length }} rows
            </el-tag>
          </template>
        </div>
      </div>

      <template v-if="displayMode === 'table' && !isTerminalJsonRawView && tableViewMode === 'card'">
        <div class="terminal-json-scroll terminal-json-cards">
          <el-card v-for="(row, index) in visibleTableRows" :key="index" class="terminal-json-card" shadow="never">
            <template #header>
              <strong>{{ cardTitle(row, index) }}</strong>
            </template>
            <div v-for="column in tableColumns.filter(column => column.prop !== resultView.titleField)"
                 :key="column.prop" class="terminal-json-card-field">
              <span>{{ column.label }}</span><span>{{ row[column.prop] }}</span>
            </div>
            <details v-if="resultView.details.length" class="terminal-json-details">
              <summary>Details</summary>
              <div v-for="field in resultView.details" :key="field" class="terminal-json-card-field">
                <span>{{ field }}</span><span>{{ row[field] }}</span>
              </div>
            </details>
            <div v-if="getTerminalJsonRowActions(row).length" class="terminal-json-row-actions">
              <el-button v-for="(action, actionIndex) in getTerminalJsonRowActions(row).slice(0, 2)"
                         :key="actionIndex" size="small" @click.stop="confirmTableAction(action)">
                {{ action.label }}
              </el-button>
              <el-dropdown v-if="getTerminalJsonRowActions(row).length > 2" trigger="click" @command="actionIndex => confirmTableAction(getTerminalJsonRowActions(row)[actionIndex])">
                <el-button size="small" @click.stop>More</el-button>
                <template #dropdown><el-dropdown-menu>
                  <el-dropdown-item v-for="(action, actionIndex) in getTerminalJsonRowActions(row).slice(2)"
                                    :key="actionIndex + 2" :command="actionIndex + 2">{{ action.label }}</el-dropdown-item>
                </el-dropdown-menu></template>
              </el-dropdown>
            </div>
          </el-card>
        </div>
      </template>

      <template v-else-if="displayMode === 'table' && !isTerminalJsonRawView">
        <div class="terminal-json-scroll terminal-json-table-scroll">
          <el-table
            :data="visibleTableRows"
            border
            stripe
            style="width: 100%;"
            @sort-change="handleTableSortChange"
          >
            <el-table-column v-if="resultView.details.length" type="expand" width="48">
              <template #default="{ row }">
                <div class="terminal-json-expanded">
                  <div v-for="field in resultView.details" :key="field" class="terminal-json-card-field">
                    <span>{{ field }}</span><span>{{ row[field] }}</span>
                  </div>
                </div>
              </template>
            </el-table-column>
            <el-table-column
              v-for="column in tableColumns"
              :key="column.prop"
              :prop="column.prop"
              :label="column.label"
              :width="column.width || undefined"
              :min-width="column.minWidth || (column.width ? undefined : 140)"
              show-overflow-tooltip
              sortable="custom"
              :sort-orders="['descending', 'ascending', null]"
            />
            <el-table-column
              v-if="tableHasActions"
              label="Actions"
              :min-width="actionColumnWidth"
            >
              <template #default="{ row }">
                <div class="terminal-json-row-actions terminal-json-row-actions-inline">
                  <el-button
                    v-for="(action, index) in getTerminalJsonRowActions(row).slice(0, 2)"
                    :key="index"
                    size="small"
                    @click.stop="confirmTableAction(action)"
                  >
                    {{ action.label }}
                  </el-button>
                  <el-dropdown
                    v-if="getTerminalJsonRowActions(row).length > 2"
                    trigger="click"
                    placement="bottom-start"
                    @command="index => confirmTableAction(getTerminalJsonRowActions(row)[index])"
                  >
                    <el-button size="small" @click.stop>More</el-button>
                    <template #dropdown>
                      <el-dropdown-menu>
                        <el-dropdown-item
                          v-for="(action, index) in getTerminalJsonRowActions(row).slice(2)"
                          :key="index + 2"
                          :command="index + 2"
                        >
                          {{ action.label }}
                        </el-dropdown-item>
                      </el-dropdown-menu>
                    </template>
                  </el-dropdown>
                </div>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </template>

      <template v-else-if="displayMode === 'grouped' && !isTerminalJsonRawView">
        <div class="terminal-json-scroll">
          <div
            v-for="group in groupedSections"
            :key="group.key"
            class="terminal-json-grouped-section"
          >
            <div class="terminal-json-grouped-title">
              {{ group.key }}
            </div>

            <div
              v-for="item in group.items"
              :key="item.key"
              class="terminal-json-grouped-row"
            >
              <div class="terminal-json-grouped-label">
                {{ item.label }}
              </div>

              <div class="terminal-json-grouped-value">
                {{ item.value }}
              </div>
            </div>
          </div>
        </div>
      </template>

      <template v-else-if="displayMode === 'flat' && !isTerminalJsonRawView">
        <div class="terminal-json-scroll">
          <div
            v-for="item in flatRows"
            :key="item.key"
            class="terminal-json-flat-row"
          >
            <div class="terminal-json-flat-label">
              {{ item.label }}
            </div>

            <div class="terminal-json-flat-value">
              {{ item.value }}
            </div>
          </div>
        </div>
      </template>

      <template v-else>
        <div class="terminal-json-scroll">
          <pre class="terminal-json-raw"><code>{{ formattedRawText }}</code></pre>
        </div>
      </template>
    </div>
  </el-dialog>

  <el-dialog
    v-model="resultVisible"
    title="Command Result"
    width="760px"
    append-to-body
  >
    <div class="terminal-json-action-result-meta">
      <el-tag :type="resultStatusType" size="small">{{ activeResult.status }}</el-tag>
      <code class="terminal-json-action-result-command">{{ activeResult.command }}</code>
    </div>
    <pre class="terminal-json-action-result-output">{{ activeResult.output || (activeResult.complete ? '(no output)' : 'Running…') }}</pre>
    <template #footer>
      <el-button :disabled="!activeResult.output" @click="copyResultActionOutput">Copy</el-button>
      <el-button @click="resultVisible = false">Close</el-button>
    </template>
  </el-dialog>
</template>

<script>
import { canRerunTerminalSource } from '../utils/terminalRerun.js'
import { getTerminalReplayAction } from '../utils/terminalOperation.js'
import { h, ref } from 'vue'
import { ElMessage, ElMessageBox, ElRadioGroup, ElRadioButton } from 'element-plus'
import { JSON_ROW_SOURCE, getJsonRenderModel, findJsonOutput, normalizeJsonView, resolveJsonViewRowActions } from '../utils/terminalJson.js'


export default {
  name: 'TerminalJsonDialog',

  props: {
    selectedId: {
      type: [String, Number],
      default: '',
    },

    currentConnection: {
      type: Object,
      default: null,
    },

    machineAliasMap: {
      type: Object,
      default: () => ({}),
    },
  },

  emits: ['save-json-output', 'run-result-action', 'rerun-json'],

  data() {
    return {
      visible: false,
      title: 'JSON Viewer',
      text: '',
      displayMode: 'raw',
      tableColumns: [],
      tableRows: [],
      resultView: { titleField: '', columns: [], details: [], actions: [] },
      tableViewMode: 'table',
      actionConnectionId: '',
      actionTargetName: '',
      actionConfirming: false,
      resultVisible: false,
      activeResult: { runId: '', clientId: '', command: '', output: '', status: 'Running', complete: false, success: false },
      flatRows: [],
      groupedSections: [],
      tableSearchText: '',
      isRawViewVisible: false,
      savingJsonArtifact: false,
      commandInfo: {},
      refreshRunning: false,
      refreshRun: null,
      actionRun: null,
      tableSort: {
        prop: '',
        order: '',
      },
    }
  },

  computed: {
    formattedRawText() {
      return this.formatTerminalJsonRawForDisplay(this.text)
    },

    canRunAgain() {
      const info = this.commandInfo || {}
      return canRerunTerminalSource({ operation: info.operation })
    },

    hasTerminalJsonRenderView() {
      return ['table', 'grouped', 'flat'].includes(this.displayMode)
    },

    isTerminalJsonRawView() {
      return this.displayMode === 'raw' || this.isRawViewVisible
    },

    resultStatusType() {
      if (!this.activeResult.complete) return 'info'
      return this.activeResult.status === 'Partial' ? 'warning' : (this.activeResult.success ? 'success' : 'danger')
    },

    tableHasActions() {
      return this.tableRows.some(row => this.getTerminalJsonRowActions(row).length > 0)
    },

    actionColumnWidth() {
      const count = Math.min(3, Math.max(0, ...this.tableRows.map(row => this.getTerminalJsonRowActions(row).length)))
      return count === 1 ? 108 : count === 2 ? 176 : 248
    },

    filteredTableRows() {
      const rows = Array.isArray(this.tableRows) ? this.tableRows : []
      const keyword = String(this.tableSearchText || '').trim().toLowerCase()

      if (!keyword) {
        return rows
      }

      // table 搜索只做前端行筛选，不改原始 JSON。
      return rows.filter((row) => {
        return [...this.tableColumns, ...this.resultView.details.map(prop => ({ prop }))].some((column) => {
          return String(row[column.prop] ?? '').toLowerCase().includes(keyword)
        })
      })
    },

    visibleTableRows() {
      return this.sortTerminalJsonTableRows(this.filteredTableRows)
    },
  },

  watch: {
    visible(value) {
      if (!value) {
        this.reset()
      }
    },
  },

  methods: {
    open(line) {
      if (!line || !line.isJsonMessage) return

      const jsonText = String(line.jsonText || '').trim()
      this.title = 'JSON Viewer'
      this.commandInfo = this.normalizeTerminalJsonCommandInfo(line.jsonCommandInfo || line.commandInfo || {})
      this.actionConnectionId = String(this.selectedId || '')
      this.actionTargetName = this.resolveResultActionTargetName(this.actionConnectionId)
      this.actionConfirming = false
      this.refreshRunning = false
      this.refreshRun = null
      this.actionRun = null
      this.viewMetadata = line.meta?.resultView || line.jsonView || {}
      this.tableViewMode = typeof window !== 'undefined' && window.matchMedia?.('(max-width: 768px)').matches ? 'card' : 'table'
      this.setTerminalJsonContent(jsonText)
      this.visible = true
    },

    setTerminalJsonContent(jsonText, { preserveTableState = false } = {}) {
      const model = getJsonRenderModel(jsonText, this.viewMetadata)
      this.text = jsonText
      if (!preserveTableState || model.mode !== 'table') {
        this.tableSearchText = ''
        this.tableSort = { prop: '', order: '' }
      }
      this.isRawViewVisible = false

      this.displayMode = model.mode
      this.resultView = normalizeJsonView(this.viewMetadata, model.columns)
      this.tableColumns = model.mode === 'table' ? this.resultView.columns : model.columns
      this.tableRows = model.rows
      this.flatRows = model.flatRows
      this.groupedSections = model.groups

    },

    reset() {
      this.title = 'JSON Viewer'
      this.text = ''
      this.displayMode = 'raw'
      this.tableColumns = []
      this.tableRows = []
      this.viewMetadata = {}
      this.resultView = { titleField: '', columns: [], details: [], actions: [] }
      this.tableViewMode = 'table'
      this.flatRows = []
      this.groupedSections = []
      this.tableSearchText = ''
      this.isRawViewVisible = false
      this.savingJsonArtifact = false
      this.commandInfo = {}
      this.actionConnectionId = ''
      this.actionTargetName = ''
      this.actionConfirming = false
      this.refreshRunning = false
      this.refreshRun = null
      this.actionRun = null
      this.tableSort = {
        prop: '',
        order: '',
      }
    },

    async runAgain() {
      if (!this.visible || this.refreshRunning || this.actionRun || !this.canRunAgain) return
      const clientId = this.actionConnectionId
      if (!clientId || String(this.selectedId || '') !== clientId) {
        ElMessage.warning('The target device has changed')
        return
      }

      const info = this.commandInfo || {}
      const replay = getTerminalReplayAction(info.operation)
      if (!replay) return
      const runId = this.createResultActionRunId()
      this.refreshRun = { runId, clientId, chunks: [], view: null, jsonText: '' }
      this.refreshRunning = true
      this.$emit('rerun-json', {
        runId, clientId,
        ...replay,
        onDone: ok => {
          if (!ok && this.refreshRun?.runId === runId) {
            this.refreshRunning = false
            this.refreshRun = null
            ElMessage.error('Run Again failed to start')
          }
        },
      })
    },

    handleJsonRefreshResult(payload = {}, runId = '') {
      if (!this.refreshRun || !this.visible || this.refreshRun.runId !== runId
          || String(payload.client_id || '') !== this.refreshRun.clientId) return
      this.refreshRun.chunks.push(String(payload.text ?? ''))
      if (payload.result?.data !== undefined) {
        this.refreshRun.jsonText = JSON.stringify(payload.result.data)
        this.refreshRun.view = payload.result.view || null
      }
    },

    handleJsonRefreshComplete(payload = {}, runId = '') {
      if (!this.refreshRun || !this.visible || this.refreshRun.runId !== runId
          || String(payload.client_id || '') !== this.refreshRun.clientId) return
      const chunks = this.refreshRun.chunks
      const updatedView = this.refreshRun.view
      const structuredJson = this.refreshRun.jsonText
      this.refreshRun = null
      this.refreshRunning = false
      const status = String(payload.status || '').trim()
      if (status ? status !== 'success' : payload.success !== true) {
        ElMessage.error('Run Again failed; previous result kept')
        return
      }
      // A rerun is a new Terminal event, not a mutation of the historical output.
      const candidates = [structuredJson, chunks.join(''), chunks.join('\n')]
      const validText = candidates.map(text => findJsonOutput(text)).find(Boolean)
      if (validText === undefined) {
        ElMessage.error('Run Again did not return valid JSON; previous result kept')
        return
      }
      this.viewMetadata = updatedView || {}
      this.setTerminalJsonContent(validText.trim(), { preserveTableState: true })
    },

    getTerminalJsonRowActions(row) {
      return resolveJsonViewRowActions(this.resultView, row?.[JSON_ROW_SOURCE])
    },

    cardTitle(row, index) {
      return (this.resultView.titleField && row?.[this.resultView.titleField]) || `Record ${index + 1}`
    },

    createResultActionRunId() {
      if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
        return crypto.randomUUID()
      }
      return `result-action-${Date.now()}-${Math.random().toString(16).slice(2)}`
    },

    resolveResultActionTargetName(clientId) {
      const connection = this.currentConnection
      if (!connection || String(connection.client_id || '') !== clientId) {
        return clientId || 'Unknown Client'
      }
      const machineId = String(connection.machine_id || '').trim()
      const alias = String(this.machineAliasMap?.[machineId] || '').trim()
      const hostname = String(connection.hostname || '').trim()
      return alias || hostname || clientId || 'Unknown Client'
    },

    async confirmTableAction(action) {
      if (this.actionConfirming || this.actionRun || this.refreshRunning || !action?.command) return
      const clientId = this.actionConnectionId
      if (!clientId || String(this.selectedId || '') !== clientId) {
        ElMessage.warning('The target device has changed')
        return
      }
      this.actionConfirming = true
      const presentation = ref('terminal')
      try {
        // Omitted/invalid confirm values remain safe: only literal false skips the prompt.
        if (action.confirm !== false) {
          await ElMessageBox.confirm(
            h('div', null, [
              h('div', null, [
                'Run the following command on ',
                h('strong', null, this.actionTargetName),
                '?',
              ]),
              h('pre', { style: {
                margin: '8px 0 0', padding: '6px 12px',
                background: '#f5f7fa', border: '1px solid #dcdfe6',
                borderRadius: '6px', color: '#303133',
                fontFamily: 'Monaco, Menlo, Consolas, monospace',
                fontSize: '13px', lineHeight: '1.35',
                whiteSpace: 'pre-wrap', overflowWrap: 'anywhere',
                maxHeight: '45vh', overflowY: 'auto',
              } }, [h('code', null, action.command)]),
              h('div', { style: { marginTop: '12px', marginBottom: '6px' } }, 'Output to'),
              h(() => h(ElRadioGroup, {
                modelValue: presentation.value,
                'onUpdate:modelValue': value => { presentation.value = value },
                size: 'small',
              }, () => [
                h(ElRadioButton, { value: 'terminal', label: 'terminal' }, () => 'Terminal'),
                h(ElRadioButton, { value: 'dialog', label: 'dialog' }, () => 'New Dialog'),
              ])),
            ]),
            'Execute Command',
            { type: 'warning', confirmButtonText: 'Run', cancelButtonText: 'Cancel' },
          )
        }
      } catch (_error) {
        return
      } finally {
        this.actionConfirming = false
      }

      if (!this.visible || String(this.selectedId || '') !== clientId) {
        ElMessage.warning('The target device has changed')
        return
      }
      const outputMode = presentation.value
      const runId = this.createResultActionRunId()
      this.actionRun = { runId, clientId, refresh: action.refresh === true }
      if (outputMode === 'dialog') {
        this.activeResult = {
          runId, clientId, command: action.command,
          output: '', status: 'Running', complete: false, success: false,
        }
        this.resultVisible = true
      }
      // Terminal actions leave the JSON Viewer open, including when refresh is false.
      this.$emit('run-result-action', {
        command: action.command, clientId, presentation: outputMode, runId,
        onDone: (ok) => {
          if (ok || this.actionRun?.runId !== runId) return
          this.actionRun = null
          if (outputMode === 'dialog' && this.activeResult.runId === runId && !this.activeResult.complete) {
            this.activeResult.complete = true
            this.activeResult.status = 'Failed'
            this.activeResult.output = 'Command submission failed'
          }
        },
      })
    },

    handleResultActionCommandResult(payload = {}, runId = '') {
      if (runId !== this.activeResult.runId
          || String(payload.client_id || '') !== this.activeResult.clientId) return true

      const chunk = String(payload.text ?? '').replace(/\r\n/g, '\n').replace(/\r/g, '\n')
      if (chunk) {
        const current = this.activeResult.output
        const separator = current && !current.endsWith('\n') && !chunk.startsWith('\n') ? '\n' : ''
        this.activeResult.output = `${current}${separator}${chunk}`
      }
      return true
    },

    handleResultActionCommandComplete(payload = {}, runId = '') {
      const actionRun = this.actionRun
      if (!actionRun || actionRun.runId !== runId
          || String(payload.client_id || '') !== actionRun.clientId) return true

      const status = String(payload.status || '').trim()
      const success = status ? status === 'success' : payload.success === true
      if (this.activeResult.runId === runId) {
        this.activeResult.complete = true
        this.activeResult.success = success
        this.activeResult.status = status === 'cancelled' || (!status && payload.cancelled) ? 'Cancelled'
          : status === 'partial' ? 'Partial'
          : status === 'timed_out' ? 'Timed out'
          : status === 'interrupted' ? 'Interrupted'
          : success ? 'Success' : 'Failed'
      }
      this.actionRun = null
      if (success && actionRun.refresh && this.visible
          && String(this.selectedId || '') === actionRun.clientId) {
        if (!this.canRunAgain) {
          ElMessage.warning('This JSON result has no replayable source')
        } else {
          // SSE clears the completed task after notifying subscribers. Wait for
          // that state update before submitting the original query again.
          this.$nextTick(() => {
            if (this.visible && String(this.selectedId || '') === actionRun.clientId) {
              void this.runAgain()
            }
          })
        }
      }
      return true
    },

    async copyResultActionOutput() {
      const output = this.activeResult.output
      if (!output) return
      try {
        if (typeof navigator !== 'undefined' && navigator.clipboard?.writeText) {
          await navigator.clipboard.writeText(output)
        } else {
          this.copyTextWithLegacyTextarea(output)
        }
        ElMessage.success('Result copied')
      } catch (error) {
        ElMessage.error(error.message || 'Copy failed')
      }
    },

    formatTerminalJsonRawForDisplay(jsonText) {
      const raw = String(jsonText || '').trim()
      if (!raw) return ''

      try {
        return JSON.stringify(JSON.parse(raw), null, 2)
      } catch (e) {
        return raw
      }
    },

    async copyTerminalJsonRaw() {
      const raw = String(this.text || '')
      if (!raw) return

      try {
        if (typeof navigator !== 'undefined' && navigator.clipboard?.writeText) {
          await navigator.clipboard.writeText(raw)
        } else {
          this.copyTextWithLegacyTextarea(raw)
        }

        ElMessage.success('Raw JSON copied')
      } catch (e) {
        try {
          this.copyTextWithLegacyTextarea(raw)
          ElMessage.success('Raw JSON copied')
        } catch (_error) {
          ElMessage.error('Copy failed')
        }
      }
    },

    toggleTerminalJsonViewMode() {
      if (!this.hasTerminalJsonRenderView) return

      // 可 render 的 JSON 支持 raw/render 视图切换。
      this.isRawViewVisible = !this.isRawViewVisible
    },

    normalizeTerminalJsonCommandInfo(info) {
      const payload = info && typeof info === 'object' ? info : {}
      const commandName = String(payload.command_name || payload.source_command || payload.name || '').trim()
      const commandId = payload.command_id ?? payload.source_command_id ?? null

      return {
        ...payload,
        command_id: commandId,
        source_command_id: commandId,
        command_name: commandName,
        name: commandName,
        source_command: commandName,
      }
    },



    saveTerminalJsonToArtifact() {
  if (this.savingJsonArtifact) return

  const raw = String(this.text || '')
  if (!raw.trim()) {
    ElMessage.warning('No JSON to save')
    return
  }

  this.savingJsonArtifact = true

  this.$emit('save-json-output', {
    content: raw,
    saveContext: this.commandInfo,
    onDone: () => {
      this.savingJsonArtifact = false
    },
  })
},

    copyTextWithLegacyTextarea(text) {
      const textarea = document.createElement('textarea')
      textarea.value = text
      textarea.setAttribute('readonly', 'readonly')
      textarea.style.position = 'fixed'
      textarea.style.left = '-9999px'
      textarea.style.top = '-9999px'
      document.body.appendChild(textarea)
      textarea.select()

      try {
        const copied = document.execCommand('copy')
        if (!copied) {
          throw new Error('copy command failed')
        }
      } finally {
        document.body.removeChild(textarea)
      }
    },

    handleTableSortChange({ prop, order }) {
      this.tableSort = {
        prop: prop || '',
        order: order || '',
      }
    },

    sortTerminalJsonTableRows(rows) {
      const safeRows = Array.isArray(rows) ? rows : []
      const prop = this.tableSort.prop
      const order = this.tableSort.order

      if (!prop || !order) {
        return safeRows
      }

      const direction = order === 'descending' ? -1 : 1

      return safeRows
        .map((row, index) => ({ row, index }))
        .sort((left, right) => {
          const result = this.compareTerminalJsonSortValues(left.row?.[prop], right.row?.[prop])

          if (result === 0) {
            return left.index - right.index
          }

          return result * direction
        })
        .map(item => item.row)
    },

    compareTerminalJsonSortValues(left, right) {
      const leftMeta = this.getTerminalJsonSortMeta(left)
      const rightMeta = this.getTerminalJsonSortMeta(right)

      if (leftMeta.type === 'empty' && rightMeta.type !== 'empty') return 1
      if (leftMeta.type !== 'empty' && rightMeta.type === 'empty') return -1
      if (leftMeta.type === 'empty' && rightMeta.type === 'empty') return 0

      if (leftMeta.type === rightMeta.type) {
        if (leftMeta.type === 'string') {
          return leftMeta.value.localeCompare(rightMeta.value, undefined, {
            sensitivity: 'base',
          })
        }

        if (leftMeta.value < rightMeta.value) return -1
        if (leftMeta.value > rightMeta.value) return 1
        return 0
      }

      return leftMeta.text.localeCompare(rightMeta.text, undefined, {
        sensitivity: 'base',
      })
    },

    getTerminalJsonSortMeta(value) {
      const text = String(value ?? '').trim()

      if (!text) {
        return {
          type: 'empty',
          value: '',
          text,
        }
      }

      if (/^[+-]?(?:\d+\.?\d*|\.\d+)(?:e[+-]?\d+)?$/i.test(text)) {
        return {
          type: 'number',
          value: Number(text),
          text,
        }
      }

      const parsedDate = Date.parse(text)
      if (!Number.isNaN(parsedDate) && this.isTerminalJsonDateLikeString(text)) {
        return {
          type: 'date',
          value: parsedDate,
          text,
        }
      }

      return {
        type: 'string',
        value: text,
        text,
      }
    },

    isTerminalJsonDateLikeString(text) {
      return /^\d{4}[-/]\d{1,2}[-/]\d{1,2}/.test(text)
        || /^\d{1,2}[-/]\d{1,2}[-/]\d{2,4}/.test(text)
        || /^\d{4}-\d{2}-\d{2}T/.test(text)
        || /(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{1,2}/i.test(text)
    },
  },
}
</script>

<style scoped>
.terminal-json-wrap {
  min-height: 220px;
}

.terminal-json-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--line, #ebeef5);
  flex-wrap: wrap;
  gap: 12px;
}

.terminal-json-toolbar-left,
.terminal-json-toolbar-right {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.terminal-json-toolbar-left :deep(.el-button) {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 6px 16px;
  height: 26px;
}

.terminal-json-search {
  width: 240px;
}

/* Desktop keeps direct actions; allow long labels to wrap inside their cell. */
.terminal-json-row-actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  min-width: 0;
  white-space: normal;
}

.terminal-json-row-actions :deep(.el-button) {
  margin-left: 0;
  max-width: 100%;
  height: auto;
  min-height: 24px;
  white-space: normal;
  overflow-wrap: anywhere;
}


.terminal-json-action-result-meta {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}

.terminal-json-action-result-command {
  overflow-wrap: anywhere;
  white-space: pre-wrap;
}

.terminal-json-action-result-output {
  max-height: 55vh;
  min-height: 160px;
  overflow: auto;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  padding: 12px;
  border: 1px solid var(--line, #ebeef5);
  border-radius: 4px;
}

.terminal-json-scroll {
  max-height: 65vh;
  min-width: 0;
  max-width: 100%;
  overflow: auto;
  -webkit-overflow-scrolling: touch;
}

/* Leave the table at container width so Element Plus owns horizontal scrolling. */
.terminal-json-table-scroll {
  width: 100%;
  touch-action: pan-x pan-y;
}

.terminal-json-table-scroll :deep(.el-scrollbar__wrap) {
  -webkit-overflow-scrolling: touch;
  touch-action: pan-x pan-y;
}

/* 与 Artifact Info / Image Info 一致的 section + 双列键值布局。 */
.terminal-json-grouped-section {
  margin-bottom: 20px;
}

.terminal-json-grouped-title {
  font-weight: 600;
  font-size: 14px;
  margin-bottom: 10px;
}

.terminal-json-grouped-row {
  display: grid;
  grid-template-columns: 180px minmax(0, 1fr);
  gap: 12px;
  padding: 8px 0;
  border-bottom: 1px solid #ebeef5;
}

.terminal-json-grouped-label {
  color: #606266;
  font-weight: 400;
  word-break: break-word;
}

.terminal-json-grouped-value {
  min-width: 0;
  word-break: break-word;
  white-space: pre-wrap;
  font-family: Monaco, Menlo, "Ubuntu Mono", Consolas, monospace;
  font-size: 12px;
  line-height: 1.5;
}

.terminal-json-flat-row {
  display: grid;
  grid-template-columns: 220px 1fr;
  gap: 12px;
  padding: 8px 0;
  border-bottom: 1px solid #ebeef5;
}

.terminal-json-flat-label {
  color: #606266;
  font-weight: 500;
  word-break: break-word;
}

.terminal-json-flat-value {
  word-break: break-word;
}

.terminal-json-raw {
  margin: 0;
  padding: 16px;
  white-space: pre-wrap;
  word-break: break-word;
  overflow: auto;
  border: 1px solid var(--line, #dcdfe6);
  border-radius: 12px;
  background: #f8fafc;
  color: #1f2937;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.55);
  font-family: Monaco, Menlo, "Ubuntu Mono", Consolas, monospace;
  font-size: 13px;
  line-height: 1.65;
  tab-size: 2;
}

.terminal-json-raw code {
  font-family: inherit;
}


/* Cards and expanded rows display detail fields from the same raw JSON. */
.terminal-json-cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 270px), 1fr)); gap: 12px; }
.terminal-json-card { min-width: 0; }
.terminal-json-card-field { display: grid; grid-template-columns: minmax(85px, 34%) minmax(0, 1fr); gap: 10px; padding: 6px 0; border-bottom: 1px solid var(--line, #ebeef5); }
.terminal-json-card-field > span { min-width: 0; overflow-wrap: anywhere; white-space: pre-wrap; }
.terminal-json-card-field > span:first-child { color: var(--el-text-color-secondary, #606266); }
.terminal-json-details { margin: 10px 0; }
.terminal-json-details summary { cursor: pointer; }
.terminal-json-expanded { padding: 8px 20px; }
.terminal-json-card .terminal-json-row-actions { margin-top: 12px; }

@media (max-width: 768px), (max-height: 720px) {
  .terminal-json-toolbar {
    flex-direction: column;
    align-items: flex-start;
    margin-bottom: 10px;
    padding-bottom: 10px;
  }

  .terminal-json-toolbar-left,
  .terminal-json-toolbar-right,
  .terminal-json-search {
    width: 100%;
  }
}
</style>