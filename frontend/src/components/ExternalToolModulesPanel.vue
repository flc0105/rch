<template>
  <div class="external-tool-modules-panel">
    <div class="external-tool-detail-section-title">Modules</div>
    <div v-if="modules.length" class="external-tool-package-modules detail">
      <div
        v-for="module in modules"
        :key="module.id"
        class="external-tool-package-module-card"
      >
        <div class="external-tool-package-module-content">
          <div class="external-tool-package-module-title-row">
            <span class="strong">{{ module.display_name || module.id }}</span>
            <el-tag size="small" :type="getExecutionTagType(module)">{{ formatExecutionLabel(module) }}</el-tag>
          </div>
          <div class="external-tool-package-module-desc" :title="module.description || ''">
            {{ module.description || 'No description' }}
          </div>
        </div>
        <el-button
          size="small"
          type="primary"
          plain
          :disabled="!canRunModuleAction(module)"
          @click.stop="$emit('run', module)"
        >
          {{ getRunButtonLabel(module) }}
        </el-button>
      </div>
    </div>
    <div v-else class="external-tool-empty small">
      No runnable modules.
    </div>
  </div>
</template>

<script>
import { formatExecutionLabel, getExecutionTagType, getRunButtonLabel } from '../utils/externalToolPresentation.js'

export default {
  name: 'ExternalToolModulesPanel',
  props: {
    modules: { type: Array, required: true },
    canRunModuleAction: { type: Function, required: true },
  },
  emits: ['run'],
  methods: { formatExecutionLabel, getExecutionTagType, getRunButtonLabel },
}
</script>

<style scoped>
.external-tool-package-detail-section {
  margin-top: 18px;
}

.external-tool-package-modules.detail {
  margin-top: 10px;
}

.external-tool-package-modules {
  margin-top: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.external-tool-modules-panel {
  padding: 14px;
  border: 1px solid rgba(15, 23, 42, 0.06);
  border-radius: 14px;
  background: #f8fafc;
}

.external-tool-package-module-card {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 12px;
  border: 1px solid rgba(15, 23, 42, 0.06);
  border-radius: 12px;
  background: #fff;
  box-shadow: 0 2px 10px rgba(15, 23, 42, 0.03);
}

.external-tool-package-module-content {
  min-width: 0;
  flex: 1 1 auto;
}

.external-tool-package-module-title-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.external-tool-package-module-desc {
  margin-top: 6px;
  color: var(--muted, #64748b);
  font-size: 13px;
  line-height: 1.45;
}

.strong {
  font-weight: 700;
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

.external-tool-detail-section-title {
  padding: 0 0 8px;
  font-weight: 700;
  border-bottom: 0;
  background: transparent;
}

.strong {
  font-weight: 700;
}

@media (max-width: 960px) {
.external-tool-package-mobile-modules {
    margin-top: 12px;
  }

.external-tool-package-mobile-modules .external-tool-package-module-card {
    flex-direction: column;
    align-items: stretch;
  }

.external-tool-package-mobile-modules .external-tool-package-module-card > .el-button {
    width: 100%;
    min-height: 32px;
    height: 32px;
    border-radius: 10px;
    padding-inline: 12px;
    justify-content: center;
    margin-left: 0;
  }
}

@media (max-width: 640px) {
.external-tool-package-modules {
  margin-top: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.strong {
  font-weight: 700;
}

.external-tool-package-module-card {
    flex-direction: column;
  }

.external-tool-package-module-card > .el-button {
    width: 100%;
  }
}
</style>
