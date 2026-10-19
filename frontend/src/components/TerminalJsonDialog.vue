<template>
  <el-dialog
    v-model="visible"
    :title="title"
    width="980px"
    top="8vh"
    class="fixed-dialog"
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
            v-if="hasTerminalJsonRenderView"
            size="small"
            @click="toggleTerminalJsonViewMode"
          >
            {{ isTerminalJsonRawView ? 'Render View' : 'Raw View' }}
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

      <template v-if="displayMode === 'table' && !isTerminalJsonRawView">
        <div class="terminal-json-scroll terminal-json-table-scroll">
          <el-table
            :data="visibleTableRows"
            border
            stripe
            style="width: 100%;"
            @sort-change="handleTableSortChange"
          >
            <el-table-column
              v-for="column in tableColumns"
              :key="column.prop"
              :prop="column.prop"
              :label="column.label"
              min-width="140"
              show-overflow-tooltip
              sortable="custom"
              :sort-orders="['descending', 'ascending', null]"
            />
            <el-table-column
              v-if="tableHasActions"
              label="Actions"
              min-width="180"
            >
              <template #default="{ row }">
                <template v-if="getTerminalJsonRowActions(row).length <= 2">
                  <el-button
                    v-for="(action, index) in getTerminalJsonRowActions(row)"
                    :key="index"
                    size="small"
                    @click.stop="confirmTableAction(action)"
                  >
                    {{ action.label }}
                  </el-button>
                </template>
                <el-dropdown
                  v-else
                  trigger="click"
                  placement="bottom-start"
                  @command="index => confirmTableAction(getTerminalJsonRowActions(row)[index])"
                >
                  <el-button size="small" @click.stop>More</el-button>
                  <template #dropdown>
                    <el-dropdown-menu>
                      <el-dropdown-item
                        v-for="(action, index) in getTerminalJsonRowActions(row)"
                        :key="index"
                        :command="index"
                      >
                        {{ action.label }}
                      </el-dropdown-item>
                    </el-dropdown-menu>
                  </template>
                </el-dropdown>
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
</template>

<script>
import { h } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

const RESULT_ACTIONS = Symbol('terminalJsonRowActions')

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
  },

  emits: ['save-json-output', 'run-result-action'],

  data() {
    return {
      visible: false,
      title: 'JSON Viewer',
      text: '',
      displayMode: 'raw',
      tableColumns: [],
      tableRows: [],
      actionConnectionId: '',
      actionConfirming: false,
      flatRows: [],
      groupedSections: [],
      tableSearchText: '',
      isRawViewVisible: false,
      savingJsonArtifact: false,
      commandInfo: {},
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

    hasTerminalJsonRenderView() {
      return ['table', 'grouped', 'flat'].includes(this.displayMode)
    },

    isTerminalJsonRawView() {
      return this.displayMode === 'raw' || this.isRawViewVisible
    },

    tableHasActions() {
      return this.tableRows.some(row => this.getTerminalJsonRowActions(row).length > 0)
    },

    filteredTableRows() {
      const rows = Array.isArray(this.tableRows) ? this.tableRows : []
      const keyword = String(this.tableSearchText || '').trim().toLowerCase()

      if (!keyword) {
        return rows
      }

      // table 搜索只做前端行筛选，不改原始 JSON。
      return rows.filter((row) => {
        return this.tableColumns.some((column) => {
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
      const tableModel = this.tryBuildTerminalJsonTableModel(jsonText)
      const groupedModel = tableModel ? null : this.tryBuildTerminalJsonGroupedModel(jsonText)
      const flatModel = tableModel || groupedModel ? null : this.tryBuildTerminalJsonFlatModel(jsonText)

      this.title = 'JSON Viewer'
      this.text = jsonText
      this.commandInfo = this.normalizeTerminalJsonCommandInfo(line.jsonCommandInfo || line.commandInfo || {})
      this.actionConnectionId = String(this.selectedId || '')
      this.actionConfirming = false
      this.tableSearchText = ''
      this.isRawViewVisible = false
      this.savingJsonArtifact = false
      this.tableSort = {
        prop: '',
        order: '',
      }

      if (tableModel) {
        this.displayMode = 'table'
        this.tableColumns = tableModel.columns
        this.tableRows = tableModel.rows
        this.flatRows = []
        this.groupedSections = []
      } else if (groupedModel) {
        this.displayMode = 'grouped'
        this.tableColumns = []
        this.tableRows = []
        this.flatRows = []
        this.groupedSections = groupedModel
      } else if (flatModel) {
        this.displayMode = 'flat'
        this.tableColumns = []
        this.tableRows = []
        this.flatRows = flatModel
        this.groupedSections = []
      } else {
        this.displayMode = 'raw'
        this.tableColumns = []
        this.tableRows = []
        this.flatRows = []
        this.groupedSections = []
      }

      this.visible = true
    },

    reset() {
      this.title = 'JSON Viewer'
      this.text = ''
      this.displayMode = 'raw'
      this.tableColumns = []
      this.tableRows = []
      this.flatRows = []
      this.groupedSections = []
      this.tableSearchText = ''
      this.isRawViewVisible = false
      this.savingJsonArtifact = false
      this.commandInfo = {}
      this.actionConnectionId = ''
      this.actionConfirming = false
      this.tableSort = {
        prop: '',
        order: '',
      }
    },

    isTerminalJsonPlainObject(value) {
      return !!value && typeof value === 'object' && !Array.isArray(value)
    },

    tryBuildTerminalJsonTableModel(jsonText) {
      const raw = String(jsonText || '').trim()
      if (!raw) return null

      let parsed
      try {
        parsed = JSON.parse(raw)
      } catch (e) {
        return null
      }

      if (!Array.isArray(parsed) || !parsed.length) {
        return null
      }

      if (!parsed.every(item => this.isTerminalJsonPlainObject(item))) {
        return null
      }

      // _actions 是可选的每行元数据，不参与原表格字段一致性比较。
      const firstKeys = Object.keys(parsed[0]).filter(key => key !== '_actions')
      if (!firstKeys.length) {
        return null
      }

      const sortedFirstKeys = [...firstKeys].sort()

      const hasSameStructure = parsed.every((item) => {
        const keys = Object.keys(item).filter(key => key !== '_actions')
        if (keys.length !== firstKeys.length) return false

        const sortedKeys = [...keys].sort()
        for (let i = 0; i < sortedFirstKeys.length; i += 1) {
          if (sortedKeys[i] !== sortedFirstKeys[i]) return false
        }

        return true
      })

      if (!hasSameStructure) {
        return null
      }

      return {
        columns: firstKeys.map((key) => ({
          prop: key,
          label: key,
        })),

        rows: parsed.map((item) => {
          const row = {}

          firstKeys.forEach((key) => {
            const value = item[key]

            if (value === null || value === undefined) {
              row[key] = ''
            } else if (typeof value === 'object') {
              row[key] = JSON.stringify(value)
            } else {
              row[key] = String(value)
            }
          })

          Object.defineProperty(row, RESULT_ACTIONS, {
            value: this.normalizeTerminalJsonRowActions(item._actions),
            configurable: true,
          })
          return row
        }),
      }
    },

    getTerminalJsonRowActions(row) {
      return row?.[RESULT_ACTIONS] || []
    },

    normalizeTerminalJsonRowActions(actions) {
      if (!Array.isArray(actions)) return []
      return actions.flatMap((action) => {
        if (!this.isTerminalJsonPlainObject(action)) return []
        const label = typeof action.label === 'string' ? action.label.trim() : ''
        const command = typeof action.command === 'string' ? action.command.trim() : ''
        return label && command ? [{ label, command }] : []
      })
    },

    async confirmTableAction(action) {
      if (this.actionConfirming || !action?.command) return
      this.actionConfirming = true
      const clientId = this.actionConnectionId
      try {
        await ElMessageBox.confirm(
          h('div', null, [
            h('div', null, `Client: ${clientId || 'Not selected'}`),
            h('pre', { style: {
              whiteSpace: 'pre-wrap', overflowWrap: 'anywhere',
              maxHeight: '45vh', overflowY: 'auto',
            } }, action.command),
          ]),
          'Execute command?',
          { type: 'warning', confirmButtonText: 'Run', cancelButtonText: 'Cancel' },
        )
      } catch (_error) {
        return
      } finally {
        this.actionConfirming = false
      }
      this.$emit('run-result-action', { command: action.command, clientId })
      this.visible = false
    },

    tryBuildTerminalJsonGroupedModel(jsonText) {
      const raw = String(jsonText || '').trim()
      if (!raw) return null

      let parsed
      try {
        parsed = JSON.parse(raw)
      } catch (e) {
        return null
      }

      if (!this.isTerminalJsonPlainObject(parsed)) return null

      const keys = Object.keys(parsed)
      // Grouped 只接受多个外层分组，且每个分组必须是非空对象。
      if (keys.length < 2 || !keys.every(key => this.isTerminalJsonPlainObject(parsed[key]) && Object.keys(parsed[key]).length > 0)) {
        return null
      }

      return keys.map(key => ({
        key,
        items: Object.keys(parsed[key]).map(itemKey => ({
          key: itemKey,
          label: itemKey,
          // 内层值保持单行；对象和数组仅序列化，不继续展开。
          value: this.formatTerminalJsonFlatValue(parsed[key][itemKey]),
        })),
      }))
    },

    tryBuildTerminalJsonFlatModel(jsonText) {
      const raw = String(jsonText || '').trim()
      if (!raw) return null

      let parsed
      try {
        parsed = JSON.parse(raw)
      } catch (e) {
        return null
      }

      if (!this.isTerminalJsonPlainObject(parsed)) {
        return null
      }

      return Object.keys(parsed).map((key) => ({
        key,
        label: key,
        value: this.formatTerminalJsonFlatValue(parsed[key]),
      }))
    },

    formatTerminalJsonFlatValue(value) {
      if (value === null || value === undefined) {
        return ''
      }

      if (typeof value === 'object') {
        try {
          return JSON.stringify(value)
        } catch (e) {
          return String(value)
        }
      }

      return String(value)
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
        category: String(payload.category || 'command_output').trim() || 'command_output',
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

.terminal-json-scroll {
  max-height: 65vh;
  overflow: auto;
}

/* JSON table 横向内容超出时才显示滚动条。 */
.terminal-json-table-scroll :deep(.el-table) {
  min-width: max-content;
}

.terminal-json-table-scroll :deep(.el-table__inner-wrapper),
.terminal-json-table-scroll :deep(.el-table__header-wrapper),
.terminal-json-table-scroll :deep(.el-table__body-wrapper) {
  min-width: max-content;
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