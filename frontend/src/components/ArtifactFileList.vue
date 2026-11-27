<template>
    <section class="artifact-main-panel">
      <div class="artifact-location">
        <span class="artifact-location-title" :title="currentFolderLabel">{{ currentFolderLabel }}</span>
        <span class="artifact-location-count">{{ filteredArtifactItems.length }} files</span>
      </div>

      <div class="dialog-table-shell">
    <el-table
      ref="artifactTableRef"
      :data="filteredArtifactItems"
      v-loading="artifactLoading"
      stripe
      width="100%"
      height="100%"
      empty-text="No artifacts available"
      table-layout="fixed"
      row-key="artifact_id"
      @selection-change="handleTableSelectionChange"
    >
      <el-table-column
        type="selection"
        width="40"
        align="center"
      />
      <el-table-column
        prop="original_name"
        label="Name"
        min-width="240"
        show-overflow-tooltip
      >

        <template #default="{ row }">
          <div class="artifact-file-name" :title="formatArtifactName(row)">
            <File :size="16" aria-hidden="true" />
            <span class="ellipsis">{{ formatArtifactName(row) }}</span>
          </div>
        </template>
      </el-table-column>

      <el-table-column
        label="Size"
        width="104"
        align="right"
        show-overflow-tooltip
      >
        <template #default="{ row }">
          <span class="ellipsis" :title="formatBytes(row.size)">{{ formatBytes(row.size) }}</span>
        </template>
      </el-table-column>


      <el-table-column
        label="Saved"
        width="166"
        show-overflow-tooltip
      >
        <template #default="{ row }">
          <div class="ellipsis">
            {{ row.saved_at || '-' }}
          </div>
        </template>
      </el-table-column>

      <el-table-column
        label="Actions"
        width="188"
        align="center"
      >
        <template #default="{ row }">
          <div class="table-actions table-actions-links">
            <a
              href="#"
              class="table-action-link"
              @click.prevent="$emit('preview', row)"
            >
              Preview
            </a>

            <a
              class="table-action-link"
              :href="row.download_url"
              target="_blank"
            >
              Download
            </a>

            <template v-if="useArtifactMoreMenu(row)">

              <ArtifactActionMenu :shared="isSharedFileItem(row)" :standalone-mode="standaloneMode"
                                  :selected-id="selectedId" send-label="Send to Current Device"
                                  @command="command => $emit('more', row, command)">
                <span class="table-action-link">More</span>
              </ArtifactActionMenu>
            </template>

            <a
              v-else
              href="#"
              class="table-action-link danger"
              @click.prevent="$emit('delete', row)"
            >
              Delete
            </a>
          </div>
        </template>
      </el-table-column>
    </el-table>
  </div>

  <div class="mobile-file-list-shell">
    <div
      class="mobile-file-list"
      v-loading="artifactLoading"
    >
      <div
        v-if="!filteredArtifactItems.length && !artifactLoading"
        class="empty-state"
      >
        No artifacts available
      </div>

      <div
        v-else
        class="mobile-file-grid"
      >
        <div
          v-for="row in filteredArtifactItems"
          :key="row.artifact_id"
          class="mobile-file-card"
        >
          <div class="mobile-file-check-anchor">
            <el-checkbox
              :model-value="isArtifactSelected(row)"
              @change="checked => $emit('toggle-selection', row, checked)"
            />
          </div>

          <div class="mobile-file-card-top">
            <div class="mobile-file-icon"><File :size="20" aria-hidden="true" /></div>

            <div class="mobile-file-main">
              <div class="mobile-file-name">
                {{ formatArtifactName(row) }}
              </div>

              <div class="mobile-file-meta">
                <div class="mobile-file-meta-item">
                  <div class="mobile-file-meta-label">Size</div>
                  <div class="mobile-file-meta-value">
                    {{ formatBytes(row.size) }}
                  </div>
                </div>

                <div class="mobile-file-meta-item">
                  <div class="mobile-file-meta-label">Created</div>
                  <div class="mobile-file-meta-value">
                    {{ row.saved_at || '-' }}
                  </div>
                </div>
              </div>

              <div class="mobile-file-actions">
                <el-button
                  size="small"
                  type="primary"
                  plain
                  @click="$emit('preview', row)"
                >
                  Preview
                </el-button>

                <a :href="row.download_url" target="_blank">
                  <el-button size="small" type="primary" plain>
                    Download
                  </el-button>
                </a>

                <template v-if="useArtifactMoreMenu(row)">

                  <ArtifactActionMenu :shared="isSharedFileItem(row)" :standalone-mode="standaloneMode"
                                      :selected-id="selectedId" send-label="Send"
                                      @command="command => $emit('more', row, command)">
                    <el-button size="small" type="primary" plain>More</el-button>
                  </ArtifactActionMenu>
                </template>

                <el-button
                  v-else
                  size="small"
                  type="danger"
                  plain
                  @click="$emit('delete', row)"
                >
                  Delete
                </el-button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
      </div>
    </section>
</template>

<script>
import { File } from '@lucide/vue'
import ArtifactActionMenu from './ArtifactActionMenu.vue'
import { formatBytes } from '../utils/formatters.js'
import { formatArtifactName, isSharedFileItem, useArtifactMoreMenu } from '../utils/artifactPresentation.js'
export default {
  name: 'ArtifactFileList',
  props: {
    currentFolderLabel: { type: String, required: true },
    filteredArtifactItems: { type: Array, required: true },
    artifactLoading: { type: Boolean, required: true },
    selectedArtifactIds: { type: Array, required: true },
    standaloneMode: { type: Boolean, required: true },
    selectedId: { type: [String, Number], required: true },
  },
  emits: ['selection-change', 'toggle-selection', 'preview', 'more', 'delete'],
  components: { File, ArtifactActionMenu },
  data: () => ({ synchronizingSelection: false }),
  watch: {
    selectedArtifactIds: { handler: 'syncTableSelection', flush: 'post' },
  },
  mounted() { this.syncTableSelection() },
  methods: {
    formatBytes, formatArtifactName, isSharedFileItem, useArtifactMoreMenu,
    handleTableSelectionChange(rows) {
      if (!this.synchronizingSelection) this.$emit('selection-change', rows)
    },
    syncTableSelection() {
      const table = this.$refs.artifactTableRef
      if (!table) return
      const selected = new Set(this.selectedArtifactIds)
      const actual = new Set(table.getSelectionRows().map(row => String(row.artifact_id || '').trim()))
      this.synchronizingSelection = true
      try {
        for (const row of this.filteredArtifactItems) {
          const id = String(row.artifact_id || '').trim()
          if (selected.has(id) !== actual.has(id)) table.toggleRowSelection(row, selected.has(id))
        }
      } finally {
        this.synchronizingSelection = false
      }
    },
    isArtifactSelected(row) {
      const artifactId = String(row?.artifact_id || '').trim()
      return Boolean(artifactId && this.selectedArtifactIds.includes(artifactId))
    },

  },
}
</script>
