<template>
  <div class="external-tool-instance-toolbar">
    <div class="external-tool-hint">
      Target: {{ activeDeviceFilterLabel }}.
    </div>
  </div>

  <div v-if="filteredInstances.length" class="external-tool-instance-table-shell">
    <el-table
      :data="filteredInstances"
      size="small"
      class="external-tool-instance-table"
      height="560"
      row-key="row_key"
    >
  <!--            <el-table-column label="Target" min-width="190">-->
  <!--              <template #default="{ row }">-->
  <!--                <div class="mono strong" :title="row.machine_id || row.device_id">{{ row.machine_label || '-' }}</div>-->
  <!--&lt;!&ndash;                <div class="muted mono" :title="row.connection_id || row.device_id">&ndash;&gt;-->
  <!--&lt;!&ndash;                  {{ row.connection_id ? `conn: ${shortenDeviceId(row.connection_id)}` : '-' }}&ndash;&gt;-->
  <!--&lt;!&ndash;                </div>&ndash;&gt;-->
  <!--              </template>-->
  <!--            </el-table-column>-->


      <el-table-column label="Instance" min-width="170">
        <template #default="{ row }">
          <div class="mono strong" :title="row.instance_id">{{ row.instance_id }}</div>
          <div class="muted mono" :title="row.tool_id">{{ row.tool_id }}</div>
        </template>
      </el-table-column>

      <el-table-column label="Status" width="110">
        <template #default="{ row }">
          <el-tag size="small" :type="statusTagType(row.status)">
            {{ row.status || '-' }}
          </el-tag>
        </template>
      </el-table-column>



      <el-table-column label="PID" width="95">
        <template #default="{ row }">
          <span class="mono">{{ row.pid || '-' }}</span>
        </template>
      </el-table-column>

      <el-table-column label="Port" min-width="210">
        <template #default="{ row }">
          <span class="mono" :title="formatPortInfo(row)">{{ formatPortInfo(row) }}</span>
        </template>
      </el-table-column>

      <el-table-column label="Started" width="180">
        <template #default="{ row }">
          <span class="mono muted">{{ shortTime(row.started_at) }}</span>
        </template>
      </el-table-column>

      <el-table-column label="Actions" width="240">
        <template #default="{ row }">
          <div class="external-tool-table-actions">
            <el-button size="small" plain @click="$emit('logs', row)">
              Logs
            </el-button>
  <!--                  <el-button size="small" plain @click="$emit('more', 'info', row)">-->
  <!--                    Info-->
  <!--                  </el-button>-->
            <el-button
              size="small"
              type="danger"
              plain
              :disabled="!row.running && row.status !== 'stale'"
              @click="$emit('stop', row)"
            >
              Stop
            </el-button>
            <el-dropdown
              trigger="click"
              size="small"
              @command="$emit('more', $event, row)"
            >
              <el-button size="small" plain>
                More
              </el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="info">
                    Info
                  </el-dropdown-item>


                  <el-dropdown-item command="restart" :disabled="!canRestartInstance(row)">
                    Restart
                  </el-dropdown-item>
                  <el-dropdown-item command="clear_logs" :disabled="!canModifyStoppedInstanceFiles(row)">
                    Clear Logs
                  </el-dropdown-item>
                  <el-dropdown-item command="remove" :disabled="!canModifyStoppedInstanceFiles(row)">
                    Remove
                  </el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>
        </template>
      </el-table-column>
    </el-table>
  </div>

  <div v-if="filteredInstances.length" class="external-tool-instance-card-shell">
    <div class="external-tool-instance-card-list">
      <div
        v-for="row in filteredInstances"
        :key="row.row_key"
        class="external-tool-instance-card"
      >
        <div class="external-tool-instance-card-top">
          <div class="external-tool-instance-icon">
            <span :class="{ running: row.running, stale: row.status === 'stale' }"></span>
          </div>

          <div class="external-tool-instance-card-main">
            <div class="external-tool-instance-name" :title="row.instance_id">
              {{ row.instance_id }}
            </div>

            <div class="external-tool-instance-tags">
              <el-tag size="small" :type="statusTagType(row.status)">
                {{ row.status || '-' }}
              </el-tag>
              <el-tag size="small" type="info">
                {{ row.display_name || row.tool_id }}
              </el-tag>
            </div>

            <div class="external-tool-instance-meta">
              <div class="external-tool-instance-meta-item">
                <div class="external-tool-instance-meta-label">Tool</div>
                <div class="external-tool-instance-meta-value mono" :title="row.tool_id">
                  {{ row.tool_id || '-' }}
                </div>
              </div>

              <div class="external-tool-instance-meta-item">
                <div class="external-tool-instance-meta-label">PID</div>
                <div class="external-tool-instance-meta-value mono">
                  {{ row.pid || '-' }}
                </div>
              </div>

              <div class="external-tool-instance-meta-item">
                <div class="external-tool-instance-meta-label">Port</div>
                <div class="external-tool-instance-meta-value mono" :title="formatPortInfo(row)">
                  {{ formatPortInfo(row) }}
                </div>
              </div>

              <div class="external-tool-instance-meta-item">
                <div class="external-tool-instance-meta-label">Started</div>
                <div class="external-tool-instance-meta-value mono">
                  {{ shortTime(row.started_at) }}
                </div>
              </div>
            </div>

            <div class="external-tool-instance-card-actions">
              <el-button size="small" type="primary" plain @click="$emit('logs', row)">
                Logs
              </el-button>
              <el-button
                size="small"
                type="danger"
                plain
                :disabled="!row.running && row.status !== 'stale'"
                @click="$emit('stop', row)"
              >
                Stop
              </el-button>
              <el-dropdown
                trigger="click"
                size="small"
                @command="$emit('more', $event, row)"
              >
                <el-button size="small" plain>
                  More
                </el-button>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item command="info">
                      Info
                    </el-dropdown-item>
                    <el-dropdown-item command="restart" :disabled="!canRestartInstance(row)">
                      Restart
                    </el-dropdown-item>
                    <el-dropdown-item command="clear_logs" :disabled="!canModifyStoppedInstanceFiles(row)">
                      Clear Logs
                    </el-dropdown-item>
                    <el-dropdown-item command="remove" :disabled="!canModifyStoppedInstanceFiles(row)">
                      Remove
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

  <div v-else class="external-tool-empty">
    {{ searchText || deviceFilter ? 'No matching instances' : 'No instances yet. Start one from Packages.' }}
  </div>
</template>

<script>
export default {
  name: 'ExternalToolInstancesPanel',
  props: {
    filteredInstances: { type: Array, required: true },
    activeDeviceFilterLabel: { type: String, required: true },
    searchText: { type: String, required: true },
    deviceFilter: { type: String, required: true },
    statusTagType: { type: Function, required: true },
    formatPortInfo: { type: Function, required: true },
    shortTime: { type: Function, required: true },
    canRestartInstance: { type: Function, required: true },
    canModifyStoppedInstanceFiles: { type: Function, required: true },
  },
  emits: ['logs', 'stop', 'more'],
}
</script>

<style scoped>
.strong {
  font-weight: 700;
}

.muted {
  color: var(--muted, #64748b);
}

.external-tool-table-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.external-tool-table-actions :deep(.el-button + .el-button) {
  margin-left: 0;
}

.external-tool-instance-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex: 0 0 auto;
  margin-bottom: 8px;
}

.external-tool-hint {
  color: var(--muted, #64748b);
  font-size: 12px;
}

.external-tool-instance-table-shell {
  flex: 0 0 auto;
  min-height: 0;
  height: 560px;
  overflow: hidden;
}

.external-tool-instance-table {
  width: 100%;
  height: 100% !important;
  border-radius: 12px;
  overflow: hidden;
}

.external-tool-instance-table :deep(.el-table__inner-wrapper),
.external-tool-instance-table :deep(.el-scrollbar),
.external-tool-instance-table :deep(.el-scrollbar__wrap) {
  height: 100% !important;
}

.external-tool-instance-table :deep(.el-scrollbar__wrap) {
  overflow-y: auto !important;
  overflow-x: auto !important;
}

.external-tool-instance-table :deep(.el-table__body-wrapper) {
  overflow-y: auto !important;
}

.external-tool-instance-table :deep(th.el-table__cell) {
  background: #f8fafc !important;
  color: #475569;
  font-weight: 700;
}

.external-tool-instance-table :deep(.el-table__body td.el-table__cell) {
  padding: 10px 0;
}

.external-tool-instance-table :deep(tr) {
  background: #fff;
}

.external-tool-instance-table :deep(.cell) {
  line-height: 1.55;
}

.external-tool-instance-card-shell,
.external-tool-instance-card-list {
  display: none;
}

.external-tool-instance-card-list {
  grid-template-columns: 1fr;
  gap: 12px;
  height: 100%;
  min-height: 0;
  overflow-y: auto;
  padding-right: 2px;
}

.external-tool-instance-card {
  background: #fff;
  border: 1px solid rgba(15, 23, 42, 0.06);
  border-radius: 14px;
  padding: 12px;
  box-shadow: 0 4px 14px rgba(15, 23, 42, 0.04);
}

.external-tool-instance-card-top {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  min-width: 0;
}

.external-tool-instance-icon {
  flex: 0 0 auto;
  width: 22px;
  height: 22px;
  margin-top: 2px;
  border-radius: 999px;
  background: #f8fafc;
  border: 1px solid rgba(15, 23, 42, 0.08);
  display: flex;
  align-items: center;
  justify-content: center;
}

.external-tool-instance-icon span {
  width: 8px;
  height: 8px;
  border-radius: 999px;
  background: var(--muted-2, #94a3b8);
}

.external-tool-instance-icon span.running {
  background: var(--el-color-success);
}

.external-tool-instance-icon span.stale {
  background: var(--el-color-danger);
}

.external-tool-instance-card-main {
  min-width: 0;
  flex: 1;
}

.external-tool-instance-name {
  font-size: 14px;
  font-weight: 700;
  color: var(--text, #0f172a);
  line-height: 1.4;
  word-break: break-word;
}

.external-tool-instance-tags {
  margin-top: 10px;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.external-tool-instance-meta {
  margin-top: 8px;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 6px 10px;
}

.external-tool-instance-meta-item {
  min-width: 0;
}

.external-tool-instance-meta-label {
  font-size: 11px;
  color: var(--muted-2, #94a3b8);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.external-tool-instance-meta-value {
  margin-top: 2px;
  font-size: 12px;
  color: var(--text, #0f172a);
  word-break: break-word;
  line-height: 1.4;
}

.external-tool-instance-card-actions {
  margin-top: 12px;
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  align-items: stretch;
}

.external-tool-instance-card-actions :deep(.el-button),
.external-tool-instance-card-actions :deep(.el-dropdown),
.external-tool-instance-card-actions :deep(.el-dropdown .el-button) {
  width: 100%;
  min-width: 0;
  margin: 0;
}

.external-tool-instance-card-actions :deep(.el-button) {
  min-height: 32px;
  height: 32px;
  border-radius: 10px;
  padding-inline: 12px;
  justify-content: center;
}

.external-tool-instance-card-actions :deep(.el-dropdown) {
  display: block;
}

.external-tool-empty {
  flex: 1 1 auto;
  min-height: 0;
  padding: 64px 16px;
  text-align: center;
  color: var(--muted, #64748b);
}

.external-tool-empty.small {
  padding: 20px 8px;
}

.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
}

.strong {
  font-weight: 700;
}

.muted {
  color: var(--muted, #64748b);
}

@media (max-width: 768px), (max-height: 720px) {
.external-tool-instance-table-shell {
    display: none !important;
  }

.external-tool-instance-card-shell {
    display: flex !important;
    flex: 1 1 auto !important;
    min-height: 0 !important;
    overflow: hidden !important;
  }

.external-tool-instance-card-list {
    display: grid !important;
    flex: 1 1 auto !important;
    min-height: 0 !important;
    overflow-y: auto !important;
  }
}

@media (max-width: 640px) {
.strong {
  font-weight: 700;
}

.muted {
  color: var(--muted, #64748b);
}

.external-tool-instance-meta {
    grid-template-columns: 1fr;
  }

.external-tool-instance-card-actions {
    grid-template-columns: 1fr;
    gap: 6px;
  }
}
</style>
