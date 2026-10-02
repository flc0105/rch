<template>
  <el-dialog
    :model-value="visible"
    title="Command History"
    width="1120px"
    top="5vh"
    class="fixed-dialog recent-files-dialog command-history-dialog"
    modal-class="command-history-overlay"
    @update:model-value="handleVisibleChange"
  >
    <div class="fixed-dialog-body">
      <div class="dialog-head">
        <div class="dialog-head-left">
          <el-button
            size="small"
            @click="reloadCommandHistoryDialogData"
          >
            Refresh
          </el-button>

          <el-button
            size="small"
            type="danger"
            @click="clearCommandHistory"
          >
            Clear History
          </el-button>
        </div>

        <div class="dialog-head-right">
          <div class="command-history-toolbar">
            <div class="command-history-search-summary">
              <span>
                Quick {{ commandHistorySearchSummary.quickVisible }} / {{ commandHistorySearchSummary.quickTotal }}
              </span>

              <span>
                Execution {{ commandHistorySearchSummary.fullVisible }} / {{ commandHistorySearchSummary.fullTotal }}
              </span>
            </div>

            <el-input
              v-model="commandHistorySearchText"
              size="small"
              clearable
              class="command-history-search-input"
              placeholder="Search"
            />
          </div>
        </div>
      </div>

      <el-tabs
        v-model="commandHistoryActiveTab"
        class="command-history-tabs"
      >
        <el-tab-pane label="Quick History" name="quick">
          <div class="dialog-table-shell quick-history-table-shell">
            <el-table
              :data="filteredCommandHistoryItems"
              v-loading="commandHistoryLoading"
              stripe
              width="100%"
              height="100%"
              :empty-text="commandHistorySearchText ? 'No matching commands' : 'No command history available'"
              table-layout="fixed"
              @row-dblclick="applyHistoryCommand"
            >
              <el-table-column
                prop="index"
                label="#"
                width="90"
                align="center"
              >
                <template #default="{ row }">
                  <div class="ellipsis">
<!--                    {{ row.is_pinned ? '⭐ ' : '' }}-->
                    {{ row.index || '-' }}
                  </div>
                </template>
              </el-table-column>

              <el-table-column
                prop="command"
                label="Command"
                min-width="260"
                show-overflow-tooltip
              >
                <template #default="{ row }">
                  <div class="ellipsis mono">
                    {{ row.command || '-' }}
                  </div>
                </template>
              </el-table-column>

              <el-table-column
                prop="last_used_at"
                label="Last Used"
                width="240"
                show-overflow-tooltip
              >
                <template #default="{ row }">
                  <div class="ellipsis">
                    {{ formatDateTimeStandard(row.last_used_at || row.created_at || row.started_at) || '-' }}
                  </div>
                </template>
              </el-table-column>

              <el-table-column
                prop="status"
                label="Status"
                width="120"
                align="center"
              >
                <template #default="{ row }">
                  <el-tag
                    :type="buildCommandExecutionStatusTagType(row.status)"
                    size="small"
                  >
                    {{ row.status || '-' }}
                  </el-tag>
                </template>
              </el-table-column>

              <el-table-column
                label="Actions"
                width="240"
                align="center"
                fixed="right"
              >
                <template #default="{ row }">
                  <div class="table-actions table-actions-links history-actions-row">
                    <div class="history-actions-group">
<!--                      <a-->
<!--                        href="#"-->
<!--                        class="table-action-link"-->
<!--                        @click.prevent="applyHistoryCommand(row)"-->
<!--                      >-->
<!--                        Use-->
<!--                      </a>-->


                       <el-button
                      size="small"
                      circle
                      plain
                      title="Use"
                      aria-label="Use"
@click.prevent="applyHistoryCommand(row)"
                  >
             <el-icon><Select /></el-icon>
                       </el-button>


                                           <el-button
                      size="small"
                      circle
                      plain
                      title="Pin"
                      aria-label="Pin"
                                           @click.prevent="toggleCommandHistoryPinned(row)">
 <el-icon>
  <Star v-if="!row.is_pinned" />
  <StarFilled v-else />
</el-icon>



                                           </el-button>


<!--                      <a-->
<!--                        href="#"-->
<!--                        class="table-action-link"-->
<!--                        @click.prevent="toggleCommandHistoryPinned(row)"-->
<!--                      >-->
<!--                        {{ row.is_pinned ? 'Unpin' : 'Pin' }}-->
<!--                      </a>-->
                    </div>

                    <template v-if="row.is_pinned">
                      <span class="history-actions-divider"></span>

                      <div class="history-actions-move-group">
<!--                        <a-->
<!--                          href="#"-->
<!--                          class="table-action-link"-->
<!--                          :class="{ 'history-action-disabled': !canMovePinned(row, 'up') }"-->
<!--                          @click.prevent="canMovePinned(row, 'up') && moveCommandHistoryPinned(row, 'up')"-->
<!--                        >-->

                         <el-button
                      size="small"
                      circle
                      plain
                      title="Move Up"
                      aria-label="Move Up"
                      :class="{ 'history-action-disabled': !canMovePinned(row, 'up') }"
                      @click.prevent="canMovePinned(row, 'up') && moveCommandHistoryPinned(row, 'up')">
                           <el-icon>
  <ArrowUp />
</el-icon>
                        </el-button>

<!--                        <a-->
<!--                          href="#"-->
<!--                          class="table-action-link"-->
<!--                          :class="{ 'history-action-disabled': !canMovePinned(row, 'down') }"-->
<!--                          @click.prevent="canMovePinned(row, 'down') && moveCommandHistoryPinned(row, 'down')"-->
<!--                        >-->

                          <el-button
                      size="small"
                      circle
                      plain
                      title="Move Down"
                      aria-label="Move Down"
                                                    :class="{ 'history-action-disabled': !canMovePinned(row, 'down') }"
  @click.prevent="canMovePinned(row, 'down') && moveCommandHistoryPinned(row, 'down')">


                                                     <el-icon>
  <ArrowDown />
</el-icon>
                        </el-button>
                      </div>
                    </template>
                  </div>
                </template>
              </el-table-column>
            </el-table>
          </div>

          <div class="quick-history-mobile-shell">
            <div
              class="mobile-file-list"
              v-loading="commandHistoryLoading"
            >
              <div
                v-if="!filteredCommandHistoryItems.length && !commandHistoryLoading"
                class="empty-state"
              >
                No command history available
              </div>

              <div
                v-else
                class="mobile-file-grid"
              >
                <div
                  v-for="row in filteredCommandHistoryItems"
                  :key="`${row.index}-${row.command}-${row.last_used_at || row.created_at || row.started_at}`"
                  class="mobile-file-card quick-history-card"
                >
                  <div class="mobile-file-card-top">
                    <div class="mobile-file-icon">⌘</div>

                    <div class="mobile-file-main">
                      <div class="mobile-file-name mono">
                        {{ row.is_pinned ? '⭐ ' : '' }}{{ row.command || '-' }}
                      </div>

                      <div class="mobile-file-tags">
                        <el-tag size="small" type="info">
                          #{{ row.index || '-' }}
                        </el-tag>

                        <el-tag
                          size="small"
                          :type="buildCommandExecutionStatusTagType(row.status)"
                        >
                          {{ row.status || '-' }}
                        </el-tag>
                      </div>

                      <div class="mobile-file-meta">
                        <div class="mobile-file-meta-item">
                          <div class="mobile-file-meta-label">Last Used</div>
                          <div class="mobile-file-meta-value">
                            {{ formatDateTimeStandard(row.last_used_at || row.created_at || row.started_at) || '-' }}
                          </div>
                        </div>
                      </div>

                      <div class="mobile-file-actions mobile-history-actions-row">
                        <el-button
                          size="small"
                          type="primary"
                          plain
                          @click="applyHistoryCommand(row)"
                        >
                          Use
                        </el-button>

                        <el-button
                          size="small"
                          plain
                          @click="toggleCommandHistoryPinned(row)"
                        >
                          {{ row.is_pinned ? 'Unpin' : 'Pin' }}
                        </el-button>

                        <template v-if="row.is_pinned">
                          <span class="mobile-history-actions-divider"></span>

                          <div class="mobile-history-move-group">
                            <el-button
                              size="small"
                              plain
                              class="mobile-history-disabled-btn"
                              :class="{ 'is-disabled': !canMovePinned(row, 'up') }"
                              :disabled="!canMovePinned(row, 'up')"
                              @click="canMovePinned(row, 'up') && moveCommandHistoryPinned(row, 'up')"
                            >
                              Up
                            </el-button>

                            <el-button
                              size="small"
                              plain
                              class="mobile-history-disabled-btn"
                              :class="{ 'is-disabled': !canMovePinned(row, 'down') }"
                              :disabled="!canMovePinned(row, 'down')"
                              @click="canMovePinned(row, 'down') && moveCommandHistoryPinned(row, 'down')"
                            >
                              Down
                            </el-button>
                          </div>
                        </template>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </el-tab-pane>

        <el-tab-pane label="Execution History" name="full">
          <div
            class="command-execution-list-shell"
            v-loading="commandExecutionHistoryLoading"
          >
            <div
              v-if="!filteredCommandExecutionItems.length && !commandExecutionHistoryLoading"
              class="empty-state"
            >
              {{ commandHistorySearchText ? 'No matching executions' : 'No execution history available' }}
            </div>

            <div
              v-else
              class="command-execution-list"
            >
              <el-card
                v-for="item in filteredCommandExecutionItems"
                :key="item.entry_id"
                class="execution-history-card"
                shadow="hover"
              >
                <div class="execution-history-card-inner">
                  <div class="execution-history-card-header">
                    <div class="execution-history-command mono">
                      {{ item.command || '-' }}
                    </div>

                    <div class="execution-history-badges">
                      <el-tag
                        :type="buildCommandExecutionStatusTagType(item.status)"
                        size="small"
                      >
                        {{ item.status || '-' }}
                      </el-tag>

                      <el-tag
                        v-if="Array.isArray(item.files) && item.files.length"
                        type="primary"
                        size="small"
                      >
                        📎 {{ (item.files || []).length }}
                      </el-tag>

                      <el-tag
                        v-if="item.output_truncated"
                        type="warning"
                        size="small"
                      >
                        ✂️ truncated
                      </el-tag>
                    </div>
                  </div>

                  <div class="execution-history-meta">
                    <span class="execution-history-source mono">{{ item.source || '-' }}</span>
                    <span class="execution-history-separator">•</span>
                    <span class="execution-history-time">
                      {{ formatDateTimeStandard(item.started_at) || '-' }}
                    </span>
                  </div>

<!--                  <div class="execution-history-stats">-->
<!--                    <div class="execution-history-stat-item">-->
<!--                      <span class="execution-history-stat-label">Duration</span>-->
<!--                      <span class="execution-history-stat-value">-->
<!--                        {{ formatCommandExecutionDuration(item) }}-->
<!--                      </span>-->
<!--                    </div>-->

<!--                    <div class="execution-history-stat-item">-->
<!--                      <span class="execution-history-stat-label">Chunks</span>-->
<!--                      <span class="execution-history-stat-value">-->
<!--                        {{ item.output_chunk_count || 0 }}-->
<!--                      </span>-->
<!--                    </div>-->

<!--                    <div class="execution-history-stat-item">-->
<!--                      <span class="execution-history-stat-label">Lines</span>-->
<!--                      <span class="execution-history-stat-value">-->
<!--                        {{ item.output_line_count || 0 }}-->
<!--                      </span>-->
<!--                    </div>-->
<!--                  </div>-->

                  <div
                    class="execution-history-summary"
                    :title="buildCommandExecutionSingleLineSummary(item)"
                  >
                    {{ buildCommandExecutionSingleLineSummary(item) }}
                  </div>

                  <div class="execution-history-actions">
                    <el-button
                      plain
                      size="small"
                      @click="applyHistoryCommand(item)"
                    >
                      Use
                    </el-button>

                    <el-button
                      plain
                      size="small"
                      @click="openCommandExecutionDetail(item)"
                    >
                      Details
                    </el-button>

                    <el-button
                      type="danger"
                      plain
                      size="small"
                      :loading="commandExecutionDeletingEntryId === item.entry_id"
                      @click="deleteCommandExecutionItem(item)"
                    >
                      Delete
                    </el-button>
                  </div>
                </div>
              </el-card>

              <div
                v-if="commandExecutionHasMore"
                class="execution-history-load-more"
              >
                <el-button
                  plain
                  :loading="commandExecutionLoadingMore"
                  @click="loadMoreCommandExecutionHistory"
                >
                  Load More
                </el-button>
              </div>
            </div>
          </div>
        </el-tab-pane>
      </el-tabs>
    </div>
  </el-dialog>

  <CommandExecutionDetailDialog
    v-model:visible="commandExecutionDetailDialogVisible"
    :entry="selectedCommandExecutionEntry"
    :output-records="selectedCommandExecutionOutputRecordsDesc"
    :output-sort-order="commandExecutionOutputSortOrder"
    :build-command-execution-status-tag-type="buildCommandExecutionStatusTagType"
    :format-command-execution-duration="formatCommandExecutionDuration"
    :format-date-time-standard="formatDateTimeStandard"
    :build-command-execution-summary="buildCommandExecutionSummary"
    :format-command-execution-record-text="formatCommandExecutionRecordText"
    :get-command-execution-file-status-text="getCommandExecutionFileStatusText"
    :format-bytes="formatBytes"
    @toggle-output-sort="toggleCommandExecutionOutputSort"
    @preview-file="$emit('preview-file', $event)"
  />
</template>

<script>
import { ElMessage, ElMessageBox } from 'element-plus'
import CommandExecutionDetailDialog from './CommandExecutionDetailDialog.vue'
import {EditPen} from "@element-plus/icons-vue";
import { Star, StarFilled, ArrowUp, ArrowDown, Select } from '@element-plus/icons-vue'
import { diffDateTimeMs } from '../utils/formatters.js'

export default {
  name: 'CommandHistoryDialog',

  components: {
    EditPen,
    Select,
Star,
    StarFilled,
    CommandExecutionDetailDialog,
    ArrowUp, ArrowDown
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

    formatDateTimeStandard: {
      type: Function,
      required: true,
    },

    formatBytes: {
      type: Function,
      required: true,
    },

    reloadCommandCandidates: {
      type: Function,
      default: null,
    },
  },

  emits: [
    'apply-command',
    'preview-file',
  ],

  data() {
    return {
      visible: false,
      commandHistoryLoading: false,
      commandHistoryItems: [],
      commandHistoryPinningCommand: '',
      commandExecutionHistoryLoading: false,
      commandExecutionLoadingMore: false,
      commandExecutionItems: [],
      commandExecutionNextCursor: '',
      commandExecutionHasMore: false,
      commandExecutionTotalCount: 0,
      commandExecutionDeletingEntryId: '',
      commandHistoryActiveTab: 'quick',
      commandHistorySearchText: '',
      commandExecutionDetailDialogVisible: false,
      selectedCommandExecutionEntryId: '',
      commandExecutionOutputSortOrder: 'desc',
      commandExecutionRequestGeneration: 0,
      commandHistorySearchTimer: null,
    }
  },

  computed: {
    normalizedCommandHistorySearchText() {
      return String(this.commandHistorySearchText || '').trim().toLowerCase()
    },

    filteredCommandHistoryItems() {
      const keyword = this.normalizedCommandHistorySearchText
      const items = Array.isArray(this.commandHistoryItems) ? this.commandHistoryItems : []

      if (!keyword) return items

      return items.filter(item => String(item?.command || '').toLowerCase().includes(keyword))
    },

    filteredCommandExecutionItems() {
      const keyword = this.normalizedCommandHistorySearchText
      const items = Array.isArray(this.commandExecutionItems) ? this.commandExecutionItems : []

      if (!keyword) return items

      return items.filter(item => String(item?.command || '').toLowerCase().includes(keyword))
    },

    commandHistorySearchSummary() {
      return {
        quickVisible: this.filteredCommandHistoryItems.length,
        quickTotal: Array.isArray(this.commandHistoryItems) ? this.commandHistoryItems.length : 0,
        fullVisible: this.filteredCommandExecutionItems.length,
        fullTotal: Number(this.commandExecutionTotalCount || 0),
      }
    },

    selectedCommandExecutionEntry() {
      return this.commandExecutionItems.find(item => item.entry_id === this.selectedCommandExecutionEntryId) || null
    },

    selectedCommandExecutionOutputRecordsDesc() {
      const records = this.selectedCommandExecutionEntry && Array.isArray(this.selectedCommandExecutionEntry.output_records)
        ? this.selectedCommandExecutionEntry.output_records
        : []

      const sorted = [...records].sort((a, b) => Number(b.seq || 0) - Number(a.seq || 0))

      if (this.commandExecutionOutputSortOrder === 'asc') {
        sorted.reverse()
      }

      return sorted
    },
  },

  watch: {
    commandExecutionDetailDialogVisible(value) {
      if (!value) {
        this.selectedCommandExecutionEntryId = ''
      }
    },

    commandHistorySearchText() {
      if (this.commandHistorySearchTimer) {
        window.clearTimeout(this.commandHistorySearchTimer)
      }

      if (!this.visible) return

      this.commandHistorySearchTimer = window.setTimeout(() => {
        this.commandHistorySearchTimer = null
        this.reloadCommandExecutionHistory({ silent: true })
      }, 250)
    },
  },

  methods: {
    getSelectedHistoryMachineId() {
      return String(this.currentConnection?.machine_id || '').trim()
    },

    async open() {
      if (!this.selectedId) {
        ElMessage.warning('Please select a device')
        return
      }

      const machineId = this.getSelectedHistoryMachineId()

      if (!machineId) {
        ElMessage.warning('Current device identity is unavailable')
        return
      }

      this.visible = true
      await this.reloadCommandHistoryDialogData()
    },

    close() {
      this.handleVisibleChange(false)
    },

    isOpen() {
      return this.visible
    },

    handleVisibleChange(value) {
      this.visible = value

      if (!value) {
        if (this.commandHistorySearchTimer) {
          window.clearTimeout(this.commandHistorySearchTimer)
          this.commandHistorySearchTimer = null
        }
        this.commandExecutionRequestGeneration += 1
        this.commandHistorySearchText = ''
        this.commandExecutionDetailDialogVisible = false
        this.selectedCommandExecutionEntryId = ''
      }
    },

    async reloadCandidates(options = {}) {
      if (typeof this.reloadCommandCandidates !== 'function') return

      try {
        await this.reloadCommandCandidates(options)
      } catch (_error) {
      }
    },

    getCommandExecutionSearchQuery() {
      return String(this.commandHistorySearchText || '').trim()
    },

    async reloadCommandExecutionHistory(options = {}) {
      const silent = !!options.silent
      const machineId = this.getSelectedHistoryMachineId()
      if (!machineId) return

      const query = this.getCommandExecutionSearchQuery()
      const generation = ++this.commandExecutionRequestGeneration
      this.commandExecutionHistoryLoading = true

      try {
        const params = new URLSearchParams({ limit: '50' })
        if (query) params.set('query', query)

        const res = await fetch(
          `/api/machines/${encodeURIComponent(machineId)}/command-history/full?${params.toString()}`,
        )
        const json = await res.json()

        if (
          generation !== this.commandExecutionRequestGeneration
          || machineId !== this.getSelectedHistoryMachineId()
          || query !== this.getCommandExecutionSearchQuery()
        ) {
          return
        }

        if (!res.ok || json.code !== 0) {
          throw new Error(json.message || 'Failed to load full command history')
        }

        const data = json.data && typeof json.data === 'object' ? json.data : {}
        this.commandExecutionItems = Array.isArray(data.items) ? data.items : []
        this.commandExecutionNextCursor = String(data.next_cursor || '')
        this.commandExecutionHasMore = data.has_more === true
        this.commandExecutionTotalCount = Number(data.total_count || this.commandExecutionItems.length)

        if (
          this.selectedCommandExecutionEntryId
          && !this.commandExecutionItems.some(item => item.entry_id === this.selectedCommandExecutionEntryId)
        ) {
          this.commandExecutionDetailDialogVisible = false
          this.selectedCommandExecutionEntryId = ''
        }
      } catch (e) {
        if (generation !== this.commandExecutionRequestGeneration) return

        this.commandExecutionItems = []
        this.commandExecutionNextCursor = ''
        this.commandExecutionHasMore = false
        this.commandExecutionTotalCount = 0

        if (!silent) {
          ElMessage.error(e.message || 'Failed to load full command history')
        }
      } finally {
        if (generation === this.commandExecutionRequestGeneration) {
          this.commandExecutionHistoryLoading = false
        }
      }
    },

    async reloadCommandHistoryDialogData(options = {}) {
      const silent = !!options.silent

      if (!this.selectedId) {
        if (!silent) {
          ElMessage.warning('Please select a device')
        }
        return
      }

      const machineId = this.getSelectedHistoryMachineId()

      if (!machineId) {
        this.commandHistoryItems = []
        this.commandExecutionItems = []
        this.commandExecutionNextCursor = ''
        this.commandExecutionHasMore = false
        this.commandExecutionTotalCount = 0

        if (!silent) {
          ElMessage.warning('Current device identity is unavailable')
        }
        return
      }

      this.commandHistoryLoading = true

      try {
        const quickRes = await fetch(`/api/machines/${encodeURIComponent(machineId)}/command-history`)
        const quickJson = await quickRes.json()

        if (!quickRes.ok || quickJson.code !== 0) {
          throw new Error(quickJson.message || 'Failed to load command history')
        }

        this.commandHistoryItems = Array.isArray(quickJson.data) ? quickJson.data : []
        await this.reloadCommandExecutionHistory({ silent })
        await this.reloadCandidates()
      } catch (e) {
        this.commandHistoryItems = []

        if (!silent) {
          ElMessage.error(e.message || 'Failed to load command history')
        }
      } finally {
        this.commandHistoryLoading = false
      }
    },

    async loadMoreCommandExecutionHistory() {
      if (this.commandExecutionLoadingMore || !this.commandExecutionHasMore) return

      const machineId = this.getSelectedHistoryMachineId()
      if (!machineId) return

      const generation = this.commandExecutionRequestGeneration
      const query = this.getCommandExecutionSearchQuery()
      const cursor = this.commandExecutionNextCursor
      this.commandExecutionLoadingMore = true
      try {
        const params = new URLSearchParams({ limit: '50' })
        if (cursor) {
          params.set('cursor', cursor)
        }
        if (query) {
          params.set('query', query)
        }
        const res = await fetch(
          `/api/machines/${encodeURIComponent(machineId)}/command-history/full?${params.toString()}`,
        )
        const json = await res.json()
        if (!res.ok || json.code !== 0) {
          throw new Error(json.message || 'Failed to load more execution history')
        }

        if (
          generation !== this.commandExecutionRequestGeneration
          || machineId !== this.getSelectedHistoryMachineId()
          || query !== this.getCommandExecutionSearchQuery()
          || cursor !== this.commandExecutionNextCursor
        ) {
          return
        }

        const data = json.data && typeof json.data === 'object' ? json.data : {}
        const items = Array.isArray(data.items) ? data.items : []
        const existingIds = new Set(this.commandExecutionItems.map(item => item?.entry_id).filter(Boolean))
        for (const item of items) {
          if (item?.entry_id && existingIds.has(item.entry_id)) continue
          this.commandExecutionItems.push(item)
          if (item?.entry_id) existingIds.add(item.entry_id)
        }
        this.commandExecutionNextCursor = String(data.next_cursor || '')
        this.commandExecutionHasMore = data.has_more === true
        this.commandExecutionTotalCount = Number(data.total_count || this.commandExecutionTotalCount || this.commandExecutionItems.length)
      } catch (e) {
        ElMessage.error(e.message || 'Failed to load more execution history')
      } finally {
        this.commandExecutionLoadingMore = false
      }
    },

    applyHistoryCommand(row) {
      if (!row || !row.command) return

      this.visible = false
      this.$emit('apply-command', row)
    },

    openCommandExecutionDetail(row) {
      if (!row || !row.entry_id) return

      this.selectedCommandExecutionEntryId = row.entry_id
      this.commandExecutionDetailDialogVisible = true
    },

    async toggleCommandHistoryPinned(row) {
      if (!this.selectedId) {
        ElMessage.warning('Please select a device')
        return
      }

      const machineId = this.getSelectedHistoryMachineId()

      if (!machineId) {
        ElMessage.warning('Current device identity is unavailable')
        return
      }

      if (!row || !row.command) return

      const commandText = String(row.command || '')
      this.commandHistoryPinningCommand = commandText

      try {
        const res = await fetch(`/api/machines/${encodeURIComponent(machineId)}/command-history/pin`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            command: commandText,
            is_pinned: !row.is_pinned,
          }),
        })

        const json = await res.json()

        if (!res.ok || json.code !== 0) {
          throw new Error(json.message || 'Failed to update pinned command')
        }

        await this.reloadCommandHistoryDialogData({ silent: true })
        ElMessage.success(row.is_pinned ? 'Removed from pinned commands' : 'Pinned command updated')
      } catch (e) {
        ElMessage.error(e.message || 'Failed to update pinned command')
      } finally {
        this.commandHistoryPinningCommand = ''
      }
    },

    canMovePinned(row, direction) {
  if (!row || !row.is_pinned) return false

  const pinnedItems = (this.commandHistoryItems || []).filter(item => item?.is_pinned)
  const index = pinnedItems.findIndex(item => item === row || item.command === row.command)

  if (index < 0) return false
  if (direction === 'up') return index > 0
  if (direction === 'down') return index < pinnedItems.length - 1

  return false
},

    async moveCommandHistoryPinned(row, direction) {
      if (!this.selectedId) {
        ElMessage.warning('Please select a device')
        return
      }

      const machineId = this.getSelectedHistoryMachineId()

      if (!machineId) {
        ElMessage.warning('Current device identity is unavailable')
        return
      }

      if (!row || !row.command || !row.is_pinned) return

      const directionText = String(direction || '').trim().toLowerCase()

      if (!['up', 'down'].includes(directionText)) return
      if (directionText === 'up' && !this.canMovePinned(row, 'up')) return
      if (directionText === 'down' && !this.canMovePinned(row, 'down')) return

      try {
        const res = await fetch(`/api/machines/${encodeURIComponent(machineId)}/command-history/pin/move`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            command: String(row.command || ''),
            direction: directionText,
          }),
        })

        const json = await res.json()

        if (!res.ok || json.code !== 0) {
          throw new Error(json.message || 'Failed to move pinned command')
        }

        await this.reloadCommandHistoryDialogData({ silent: true })
      } catch (e) {
        ElMessage.error(e.message || 'Failed to move pinned command')
      }
    },

    async deleteCommandExecutionItem(row) {
      if (!this.selectedId) {
        ElMessage.warning('Please select a device')
        return
      }

      const machineId = this.getSelectedHistoryMachineId()

      if (!machineId) {
        ElMessage.warning('Current device identity is unavailable')
        return
      }

      if (!row || !row.entry_id) return

      try {
        await ElMessageBox.confirm(
          'Delete this execution history entry?',
          'Delete Entry',
          {
            type: 'warning',
            confirmButtonText: 'Delete',
            cancelButtonText: 'Cancel',
          }
        )

        this.commandExecutionDeletingEntryId = row.entry_id

        const res = await fetch(`/api/machines/${encodeURIComponent(machineId)}/command-history/full/${encodeURIComponent(row.entry_id)}`, {
          method: 'DELETE',
        })

        const json = await res.json()

        if (!res.ok || json.code !== 0) {
          throw new Error(json.message || 'Failed to delete execution history entry')
        }

        await this.reloadCommandHistoryDialogData({ silent: true })
        ElMessage.success('Execution history entry deleted')
      } catch (e) {
        if (e === 'cancel' || e === 'close' || e?.toString?.().includes('cancel')) return
        ElMessage.error(e.message || 'Failed to delete execution history entry')
      } finally {
        this.commandExecutionDeletingEntryId = ''
      }
    },

    async clearCommandHistory() {
  if (!this.selectedId) {
    ElMessage.warning('Please select a device')
    return
  }

  const machineId = this.getSelectedHistoryMachineId()

  if (!machineId) {
    ElMessage.warning('Current device identity is unavailable')
    return
  }

  try {
    await ElMessageBox.confirm(
      'Clear command history for the current device? Pinned commands will be kept.',
      'Clear History',
      {
        type: 'warning',
        confirmButtonText: 'Clear',
        cancelButtonText: 'Cancel',
      }
    )

    const res = await fetch(`/api/machines/${encodeURIComponent(machineId)}/command-history`, {
      method: 'DELETE',
    })

    const json = await res.json()

    if (!res.ok || json.code !== 0) {
      throw new Error(json.message || 'Failed to clear command history')
    }

    this.commandHistorySearchText = ''
    this.commandExecutionDetailDialogVisible = false
    this.selectedCommandExecutionEntryId = ''

    // pinned history 单独存储，clear 后重新拉取 quick history，避免 pinned 临时消失后刷新又冒出来。
    await this.reloadCommandHistoryDialogData({ silent: true })
    await this.reloadCandidates({ reset: true })

    ElMessage.success('Command history cleared')
  } catch (e) {
    if (e === 'cancel' || e === 'close' || e?.toString?.().includes('cancel')) return
    ElMessage.error(e.message || 'Failed to clear command history')
  }
},

    // async clearCommandHistory() {
    //   if (!this.selectedId) {
    //     ElMessage.warning('Please select a device')
    //     return
    //   }
    //
    //   const machineId = this.getSelectedHistoryMachineId()
    //
    //   if (!machineId) {
    //     ElMessage.warning('Current device identity is unavailable')
    //     return
    //   }
    //
    //   try {
    //     await ElMessageBox.confirm(
    //       'Clear command history for the current device?',
    //       'Clear History',
    //       {
    //         type: 'warning',
    //         confirmButtonText: 'Clear',
    //         cancelButtonText: 'Cancel',
    //       }
    //     )
    //
    //     const res = await fetch(`/api/machines/${encodeURIComponent(machineId)}/command-history`, {
    //       method: 'DELETE',
    //     })
    //
    //     const json = await res.json()
    //
    //     if (!res.ok || json.code !== 0) {
    //       throw new Error(json.message || 'Failed to clear command history')
    //     }
    //
    //     this.commandHistoryItems = []
    //     this.commandExecutionItems = []
    //     this.commandHistorySearchText = ''
    //     this.commandExecutionDetailDialogVisible = false
    //     this.selectedCommandExecutionEntryId = ''
    //     await this.reloadCandidates({ reset: true })
    //     ElMessage.success('Command history cleared')
    //   } catch (e) {
    //     if (e === 'cancel' || e === 'close' || e?.toString?.().includes('cancel')) return
    //     ElMessage.error(e.message || 'Failed to clear command history')
    //   }
    // },

    buildCommandExecutionStatusTagType(status) {
      const value = String(status || '').toLowerCase()

      if (value === 'success') return 'success'
      if (value === 'error') return 'danger'
      if (value === 'running') return 'warning'

      return 'info'
    },

    formatCommandExecutionDuration(entryOrDuration) {
      const ms = entryOrDuration && typeof entryOrDuration === 'object'
        ? diffDateTimeMs(
          entryOrDuration.started_at || entryOrDuration.created_at,
          entryOrDuration.finished_at,
        )
        : Number(entryOrDuration || 0)

      if (!ms) return '0ms'
      if (ms < 1000) return `${Math.floor(ms)}ms`

      const totalSeconds = Math.floor(ms / 1000)
      const hours = Math.floor(totalSeconds / 3600)
      const minutes = Math.floor((totalSeconds % 3600) / 60)
      const seconds = totalSeconds % 60

      const parts = []

      if (hours) parts.push(`${hours}h`)
      if (minutes) parts.push(`${minutes}m`)
      if (seconds || !parts.length) parts.push(`${seconds}s`)

      return parts.join(' ')
    },

    buildCommandExecutionSummary(item) {
      const calculatedSummary = String(item?.output_summary || '').trim()
      if (calculatedSummary) return calculatedSummary

      const files = Array.isArray(item?.files) ? item.files : []
      if (files.length) return `Produced ${files.length} file(s)`

      const records = Array.isArray(item?.output_records) ? item.output_records : []
      for (let index = records.length - 1; index >= 0; index -= 1) {
        const text = String(records[index]?.text || '').trim()
        if (!text) continue
        if (!text.includes('\n') && !text.includes('\r')) return text
        break
      }

      if (String(item?.status || '').toLowerCase() === 'success') return 'Command completed'
      if (String(item?.status || '').toLowerCase() === 'error') return 'Command failed'
      return 'No output'
    },

    formatCommandExecutionRecordText(text) {
      return String(text || '')
    },

    getCommandExecutionFileStatusText(file) {
      if (!file) return ''

      return file.is_available ? '' : (file.status_text || 'File removed')
    },

    buildCommandExecutionSingleLineSummary(item) {
      return this.buildCommandExecutionSummary(item)
    },

    toggleCommandExecutionOutputSort() {
      this.commandExecutionOutputSortOrder = this.commandExecutionOutputSortOrder === 'asc' ? 'desc' : 'asc'
    },
  },
}
</script>

<style scoped>
/* History dialog：Execution History 使用 el-card 外壳，内部保留原来的卡片信息结构。 */
.fixed-dialog-body {
  height: 100%;
  min-height: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.dialog-head {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 10px;
  align-items: center;
  margin-bottom: 12px;
  flex-shrink: 0;
}

.dialog-head-left {
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
  min-width: 0;
}

.dialog-head-left :deep(.el-button) {
  height: 32px;
  min-height: 32px;
  padding-inline: 12px;
  border-radius: 10px;
  margin: 0;
}

.dialog-head-right {
  min-width: 0;
  width: 100%;
}

.command-history-toolbar {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 12px;
  flex-wrap: wrap;
  width: 100%;
}

.command-history-search-input {
  width: min(300px, 100%);
}

.command-history-search-input :deep(.el-input__wrapper) {
  min-height: 32px;
  height: 32px;
  border-radius: 10px;
}

.command-history-search-summary {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  min-height: 32px;
  color: var(--muted);
  font-size: 12px;
  line-height: 32px;
}

.command-history-search-summary span {
  display: inline-flex;
  align-items: center;
  height: 32px;
  color: #64748b;
  white-space: nowrap;
}

.command-history-tabs {
  min-height: 0;
  height: 100%;
  display: flex;
  flex-direction: column;
}

.command-history-tabs :deep(.el-tabs__header) {
  margin-bottom: 12px;
}

.command-history-tabs :deep(.el-tabs__content) {
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
}

.command-history-tabs :deep(.el-tab-pane) {
  height: 100%;
  min-height: 0;
}

.dialog-table-shell {
  min-height: 0;
  overflow: hidden;
}

.quick-history-table-shell {
  height: 100%;
  min-height: 320px;
}

.quick-history-table-shell :deep(.el-table),
.quick-history-table-shell :deep(.el-table__inner-wrapper),
.quick-history-table-shell :deep(.el-scrollbar) {
  width: 100%;
  height: 100% !important;
}

.quick-history-table-shell :deep(.el-scrollbar__wrap) {
  height: 100% !important;
  overflow-y: auto !important;
  overflow-x: auto !important;
}

.quick-history-table-shell :deep(.el-table__body-wrapper) {
  overflow-y: auto !important;
}

.quick-history-table-shell :deep(.el-table th.el-table__cell) {
  background: #f8fafc !important;
  color: #475569;
  font-weight: 700;
}

.quick-history-table-shell :deep(.el-table tr) {
  background: #fff;
}

.quick-history-table-shell :deep(.el-table .cell) {
  line-height: 1.5;
}

.ellipsis {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}

.table-actions {
  display: flex;
  align-items: center;
  justify-content: center;
  flex-wrap: nowrap;
  min-height: 28px;
  white-space: nowrap;
}

.table-actions-links {
  gap: 10px;
}

.table-action-link,
.table-action-link:link,
.table-action-link:visited,
.table-action-link:active {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  line-height: 1;
  color: var(--el-color-primary) !important;
  text-decoration: none !important;
  font-size: 12px;
  white-space: nowrap;
  vertical-align: middle;
}

.table-action-link:hover {
  color: var(--el-color-primary-light-5) !important;
  text-decoration: none !important;
}

.history-actions-row {
  display: inline-flex;
  align-items: center;
  justify-content: flex-end;
  gap: 0;
  white-space: nowrap;
}

.history-actions-group {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.history-actions-divider {
  display: inline-block;
  width: 1px;
  height: 14px;
  margin-left: 8px;
  margin-right: 8px;
  background: #dcdfe6;
  vertical-align: middle;
}

.history-actions-move-group {
  display: inline-grid;
  grid-template-columns: 24px 24px;
  align-items: center;
  column-gap: 8px;
}

.history-action-disabled {
  color: #c0c4cc !important;
  cursor: not-allowed !important;
  pointer-events: none !important;
  text-decoration: none !important;
}

.table-action-link.history-action-disabled,
.table-action-link.history-action-disabled:link,
.table-action-link.history-action-disabled:visited,
.table-action-link.history-action-disabled:active,
.table-action-link.history-action-disabled:hover {
  color: #c0c4cc !important;
  cursor: not-allowed !important;
  pointer-events: none !important;
  text-decoration: none !important;
}

.quick-history-mobile-shell,
.mobile-file-list {
  display: none;
}

.mobile-file-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: 12px;
  overflow-y: auto;
  min-height: 0;
  padding-right: 2px;
  align-content: start;
}
.mobile-file-card {
  background: #fff;
  border: 1px solid rgba(15, 23, 42, 0.06);
  border-radius: 14px;
  padding: 12px;
  box-shadow: 0 4px 14px rgba(15, 23, 42, 0.04);
}

.mobile-file-card-top {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  min-width: 0;
}

.mobile-file-icon {
  flex: 0 0 auto;
  font-size: 20px;
  line-height: 1;
  margin-top: 2px;
}

.mobile-file-main {
  min-width: 0;
  flex: 1;
}

.mobile-file-name {
  font-size: 14px;
  font-weight: 700;
  color: var(--text);
  line-height: 1.4;
  word-break: break-word;
}

.quick-history-card .mobile-file-name {
  font-size: 13px;
}

.mobile-file-tags {
  margin-top: 10px;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.mobile-file-meta {
  margin-top: 8px;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 6px 10px;
}

.mobile-file-meta-item {
  min-width: 0;
}

.mobile-file-meta-label {
  font-size: 11px;
  color: var(--muted-2);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.mobile-file-meta-value {
  margin-top: 2px;
  font-size: 12px;
  color: var(--text);
  word-break: break-word;
  line-height: 1.4;
}

.mobile-file-actions {
  margin-top: 12px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.mobile-file-actions :deep(.el-button) {
  margin: 0;
  min-height: 32px;
  border-radius: 10px;
  padding-inline: 12px;
}

.mobile-history-actions-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px;
}

.mobile-history-actions-divider {
  width: 1px;

  align-self: stretch;
  background: #dcdfe6;
  margin: 0 2px;
}

.mobile-history-move-group {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.mobile-history-move-group :deep(.el-button) {
  min-width: 56px;
}

.mobile-history-disabled-btn.is-disabled,
.mobile-history-disabled-btn.is-disabled:hover,
.mobile-history-disabled-btn.is-disabled:focus {
  opacity: 0.45;
  cursor: not-allowed;
}

/* Execution History 卡片 */
.command-execution-list-shell {
  height: 100%;
  min-height: 320px;
  overflow: hidden;
}

.command-execution-list {
  height: 100%;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 4px 2px 4px 0;
}

.execution-history-card.el-card {
  flex: 0 0 auto;
  border: 1px solid #eef2f6;
  border-radius: 16px;
  background: #fff;
  overflow: hidden;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.02);
  transition: border-color 0.2s ease, box-shadow 0.2s ease, transform 0.2s ease;
}

.execution-history-card.el-card:hover {
  border-color: #e2e8f0;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.04);
  transform: translateY(-1px);
}

.execution-history-card :deep(.el-card__body) {
  padding: 0 !important;
}

.execution-history-card-inner {
  padding: 16px 20px;
}

.execution-history-card-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
}

.execution-history-command {
  display: block;
  font-size: 14px;
  font-weight: 600;
  color: #1e293b;
  line-height: 1.4;
  flex: 0 1 560px;
  max-width: min(560px, 100%);
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  word-break: normal;
}

.execution-history-badges {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.execution-history-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  font-size: 12px;
  color: #6b7280;
}

.execution-history-source {
  color: #475569;
}

.execution-history-separator {
  color: #d1d5db;
}

/*
//
//.execution-history-stats {
//  display: flex;
//  flex-wrap: wrap;
//  gap: 16px;
//  margin-bottom: 12px;
//  padding: 10px 0;
//  border-top: 1px solid #f0f2f5;
//  border-bottom: 1px solid #f0f2f5;
//}
//
//.execution-history-stat-item {
//  display: flex;
//  align-items: baseline;
//  gap: 6px;
//  min-width: 0;
//}
//
//.execution-history-stat-label {
//  font-size: 11px;
//  font-weight: 500;
//  color: #9ca3af;
//  text-transform: uppercase;
//  letter-spacing: 0.3px;
//}
//
//.execution-history-stat-value {
//  font-size: 13px;
//  font-weight: 500;
//  color: #1e293b;
//}
 */

.execution-history-summary {
  font-size: 12px;
  color: #4b5563;
  line-height: 1.5;
  margin-bottom: 14px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.execution-history-load-more {
  display: flex;
  justify-content: center;
  padding: 12px 0 4px;
}

.execution-history-actions {
  display: flex;
  justify-content: flex-end;
}

.execution-history-actions :deep(.el-button + .el-button) {
  margin-left: 12px;
}

.empty-state {
  color: var(--muted-2);
  text-align: center;
  padding: 24px;
}

@media (max-width: 960px) {
  .dialog-head {
    grid-template-columns: 1fr;
  }

  .dialog-head-left,
  .dialog-head-right {
    width: 100%;
  }

  .command-history-toolbar {
    justify-content: flex-start;
  }
}

@media (max-width: 768px), (max-height: 720px) {
  .quick-history-table-shell {
    display: none;
  }

  .quick-history-mobile-shell {
    display: flex;
    flex: 1 1 auto;
    height: 100%;
    min-height: 0;
    overflow: hidden;
  }

  .quick-history-mobile-shell .mobile-file-list {
    display: block;
    flex: 1 1 auto;
    height: 100%;
    min-height: 0;
    overflow: hidden;
  }

.quick-history-mobile-shell .mobile-file-grid {
  height: 100%;
  min-height: 0;
  overflow-y: auto;
  -webkit-overflow-scrolling: touch;
  align-content: start;
}

  .dialog-head-left {
    flex-wrap: wrap;
    align-items: stretch;
  }

  .command-history-toolbar {
    justify-content: flex-start;
  }

  .command-history-search-input {
    width: 100%;
  }

  .command-history-search-summary {
    width: 100%;
    justify-content: space-between;
  }

  .execution-history-card-inner {
    padding: 14px 16px;
  }

  .execution-history-card-header {
    flex-direction: column;
    align-items: flex-start;
    width: 100%;
    min-width: 0;
  }

  .execution-history-command {
    width: 100%;
    max-width: 100%;
    flex: 0 1 auto;
  }

  .execution-history-badges {
    justify-content: flex-start;
  }



  .execution-history-summary {
    white-space: normal;
    word-break: break-word;
  }

  .execution-history-actions {
    justify-content: flex-start;
    flex-wrap: wrap;
    gap: 8px;
  }

  .execution-history-actions :deep(.el-button + .el-button) {
    margin-left: 0;
  }
}

@media (max-width: 640px) {
  .mobile-file-actions {
    gap: 6px;
  }

  .mobile-file-actions :deep(.el-button) {
    flex: 1 1 calc(50% - 6px);
    justify-content: center;
  }

  .mobile-history-actions-row {
    align-items: stretch;
  }

  .mobile-history-actions-divider {
    display: none;
  }

  .mobile-history-move-group {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 6px;
    width: 100%;
  }

  .mobile-history-move-group :deep(.el-button) {
    width: 100%;
    min-width: 0;
    margin: 0;
  }

  .mobile-history-move-group :deep(.el-button + .el-button) {
    margin-left: 0;
  }

  .execution-history-actions {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 6px;
    width: 100%;
  }

  .execution-history-actions :deep(.el-button) {
    width: 100%;
    min-height: 32px;
    margin: 0 !important;
    border-radius: 10px;
    justify-content: center;
  }

  .execution-history-actions :deep(.el-button:last-child) {
    grid-column: 1 / -1;
  }
}
</style>

<style>


/* Detail 弹窗标题限制为一行，超出省略。 */
.command-execution-detail-dialog .el-dialog__title {
  display: block;
  max-width: calc(100% - 44px);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}


.command-history-overlay .el-overlay-dialog {
  overflow: hidden !important;
}

.command-history-overlay .el-dialog {
  height: 78vh !important;
  max-height: 78vh !important;
  margin-top: 5vh !important;
  display: flex !important;
  flex-direction: column !important;
  overflow: hidden !important;
}

.command-history-overlay .el-dialog__header {
  flex: 0 0 auto !important;
}

.command-history-overlay .el-dialog__body {
  flex: 1 1 auto !important;
  min-height: 0 !important;
  overflow: hidden !important;
  padding-top: 12px !important;
  padding-bottom: 12px !important;
}

@media (max-width: 768px), (max-height: 720px) {
  .command-history-overlay .el-dialog {
    width: 100vw !important;
    max-width: 100vw !important;
    height: 100dvh !important;
    max-height: 100dvh !important;
    margin: 0 !important;
    border-radius: 0 !important;
  }

  .command-history-overlay .el-dialog__header {
    padding: 14px 16px 10px !important;
  }

  .command-history-overlay .el-dialog__body {
    padding: 10px 12px 12px !important;
  }
}
</style>


<style>
/* CommandExecutionDetailDialog：只做紧凑对齐，不额外撑高。 */

/* 1 / 2：顶部信息卡片统一为紧凑高度。 */
.command-execution-detail-dialog .background-job-stats {
  align-items: stretch;
}

.command-execution-detail-dialog .background-job-stat {
  height: 64px;
  min-height: 64px;
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  justify-content: center;
  padding-top: 8px;
  padding-bottom: 8px;
}

.command-execution-detail-dialog .background-job-stat-value {
  min-height: 20px;
  display: flex;
  align-items: center;
}

/* 3 / 4：两个面板标题栏统一为紧凑高度。 */
.command-execution-detail-dialog .background-job-panel-title {
  height: 38px;
  min-height: 38px;
  box-sizing: border-box;
  display: flex;
  align-items: center;
  padding-top: 8px;
  padding-bottom: 8px;
}




@media (max-width: 768px), (max-height: 720px) {
  .command-execution-detail-dialog .background-job-stat {
    height: auto;
    min-height: 64px;
  }

  .command-execution-detail-dialog .background-job-panel-title {
    height: auto;
    min-height: 38px;
  }

  .command-execution-detail-dialog .command-output-panel-title {
    flex-direction: row;
    align-items: center;
    justify-content: space-between;
    flex-wrap: nowrap;
  }

  .command-execution-detail-dialog .command-output-panel-title .el-button {
    width: auto;
  }
}
</style>