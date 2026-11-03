<template>
  <el-dialog
      v-model="visible"
      title="Agent Outputs"
      width="1320px"
      top="4vh"
      class="fixed-dialog agent-outputs-dialog"
      modal-class="agent-outputs-overlay"
  >
    <div class="fixed-dialog-body agent-outputs-body">
      <div class="agent-outputs-toolbar">
        <div class="agent-outputs-toolbar-left">
          <el-button
              type="primary"
              plain
              class="toolbar-btn"
              size="small"
              @click="$emit('open-builder')"
          >
            Build Agent
          </el-button>

          <el-button
              class="toolbar-btn"
              size="small"
              :loading="loading"
              @click="loadAgentOutputs"
          >
            Refresh
          </el-button>

          <el-button
              class="toolbar-btn"
              size="small"
              type="danger"
              plain
              :disabled="!selectedOutputFileNames.length"
              :loading="bulkDeleting"
              @click="deleteSelectedAgentOutputs"
          >
            Delete{{ selectedOutputFileNames.length ? ` (${selectedOutputFileNames.length})` : '' }}
          </el-button>
        </div>

        <div class="agent-outputs-toolbar-right">
          <el-select
              v-model="outputBuilderFilter"
              class="agent-output-builder-filter"
              clearable
              filterable
              size="small"
              placeholder="Filter builder"
          >
            <el-option
                v-for="builder in builderOptions"
                :key="builder"
                :label="builder"
                :value="builder"
            />
          </el-select>

          <span class="agent-outputs-count">
            {{ outputCountText }}
          </span>
        </div>
      </div>

      <div class="agent-outputs-table-wrap">
        <el-table
            ref="agentOutputsTableRef"
            :data="filteredOutputs"
            v-loading="loading"
            stripe
            border
            height="100%"
            table-layout="fixed"
            row-key="file_name"
            class="dialog-table-shell"
            empty-text="No agent outputs"
            @selection-change="handleOutputSelectionChange"
        >
          <el-table-column
              type="selection"
              width="46"
              align="center"
          />

          <el-table-column
              label="Filename"
              min-width="340"
          >
            <template #default="{ row }">
              <div class="agent-output-file-cell">
                <div
                    class="agent-output-file-name"
                    :title="row.file_name"
                >
                  {{ row.file_name || '-' }}
                </div>
              </div>
            </template>
          </el-table-column>

          <el-table-column
              label="Builder"
              min-width="70"
          >
            <template #default="{ row }">
              {{ row.builder || '-' }}
            </template>
          </el-table-column>

          <el-table-column
              label="OS"
              min-width="70"
          >
            <template #default="{ row }">
              <!--              <el-tag-->
              <!--                size="small"-->
              <!--                effect="plain"-->
              <!--              >-->
              {{ describeAgentTargetOs(row.target_os) }}
              <!--              </el-tag>-->
            </template>
          </el-table-column>

          <el-table-column
              label="Size"
              min-width="80"
              align="center"
          >
            <template #default="{ row }">
              <span>{{ formatOutputBytes(row.size) }}</span>
            </template>
          </el-table-column>

          <el-table-column
              label="Actions"
              width="160"
              align="center"
              fixed="right"
          >
            <template #default="{ row }">
              <div class="agent-output-actions">
                <el-tooltip
                    content="Download"
                    placement="top"
                >
                  <el-button
                      size="small"
                      type="primary"
                      circle
                      plain
                      title="Download"
                      aria-label="Download"
                      :disabled="!row.download_url"
                      @click="downloadAgentOutput(row)"
                  >
                    <el-icon>
                      <DownloadIcon/>
                    </el-icon>
                  </el-button>
                </el-tooltip>

                <el-tooltip
                    content="Delete"
                    placement="top"
                >
                  <el-button
                      size="small"
                      type="danger"
                      circle
                      plain
                      title="Delete"
                      aria-label="Delete"
                      :loading="isAgentOutputDeleting(row.file_name)"
                      :disabled="isAgentOutputDeleting(row.file_name)"
                      @click="deleteAgentOutput(row)"
                  >
                    <el-icon>
                      <DeleteIcon/>
                    </el-icon>
                  </el-button>
                </el-tooltip>

                <el-dropdown
                    trigger="click"
                    placement="bottom-end"
                    @command="command => handleAgentOutputMoreCommand(command, row)"
                >
                  <el-button
                      size="small"
                      circle
                      plain
                      title="More"
                      aria-label="More"
                  >
                    <el-icon>
                      <MoreFilledIcon/>
                    </el-icon>
                  </el-button>

                  <template #dropdown>
                    <el-dropdown-menu>
                      <el-dropdown-item command="info">
                        Info
                      </el-dropdown-item>
                    </el-dropdown-menu>
                  </template>
                </el-dropdown>
              </div>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <div class="agent-outputs-mobile-wrap">
        <div
            class="agent-outputs-mobile-list"
            v-loading="loading"
        >
          <div
              v-if="!filteredOutputs.length && !loading"
              class="agent-outputs-empty"
          >
            No agent outputs
          </div>

          <div
              v-else
              class="agent-outputs-mobile-grid"
          >
            <div
                v-for="row in filteredOutputs"
                :key="row.file_name"
                class="agent-output-mobile-card"
            >
              <div class="agent-output-mobile-checkbox">
                <el-checkbox
                    :model-value="isAgentOutputSelected(row)"
                    @change="checked => toggleAgentOutputSelection(row, checked)"
                />
              </div>

              <div class="agent-output-mobile-top">
                <div class="agent-output-mobile-icon">
                  📦
                </div>

                <div class="agent-output-mobile-main">
                  <div
                      class="agent-output-mobile-name"
                      :title="row.file_name"
                  >
                    {{ row.file_name || '-' }}
                  </div>

                  <div class="agent-output-mobile-tags">
                    <el-tag size="small">
                      {{ row.builder || '-' }}
                    </el-tag>

                    <el-tag
                        v-if="String(row.builder || '').trim().toLowerCase() !== 'bundle'"
                        size="small"
                        type="info"
                        effect="plain"
                    >
                      {{ describeAgentTargetOs(row.target_os) }} / {{ row.target_arch || '-' }}
                    </el-tag>
                  </div>

                  <div class="agent-output-mobile-meta">
                    <div class="agent-output-mobile-meta-item">
                      <div class="agent-output-mobile-meta-label">Version</div>
                      <div class="agent-output-mobile-meta-value">
                        {{ row.build_version || '-' }}
                      </div>
                    </div>

                    <div class="agent-output-mobile-meta-item">
                      <div class="agent-output-mobile-meta-label">Build Time</div>
                      <div class="agent-output-mobile-meta-value">
                        {{ formatOutputDateTime(row.build_time) }}
                      </div>
                    </div>

                    <div class="agent-output-mobile-meta-item">
                      <div class="agent-output-mobile-meta-label">Size</div>
                      <div class="agent-output-mobile-meta-value">
                        {{ formatOutputBytes(row.size) }}
                      </div>
                    </div>
                  </div>

                  <div class="agent-output-mobile-actions">
                    <div class="agent-output-mobile-action-item">
                      <el-button
                          size="small"
                          type="primary"
                          plain
                          :disabled="!row.download_url"
                          @click="downloadAgentOutput(row)"
                      >
                        Download
                      </el-button>
                    </div>

                    <div class="agent-output-mobile-action-item">
                      <el-button
                          size="small"
                          type="danger"
                          plain
                          :loading="isAgentOutputDeleting(row.file_name)"
                          :disabled="isAgentOutputDeleting(row.file_name)"
                          @click="deleteAgentOutput(row)"
                      >
                        Delete
                      </el-button>
                    </div>

                    <div class="agent-output-mobile-action-item">
                      <el-dropdown
                          trigger="click"
                          placement="bottom-end"
                          class="agent-output-mobile-more-dropdown"
                          @command="command => handleAgentOutputMoreCommand(command, row)"
                      >
                        <el-button
                            size="small"
                            plain
                            class="agent-output-mobile-more-button"
                        >
                          <el-icon>
                            <MoreFilledIcon/>
                          </el-icon>
                          More
                        </el-button>

                        <template #dropdown>
                          <el-dropdown-menu>
                            <el-dropdown-item command="info">
                              Info
                            </el-dropdown-item>
                          </el-dropdown-menu>
                        </template>
                      </el-dropdown>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </el-dialog>

  <el-dialog
      v-model="agentOutputInfoDialogVisible"
      title="Agent Output Info"
      width="760px"
      top="8vh"
      class="fixed-dialog agent-output-info-dialog"
  >
    <div class="agent-output-info-body">
      <template v-if="agentOutputInfoItem">
        <div
            v-for="item in formattedAgentOutputInfoRows"
            :key="item.key"
            class="agent-output-info-row"
        >
          <div class="agent-output-info-label">
            {{ item.label }}
          </div>

          <div
              class="agent-output-info-value"
              :class="{ 'agent-output-mono': item.mono }"
          >
            {{ item.value }}
          </div>
        </div>
      </template>

      <el-empty
          v-else
          description="No agent output info available"
      />
    </div>
  </el-dialog>
</template>

<script>
import {ElMessage, ElMessageBox} from 'element-plus'
import {Delete, Download, MoreFilled} from '@element-plus/icons-vue'
import {formatBytes, formatDateTimeStandard} from '../utils/formatters.js'
import { listAgentOutputs, deleteAgentOutput } from '../api/agentApi.js'

export default {
  name: 'AgentOutputsDialog',

  components: {
    DeleteIcon: Delete,
    DownloadIcon: Download,
    MoreFilledIcon: MoreFilled,
  },

  props: {
    // formatDateTimeStandard: {
    //   type: Function,
    //   default: null,
    // },
    //
    // formatBytes: {
    //   type: Function,
    //   default: null,
    // },
  },

  emits: [
    'open-builder',
  ],

  data() {
    return {
      visible: false,
      loading: false,
      outputs: [],
      outputBuilderFilter: '',
      selectedOutputFileNames: [],
      bulkDeleting: false,
      agentOutputsDeleting: {},
      agentOutputInfoDialogVisible: false,
      agentOutputInfoItem: null,
    }
  },

  computed: {
    builderOptions() {
      const builders = new Set()
      ;(this.outputs || []).forEach(item => {
        const builder = String(item?.builder || '').trim()
        if (builder) builders.add(builder)
      })
      return Array.from(builders).sort((a, b) => a.localeCompare(b))
    },

    filteredOutputs() {
      const builder = String(this.outputBuilderFilter || '').trim()
      if (!builder) return this.outputs || []
      return (this.outputs || []).filter(item => String(item?.builder || '').trim() === builder)
    },

    selectedOutputs() {
      const selected = new Set(this.selectedOutputFileNames)
      return (this.outputs || []).filter(item => selected.has(String(item?.file_name || '').trim()))
    },

    outputCountText() {
      const count = this.filteredOutputs.length
      const total = this.outputs.length
      const base = `${count} ${count === 1 ? 'output' : 'outputs'}`
      return count === total ? base : `${base} / ${total} total`
    },

    formattedAgentOutputInfoRows() {
      const row = this.agentOutputInfoItem || {}
      const rows = [
        {
          key: 'file_name',
          label: 'Filename',
          value: row.file_name || '-',
        },

        {
          key: 'builder',
          label: 'Builder',
          value: row.builder || '-',
        },

        {
          key: 'build_version',
          label: 'Version',
          value: row.build_version || '-',
        },
        {
          key: 'target_os',
          label: 'OS',
          value: row.target_os || '-',
        },
        {
          key: 'target_arch',
          label: 'Arch',
          value: row.target_arch || '-',
        },
        {
          key: 'source',
          label: 'Source',
          value: this.formatAgentSourceText(row.source),
        },
        {
          key: 'socket',
          label: 'Socket',
          value: this.formatAgentListenerText(row),
          mono: true,
        },
        {
          key: 'web',
          label: 'Web',
          value: this.formatAgentWebListenerText(row),
          mono: true,
        },
        {
          key: 'build_time',
          label: 'Build Time',
          value: this.formatOutputDateTime(row.build_time),
        },
        {
          key: 'size',
          label: 'Size',
          value: this.formatOutputBytes(row.size),
        },
      ]

      return rows.map(item => ({
        ...item,
        value: this.formatAgentOutputInfoValue(item.value),
      }))
    },
  },

  methods: {
    async open() {
      this.visible = true
      await this.loadAgentOutputs()
    },

    isOpen() {
      return this.visible
    },

    async refreshIfOpen(options = {}) {
      if (!this.visible) return
      await this.loadAgentOutputs(options)
    },

    describeAgentTargetOs(targetOs) {
      const mapping = {
        win: 'Windows',
        mac: 'macOS',
        linux: 'Linux',
        bundle: '-',
      }

      return mapping[targetOs] || targetOs || 'macOS'
    },

    formatAgentSourceText(value) {
      const source = String(value || '').trim()
      if (!source) return '-'

      const mapping = {
        manual: 'Manual',
        update: 'Update',
        loader: 'Loader',
      }

      return mapping[source] || source
    },

    formatAgentListenerText(row) {
      const host = String(row?.server_host || '').trim()
      const port = Number(row?.server_port || 0)
      if (!host || !port) return '-'
      return `${host}:${port}`
    },

    formatAgentWebListenerText(row) {
      const scheme = String(row?.server_web_scheme || 'http').trim() || 'http'
      const host = String(row?.server_web_host || row?.server_host || '').trim()
      const port = Number(row?.web_port || 0)
      if (!host || !port) return '-'
      return `${scheme}://${host}:${port}`
    },

    formatOutputDateTime(value) {
      return formatDateTimeStandard(value)
    },

    formatOutputBytes(value) {
      return formatBytes(value)
    },

    formatAgentOutputInfoValue(value) {
      if (value === null || value === undefined || value === '') return '-'
      if (Array.isArray(value)) return value.length ? value.join(', ') : '-'

      if (typeof value === 'object') {
        try {
          return JSON.stringify(value)
        } catch (_e) {
          return String(value)
        }
      }

      return String(value)
    },

    getAgentOutputFileName(row) {
      return String(row?.file_name || '').trim()
    },

    handleAgentOutputMoreCommand(command, row) {
      if (command === 'info') {
        this.openAgentOutputInfo(row)
      }
    },

    openAgentOutputInfo(row) {
      this.agentOutputInfoItem = row || null
      this.agentOutputInfoDialogVisible = true
    },

    downloadAgentOutput(row) {
      const url = String(row?.download_url || '').trim()
      if (!url) {
        ElMessage.warning('Download URL unavailable')
        return
      }

      window.open(url, '_blank', 'noopener,noreferrer')
    },

    isAgentOutputSelected(row) {
      const fileName = this.getAgentOutputFileName(row)
      return Boolean(fileName && this.selectedOutputFileNames.includes(fileName))
    },

    toggleAgentOutputSelection(row, checked) {
      const fileName = this.getAgentOutputFileName(row)
      if (!fileName) return

      if (checked) {
        if (!this.selectedOutputFileNames.includes(fileName)) {
          this.selectedOutputFileNames = [...this.selectedOutputFileNames, fileName]
        }
        return
      }

      this.selectedOutputFileNames = this.selectedOutputFileNames.filter(item => item !== fileName)
    },

    handleOutputSelectionChange(rows) {
      this.selectedOutputFileNames = (rows || [])
          .map(item => String(item?.file_name || '').trim())
          .filter(Boolean)
    },

    pruneOutputSelection() {
      const available = new Set(
          (this.outputs || [])
              .map(item => String(item?.file_name || '').trim())
              .filter(Boolean)
      )
      this.selectedOutputFileNames = this.selectedOutputFileNames.filter(item => available.has(item))
    },

    isAgentOutputDeleting(fileName) {
      return Boolean(this.agentOutputsDeleting[String(fileName || '').trim()])
    },

    async loadAgentOutputs({silent = false} = {}) {
      if (!silent) this.loading = true

      try {
        const res = await listAgentOutputs()
        const json = await res.json()

        if (!res.ok || json.code !== 0) {
          throw new Error(json.message || 'Failed to load agent outputs')
        }

        this.outputs = Array.isArray(json.data) ? json.data : []
        this.pruneOutputSelection()
      } catch (e) {
        this.outputs = []

        if (!silent) {
          ElMessage.error(e.message || 'Failed to load agent outputs')
        }
      } finally {
        if (!silent) this.loading = false
      }
    },

    async requestDeleteAgentOutput(fileName) {
      const normalized = String(fileName || '').trim()
      if (!normalized) throw new Error('Invalid file name')

      const res = await deleteAgentOutput(normalized)
      const json = await res.json()

      if (!res.ok || json.code !== 0) {
        throw new Error(json.message || 'Delete failed')
      }

      return json.data || {}
    },

    async deleteAgentOutput(row) {
      const fileName = String(row?.file_name || '').trim()
      if (!fileName || this.isAgentOutputDeleting(fileName)) return

      try {
        await ElMessageBox.confirm(
            `Delete agent output ${fileName}?`,
            'Delete agent output',
            {
              confirmButtonText: 'Delete',
              cancelButtonText: 'Cancel',
              type: 'warning',
            }
        )
      } catch (_e) {
        return
      }

      this.agentOutputsDeleting = {
        ...this.agentOutputsDeleting,
        [fileName]: true,
      }

      try {
        await this.requestDeleteAgentOutput(fileName)
        this.outputs = this.outputs.filter(item => String(item?.file_name || '').trim() !== fileName)
        this.selectedOutputFileNames = this.selectedOutputFileNames.filter(item => item !== fileName)
        if (this.getAgentOutputFileName(this.agentOutputInfoItem) === fileName) {
          this.agentOutputInfoDialogVisible = false
          this.agentOutputInfoItem = null
        }
        ElMessage.success('Deleted')
      } catch (e) {
        ElMessage.error(e.message || 'Delete failed')
      } finally {
        this.agentOutputsDeleting = {
          ...this.agentOutputsDeleting,
          [fileName]: false,
        }
      }
    },

    async deleteSelectedAgentOutputs() {
      const selected = this.selectedOutputs
      if (!selected.length || this.bulkDeleting) return

      try {
        await ElMessageBox.confirm(
            `Delete ${selected.length} selected agent output(s)?`,
            'Delete Selected Agent Outputs',
            {
              confirmButtonText: 'Delete',
              cancelButtonText: 'Cancel',
              type: 'warning',
            }
        )
      } catch (_e) {
        return
      }

      this.bulkDeleting = true
      let deletedCount = 0
      let failedCount = 0
      const deletingMap = {...this.agentOutputsDeleting}

      selected.forEach(item => {
        const fileName = String(item?.file_name || '').trim()
        if (fileName) deletingMap[fileName] = true
      })
      this.agentOutputsDeleting = deletingMap

      try {
        for (const item of selected) {
          const fileName = String(item?.file_name || '').trim()
          if (!fileName) continue

          try {
            await this.requestDeleteAgentOutput(fileName)
            deletedCount += 1
          } catch (_e) {
            failedCount += 1
          } finally {
            this.agentOutputsDeleting = {
              ...this.agentOutputsDeleting,
              [fileName]: false,
            }
          }
        }

        const deletedNames = new Set(selected.map(item => String(item?.file_name || '').trim()).filter(Boolean))
        this.outputs = this.outputs.filter(item => !deletedNames.has(String(item?.file_name || '').trim()))
        this.selectedOutputFileNames = []

        if (this.agentOutputInfoItem && deletedNames.has(this.getAgentOutputFileName(this.agentOutputInfoItem))) {
          this.agentOutputInfoDialogVisible = false
          this.agentOutputInfoItem = null
        }

        if (failedCount) {
          ElMessage.warning(`Deleted ${deletedCount}, failed ${failedCount}`)
        } else {
          ElMessage.success(`Deleted ${deletedCount} item(s)`)
        }
      } finally {
        this.bulkDeleting = false
      }
    },
  },
}
</script>

<style scoped>
.agent-outputs-body {
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
  width: 100%;
  height: 100%;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  box-sizing: border-box;
}

.agent-outputs-toolbar {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  min-width: 0;
  gap: 12px;
  margin-bottom: 12px;
  box-sizing: border-box;
}

.agent-outputs-toolbar-left,
.agent-outputs-toolbar-right {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.agent-outputs-toolbar-left {
  flex: 1 1 auto;
}

.agent-outputs-toolbar-right {
  flex: 0 0 auto;
  justify-content: flex-end;
  margin-left: auto;
}

.agent-outputs-toolbar :deep(.el-button.toolbar-btn) {
  height: 32px;
  min-height: 32px;
  padding: 0 12px;
  border-radius: 10px;
  margin: 0;
}

.agent-output-builder-filter {
  width: 180px;
}

.agent-output-builder-filter :deep(.el-select__wrapper) {
  min-height: 32px;
  height: 32px;
  border-radius: 10px;
}

.agent-outputs-count {
  font-size: 13px;
  color: #667085;
  white-space: nowrap;
}

.agent-outputs-table-wrap {
  flex: 1 1 auto;
  width: 100%;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}

.agent-outputs-table-wrap :deep(.el-table) {
  width: 100% !important;
  height: 100% !important;
}

.agent-outputs-table-wrap :deep(.el-table__body-wrapper) {
  overflow-y: auto !important;
}

.agent-output-file-cell {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
  padding: 2px 0;
}

.agent-output-file-name {
  min-width: 0;
  color: #111827;
  line-height: 1.45;
  word-break: break-all;
}

.agent-output-mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
  font-size: 12px;
  color: #374151;
  word-break: break-all;
}

.agent-output-actions {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding-top: 2px;
}

.agent-output-actions :deep(.el-button) {
  margin: 0;
}

.agent-output-actions .disabled {
  opacity: 0.55;
  pointer-events: none;
}

.agent-outputs-mobile-wrap {
  display: none;
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
}

.agent-outputs-mobile-list {
  width: 100%;
  height: 100%;
  min-height: 0;
  overflow: auto;
}

.agent-outputs-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 180px;
  color: #909399;
  font-size: 14px;
}

.agent-outputs-mobile-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: 12px;
  padding-bottom: 10px;
}

.agent-output-mobile-card {
  position: relative;
  padding: 14px 14px 14px 12px;
  border: 1px solid #ebeef5;
  border-radius: 14px;
  background: #fff;
  box-shadow: 0 8px 22px rgba(15, 23, 42, 0.06);
}

.agent-output-mobile-checkbox {
  position: absolute;
  top: 10px;
  right: 12px;
  z-index: 1;
}

.agent-output-mobile-top {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  min-width: 0;
}

.agent-output-mobile-icon {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border-radius: 12px;
  background: #f5f7fa;
  font-size: 20px;
}

.agent-output-mobile-main {
  flex: 1 1 auto;
  min-width: 0;
}

.agent-output-mobile-name {
  padding-right: 36px;
  color: #111827;
  font-weight: 600;
  line-height: 1.45;
  word-break: break-all;
}

.agent-output-mobile-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}

.agent-output-mobile-meta {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px 12px;
  margin-top: 12px;
}

.agent-output-mobile-meta-item {
  min-width: 0;
}

.agent-output-mobile-meta-item:first-child {
  grid-column: 1 / -1;
}

.agent-output-mobile-meta-label {
  margin-bottom: 3px;
  color: #8a94a6;
  font-size: 12px;
  line-height: 1.2;
}

.agent-output-mobile-meta-value {
  min-width: 0;
  color: #303133;
  font-size: 13px;
  line-height: 1.35;
  word-break: break-word;
}

.agent-output-mobile-actions {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  margin-top: 14px;
}

.agent-output-mobile-action-item {
  min-width: 0;
}

.agent-output-mobile-actions > .agent-output-mobile-action-item:last-child:nth-child(odd) {
  grid-column: 1 / -1;
}

.agent-output-mobile-actions :deep(.el-button) {
  width: 100%;
  height: 34px;
  margin: 0;
  border-radius: 10px;
}

.agent-output-mobile-more-dropdown {
  width: 100%;
}

.agent-output-mobile-more-dropdown :deep(.el-tooltip__trigger) {
  width: 100%;
}

.agent-output-mobile-more-button :deep(.el-icon) {
  margin-right: 4px;
}

.agent-output-info-body {
  max-height: 65vh;
  overflow: auto;
}

.agent-output-info-row {
  display: grid;
  grid-template-columns: 180px 1fr;
  gap: 12px;
  padding: 9px 0;
  border-bottom: 1px solid #ebeef5;
}

.agent-output-info-label {
  color: #606266;
  font-weight: 500;
}

.agent-output-info-value {
  color: #303133;
  word-break: break-word;
}

@media (max-width: 768px) {
  .agent-outputs-toolbar {
    align-items: stretch;
    flex-direction: column;
  }

  .agent-outputs-toolbar-left,
  .agent-outputs-toolbar-right {
    width: 100%;
  }

  .agent-outputs-toolbar-left {
    flex-wrap: wrap;
  }

  .agent-outputs-toolbar-left :deep(.el-button.toolbar-btn) {
    flex: 1 1 calc(50% - 4px);
  }

  .agent-outputs-toolbar-left :deep(.el-button.toolbar-btn:last-child:nth-child(odd)) {
    flex-basis: 100%;
  }

  .agent-outputs-toolbar-right {
    justify-content: flex-start;
    margin-left: 0;
    flex-wrap: wrap;
  }

  .agent-output-builder-filter {
    width: 100%;
  }

  .agent-outputs-count {
    width: 100%;
  }

  .agent-outputs-table-wrap {
    display: none;
  }

  .agent-outputs-mobile-wrap {
    display: flex;
  }

  .agent-output-info-row {
    grid-template-columns: 118px 1fr;
  }
}
</style>

<style>
/* AgentOutputsDialog: 构建产物状态和表格滚动放在组件内部。 */
.agent-outputs-overlay .el-dialog {
  height: 76vh !important;
  max-height: 76vh !important;
  display: flex !important;
  flex-direction: column !important;
  overflow: hidden !important;
}

.agent-outputs-overlay .el-dialog__header {
  flex: 0 0 auto !important;
}

.agent-outputs-overlay .el-dialog__body {
  display: flex !important;
  flex: 1 1 auto !important;
  width: 100% !important;
  min-width: 0 !important;
  min-height: 0 !important;
  overflow: hidden !important;
  box-sizing: border-box !important;
}

.agent-outputs-overlay .agent-outputs-body {
  flex: 1 1 auto !important;
  width: 100% !important;
  min-height: 0 !important;
}

@media (min-width: 769px) {
  .agent-outputs-overlay .el-dialog {
    width: 1120px !important;
    max-width: calc(100vw - 32px) !important;
    height: 76vh !important;
    max-height: 76vh !important;
    margin: 4vh auto 0 !important;
    border-radius: var(--el-border-radius-small) !important;
  }
}

@media (max-width: 768px) {
  .agent-outputs-overlay .el-dialog {
    width: 100vw !important;
    max-width: 100vw !important;
    height: 100dvh !important;
    max-height: 100dvh !important;
    margin: 0 !important;
    border-radius: 0 !important;
  }

  .agent-outputs-overlay .el-dialog__header {
    padding: 14px 16px 10px !important;
  }

  .agent-outputs-overlay .el-dialog__body {
    padding: 10px 12px 12px !important;
  }
}
</style>
