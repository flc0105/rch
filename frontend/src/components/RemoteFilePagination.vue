<template>
      <div class="dialog-pagination-wrap">
        <div class="dialog-pagination-bar">
          <div class="dialog-pagination-meta">

            <span v-if="hasRemoteClipboard">
              {{ remoteClipboardActionText }} {{ remoteClipboardPaths.length }} ·
            </span>

            <span v-if="isRemoteSearchActive">
              Search "{{ normalizeRemoteSearchKeyword() }}"{{ remoteSearchRecursive ? ' recursively' : '' }} ·
            </span>

            <span>Visible {{ remoteFilesTotal }} </span>

            <span v-if="!showHiddenFiles && remoteFilesHiddenTotal > 0">
              · Hidden {{ remoteFilesHiddenTotal }}
            </span>

            <span v-if="remoteFilesAllTotal > remoteFilesTotal">
              · All {{ remoteFilesAllTotal }}
            </span>

            <span v-if="remoteFilesTotalPages > 1">
              · Page {{ remoteFilesPage }} / {{ remoteFilesTotalPages }}
            </span>

          </div>

          <el-pagination
              background
              layout="total, sizes, prev, pager, next"
              :prev-icon="paginationPrevIcon" :next-icon="paginationNextIcon"
              :current-page="remoteFilesPage"
              :page-size="remoteFilesPageSize"
              :page-sizes="remoteFilesPageSizeOptions"
              :total="remoteFilesTotal"
              :pager-count="5"
              @current-change="handleRemotePageChange"
              @size-change="handleRemotePageSizeChange"
          />
        </div>
      </div>

      <div class="remote-mobile-pagination" aria-label="Remote file pagination">
        <div class="remote-mobile-pagination-meta">
          <span class="remote-mobile-total-count">{{ remoteFilesTotal }} items</span>
          <el-dropdown trigger="click" popper-class="remote-mobile-page-size-popper" @command="handleRemotePageSizeChange">
            <button type="button" class="remote-mobile-page-size-button" aria-label="Items per page">
              {{ remoteFilesPageSize }}/page <ChevronDown :size="13" aria-hidden="true" />
            </button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item
                    v-for="size in remoteFilesPageSizeOptions"
                    :key="`mobile-page-size-${size}`"
                    :command="size"
                >
                  {{ size }} per page
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>

        <nav class="remote-mobile-page-controls" aria-label="Pages">
          <button
              type="button"
              class="remote-mobile-page-button remote-mobile-page-arrow"
              aria-label="Previous page"
              :disabled="remoteFilesPage <= 1"
              @click="handleRemotePageChange(remoteFilesPage - 1)"
          ><ChevronLeft :size="17" aria-hidden="true" /></button>
          <template v-for="item in remoteMobilePageItems" :key="item.key">
            <span v-if="item.type === 'ellipsis'" class="remote-mobile-page-ellipsis" aria-hidden="true">…</span>
            <button
                v-else
                type="button"
                class="remote-mobile-page-button"
                :class="{ active: item.page === remoteFilesPage }"
                :aria-current="item.page === remoteFilesPage ? 'page' : undefined"
                :aria-label="`Page ${item.page}`"
                @click="handleRemotePageChange(item.page)"
            >{{ item.page }}</button>
          </template>
          <button
              type="button"
              class="remote-mobile-page-button remote-mobile-page-arrow"
              aria-label="Next page"
              :disabled="remoteFilesPage >= remoteFilesTotalPages"
              @click="handleRemotePageChange(remoteFilesPage + 1)"
          ><ChevronRight :size="17" aria-hidden="true" /></button>
        </nav>
      </div>
</template>

<script>
import { ChevronLeft, ChevronRight, ChevronDown } from '@lucide/vue'

export default {
  components: { ChevronLeft, ChevronRight, ChevronDown },
  name: 'RemoteFilePagination',
  props: {
    hasRemoteClipboard: { type: Boolean, required: true },
    remoteClipboardActionText: { type: String, required: true },
    remoteClipboardPaths: { type: Array, required: true },
    isRemoteSearchActive: { type: Boolean, required: true },
    remoteSearchKeyword: { type: String, required: true },
    remoteSearchRecursive: { type: Boolean, required: true },
    remoteFilesTotal: { type: Number, required: true },
    showHiddenFiles: { type: Boolean, required: true },
    remoteFilesHiddenTotal: { type: Number, required: true },
    remoteFilesAllTotal: { type: Number, required: true },
    remoteFilesTotalPages: { type: Number, required: true },
    remoteFilesPage: { type: Number, required: true },
    remoteFilesPageSize: { type: Number, required: true },
  },
  emits: ['page-change', 'page-size-change'],
  data() { return { remoteFilesPageSizeOptions: [50, 100, 200] } },
  computed: {
    paginationPrevIcon() { return ChevronLeft },
    paginationNextIcon() { return ChevronRight },
    remoteMobilePageItems() {
      const total = Math.max(1, Number(this.remoteFilesTotalPages) || 1)
      const current = Math.min(total, Math.max(1, Number(this.remoteFilesPage) || 1))
      let pages

      if (total <= 5) {
        pages = Array.from({ length: total }, (_, index) => index + 1)
      } else if (current <= 4) {
        pages = [1, 2, 3, 4, 'ellipsis', total]
      } else if (current >= total - 3) {
        pages = [1, 'ellipsis', total - 3, total - 2, total - 1, total]
      } else {
        pages = [1, 'ellipsis', current - 1, current, current + 1, 'ellipsis', total]
      }

      return pages.map((page, index) => page === 'ellipsis'
        ? { type: 'ellipsis', key: `ellipsis-${index}` }
        : { type: 'page', page, key: `page-${page}` })
    },
  },
  methods: {
    handleRemotePageChange(...args) { this.$emit('page-change', ...args) },
    handleRemotePageSizeChange(...args) { this.$emit('page-size-change', ...args) },
    normalizeRemoteSearchKeyword() { return String(this.remoteSearchKeyword || '').trim() },
  },
}
</script>
