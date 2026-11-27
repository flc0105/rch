<template>
  <div v-if="filteredModules.length" class="external-tool-package-split">
    <div class="external-tool-package-list-panel">
      <div class="external-tool-package-list">
        <div
          v-for="item in filteredModules"
          :key="item.id"
          class="external-tool-card external-tool-package-list-card"
          :class="{ active: selectedPackage?.id === item.id }"
          @click="$emit('select', item)"
        >
          <div class="external-tool-card-main">
            <div class="external-tool-package-list-title" :title="item.display_name || item.id">
              {{ item.display_name || item.id }}
            </div>
            <div class="external-tool-package-list-status">
              <el-tag
                v-if="getModuleInstallStatus(item).label"
                size="small"
                :type="getModuleInstallStatus(item).type"
                effect="plain"
              >
                {{ getModuleInstallStatus(item).label }}
              </el-tag>
              <span v-else class="muted small-text">Unknown</span>
              <template v-if="selectedPackage?.id === item.id">
                <el-tag size="small" type="info" class="external-tool-package-list-mobile-meta-tag">
                  {{ formatPlatforms(item.platforms) }}
                </el-tag>
                <el-tag
                  v-if="item.version"
                  size="small"
                  type="info"
                  class="external-tool-package-list-mobile-meta-tag"
                >
                  {{ formatVersionLabel(item.version) }}
                </el-tag>
              </template>
            </div>
            <div class="external-tool-package-list-desc" :title="item.description || ''">
              {{ item.description || 'No description' }}
            </div>

            <div
              v-if="selectedPackage?.id === item.id"
              class="external-tool-package-mobile-detail"
              @click.stop
            >
              <div class="external-tool-package-mobile-actions">
                <el-button
                  class="external-tool-package-mobile-action-button"
                  size="small"
                  type="primary"
                  plain
                  :disabled="!canInstallPackageAction(item)"
                  @click.stop="$emit('install', item)"
                >
                  {{ getInstallMenuLabel(item) }}
                </el-button>

                <el-dropdown
                  trigger="click"
                  size="small"
                  @command="$emit('more', $event, item)"
                >
                  <el-button
                    class="external-tool-package-mobile-action-button"
                    size="small"
                    plain
                    @click.stop
                  >
                    More
                  </el-button>
                  <template #dropdown>
                    <el-dropdown-menu>
                      <el-dropdown-item command="download">
                        Download Zip
                      </el-dropdown-item>
                      <el-dropdown-item command="edit">
                        Edit Metadata
                      </el-dropdown-item>
                      <el-dropdown-item divided command="status" :disabled="!canUsePackageAction(item)">
                        Install Status
                      </el-dropdown-item>
                      <el-dropdown-item command="copy" :disabled="!canUsePackageAction(item)">
                        Copy Command
                      </el-dropdown-item>
                      <el-dropdown-item
                        command="clear_cache"
                        divided
                        :disabled="!canUsePackageAction(item)"
                      >
                        Clear Package Cache
                      </el-dropdown-item>
                      <el-dropdown-item
                        command="uninstall"
                        :disabled="!canUninstallPackageAction(item)"
                      >
                        {{ getUninstallMenuLabel(item) }}
                      </el-dropdown-item>
                    </el-dropdown-menu>
                  </template>
                </el-dropdown>
              </div>

              <ExternalToolModulesPanel
                class="external-tool-package-mobile-modules"
                :modules="getPackageModules(item)"
                :can-run-module-action="canRunModuleAction"
                @run="$emit('run', $event)"
              />
            </div>
          </div>
        </div>
      </div>
    </div>

    <div class="external-tool-package-detail-panel">
      <div v-if="selectedPackage" class="external-tool-package-detail-card">
        <div class="external-tool-package-detail-header">
          <div class="external-tool-package-detail-main">
            <div class="external-tool-title large" :title="selectedPackage.display_name || selectedPackage.id">
              {{ selectedPackage.display_name || selectedPackage.id }}
            </div>
            <div class="external-tool-package-detail-tags">
              <el-tag size="small" type="info">
                {{ formatPlatforms(selectedPackage.platforms) }}
              </el-tag>
              <el-tag v-if="selectedPackage.version" size="small" type="info">
                {{ formatVersionLabel(selectedPackage.version) }}
              </el-tag>
              <el-tag
                v-if="getModuleInstallStatus(selectedPackage).label"
                size="small"
                :type="getModuleInstallStatus(selectedPackage).type"
                effect="plain"
              >
                {{ getModuleInstallStatus(selectedPackage).label }}
              </el-tag>
            </div>
            <div class="external-tool-desc external-tool-package-detail-desc" :title="selectedPackage.description || ''">
              {{ selectedPackage.description || 'No description' }}
            </div>
          </div>

          <div class="external-tool-package-detail-actions">
            <div class="external-tool-package-detail-action-row">
              <el-button
                class="external-tool-package-detail-action-button"
                size="small"
                type="primary"
                plain
                :disabled="!canInstallPackageAction(selectedPackage)"
                @click="$emit('install', selectedPackage)"
              >
                {{ getInstallMenuLabel(selectedPackage) }}
              </el-button>

              <el-dropdown
                trigger="click"
                size="small"
                @command="$emit('more', $event, selectedPackage)"
              >
                <el-button class="external-tool-package-detail-action-button" size="small" plain>
                  More
                </el-button>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item command="download">
                      Download Zip
                    </el-dropdown-item>
                    <el-dropdown-item command="edit">
                      Edit Metadata
                    </el-dropdown-item>
                    <el-dropdown-item divided command="status" :disabled="!canUsePackageAction(selectedPackage)">
                      Install Status
                    </el-dropdown-item>
                    <el-dropdown-item command="copy" :disabled="!canUsePackageAction(selectedPackage)">
                      Copy Command
                    </el-dropdown-item>
                    <el-dropdown-item
                      command="clear_cache"
                      divided
                      :disabled="!canUsePackageAction(selectedPackage)"
                    >
                      Clear Package Cache
                    </el-dropdown-item>
                    <el-dropdown-item
                      command="uninstall"
                      :disabled="!canUninstallPackageAction(selectedPackage)"
                    >
                      {{ getUninstallMenuLabel(selectedPackage) }}
                    </el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </div>
          </div>
        </div>

        <ExternalToolModulesPanel
                class="external-tool-package-detail-section"
                :modules="getPackageModules(selectedPackage)"
                :can-run-module-action="canRunModuleAction"
                @run="$emit('run', $event)"
              />
      </div>
      <div v-else class="external-tool-empty">
        Select a package.
      </div>
    </div>
  </div>

  <div v-else class="external-tool-empty">
    {{ searchText ? 'No matching external tool packages' : 'No external tool meta files found' }}
  </div>
</template>

<script>
import ExternalToolModulesPanel from './ExternalToolModulesPanel.vue'

export default {
  name: 'ExternalToolPackagesPanel',
  components: { ExternalToolModulesPanel },
  props: {
    filteredModules: { type: Array, required: true },
    selectedPackage: { type: Object, default: null },
    searchText: { type: String, required: true },
    getPackageModules: { type: Function, required: true },
    getModuleInstallStatus: { type: Function, required: true },
    formatPlatforms: { type: Function, required: true },
    formatVersionLabel: { type: Function, required: true },
    canInstallPackageAction: { type: Function, required: true },
    getInstallMenuLabel: { type: Function, required: true },
    canUsePackageAction: { type: Function, required: true },
    canUninstallPackageAction: { type: Function, required: true },
    getUninstallMenuLabel: { type: Function, required: true },
    canRunModuleAction: { type: Function, required: true },
  },
  emits: ['select', 'install', 'more', 'run'],
}
</script>

<style scoped>
.external-tool-package-split {
  flex: 1 1 auto;
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(280px, 360px) minmax(0, 1fr);
  gap: 14px;
  overflow: hidden;
}

.external-tool-package-list-panel,
.external-tool-package-detail-panel {
  min-height: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.external-tool-package-list {
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding-right: 4px;
}

.external-tool-package-list-card {
  cursor: pointer;
  transition: border-color 0.15s ease, box-shadow 0.15s ease, background 0.15s ease;
}

.external-tool-package-list-card.active {
  border-color: rgba(59, 130, 246, 0.45);
  box-shadow: 0 6px 18px rgba(37, 99, 235, 0.12);
  background: #f8fbff;
}

.external-tool-package-list-title {
  font-size: 15px;
  font-weight: 700;
  color: var(--text, #0f172a);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.external-tool-package-list-status {
  margin-top: 8px;
  min-height: 22px;
  display: flex;
  align-items: center;
}

.external-tool-package-list-status {
  margin-top: 8px;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.external-tool-package-list-mobile-meta-tag {
  display: none;
}

.external-tool-package-list-desc {
  margin-top: 8px;
  color: var(--muted, #64748b);
  font-size: 13px;
  line-height: 1.45;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.external-tool-package-mobile-detail {
  display: none;
}

.external-tool-package-detail-tags {
  margin-top: 8px;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.external-tool-package-detail-desc {
  margin-top: 12px;
}

.small-text {
  font-size: 12px;
}

.external-tool-package-detail-card {
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
  padding: 16px;
  border: 1px solid rgba(15, 23, 42, 0.06);
  border-radius: 14px;
  background: #fff;
  box-shadow: 0 4px 14px rgba(15, 23, 42, 0.04);
}

.external-tool-package-detail-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.external-tool-package-detail-main {
  min-width: 0;
  flex: 1 1 auto;
}

.external-tool-package-detail-actions {
  flex: 0 0 auto;
}

.external-tool-package-detail-action-row {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
}

.external-tool-package-detail-actions :deep(.el-button.external-tool-package-detail-action-button),
.external-tool-package-detail-actions :deep(.el-dropdown .el-button.external-tool-package-detail-action-button) {
  width: auto;
  min-width: 0;
  height: 26px;
  min-height: 26px;
  padding: 0 9px;
  border-radius: 7px;
  font-size: 12px;
  line-height: 24px;
  margin-left: 0;
}

.external-tool-title.large {
  font-size: 17px;
}

.external-tool-card {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 14px;
  border: 1px solid rgba(15, 23, 42, 0.06);
  border-radius: 14px;
  background: #fff;
  box-shadow: 0 4px 14px rgba(15, 23, 42, 0.04);
}

.external-tool-card-main {
  min-width: 0;
  flex: 1;
}

.external-tool-title {
  font-size: 15px;
  font-weight: 700;
  color: var(--text, #0f172a);
  max-width: 420px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.external-tool-desc {
  margin-top: 8px;
  color: var(--muted, #64748b);
  line-height: 1.45;
}

.muted {
  color: var(--muted, #64748b);
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

.muted {
  color: var(--muted, #64748b);
}

@media (max-width: 960px) {
.external-tool-package-split {
    display: block;
    overflow: auto;
    padding-right: 4px;
  }

.external-tool-package-list-panel {
    min-height: 0;
    max-height: none;
    overflow: visible;
  }

.external-tool-package-list {
    overflow: visible;
    padding-right: 0;
  }

.external-tool-package-detail-panel {
    display: none;
  }

.external-tool-package-mobile-detail {
    display: block;
    margin-top: 12px;
    padding-top: 12px;
    border-top: 1px solid rgba(15, 23, 42, 0.08);
  }

.external-tool-package-list-mobile-meta-tag {
    display: inline-flex;
  }

.external-tool-package-mobile-actions {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 8px;
    margin-top: 12px;
  }

.external-tool-package-mobile-actions :deep(.el-button),
.external-tool-package-mobile-actions :deep(.el-dropdown),
.external-tool-package-mobile-actions :deep(.el-dropdown .el-button) {
    width: 100%;
    min-width: 0;
    margin: 0;
  }

.external-tool-package-mobile-actions :deep(.el-button) {
    min-height: 32px;
    height: 32px;
    border-radius: 10px;
    padding-inline: 12px;
    justify-content: center;
  }

.external-tool-package-mobile-actions :deep(.el-dropdown) {
    display: block;
  }

.external-tool-package-mobile-modules {
    margin-top: 12px;
  }
}

@media (max-width: 640px) {
.external-tool-card {
    flex-direction: column;
    gap: 12px;
  }

.external-tool-title {
    flex: 0 0 100%;
    max-width: 100%;
  }

.muted {
  color: var(--muted, #64748b);
}
}
</style>
