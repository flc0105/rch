<template>
  <div
      v-if="previewType === 'image' || previewType === 'text'"
      class="preview-toolbar"
  >
    <div class="preview-toolbar-left">
      <el-button v-if="previewSource === 'remote_file' && previewCacheArtifactId"
                 size="small" :loading="previewSaving" @click="$emit('save-to-saved')">
        Save to Saved Files
      </el-button>
      <template v-if="previewType === 'text'">
        <!--            <el-button-->
        <!--              size="small"-->
        <!--              @click="$emit('copy')"-->
        <!--            >-->
        <!--              Copy-->
        <!--            </el-button>-->

        <el-button
            size="small"
            @click="$emit('copy')"
        >
          Copy
        </el-button>


        <el-button
            v-if="!previewEditMode && !previewTruncated && previewEditable"
            size="small"
            type="primary"
            @click="$emit('edit')"
        >
          Edit
        </el-button>


        <template v-else-if="previewEditMode">
          <el-button
              size="small"
              type="primary"
              :loading="previewSaving"
              @click="$emit('save')"
          >
            Save
          </el-button>

          <el-dropdown trigger="click" @command="$emit('more', $event)">
            <el-button size="small">More</el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="paste">Paste</el-dropdown-item>
                <el-dropdown-item command="clear">Clear</el-dropdown-item>
                <el-dropdown-item
                    command="reload"
                    :disabled="previewSaving || previewReloading"
                >
                  Reload
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>


          <el-button
              size="small"
              :disabled="previewSaving || previewReloading"
              @click="$emit('cancel-edit')"
          >
            Cancel
          </el-button>


        </template>
      </template>

      <template v-if="previewType === 'image' && previewUrl">
        <el-button
            v-if="previewImageInfo"
            size="small"
            @click="$emit('image-info')"
        >
          Image Info
        </el-button>

        <el-button
            size="small"
            @click="$emit('open-original')"
        >
          Open Original
        </el-button>
      </template>
    </div>

    <div class="preview-toolbar-right">
      <template v-if="previewType === 'text'">
        <div class="preview-info-tags">
          <el-tag
              size="small"
              type="primary"
          >
            {{ previewSourceLabel }}
          </el-tag>

          <el-tag
              size="small"
              type="info"
          >
            {{ previewFileSize }}
          </el-tag>

          <el-tag
              size="small"
              :type="previewFileCodec === 'unknown' ? 'warning' : 'info'"
          >
            {{ previewFileEncoding }}
          </el-tag>

          <el-tag
              size="small"
              type="info"
          >
            {{ previewDetectedLanguage }}
          </el-tag>

          <el-tag
              v-if="previewTruncated"
              size="small"
              type="danger"
          >
            Truncated
          </el-tag>
        </div>
      </template>
    </div>
  </div>
</template>

<script>

export default {
  name: 'PreviewToolbar',
  props: {
    previewType: { type: String, required: true },
    previewSource: { type: String, required: true },
    previewCacheArtifactId: { type: String, required: true },
    previewSaving: { type: Boolean, required: true },
    previewEditMode: { type: Boolean, required: true },
    previewTruncated: { type: Boolean, required: true },
    previewEditable: { type: Boolean, required: true },
    previewReloading: { type: Boolean, required: true },
    previewUrl: { type: String, required: true },
    previewImageInfo: { type: Object, default: null },
    previewSourceLabel: { type: String, required: true },
    previewFileSize: { type: String, required: true },
    previewFileCodec: { type: String, required: true },
    previewFileEncoding: { type: String, required: true },
    previewDetectedLanguage: { type: String, required: true },
  },
  emits: ['save-to-saved', 'copy', 'edit', 'save', 'cancel-edit', 'image-info', 'open-original', 'more'],
}
</script>

<style scoped>
.preview-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--line);
  flex-wrap: wrap;
  gap: 12px;
}

.preview-toolbar-left {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}

.preview-toolbar-right {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}

.preview-info-tags {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}

.preview-info-tags :deep(.el-tag) {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 0 8px;
  height: 26px;
  line-height: 26px;
}

.preview-info-tags :deep(.el-tag .el-icon) {
  font-size: 14px;
}

.preview-toolbar-left :deep(.el-button) {
  margin-left: 0;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 6px 16px;
  height: 26px;
}

.preview-toolbar-left :deep(.el-button .el-icon) {
  font-size: 14px;
}

@media (max-width: 768px), (max-height: 720px) {
  .preview-toolbar {
      flex-direction: column;
      align-items: flex-start;
      flex: 0 0 auto;
      margin-bottom: 10px;
      padding-bottom: 10px;
    }

  .preview-toolbar-left,
    .preview-toolbar-right {
      width: 100%;
    }

  .preview-info-tags {
      justify-content: flex-start;
    }
}
</style>
