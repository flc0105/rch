<template>
  <el-dialog
    :model-value="visible"
    title="Background Jobs"
    width="1180px"
    top="5vh"
    class="fixed-dialog background-jobs-dialog"
    modal-class="background-jobs-overlay"
    @update:model-value="handleVisibleChange"
  >
    <div class="fixed-dialog-body background-jobs-body">
      <el-tabs
        v-model="activeTab"
        class="background-jobs-tabs"
      >
        <el-tab-pane label="Modules" name="modules">
          <div class="background-jobs-tab-panel">
            <div class="background-jobs-toolbar">
              <div class="background-jobs-toolbar-left">
                <el-button
                  size="small"
                  type="primary"
                  class="toolbar-btn"
                  plain
                  @click="createRemoteJobPrompt"
                >
                  New
                </el-button>

                <el-button
                  size="small"
                  class="toolbar-btn"
                  :loading="serverJobUploadLoading"
                  @click="triggerServerJobUpload"
                >
                  Upload
                </el-button>

                <el-button
                  size="small"
                  class="toolbar-btn"
                  :loading="backgroundJobModulesLoading"
                  @click="loadBackgroundJobModules"
                >
                  Refresh
                </el-button>

                <input
                  ref="serverJobUploadInputRef"
                  type="file"
                  accept=".py,text/x-python"
                  class="hidden-file-input"
                  @change="handleServerJobUpload"
                >
              </div>

              <div class="background-jobs-toolbar-right">
                <el-select
                  v-model="backgroundJobPlatformFilter"
                  size="small"
                  clearable
                  filterable
                  class="background-job-platform-filter"
                  placeholder="All platforms"
                >
                  <el-option
                    v-for="option in backgroundJobPlatformOptions"
                    :key="option.value"
                    :label="option.label"
                    :value="option.value"
                  />
                </el-select>

                <el-input
                  v-model="backgroundJobModuleSearchText"
                  size="small"
                  clearable
                  class="background-job-module-search"
                  placeholder="Search"
                />
              </div>
            </div>

            <div
              class="background-jobs-modules panel-lite"
              v-loading="backgroundJobModulesLoading"
            >
              <div class="background-jobs-section-title">Available Jobs</div>

              <div
                v-if="!filteredBackgroundJobModules.length && !backgroundJobModulesLoading"
                class="empty-state"
              >
                {{ hasBackgroundJobModuleFilters ? 'No matching background jobs' : 'No background jobs available' }}
              </div>

              <div
                v-else
                class="background-job-module-list"
              >
                <div
                  v-for="item in filteredBackgroundJobModules"
                  :key="item.module_id || `job:${item.job_name}`"
                  class="background-job-module-card"
                >
                  <div class="background-job-module-main">
                    <div
                      class="background-job-module-name"
                      :title="item.display_name || item.job_name"
                    >
                      {{ item.display_name || item.job_name }}
                    </div>

                    <div
                      v-if="item.subtitle"
                      class="background-job-module-key mono"
                      :title="item.subtitle"
                    >
                      {{ item.subtitle }}
                    </div>

                    <div
                      v-if="item.description"
                      class="background-job-module-desc"
                      :title="item.description"
                    >
                      {{ item.description }}
                    </div>

                    <div class="background-job-module-tags">
                      <el-tag
                        size="small"
                        :type="isJobSupportedForCurrentConnection(item) ? 'info' : 'danger'"
                      >
                        {{ formatJobPlatformLabel(item.metadata?.platforms || []) }}
                      </el-tag>

                      <el-tag
                        v-if="hasBackgroundJobParams(item)"
                        size="small"
                        type="warning"
                      >
                        Params
                      </el-tag>
                    </div>
                  </div>

                  <div class="background-job-module-actions">
                    <el-button
                      size="small"
                      type="primary"
                      plain
                      :disabled="isBackgroundJobStartDisabled(item)"
                      @click="openBackgroundJobStartDialog(item)"
                    >
                      Start
                    </el-button>

                    <el-button
                      size="small"
                      plain
                      @click="$emit('open-job-editor', item.job_name)"
                    >
                      Edit
                    </el-button>

                    <el-button
                      size="small"
                      type="danger"
                      plain
                      @click="deleteBackgroundJobModule(item.job_name)"
                    >
                      Delete
                    </el-button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </el-tab-pane>

        <el-tab-pane label="Jobs" name="jobs">
          <div class="background-jobs-tab-panel">
            <div class="background-jobs-toolbar">
              <div class="background-jobs-toolbar-left">
                <el-button
                  size="small"
                  class="toolbar-btn"
                  :loading="backgroundJobsLoading"
                  @click="loadBackgroundJobs"
                >
                  Refresh
                </el-button>
              </div>
            </div>

            <div
              class="background-jobs-list-shell panel-lite"
              v-loading="backgroundJobsLoading"
            >
              <div class="background-jobs-section-title">Reported Jobs</div>

              <div
                v-if="!sortedBackgroundJobs.length && !backgroundJobsLoading"
                class="empty-state"
              >
                No background jobs reported for this device
              </div>

              <div
                v-else
                class="background-jobs-list"
              >
                <div
                  v-for="job in sortedBackgroundJobs"
                  :key="job.job_id"
                  class="background-job-summary-card"
                >
                  <div class="background-job-summary-main">
                    <div class="background-job-summary-top">
                      <div class="background-job-summary-title-wrap">
                        <div class="background-job-summary-title-line">
                          <span class="background-job-summary-title">
                            {{job.display_name || job.job_key}}

<!--                            {{ job.job_name || job.job_key || getBackgroundJobDisplayName(job) }}-->
                          </span>

                          <el-tag
                            :type="buildBackgroundJobStateTagType(job.state)"
                            size="small"
                          >
                            {{ job.state || 'unknown' }}
                          </el-tag>
                        </div>

                        <!--                       :title="getBackgroundJobDisplayName(job)"-->
                        <div
                          class="background-job-summary-subtitle"

                        >
                          {{job.job_key || '-'}}
<!--                          {{ getBackgroundJobDisplayName(job) }}-->
                        </div>
                      </div>
                    </div>

                    <div class="background-job-summary-stats">
                      <span>{{ formatBackgroundJobDuration(job) }}</span>
                      <span>{{ job.message_count || 0 }} msgs</span>
                      <span>{{ job.file_count || 0 }} files</span>
                      <span>{{ formatDateTimeStandard(job.started_at) || '-' }}</span>
                    </div>
                  </div>

                  <div class="background-job-summary-actions">
                    <el-button
                      size="small"
                      plain
                      @click="openBackgroundJobDetail(job)"
                    >
                      Details
                    </el-button>

                    <el-button
                      size="small"
                      type="danger"
                      plain
                      :disabled="!job.job_key || !isBackgroundJobActive(job)"
                      @click="stopBackgroundJob(job)"
                    >
                      Stop
                    </el-button>

                    <el-button
                      size="small"
                      type="danger"
                      plain
                      :disabled="isBackgroundJobActive(job)"
                      @click="deleteBackgroundJob(job)"
                    >
                      Delete
                    </el-button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </el-tab-pane>
      </el-tabs>
    </div>
  </el-dialog>

  <BackgroundJobStartDialog
    ref="backgroundJobStartDialogRef"
    v-model:visible="backgroundJobStartDialogVisible"
    :item="pendingStartJobModule"
    :params="pendingStartJobModule?.metadata?.params || []"
    :param-form="backgroundJobParamForm || {}"
    :submitting="backgroundJobStartSubmitting"
    :execution-mode="backgroundJobExecutionMode"
    :selected-id="selectedId"
    :get-tab-scoped-headers="getTabScopedHeaders"
    :is-job-supported-for-current-connection="isJobSupportedForCurrentConnection"
    :format-job-platform-label="formatJobPlatformLabel"
    @update-param="updateBackgroundJobParam"
    @update-execution-mode="updateBackgroundJobExecutionMode"
    @append-output="forwardAppendOutput"
    @set-active-task="forwardSetActiveTask"
    @upload-started="$emit('upload-started', $event)"
    @cancel="closeBackgroundJobStartDialog"
    @confirm="confirmStartBackgroundJobWithParams"
  />

  <BackgroundJobDetailDialog
    v-model:visible="backgroundJobDetailDialogVisible"
    :item="selectedBackgroundJob"
    :loading="backgroundJobDetailLoading"
    :current-connection="currentConnection"
    :messages="selectedBackgroundJobMessagesDesc || []"
    :files="selectedBackgroundJob?.files || []"
    :build-background-job-state-tag-type="buildBackgroundJobStateTagType"
    :format-background-job-duration="formatBackgroundJobDuration"
    :format-date-time-standard="formatDateTimeStandard"
    :format-background-job-message-text="formatBackgroundJobMessageText"
    :format-bytes="formatBytes"
    @stop-job="stopBackgroundJob"
    @delete-job="deleteBackgroundJob"
    @open-message="openBackgroundJobMessageDialog"
    @preview-file="$emit('preview-file', $event)"
  />

  <BackgroundJobMessageDialog
    v-model:visible="backgroundJobMessageDialogVisible"
    :message="selectedBackgroundJobMessage || {}"
    :format-date-time-standard="formatDateTimeStandard"
    :format-background-job-message-text="formatBackgroundJobMessageText"
  />
</template>

<script>
import { ElMessage, ElMessageBox } from 'element-plus'
import BackgroundJobStartDialog from './BackgroundJobStartDialog.vue'
import BackgroundJobDetailDialog from './BackgroundJobDetailDialog.vue'
import BackgroundJobMessageDialog from './BackgroundJobMessageDialog.vue'
import { cloneParamValue, normalizeParamSpecs, normalizeParamType } from '../utils/parameterSchema.js'
import { diffDateTimeMs } from '../utils/formatters.js'

export default {
  name: 'BackgroundJobsDialog',

  components: {
    BackgroundJobStartDialog,
    BackgroundJobDetailDialog,
    BackgroundJobMessageDialog,
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

    getTabScopedHeaders: {
      type: Function,
      default: null,
    },

    formatBytes: {
      type: Function,
      required: true,
    },

    formatDateTimeStandard: {
      type: Function,
      required: true,
    },
  },

  emits: [
    'append-output',
    'set-active-task',
    'upload-started',
    'preview-file',
    'open-job-editor',
    'open-new-job-editor',
    'job-deleted',
  ],

  data() {
    return {
      visible: false,
      backgroundJobsLoading: false,
      backgroundJobModulesLoading: false,
      backgroundJobModules: [],
      backgroundJobs: [],
      backgroundJobsRefreshTimer: null,
      backgroundJobDetailDialogVisible: false,
      backgroundJobDetailLoading: false,
      selectedBackgroundJobId: '',
      selectedBackgroundJobDetail: null,
      activeTab: 'modules',
      backgroundJobMessageDialogVisible: false,
      selectedBackgroundJobMessage: {},
      serverJobUploadLoading: false,
      backgroundJobStartDialogVisible: false,
      backgroundJobStartSubmitting: false,
      pendingStartJobModule: null,
      backgroundJobParamForm: {},
      backgroundJobExecutionMode: 'inproc',
      backgroundJobPlatformFilter: '',
      backgroundJobModuleSearchText: '',
    }
  },

  computed: {
    // selectedBackgroundJob() {
    //   const job = this.backgroundJobs.find(item => item.job_id === this.selectedBackgroundJobId) || null
    //   if (!job) return null
    //
    //   return {
    //     ...job,
    //     display_name: this.getBackgroundJobDisplayName(job),
    //   }
    // },

    selectedBackgroundJob() {
      const summary = this.backgroundJobs.find(item => item.job_id === this.selectedBackgroundJobId) || null
      const detail = this.selectedBackgroundJobDetail
      if (detail && detail.job_id === this.selectedBackgroundJobId) {
        return summary ? { ...summary, ...detail } : detail
      }
      return summary
    },

    sortedBackgroundJobs() {
      return [...this.backgroundJobs].sort((a, b) => {
        const ta = String(a.updated_at || a.started_at || a.created_at || '')
        const tb = String(b.updated_at || b.started_at || b.created_at || '')
        return tb.localeCompare(ta)
      })
    },

    currentConnectionPlatform() {
      return this.resolveCurrentConnectionPlatform()
    },

    hasBackgroundJobModuleFilters() {
      return !!(String(this.backgroundJobPlatformFilter || '').trim() || String(this.backgroundJobModuleSearchText || '').trim())
    },

    backgroundJobPlatformOptions() {
      const options = []
      const seen = new Set()

      const addOption = (platform) => {
        const normalized = this.normalizeJobPlatform(platform)
        if (!normalized || normalized === '*' || seen.has(normalized)) return

        seen.add(normalized)
        options.push({
          value: normalized,
          label: this.formatSingleJobPlatformLabel(normalized),
        })
      }

      addOption(this.currentConnectionPlatform)

      for (const item of this.backgroundJobModules || []) {
        const metadata = this.normalizeJobMetadata(item?.metadata || {})
        for (const platform of metadata.platforms || []) {
          addOption(platform)
        }
      }

      return options
    },

    filteredBackgroundJobModules() {
      const keyword = String(this.backgroundJobModuleSearchText || '').trim().toLowerCase()
      const platform = String(this.backgroundJobPlatformFilter || '').trim()

      return (this.backgroundJobModules || []).filter(item => {
        if (platform && !this.doesJobPlatformMatchFilter(item, platform)) return false

        if (keyword) {
          const displayName = String(item.display_name || '').toLowerCase()
          const jobKey = String(item.job_key || item.job_name || '').toLowerCase()
          if (!displayName.includes(keyword) && !jobKey.includes(keyword)) return false
        }

        return true
      })
    },

    backgroundJobModuleDisplayNameMap() {
      const map = new Map()

      for (const item of this.backgroundJobModules || []) {
        const displayName = String(item.display_name || '').trim()
        if (!displayName) continue

        const keys = [
          item.job_key,
          item.job_name,
          String(item.module_id || '').replace(/^job:/, ''),
        ]

        for (const key of keys) {
          const normalized = this.normalizeBackgroundJobLookupKey(key)
          if (normalized && !map.has(normalized)) {
            map.set(normalized, displayName)
          }

          const looseNormalized = this.normalizeBackgroundJobLooseLookupKey(key)
          if (looseNormalized && !map.has(`loose:${looseNormalized}`)) {
            map.set(`loose:${looseNormalized}`, displayName)
          }
        }
      }

      return map
    },

    selectedBackgroundJobMessagesDesc() {
      const messages = this.selectedBackgroundJob && Array.isArray(this.selectedBackgroundJob.messages)
        ? this.selectedBackgroundJob.messages
        : []

      return [...messages].sort((a, b) => {
        const ta = String(a.created_at || '')
        const tb = String(b.created_at || '')
        return tb.localeCompare(ta)
      })
    },

    activeBackgroundJobKeySet() {
      const set = new Set()

      for (const job of this.backgroundJobs || []) {
        const state = String(job?.state || '').trim().toLowerCase()
        if (!['running', 'stopping'].includes(state)) continue

        const keys = [job?.job_key, job?.job_name]
        for (const key of keys) {
          const normalized = this.normalizeBackgroundJobLookupKey(key)
          if (normalized) set.add(normalized)

          const looseNormalized = this.normalizeBackgroundJobLooseLookupKey(key)
          if (looseNormalized) set.add(`loose:${looseNormalized}`)
        }
      }

      return set
    },
  },

  watch: {
    selectedId() {
      if (!this.visible) return
      this.syncBackgroundJobPlatformFilterWithConnection()
    },

    backgroundJobDetailDialogVisible(value) {
      if (!value) {
        this.selectedBackgroundJobId = ''
        this.selectedBackgroundJobDetail = null
        this.backgroundJobDetailLoading = false
      }
    },

    backgroundJobMessageDialogVisible(value) {
      if (!value) {
        this.selectedBackgroundJobMessage = {}
      }
    },

    backgroundJobStartDialogVisible(value) {
      if (!value) {
        this.closeBackgroundJobStartDialog()
      }
    },
  },

  beforeUnmount() {
    this.clearBackgroundJobsRefreshTimer()
  },

  methods: {
    forwardAppendOutput(clientId, line, kind) {
      this.$emit('append-output', clientId, line, kind)
    },

    forwardSetActiveTask(clientId, taskId) {
      this.$emit('set-active-task', clientId, taskId)
    },

    refreshRemoteFilePickerDirectory(path = '') {
      return this.$refs.backgroundJobStartDialogRef?.loadRemoteFilePickerDirectory(path || '')
    },

    async open() {
      if (!this.selectedId) {
        ElMessage.warning('Please select a device')
        return
      }

      this.visible = true
      this.syncBackgroundJobPlatformFilterWithConnection()

      await Promise.all([
        this.loadBackgroundJobModules(),
        this.loadBackgroundJobs(),
      ])
    },

    isOpen() {
      return this.visible
    },

    async refreshIfOpen() {
      if (!this.visible) return

      await Promise.all([
        this.loadBackgroundJobModules(),
        this.loadBackgroundJobs(),
      ])
    },

    async refreshModulesIfOpen() {
      if (!this.visible) return
      await this.loadBackgroundJobModules()
    },

    async refreshJobsIfOpen() {
      if (!this.visible) return
      await this.loadBackgroundJobs()
    },

    handleVisibleChange(value) {
      this.visible = value

      if (!value) {
        this.clearBackgroundJobsRefreshTimer()
      }
    },

    clearBackgroundJobsRefreshTimer() {
      if (this.backgroundJobsRefreshTimer) {
        clearTimeout(this.backgroundJobsRefreshTimer)
        this.backgroundJobsRefreshTimer = null
      }
    },

    normalizeBackgroundJobModule(item = {}) {
      const rawJobName = String(item.job_name || item.name || item.job_key || '').trim()
      const rawJobKey = String(item.job_key || '').trim()
      const rawDisplayName = String(item.display_name || '').trim()
      const metadata = this.normalizeJobMetadata(item.metadata || {})

      const isHeadingLike = /^(available\s+client\s+job\s+modules:?|available\s+remote\s+scripts:?|no\s+remote\s+scripts\s+available)$/i.test(rawJobName)
      const stripPySuffix = (value = '') => String(value).replace(/\.py$/i, '').trim()

      let jobName = rawJobName
      let jobKey = rawJobKey || stripPySuffix(rawJobName) || rawJobName
      let displayName = rawDisplayName

      if (!displayName) {
        displayName = metadata.display_name || jobName
      }

      if (!jobKey) {
        jobKey = stripPySuffix(jobName) || jobName
      }

      const subtitle = jobKey && displayName !== jobKey ? jobKey : ''
      const description = String(item.description || metadata.description || '').trim()

      return {
        ...item,
        source: 'job',
        job_name: jobName,
        job_key: jobKey,
        display_name: displayName,
        description,
        metadata,
        subtitle,
        module_id: `job:${jobKey || jobName}`,
        hidden_invalid: !jobName || isHeadingLike,
      }
    },

    normalizeJobMetadata(metadata = {}) {
      if (!metadata || typeof metadata !== 'object' || Array.isArray(metadata)) {
        return {
          name: '',
          display_name: '',
          description: '',
          platforms: [],
          params: [],
          execution_mode: 'inproc',
          allowed: ['inproc', 'subprocess'],
          execution: {
            default: 'inproc',
            allowed: ['inproc', 'subprocess'],
          },
        }
      }

      const executionMeta = metadata.execution && typeof metadata.execution === 'object' && !Array.isArray(metadata.execution)
        ? metadata.execution
        : {}
      const rawAllowed = Array.isArray(executionMeta.allowed)
        ? executionMeta.allowed
        : (Array.isArray(metadata.allowed) ? metadata.allowed : null)
      const allowed = []
      const seenAllowed = new Set()

      for (const item of rawAllowed || ['inproc', 'subprocess']) {
        const normalizedMode = String(item || '').trim().toLowerCase() === 'subprocess'
          ? 'subprocess'
          : (String(item || '').trim().toLowerCase() === 'inproc' ? 'inproc' : '')
        if (!normalizedMode || seenAllowed.has(normalizedMode)) continue
        seenAllowed.add(normalizedMode)
        allowed.push(normalizedMode)
      }

      if (!allowed.length) {
        allowed.push('inproc', 'subprocess')
      }

      const requestedDefault = String(metadata.execution_mode || executionMeta.default || '').trim().toLowerCase() === 'subprocess'
        ? 'subprocess'
        : 'inproc'
      const executionMode = allowed.includes(requestedDefault) ? requestedDefault : allowed[0]

      return {
        ...metadata,
        name: String(metadata.name || '').trim(),
        display_name: String(metadata.display_name || '').trim(),
        description: String(metadata.description || '').trim(),
        platforms: this.normalizeJobPlatforms(metadata.platforms),
        execution_mode: executionMode,
        allowed,
        execution: {
          ...executionMeta,
          default: executionMode,
          allowed,
        },
        params: normalizeParamSpecs(metadata.params),
      }
    },

    normalizeJobPlatforms(platforms) {
      const source = Array.isArray(platforms)
        ? platforms
        : (typeof platforms === 'string' && platforms.trim() ? [platforms] : [])

      const result = []
      const seen = new Set()

      for (const item of source) {
        const normalized = this.normalizeJobPlatform(item)
        if (!normalized || seen.has(normalized)) continue
        seen.add(normalized)
        result.push(normalized)
      }

      return result
    },

    normalizeJobPlatform(platform) {
      const value = String(platform || '').trim().toLowerCase()
      if (!value) return ''
      if (['*', 'all', 'any', 'common'].includes(value)) return '*'
      if (['darwin', 'mac', 'macos', 'osx'].includes(value)) return 'mac'
      if (['windows', 'win', 'win32', 'nt'].includes(value)) return 'win'
      if (['linux', 'ubuntu', 'debian', 'centos', 'fedora', 'redhat', 'rhel', 'alpine', 'arch'].includes(value)) return 'linux'
      return value
    },

    normalizeClientPlatform(osType = '') {
      const value = String(osType || '').trim().toLowerCase()
      if (!value) return ''
      if (value.includes('darwin') || value.includes('mac')) return 'mac'
      if (value.includes('win')) return 'win'
      if (value.includes('linux')) return 'linux'
      if (/(ubuntu|debian|centos|fedora|redhat|rhel|alpine|arch)/.test(value)) return 'linux'
      return this.normalizeJobPlatform(value)
    },

    resolveCurrentConnectionPlatform() {
      const conn = this.currentConnection || {}
      const candidates = [
        conn.os_alias,
        conn.os_type,
        conn.platform,
        conn.system,
        conn.os,
        conn.os_name,
      ]

      for (const candidate of candidates) {
        const normalized = this.normalizeClientPlatform(candidate)
        if (['mac', 'win', 'linux', 'ios'].includes(normalized)) return normalized
      }

      for (const candidate of candidates) {
        const normalized = this.normalizeClientPlatform(candidate)
        if (normalized) return normalized
      }

      return ''
    },

    syncBackgroundJobPlatformFilterWithConnection() {
      this.backgroundJobPlatformFilter = this.currentConnectionPlatform || ''
    },

    formatSingleJobPlatformLabel(platform) {
      return this.formatJobPlatformLabel([platform])
    },

    doesJobPlatformMatchFilter(item, platform) {
      const target = this.normalizeJobPlatform(platform)
      if (!target) return true

      const metadata = this.normalizeJobMetadata(item?.metadata || {})
      const platforms = metadata.platforms || []
      if (!platforms.length || platforms.includes('*')) return true

      return platforms.includes(target)
    },

    normalizeBackgroundJobLookupKey(value) {
      const normalized = String(value || '').trim()
        .replace(/\\/g, '/')
        .replace(/#.*/, '')
        .replace(/\.py$/i, '')

      return normalized.split('/').pop() || normalized
    },

    normalizeBackgroundJobLooseLookupKey(value) {
      return this.normalizeBackgroundJobLookupKey(value)
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '')
    },

    // findBackgroundJobModuleDisplayName(keys = []) {
    //   for (const key of keys) {
    //     const normalized = this.normalizeBackgroundJobLookupKey(key)
    //     const displayName = this.backgroundJobModuleDisplayNameMap.get(normalized)
    //     if (displayName) return displayName
    //
    //     const looseNormalized = this.normalizeBackgroundJobLooseLookupKey(key)
    //     const looseDisplayName = this.backgroundJobModuleDisplayNameMap.get(`loose:${looseNormalized}`)
    //     if (looseDisplayName) return looseDisplayName
    //   }
    //
    //   return ''
    // },

    // humanizeBackgroundJobName(value) {
    //   const normalized = this.normalizeBackgroundJobLookupKey(value)
    //   if (!normalized) return '-'
    //
    //   const withSpaces = normalized
    //     .replace(/[_-]+/g, ' ')
    //     .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    //     .trim()
    //
    //   if (!withSpaces) return normalized
    //
    //   return withSpaces.replace(/\b\w/g, char => char.toUpperCase())
    // },

    // getBackgroundJobDisplayName(job) {
    //   const ownDisplayName = String(job?.display_name || '').trim()
    //   const catalogDisplayName = this.findBackgroundJobModuleDisplayName([
    //     job?.job_key,
    //     job?.job_name,
    //     ownDisplayName,
    //   ])
    //
    //   if (catalogDisplayName) return catalogDisplayName
    //   if (ownDisplayName && !ownDisplayName.includes('#')) return ownDisplayName
    //
    //   return this.humanizeBackgroundJobName(job?.job_name || job?.job_key || ownDisplayName)
    // },

    formatJobPlatformLabel(platforms) {
      const normalized = this.normalizeJobPlatforms(platforms)

      if (!normalized.length || normalized.includes('*')) {
        return 'All OS'
      }

      const labels = normalized.map(item => {
        if (item === 'mac') return 'macOS'
        if (item === 'win') return 'Windows'
        if (item === 'linux') return 'Linux'
        if (item === 'ios') return 'iOS'
        return item
      })

      return labels.join(' / ')
    },

    isJobSupportedForCurrentConnection(item) {
      const metadata = this.normalizeJobMetadata(item?.metadata || {})
      const platforms = metadata.platforms || []
      if (!platforms.length || platforms.includes('*')) return true

      const current = this.currentConnectionPlatform
      if (!current) return true

      return platforms.includes(current)
    },

    hasBackgroundJobParams(item) {
      const metadata = this.normalizeJobMetadata(item?.metadata || {})
      return Array.isArray(metadata.params) && metadata.params.length > 0
    },

    buildBackgroundJobParamDefaults(item) {
      const metadata = this.normalizeJobMetadata(item?.metadata || {})
      const result = {}

      for (const param of metadata.params || []) {
        const type = normalizeParamType(param?.type)
        const hasDefault = Object.prototype.hasOwnProperty.call(param, 'default') && param.default !== null && param.default !== undefined
        if (hasDefault) {
          if (['remote_files', 'remote_folders'].includes(type)) {
            result[param.name] = Array.isArray(param.default) ? cloneParamValue(param.default) : []
          } else if (type === 'boolean') {
            result[param.name] = param.default === true || String(param.default).toLowerCase() === 'true'
          } else {
            result[param.name] = cloneParamValue(param.default)
          }
        } else if (['remote_files', 'remote_folders'].includes(type)) {
          result[param.name] = []
        } else if (type === 'boolean') {
          result[param.name] = false
        } else {
          result[param.name] = ''
        }
      }

      return result
    },

    openBackgroundJobStartDialog(item) {
      if (!this.selectedId) {
        ElMessage.warning('Please select a device')
        return
      }

      if (!item || !String(item.job_name || '').trim()) {
        ElMessage.warning('Invalid job name')
        return
      }

      if (!this.isJobSupportedForCurrentConnection(item)) {
        const jobName = item.display_name || item.job_name
        const platformLabel = this.formatJobPlatformLabel(item.metadata?.platforms || [])
        ElMessage.warning(`${jobName} only supports: ${platformLabel}`)
        return
      }

      if (this.isBackgroundJobStartDisabled(item)) {
        ElMessage.warning('This background job is already running')
        return
      }

      const metadata = this.normalizeJobMetadata(item?.metadata || {})
      this.pendingStartJobModule = item
      this.backgroundJobParamForm = this.buildBackgroundJobParamDefaults(item)
      this.backgroundJobExecutionMode = metadata.execution_mode || 'inproc'
      this.backgroundJobStartDialogVisible = true
    },

    closeBackgroundJobStartDialog() {
      this.backgroundJobStartDialogVisible = false
      this.backgroundJobStartSubmitting = false
      this.pendingStartJobModule = null
      this.backgroundJobParamForm = {}
      this.backgroundJobExecutionMode = 'inproc'
    },

    updateBackgroundJobParam(name, value) {
      if (!name) return

      this.backgroundJobParamForm = {
        ...this.backgroundJobParamForm,
        [name]: value,
      }
    },

    updateBackgroundJobExecutionMode(value) {
      const nextMode = String(value || '').trim().toLowerCase() === 'subprocess'
        ? 'subprocess'
        : 'inproc'
      const metadata = this.normalizeJobMetadata(this.pendingStartJobModule?.metadata || {})
      if (!metadata.allowed.includes(nextMode)) return
      this.backgroundJobExecutionMode = nextMode
    },

    coerceBackgroundJobParamValue(param, rawValue) {
      const type = normalizeParamType(param?.type)

      if (['remote_files', 'remote_folders'].includes(type)) {
        if (!Array.isArray(rawValue)) throw new Error(`Param "${param.name}" must be a path list`)
        return rawValue.map(item => String(item || '').trim()).filter(Boolean)
      }

      if (['remote_file', 'remote_folder'].includes(type)) {
        if (Array.isArray(rawValue)) throw new Error(`Param "${param.name}" must be a single path`)
        return String(rawValue || '').trim()
      }

      if (type === 'boolean') return !!rawValue
      if (type === 'textarea') return rawValue === null || rawValue === undefined ? '' : String(rawValue)

      const value = rawValue === null || rawValue === undefined ? '' : String(rawValue).trim()
      if (type === 'integer') {
        if (!/^-?\d+$/.test(value)) {
          throw new Error(`Param "${param.name}" must be an integer`)
        }

        const parsed = parseInt(value, 10)
        if (param.min !== undefined && parsed < Number(param.min)) {
          throw new Error(`Param "${param.name}" must be >= ${param.min}`)
        }
        if (param.max !== undefined && parsed > Number(param.max)) {
          throw new Error(`Param "${param.name}" must be <= ${param.max}`)
        }
        return parsed
      }

      if (type === 'number') {
        const parsed = Number(value)
        if (Number.isNaN(parsed)) {
          throw new Error(`Param "${param.name}" must be a number`)
        }
        if (param.min !== undefined && parsed < Number(param.min)) {
          throw new Error(`Param "${param.name}" must be >= ${param.min}`)
        }
        if (param.max !== undefined && parsed > Number(param.max)) {
          throw new Error(`Param "${param.name}" must be <= ${param.max}`)
        }
        return parsed
      }

      if (type === 'select') {
        if (Array.isArray(param.options) && param.options.length && !param.options.map(String).includes(value)) {
          throw new Error(`Param "${param.name}" has invalid option`)
        }
        return value
      }

      return value
    },

    buildBackgroundJobStartParams(item) {
      const metadata = this.normalizeJobMetadata(item?.metadata || {})
      const params = {}

      for (const param of metadata.params || []) {
        const hasValue = Object.prototype.hasOwnProperty.call(this.backgroundJobParamForm, param.name)
        const rawValue = hasValue ? this.backgroundJobParamForm[param.name] : ''
        const type = normalizeParamType(param.type)
        const hasRemoteMultiValue = ['remote_files', 'remote_folders'].includes(type) && Array.isArray(rawValue) && rawValue.length > 0
        const textValue = rawValue === null || rawValue === undefined ? '' : String(rawValue).trim()

        if (!hasRemoteMultiValue && !textValue) {
          if (param.required && (param.default === undefined || param.default === null || String(param.default).trim() === '')) {
            throw new Error(`Missing required param: ${param.name}`)
          }

          if (param.default !== undefined && param.default !== null && String(param.default).trim() !== '') {
            params[param.name] = this.coerceBackgroundJobParamValue(param, param.default)
          }

          continue
        }

        params[param.name] = this.coerceBackgroundJobParamValue(param, rawValue)
      }

      return params
    },

    buildJsonHeaders() {
      const headers = { 'Content-Type': 'application/json' }

      if (typeof this.getTabScopedHeaders === 'function') {
        return this.getTabScopedHeaders(headers)
      }

      return headers
    },

    async submitBackgroundJobStart(jobName, params = {}, executionMode = 'inproc') {
      const normalized = String(jobName || '').trim()
      if (!normalized) {
        ElMessage.warning('Invalid job name')
        return null
      }

      const res = await fetch(`/api/connections/${encodeURIComponent(this.selectedId)}/background-jobs/start`, {
        method: 'POST',
        headers: this.buildJsonHeaders(),
        body: JSON.stringify({
          job_name: normalized,
          params,
          execution_mode: String(executionMode || '').trim().toLowerCase() === 'subprocess' ? 'subprocess' : 'inproc',
        }),
      })

      const json = await res.json()
      if (!res.ok || json.code !== 0) {
        throw new Error(json.message || 'Failed to start background job')
      }

      const taskId = json.data && json.data.task_id
      this.$emit('set-active-task', this.selectedId, taskId || '')
      return json.data || {}
    },

    async confirmStartBackgroundJobWithParams() {
      const item = this.pendingStartJobModule
      if (!item) {
        this.closeBackgroundJobStartDialog()
        return
      }

      try {
        this.backgroundJobStartSubmitting = true
        const params = this.buildBackgroundJobStartParams(item)
        const metadata = this.normalizeJobMetadata(item.metadata || {})
        if (!metadata.allowed.includes(this.backgroundJobExecutionMode)) {
          throw new Error(`Execution mode ${this.backgroundJobExecutionMode} is not supported by this job`)
        }
        await this.submitBackgroundJobStart(item.job_name, params, this.backgroundJobExecutionMode)
        ElMessage.success(`Start request submitted: ${item.display_name || item.job_name}`)
        this.activeTab = 'jobs'
        this.closeBackgroundJobStartDialog()
        setTimeout(() => this.loadBackgroundJobs(), 500)
      } catch (e) {
        ElMessage.error(e.message || 'Failed to start background job')
      } finally {
        this.backgroundJobStartSubmitting = false
      }
    },

    async loadBackgroundJobModules() {
      if (!this.selectedId) return

      this.backgroundJobModulesLoading = true

      try {
        const res = await fetch(`/api/connections/${encodeURIComponent(this.selectedId)}/background-jobs/catalog`)
        const json = await res.json()

        if (!res.ok || json.code !== 0) {
          throw new Error(json.message || 'Failed to load background job catalog')
        }

        const modules = Array.isArray(json.data) ? json.data : []
        this.backgroundJobModules = modules
          .map(item => this.normalizeBackgroundJobModule(item))
          .filter(item => item.job_name && !item.hidden_invalid)
      } catch (e) {
        this.backgroundJobModules = []
        ElMessage.error(e.message || 'Failed to load job modules')
      } finally {
        this.backgroundJobModulesLoading = false
      }
    },

    async loadBackgroundJobs() {
      if (!this.selectedId) return

      this.backgroundJobsLoading = true

      try {
        const res = await fetch(`/api/connections/${encodeURIComponent(this.selectedId)}/background-jobs`)
        const json = await res.json()

        if (!res.ok || json.code !== 0) {
          throw new Error(json.message || 'Failed to load background jobs')
        }

        const jobs = Array.isArray(json.data) ? json.data : []
        this.backgroundJobs = jobs

        if (this.selectedBackgroundJobId) {
          const exists = jobs.some(item => item.job_id === this.selectedBackgroundJobId)
          if (!exists) {
            this.backgroundJobDetailDialogVisible = false
            this.selectedBackgroundJobId = ''
          } else if (this.backgroundJobDetailDialogVisible) {
            await this.loadBackgroundJobDetail(this.selectedBackgroundJobId, { silent: true })
          }
        }
      } catch (e) {
        this.backgroundJobs = []
        ElMessage.error(e.message || 'Failed to load background jobs')
      } finally {
        this.backgroundJobsLoading = false
      }
    },

    async loadBackgroundJobDetail(jobId, { silent = false } = {}) {
      const normalizedJobId = String(jobId || '').trim()
      if (!this.selectedId || !normalizedJobId) return

      if (!silent) {
        this.backgroundJobDetailLoading = true
      }

      try {
        const res = await fetch(
          `/api/connections/${encodeURIComponent(this.selectedId)}/background-jobs/${encodeURIComponent(normalizedJobId)}`
        )
        const json = await res.json()
        if (!res.ok || json.code !== 0) {
          throw new Error(json.message || 'Failed to load background job detail')
        }

        if (this.selectedBackgroundJobId === normalizedJobId) {
          this.selectedBackgroundJobDetail = json.data || null
        }
      } catch (e) {
        if (!silent) {
          ElMessage.error(e.message || 'Failed to load background job detail')
        }
      } finally {
        if (!silent) {
          this.backgroundJobDetailLoading = false
        }
      }
    },

    scheduleBackgroundJobsRefresh(clientId = '') {
      if (!this.visible) return
      if (clientId && clientId !== this.selectedId) return

      this.clearBackgroundJobsRefreshTimer()

      this.backgroundJobsRefreshTimer = setTimeout(() => {
        this.loadBackgroundJobs()
      }, 200)
    },

    async startBackgroundJob(jobName, params = {}, executionMode = 'inproc') {
      if (!this.selectedId) {
        ElMessage.warning('Please select a device')
        return
      }

      const normalized = String(jobName || '').trim()
      if (!normalized) {
        ElMessage.warning('Invalid job name')
        return
      }

      try {
        await this.submitBackgroundJobStart(normalized, params, executionMode)
        ElMessage.success(`Start request submitted: ${normalized}`)
        this.activeTab = 'jobs'
        setTimeout(() => this.loadBackgroundJobs(), 500)
      } catch (e) {
        ElMessage.error(e.message || 'Failed to start background job')
      }
    },

    async stopBackgroundJob(job) {
      const jobKey = String(job && job.job_key || '').trim()
      if (!this.selectedId || !jobKey) {
        ElMessage.warning('Invalid background job')
        return
      }

      try {
        await ElMessageBox.confirm(
          `Stop "${job.display_name || job.job_name || jobKey}"?`,
          'Stop Background Job',
          {
            type: 'warning',
            confirmButtonText: 'Stop',
            cancelButtonText: 'Cancel',
          }
        )

        const res = await fetch(`/api/connections/${encodeURIComponent(this.selectedId)}/background-jobs/stop`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ job_key: jobKey }),
        })

        const json = await res.json()
        if (!res.ok || json.code !== 0) {
          throw new Error(json.message || 'Failed to stop background job')
        }

        ElMessage.success(`Stop request sent: ${jobKey}`)
        await this.loadBackgroundJobs()
      } catch (e) {
        if (e === 'cancel' || e === 'close' || e?.toString?.().includes('cancel')) return
        ElMessage.error(e.message || 'Failed to stop background job')
      }
    },

    async openBackgroundJobDetail(job) {
      if (!job || !job.job_id) return
      this.selectedBackgroundJobId = job.job_id
      this.selectedBackgroundJobDetail = { ...job, messages: [], files: [] }
      this.backgroundJobDetailDialogVisible = true
      await this.loadBackgroundJobDetail(job.job_id)
    },

    isBackgroundJobActive(job) {
      const state = String(job?.state || '').trim().toLowerCase()
      return state === 'running' || state === 'stopping'
    },

    async deleteBackgroundJob(job) {
      const jobId = String(job?.job_id || '').trim()
      if (!this.selectedId || !jobId) {
        ElMessage.warning('Invalid background job')
        return
      }
      if (this.isBackgroundJobActive(job)) {
        ElMessage.warning('Stop the background job before deleting its record')
        return
      }

      try {
        await ElMessageBox.confirm(
          `Delete record "${job.display_name || job.job_name || job.job_key || jobId}"?`,
          'Delete Background Job Record',
          {
            type: 'warning',
            confirmButtonText: 'Delete',
            cancelButtonText: 'Cancel',
          }
        )

        const res = await fetch(
          `/api/connections/${encodeURIComponent(this.selectedId)}/background-jobs/${encodeURIComponent(jobId)}`,
          { method: 'DELETE' }
        )
        const json = await res.json()
        if (!res.ok || json.code !== 0) {
          throw new Error(json.message || 'Failed to delete background job record')
        }

        if (this.selectedBackgroundJobId === jobId) {
          this.backgroundJobDetailDialogVisible = false
          this.selectedBackgroundJobId = ''
          this.selectedBackgroundJobDetail = null
        }
        await this.loadBackgroundJobs()
        ElMessage.success('Background job record deleted')
      } catch (e) {
        if (e === 'cancel' || e === 'close' || e?.toString?.().includes('cancel')) return
        ElMessage.error(e.message || 'Failed to delete background job record')
      }
    },

    openBackgroundJobMessageDialog(message) {
      this.selectedBackgroundJobMessage = message || {}
      this.backgroundJobMessageDialogVisible = true
    },

    normalizeServerJobFilename(scriptName, fallbackName = 'new_job.py') {
      let normalized = String(scriptName || '').trim().replace(/\\/g, '/').replace(/^\/+/, '')
      if (!normalized) {
        normalized = fallbackName
      }

      if (!/\.py$/i.test(normalized)) {
        normalized = `${normalized}.py`
      }

      return normalized
    },

    triggerServerJobUpload() {
      if (!this.selectedId) {
        ElMessage.warning('Please select a device')
        return
      }

      const input = this.$refs.serverJobUploadInputRef
      if (input) {
        input.value = ''
        input.click()
      }
    },

    async handleServerJobUpload(event) {
      const input = event && event.target
      const file = input && input.files && input.files[0]
      if (!file) return

      if (!/\.py$/i.test(file.name || '')) {
        ElMessage.warning('Only .py files are supported')
        input.value = ''
        return
      }

      this.serverJobUploadLoading = true

      try {
        const formData = new FormData()
        formData.append('file', file, file.name)

        const res = await fetch('/api/jobs/upload', {
          method: 'POST',
          body: formData,
        })

        const json = await res.json()
        if (!res.ok || json.code !== 0) {
          throw new Error(json.message || 'Failed to upload job')
        }

        const uploadedName = this.normalizeServerJobFilename(json.data?.name || file.name)
        ElMessage.success(`Job uploaded: ${uploadedName}`)

        if (this.visible) {
          await this.loadBackgroundJobModules()
        }

        this.$emit('open-job-editor', uploadedName)
      } catch (e) {
        ElMessage.error(e.message || 'Failed to upload job')
      } finally {
        this.serverJobUploadLoading = false
        if (input) input.value = ''
      }
    },

    async deleteBackgroundJobModule(scriptName) {
      const normalizedScriptName = this.normalizeServerJobFilename(scriptName)
      if (!normalizedScriptName) {
        ElMessage.warning('Invalid job name')
        return
      }

      try {
        await ElMessageBox.confirm(
          `Delete "${normalizedScriptName}"? This action cannot be undone.`,
          'Delete Job',
          {
            type: 'warning',
            confirmButtonText: 'Delete',
            cancelButtonText: 'Cancel',
          }
        )

        const res = await fetch('/api/jobs/delete', {
          method: 'DELETE',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name: normalizedScriptName }),
        })

        const json = await res.json()
        if (!res.ok || json.code !== 0) {
          throw new Error(json.message || 'Failed to delete job')
        }

        this.$emit('job-deleted', normalizedScriptName)
        ElMessage.success(`Deleted: ${normalizedScriptName}`)

        if (this.visible) {
          await this.loadBackgroundJobModules()
        }
      } catch (e) {
        if (e === 'cancel' || e === 'close') return
        ElMessage.error(e.message || 'Failed to delete job')
      }
    },

    async createRemoteJobPrompt() {
      if (!this.selectedId) {
        ElMessage.warning('Please select a device')
        return
      }

      try {
        const { value } = await ElMessageBox.prompt(
          'Enter the new job filename',
          'New Job',
          {
            confirmButtonText: 'Create',
            cancelButtonText: 'Cancel',
            inputValue: 'new_job.py',
            inputPlaceholder: 'new_job.py',
          }
        )

        this.$emit('open-new-job-editor', value || 'new_job.py')
      } catch (e) {
        if (e === 'cancel' || e === 'close') return
      }
    },

    buildBackgroundJobStateTagType(state) {
      const value = String(state || '').toLowerCase()
      if (value === 'running') return 'success'
      if (value === 'stopping') return 'warning'
      if (value === 'error') return 'danger'
      return 'info'
    },

    formatBackgroundJobDuration(jobOrSeconds) {
      const seconds = jobOrSeconds && typeof jobOrSeconds === 'object'
        ? Math.floor(diffDateTimeMs(jobOrSeconds.started_at, jobOrSeconds.finished_at) / 1000)
        : Number(jobOrSeconds || 0)
      if (!seconds) return '0s'

      const hours = Math.floor(seconds / 3600)
      const minutes = Math.floor((seconds % 3600) / 60)
      const remain = seconds % 60

      const parts = []
      if (hours) parts.push(`${hours}h`)
      if (minutes) parts.push(`${minutes}m`)
      if (remain || !parts.length) parts.push(`${remain}s`)

      return parts.join(' ')
    },

    formatBackgroundJobMessageText(text) {
      const raw = String(text || '').trim()
      return raw.replace(/^\[[^\]]*?client=[^\]]*?\]\s*/, '')
    },

    isBackgroundJobStartDisabled(item) {
      const key = this.normalizeBackgroundJobLookupKey(item?.job_key || item?.job_name || '')
      const looseKey = this.normalizeBackgroundJobLooseLookupKey(item?.job_key || item?.job_name || '')
      const isActive = (!!key && this.activeBackgroundJobKeySet.has(key))
        || (!!looseKey && this.activeBackgroundJobKeySet.has(`loose:${looseKey}`))
      const isUnsupported = !this.isJobSupportedForCurrentConnection(item)

      return isActive || isUnsupported
    },
  },
}
</script>

<style scoped>
/* BackgroundJobsDialog 收口：主弹窗固定高度，只有 job/module 列表内部滚动。 */
.background-jobs-body {
  flex: 1 1 0;
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.background-jobs-tabs {
  flex: 1 1 0;
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.background-jobs-tabs :deep(.el-tabs__header) {
  flex: 0 0 auto;
  margin-bottom: 12px;
}

.background-jobs-tabs :deep(.el-tabs__content) {
  flex: 1 1 0;
  height: 0;
  min-height: 0;
  overflow: hidden;
}

.background-jobs-tabs :deep(.el-tab-pane) {
  height: 100%;
  min-height: 0;
  overflow: hidden;
}

.background-jobs-tab-panel {
  flex: 1 1 0;
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.background-jobs-toolbar {
  flex: 0 0 auto;
  margin-bottom: 10px;
  min-width: 0;
  display: grid;
  grid-template-columns: minmax(0, auto) minmax(320px, 1fr);
  gap: 8px 12px;
  align-items: center;
}

.background-jobs-toolbar-left,
.background-jobs-toolbar-right {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.background-jobs-toolbar-right {
  justify-content: flex-end;
}

.background-jobs-toolbar :deep(.el-button) {
  height: 32px;
  min-height: 32px;
  margin: 0;
  border-radius: 10px;
  padding-inline: 12px;
}

.background-job-platform-filter,
.background-job-module-search {
  width: 240px;
  max-width: 100%;
}

.background-job-platform-filter :deep(.el-select__wrapper),
.background-job-module-search :deep(.el-input__wrapper) {
  min-height: 32px;
  height: 32px;
  border-radius: 10px;
}

.hidden-file-input {
  display: none;
}

.panel-lite {
  flex: 1 1 0;
  min-height: 0;
  background: #fff;
  border: 1px solid rgba(15, 23, 42, 0.06);
  border-radius: 14px;
  padding: 14px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.background-jobs-section-title {
  flex: 0 0 auto;
  font-size: 14px;
  font-weight: 700;
  color: var(--text);
  margin-bottom: 12px;
}

.background-jobs-modules,
.background-jobs-list-shell {
  height: auto;
}

.background-job-module-list {
  flex: 1 1 0;
  min-height: 0;
  max-height: none !important;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding: 4px 4px 4px 0;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 16px;
  align-items: start;
  align-content: start;
}

.background-job-module-card {
  flex: 0 0 auto;
  width: 100%;
  min-width: 0;
  min-height: 200px;
  height: auto;
  box-sizing: border-box;
  padding: 14px;
  border: 1px solid rgba(15, 23, 42, 0.06);
  border-radius: 12px;
  background: #fff;
  display: flex;
  flex-direction: column;
  gap: 10px;
  overflow: visible;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
  transition: box-shadow 0.2s ease;
}

.background-job-module-card:hover {
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.12);
}

.background-job-module-main {
  flex: 1 1 auto;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.background-job-module-name,
.background-job-module-key,
.background-job-module-desc {
  min-width: 0;
  margin: 0;
}

.background-job-module-name {
  font-size: 15px;
  line-height: 22px;
  font-weight: 700;
  color: var(--text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.background-job-module-key {
  font-size: 12px;
  line-height: 18px;
  color: #667085;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.background-job-module-desc {
  font-size: 13px;
  line-height: 20px;
  color: #667085;
  overflow: hidden;
  word-break: break-word;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.background-job-module-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: flex-start;
  align-content: flex-start;
  min-height: 0;
  margin-top: auto;
}

.background-job-module-tags :deep(.el-tag) {
  margin: 0;
}

.background-job-module-actions {
  flex: 0 0 auto;
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  align-items: stretch;
}

.background-job-module-actions :deep(.el-button) {
  width: 100%;
  min-width: 0;
  margin: 0;
  border-radius: 10px;
}

.background-jobs-list {
  flex: 1 1 0;
  min-height: 0;
  max-height: none !important;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding: 4px 4px 4px 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.background-job-summary-card {
  flex: 0 0 auto;
  width: 100%;
  min-width: 0;
  height: auto;
  box-sizing: border-box;
  border: 1px solid rgba(15, 23, 42, 0.06);
  border-radius: 14px;
  padding: 14px;
  background: #fff;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 12px;
  align-items: center;
  overflow: visible;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.02);
}

.background-job-summary-main,
.background-job-summary-title-wrap {
  min-width: 0;
}

.background-job-summary-top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.background-job-summary-title-line {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.background-job-summary-title {
  font-size: 15px;
  font-weight: 700;
  color: var(--text);
  word-break: break-word;
}

.background-job-summary-subtitle {
  margin-top: 8px;
  color: var(--muted);
  font-size: 12px;
  line-height: 1.4;
  word-break: break-word;
}

.background-job-summary-stats {
  margin-top: 10px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px 14px;
  font-size: 12px;
  color: var(--muted);
}

.background-job-summary-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  flex-shrink: 0;
}

.background-job-summary-actions :deep(.el-button) {
  margin: 0;
  border-radius: 10px;
}

.empty-state {
  flex: 1 1 0;
  min-height: 220px;
  color: var(--muted-2);
  text-align: center;
  padding: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}

@media (max-width: 960px) {
  .background-job-summary-card {
    grid-template-columns: 1fr;
  }

  .background-job-summary-actions {
    justify-content: flex-start;
  }
}

@media (max-width: 768px), (max-height: 720px) {
  .background-jobs-toolbar {
    grid-template-columns: 1fr;
    gap: 8px;
  }

  .background-jobs-toolbar-left,
  .background-jobs-toolbar-right {
    width: 100%;
    justify-content: flex-start;
  }

  .background-jobs-toolbar-left :deep(.el-button) {
    flex: 1 1 0;
    width: auto;
    height: 32px !important;
    min-height: 32px !important;
  }

  .background-job-platform-filter,
  .background-job-module-search {
    flex: 1 1 100%;
    width: 100%;
  }

  .background-job-platform-filter :deep(.el-select__wrapper),
  .background-job-module-search :deep(.el-input__wrapper) {
    height: 32px !important;
    min-height: 32px !important;
  }

  .panel-lite {
    padding: 12px;
    border-radius: 14px;
  }

  .background-job-module-list {
    display: block;
    padding: 4px 2px calc(16px + env(safe-area-inset-bottom)) 0;
  }

  .background-job-module-card {
    min-height: 0;
    height: auto !important;
    padding: 12px;
    border-radius: 14px;
    overflow: visible;
    box-shadow: 0 4px 14px rgba(15, 23, 42, 0.04);
  }

  .background-job-module-card + .background-job-module-card {
    margin-top: 12px;
  }

  .background-job-module-name,
  .background-job-module-key {
    white-space: normal;
    overflow: visible;
    text-overflow: clip;
    word-break: break-word;
  }

  .background-job-module-name,
  .background-job-summary-title {
    font-size: 14px;
    line-height: 1.4;
  }

  .background-job-module-key {
    line-height: 1.4;
  }

  .background-job-module-desc {
    display: block;
    overflow: visible;
    -webkit-line-clamp: unset;
    line-height: 1.5;
  }

  .background-job-module-tags {
    margin-top: 10px;
    margin-bottom: 0;
    gap: 6px;
  }

  .background-job-module-actions,
  .background-job-summary-actions {
    margin-top: 12px;
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    width: 100%;
    gap: 8px;
    align-items: stretch;
  }

  .background-job-module-actions :deep(.el-button),
  .background-job-summary-actions :deep(.el-button) {
    width: 100%;
    min-width: 0;
    height: 32px !important;
    min-height: 32px !important;
    margin: 0;
    justify-content: center;
  }

  .background-job-module-actions :deep(.el-button:last-child:nth-child(odd)) {
    grid-column: 1 / -1;
  }

  .background-jobs-list {
    display: block;
    padding: 4px 2px calc(16px + env(safe-area-inset-bottom)) 0;
  }

  .background-job-summary-card {
    display: block;
    height: auto !important;
    min-height: 0;
    padding: 12px;
    border-radius: 14px;
    overflow: visible;
    box-shadow: 0 4px 14px rgba(15, 23, 42, 0.04);
  }

  .background-job-summary-card + .background-job-summary-card {
    margin-top: 12px;
  }


}

@media (max-width: 640px) {

}
</style>

<style>
/* BackgroundJobsDialog: 固定弹窗高度，禁止内容撑开，列表内部滚动。 */
/* BackgroundJobsDialog: 固定弹窗高度，禁止内容撑开，列表内部滚动。 */
.background-jobs-overlay .el-overlay-dialog {
  overflow: hidden !important;
}

.background-jobs-overlay .el-dialog {
  height: 78vh !important;
  max-height: 78vh !important;
  margin-top: 5vh !important;
  display: flex !important;
  flex-direction: column !important;
  overflow: hidden !important;
  box-sizing: border-box !important;
}

.background-jobs-overlay .el-dialog__header {
  flex: 0 0 auto !important;
}

.background-jobs-overlay .el-dialog__body {
  flex: 1 1 0 !important;
  min-height: 0 !important;
  overflow: hidden !important;
  display: flex !important;
  flex-direction: column !important;
  padding-top: 12px !important;
  padding-bottom: 12px !important;
  box-sizing: border-box !important;
}

.background-jobs-overlay .fixed-dialog-body,
.background-jobs-overlay .background-jobs-body {
  flex: 1 1 0 !important;
  height: auto !important;
  min-height: 0 !important;
  overflow: hidden !important;
  display: flex !important;
  flex-direction: column !important;
}

.background-jobs-overlay .background-jobs-tabs {
  flex: 1 1 0 !important;
  height: 100% !important;
  min-height: 0 !important;
  display: flex !important;
  flex-direction: column !important;
  overflow: hidden !important;
}

.background-jobs-overlay .background-jobs-tabs .el-tabs__header {
  flex: 0 0 auto !important;
}

.background-jobs-overlay .background-jobs-tabs .el-tabs__content {
  flex: 1 1 0 !important;
  height: 0 !important;
  min-height: 0 !important;
  overflow: hidden !important;
}

.background-jobs-overlay .background-jobs-tabs .el-tab-pane,
.background-jobs-overlay .background-jobs-tab-panel {
  height: 100% !important;
  min-height: 0 !important;
  overflow: hidden !important;
}

.background-jobs-overlay .background-jobs-modules,
.background-jobs-overlay .background-jobs-list-shell {
  flex: 1 1 0 !important;
  height: auto !important;
  min-height: 0 !important;
  max-height: none !important;
  overflow: hidden !important;
  display: flex !important;
  flex-direction: column !important;
}

.background-jobs-overlay .background-job-module-list,
.background-jobs-overlay .background-jobs-list {
  flex: 1 1 0 !important;
  min-height: 0 !important;
  max-height: none !important;
  overflow-y: auto !important;
}

@media (max-width: 768px), (max-height: 720px) {
  .background-jobs-overlay .el-dialog {
    position: fixed !important;
    inset: 0 !important;
    width: 100vw !important;
    max-width: 100vw !important;
    height: 100dvh !important;
    max-height: 100dvh !important;
    margin: 0 !important;
    border-radius: 0 !important;
  }

  .background-jobs-overlay .el-dialog__header {
    padding: 14px 16px 10px !important;
  }

  .background-jobs-overlay .el-dialog__body {
    flex: 1 1 0 !important;
    height: auto !important;
    min-height: 0 !important;
    padding: 10px 12px 12px !important;
  }
}

.background-job-start-tags {
  margin-bottom: 12px;
}

.background-job-param-hint {
  margin-top: 6px;
}

.background-job-detail-dialog .fixed-dialog-body,
.background-job-message-dialog .fixed-dialog-body {
  height: 100%;
  min-height: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.background-job-detail-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
}

.background-job-detail-head-left,
.background-job-file-main {
  min-width: 0;
}

.background-job-title-line {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.background-job-title {
  font-size: 15px;
  font-weight: 700;
  color: var(--text);
  word-break: break-word;
}

.background-job-subtitle {
  margin-top: 8px;
  color: var(--muted);
  font-size: 12px;
}

.background-job-card-head-right {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  flex-shrink: 0;
}

.background-job-stats {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.background-job-stat {
  padding: 10px 12px;
  border-radius: 12px;
  background: #f8fafc;
  border: 1px solid rgba(15, 23, 42, 0.05);
}

.background-job-stat-label {
  font-size: 11px;
  color: var(--muted-2);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.background-job-stat-value {
  margin-top: 4px;
  font-size: 13px;
  color: var(--text);
  word-break: break-word;
}

.background-job-panels {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 12px;
  margin-top: 14px;
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
}

.background-job-panel {
  min-height: 0;
  border: 1px solid rgba(15, 23, 42, 0.06);
  border-radius: 12px;
  background: #fafcff;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.background-job-panel-title {
  padding: 10px 12px;
  font-size: 13px;
  font-weight: 700;
  border-bottom: 1px solid rgba(15, 23, 42, 0.06);
  background: #f8fafc;
}

.background-job-message-list,
.background-job-file-list {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.background-job-message-item,
.background-job-file-item {
  padding: 10px 12px;
  border-radius: 10px;
  background: #fff;
  border: 1px solid rgba(15, 23, 42, 0.05);
}

.background-job-message-item.clickable {
  cursor: pointer;
  transition: background 0.18s ease, border-color 0.18s ease;
}

.background-job-message-item.clickable:hover {
  background: #f8fafc;
  border-color: rgba(37, 99, 235, 0.16);
}

.background-job-message-time {
  font-size: 11px;
  color: var(--muted-2);
  margin-bottom: 6px;
}

.background-job-message-text {
  font-size: 13px;
  line-height: 1.6;
  color: var(--text);
  white-space: pre-wrap;
  word-break: break-word;
}

.background-job-message-text.is-error,
.background-job-full-message-text.is-error {
  color: var(--danger);
}

.background-job-message-text.is-success,
.background-job-full-message-text.is-success {
  color: #166534;
}

.background-job-message-text.single-line {
  height: 20px;
  line-height: 20px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  word-break: normal;
}

.background-job-file-name {
  font-size: 13px;
  font-weight: 700;
  color: var(--text);
  word-break: break-word;
}

.background-job-file-meta {
  margin-top: 6px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  font-size: 12px;
  color: var(--muted);
}

.background-job-file-actions {
  margin-top: 6px;
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.background-job-full-message-time {
  font-size: 12px;
  color: var(--muted);
  margin-bottom: 10px;
}

.background-job-full-message-text {
  margin: 0;
  padding: 14px;
  min-height: 280px;
  max-height: 62vh;
  overflow: auto;
  border-radius: 14px;
  background: #f8fafc;
  border: 1px solid rgba(15, 23, 42, 0.06);
  color: var(--text);
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.65;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 13px;
}


.background-job-detail-dialog .background-job-stat {
    height: 64px;
  min-height: 64px;
    box-sizing: border-box;
  display: flex;
  flex-direction: column;
  justify-content: center;
  padding-top: 8px;
  padding-bottom: 8px;
}

.background-job-detail-dialog .background-job-stat-value {
  min-height: 20px;
  display: flex;
  align-items: center;
}

.background-job-detail-dialog .table-action-link,
.background-job-detail-dialog .table-action-link:link,
.background-job-detail-dialog .table-action-link:visited,
.background-job-detail-dialog .table-action-link:active {
  color: var(--el-color-primary) !important;
  font-size: 12px;
  line-height: 1;
  text-decoration: none !important;
  cursor: pointer;
  white-space: nowrap;
}

.background-job-detail-dialog .table-action-link:hover {
  color: var(--el-color-primary-light-5) !important;
  text-decoration: none !important;
}

.background-job-detail-dialog .empty-state,
.background-job-message-dialog .empty-state {
  color: var(--muted-2);
  text-align: center;
  padding: 24px;
}

.background-job-detail-dialog .empty-state.compact {
  padding: 12px;
}

@media (max-width: 768px), (max-height: 720px) {
  .background-job-stats,
  .background-job-panels {
    grid-template-columns: 1fr;
  }

  .background-job-detail-head {
    flex-direction: column;
    align-items: stretch;
  }

  .background-job-card-head-right {
    justify-content: flex-start;
  }
}
</style>