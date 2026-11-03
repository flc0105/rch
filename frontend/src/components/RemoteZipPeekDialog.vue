<template>
  <el-dialog
    v-model="visible"
    :title="dialogTitle"
    width="1080px"
    top="5vh"
    append-to-body
    class="remote-zip-peek-dialog"
    @closed="resetState"
  >
    <div class="remote-zip-peek-body" v-loading="loading">
      <div v-if="archiveInfo" class="remote-zip-peek-summary">
        <span class="mono" :title="archiveInfo.path">{{ archiveInfo.name }}</span>
        <span>{{ formatBytes(archiveInfo.archive_size) }}</span>
        <span>{{ archiveInfo.file_count }} files</span>
        <span>{{ archiveInfo.dir_count }} folders</span>
        <span>{{ archiveInfo.entry_count }} entries</span>
        <span>Expanded {{ formatBytes(archiveInfo.uncompressed_size) }}</span>
      </div>

      <div v-if="loadError" class="remote-zip-peek-error">
        <div class="remote-zip-peek-error-title">ZIP preview unavailable</div>
        <div>{{ loadError }}</div>
        <div class="remote-zip-peek-hint">
          Peek limits are 2 GB archive size and 5000 entries.
        </div>
      </div>

      <div v-else-if="archiveInfo" class="remote-zip-peek-layout">
        <div class="remote-zip-peek-tree-panel">
          <div class="remote-zip-peek-panel-toolbar">
            <span>Archive Tree</span>
            <div class="remote-zip-peek-panel-actions">
              <el-button size="small" link @click="setAllExpanded(true)">Expand All</el-button>
              <el-button size="small" link @click="setAllExpanded(false)">Collapse All</el-button>
            </div>
          </div>

          <div class="remote-zip-peek-tree-shell">
            <el-tree
              ref="zipTreeRef"
              :data="archiveInfo.tree || []"
              node-key="path"
              :props="zipTreeProps"
              :default-expanded-keys="defaultExpandedKeys"
              highlight-current
              @node-click="handleTreeNodeClick"
            >
              <template #default="{ data }">
                <div class="remote-zip-peek-tree-row" :title="data.path">
                  <span class="remote-zip-peek-tree-icon">{{ data.is_dir ? '📁' : '📄' }}</span>
                  <span class="remote-zip-peek-tree-name">{{ data.name }}</span>
                  <span v-if="!data.is_dir" class="remote-zip-peek-tree-size">
                    {{ formatBytes(data.size) }}
                  </span>
                </div>
              </template>
            </el-tree>
          </div>
        </div>

        <div class="remote-zip-peek-content-panel">
          <div class="remote-zip-peek-panel-toolbar">
            <span class="ellipsis" :title="selectedEntry?.path || ''">
              {{ selectedEntry?.path || 'File Content' }}
            </span>
            <span v-if="selectedEntry && !selectedEntry.is_dir" class="remote-zip-peek-entry-meta">
              {{ formatBytes(selectedEntry.size) }}
            </span>
          </div>

          <div class="remote-zip-peek-content-shell" v-loading="entryLoading">
            <pre v-if="entryType === 'text'" class="remote-zip-peek-content">{{ entryContent }}</pre>

            <div v-else-if="entryError" class="remote-zip-peek-empty remote-zip-peek-entry-error">
              {{ entryError }}
            </div>

            <div v-else class="remote-zip-peek-empty">
              Select a file from the archive tree. Files larger than 2 MB and binary files are not loaded.
            </div>
          </div>
        </div>
      </div>
    </div>

    <template #footer>
      <el-button size="small" @click="visible = false">Close</el-button>
    </template>
  </el-dialog>
</template>

<script>
import { inspectRemoteZip, readRemoteZipEntry } from '../api/remoteFilesApi.js'
import { formatBytes as formatBytesValue } from '../utils/formatters.js'

export default {
  name: 'RemoteZipPeekDialog',

  props: {
    selectedId: {
      type: String,
      default: '',
    },
  },

  data() {
    return {
      visible: false,
      loading: false,
      entryLoading: false,
      archivePath: '',
      archiveName: '',
      archiveInfo: null,
      loadError: '',
      selectedEntry: null,
      entryType: '',
      entryContent: '',
      entryError: '',
      defaultExpandedKeys: [],
      zipTreeProps: {
        children: 'children',
        label: 'name',
      },
    }
  },

  computed: {
    dialogTitle() {
      return this.archiveName ? `Peek ZIP · ${this.archiveName}` : 'Peek ZIP'
    },
  },

  methods: {
    formatBytes(value) {
      return formatBytesValue(value)
    },

    async open(row) {
      if (!this.selectedId || !row?.path) return

      this.resetState()
      this.archivePath = String(row.path || '').trim()
      this.archiveName = String(row.name || '').trim() || 'archive.zip'
      this.visible = true
      this.loading = true

      try {
        const res = await inspectRemoteZip(this.selectedId, this.archivePath)
        const json = await res.json()

        if (!res.ok || json.code !== 0) {
          throw new Error(json.message || 'Failed to inspect ZIP archive')
        }

        this.archiveInfo = json.data || null
        const roots = Array.isArray(this.archiveInfo?.tree) ? this.archiveInfo.tree : []
        this.defaultExpandedKeys = roots
          .filter(item => item?.is_dir)
          .slice(0, 1)
          .map(item => item.path)
      } catch (e) {
        this.loadError = e?.message || 'Failed to inspect ZIP archive'
      } finally {
        this.loading = false
      }
    },

    async handleTreeNodeClick(data) {
      if (!data || data.is_dir || !data.entry_name) return

      this.selectedEntry = data
      this.entryType = ''
      this.entryContent = ''
      this.entryError = ''
      this.entryLoading = true

      try {
        const res = await readRemoteZipEntry(this.selectedId, this.archivePath, data.entry_name)
        const json = await res.json()

        if (!res.ok || json.code !== 0) {
          throw new Error(json.message || 'Failed to read ZIP entry')
        }

        const payload = json.data || {}
        this.entryType = payload.type || ''
        if (this.entryType === 'text') {
          this.entryContent = String(payload.content || '')
        } else {
          this.entryError = payload.message || 'This archive entry cannot be previewed as text'
        }
      } catch (e) {
        this.entryError = e?.message || 'Failed to read ZIP entry'
      } finally {
        this.entryLoading = false
      }
    },

    setAllExpanded(expanded) {
      const tree = this.$refs.zipTreeRef
      const rootNodes = tree?.store?.root?.childNodes || []

      const apply = (nodes) => {
        for (const node of nodes) {
          node.expanded = !!expanded
          if (node.childNodes?.length) apply(node.childNodes)
        }
      }

      apply(rootNodes)
    },

    resetState() {
      this.loading = false
      this.entryLoading = false
      this.archivePath = ''
      this.archiveName = ''
      this.archiveInfo = null
      this.loadError = ''
      this.selectedEntry = null
      this.entryType = ''
      this.entryContent = ''
      this.entryError = ''
      this.defaultExpandedKeys = []
    },
  },
}
</script>

<style scoped>
.remote-zip-peek-body {
  min-height: 620px;
}

.remote-zip-peek-summary {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
  margin-bottom: 12px;
  padding: 10px 12px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #f8fafc;
  color: #64748b;
  font-size: 12px;
}

.remote-zip-peek-summary > :first-child {
  max-width: 320px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #334155;
  font-weight: 650;
}

.remote-zip-peek-layout {
  display: grid;
  grid-template-columns: minmax(300px, 36%) minmax(0, 1fr);
  gap: 12px;
  height: 570px;
}

.remote-zip-peek-tree-panel,
.remote-zip-peek-content-panel {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
}

.remote-zip-peek-panel-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-height: 38px;
  padding: 0 10px;
  border-bottom: 1px solid #e2e8f0;
  background: #f8fafc;
  color: #334155;
  font-size: 12px;
  font-weight: 650;
}

.remote-zip-peek-panel-actions {
  display: flex;
  align-items: center;
  gap: 4px;
}

.remote-zip-peek-tree-shell,
.remote-zip-peek-content-shell {
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
}

.remote-zip-peek-tree-shell {
  padding: 8px 4px;
}

.remote-zip-peek-tree-row {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  min-width: 0;
  padding-right: 8px;
}

.remote-zip-peek-tree-name {
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.remote-zip-peek-tree-size,
.remote-zip-peek-entry-meta {
  flex: 0 0 auto;
  color: #94a3b8;
  font-size: 11px;
  font-weight: 400;
}

.remote-zip-peek-content {
  min-height: 100%;
  margin: 0;
  padding: 14px;
  box-sizing: border-box;
  white-space: pre;
  overflow: auto;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
  font-size: 12px;
  line-height: 1.55;
  color: #1e293b;
  background: #fff;
}

.remote-zip-peek-empty,
.remote-zip-peek-error {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 180px;
  padding: 24px;
  text-align: center;
  color: #64748b;
  line-height: 1.6;
}

.remote-zip-peek-error {
  flex-direction: column;
  gap: 8px;
  min-height: 540px;
  border: 1px solid #fecaca;
  border-radius: 8px;
  background: #fff7f7;
  color: #b91c1c;
}

.remote-zip-peek-error-title {
  font-size: 16px;
  font-weight: 700;
}

.remote-zip-peek-hint {
  color: #64748b;
  font-size: 12px;
}

.remote-zip-peek-entry-error {
  color: #b45309;
}

.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
}

.ellipsis {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

@media (max-width: 780px) {
  .remote-zip-peek-layout {
    grid-template-columns: 1fr;
    height: auto;
  }

  .remote-zip-peek-tree-panel,
  .remote-zip-peek-content-panel {
    min-height: 320px;
  }

  .remote-zip-peek-summary {
    flex-wrap: wrap;
  }
}
</style>
