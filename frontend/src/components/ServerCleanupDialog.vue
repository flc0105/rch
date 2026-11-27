<template>
  <el-dialog v-model="visible" title="Server Cleanup" width="min(860px, 94vw)" align-center append-to-body
    class="fixed-dialog server-cleanup-dialog"
    :close-on-click-modal="!busy && !saving" :close-on-press-escape="!busy && !saving" :show-close="!busy && !saving">
    <el-tabs v-model="tab" class="cleanup-tabs">
      <el-tab-pane label="Clean Now" name="now">
        <div class="cleanup-pane">
          <div class="cleanup-overview">
            <div class="cleanup-metric">
              <span class="cleanup-muted">Available for cleanup</span>
              <strong class="cleanup-value">{{ plan ? formatBytesHuman(plan.bytes) : '—' }}</strong>
            </div>
            <div class="cleanup-metric">
              <span class="cleanup-muted">Records</span>
              <strong class="cleanup-value cleanup-value-small">{{ plan ? plan.records : '—' }}</strong>
            </div>
            <el-button size="small" :loading="loading" :disabled="busy || saving" @click="refresh">Refresh</el-button>
          </div>
          <div ref="manualScroll" class="cleanup-scroll" v-loading="loading">
            <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
            <el-alert v-if="plan?.missing_artifacts" :title="`${plan.missing_artifacts} registered Artifact files are missing. Their records are preserved.`" type="warning" :closable="false" />
            <div v-if="busy && run?.state === 'running'" class="cleanup-run" role="status">
              <div class="cleanup-toolbar"><strong>Cleaning Server…</strong><span>{{ run.processed }} / {{ run.total }} items</span></div>
              <el-progress :percentage="run.total ? Math.round(run.processed * 100 / run.total) : 0" :stroke-width="5" />
              <el-button size="small" :disabled="stopping || run.cancel_requested" @click="stop">{{ run.cancel_requested ? 'Stopping…' : 'Stop remaining items' }}</el-button>
            </div>
            <div v-if="result" class="cleanup-result" role="status">
              <div class="cleanup-toolbar"><strong>Cleanup result</strong><a v-if="result.log_url" :href="result.log_url" target="_blank" rel="noopener">View Cleanup Log</a></div>
              <div class="cleanup-result-space">{{ formatBytesHuman(result.bytes_freed) }} <span class="cleanup-muted">estimated freed</span></div>
              <div>{{ result.removed_files }} files · {{ result.removed_dirs }} folders · {{ result.removed_records }} records</div>
              <div class="cleanup-muted">{{ result.skipped_count }} skipped · {{ result.stopped_count }} not processed · {{ result.error_count }} errors</div>
              <div v-for="item in result.items.filter(item => item.errors.length)" :key="item.name" class="cleanup-error">{{ item.name }}: {{ item.errors.join('; ') }}</div>
            </div>
            <div v-if="plan?.groups.length && !loading && !plan.groups.some(group => group.entries.length || group.error)" class="cleanup-empty-inline cleanup-empty-notice">No eligible items.</div>
            <div v-if="plan?.groups.length" class="cleanup-groups">
              <section v-for="group in plan.groups" :key="group.key" class="cleanup-group"
                :class="{ 'is-selected': allSelected(group) || partSelected(group), 'is-empty': !group.entries.length && !group.error }">
                <div class="cleanup-group-header">
                  <el-checkbox :model-value="allSelected(group)" :indeterminate="partSelected(group)"
                    :aria-label="group.label" :disabled="busy || !group.entries.length" @click.stop @change="selectGroup(group, $event)" />
                  <button type="button" class="cleanup-expand" :aria-expanded="expanded.includes(group.key)"
                    :aria-label="`${expanded.includes(group.key) ? 'Collapse' : 'Expand'} ${group.label}`" @click="toggleExpanded(group.key)">
                    <span class="cleanup-group-title">
                      <strong>{{ group.label }}</strong>
                      <span class="cleanup-group-count">{{ group.count }} items<span v-if="group.records"> · {{ group.records }} records</span><span v-if="group.error" class="cleanup-error"> · Scan incomplete</span></span>
                    </span>
                    <span class="cleanup-size">{{ group.size ? formatBytesHuman(group.size) : '—' }}</span>
                    <span class="cleanup-chevron" aria-hidden="true"></span>
                  </button>
                </div>
                <div v-if="expanded.includes(group.key)" class="cleanup-group-body">
                  <div v-if="group.error" class="cleanup-error">Scan incomplete: {{ group.error }}</div>
                  <div v-if="group.startup_residue" class="cleanup-muted cleanup-hint">Prior Server instance residue. Current-instance resources are protected.</div>
                  <div v-if="group.manual_only" class="cleanup-muted cleanup-hint">Manual review only. Files with registered Artifact IDs are preserved.</div>
                  <div v-if="group.minimum_age_days" class="cleanup-muted cleanup-hint">Only closed logs at least {{ group.minimum_age_days }} day old are eligible.</div>
                  <div v-if="!group.entries.length" class="cleanup-empty-inline">No eligible items.</div>
                  <template v-else>
                    <el-input v-if="group.entries.length > 10" v-model="queries[group.key]" clearable size="small" placeholder="Search items…" class="cleanup-search" @input="pages[group.key] = 1" />
                    <div v-if="!filteredEntries(group).length" class="cleanup-empty-inline">No matching items.</div>
                    <div v-for="entry in pageEntries(group)" :key="entry.id" class="cleanup-entry">
                      <el-checkbox :model-value="selected.has(entry.id)" :aria-label="entry.name" :disabled="busy" @change="setSelected(entry.id, $event)" />
                      <div class="cleanup-entry-main">
                        <div class="cleanup-entry-name">{{ entry.name }}</div>
                        <div v-if="entry.path" class="cleanup-path" :title="entry.path">{{ entry.path }}</div>
                        <div class="cleanup-muted">{{ formatDateTimeLocal(entry.modified * 1000) }}<span v-if="entry.dirs"> · {{ entry.files }} files · {{ entry.dirs }} folders</span></div>
                        <details v-if="entry.children.length" class="cleanup-children">
                          <summary>Contents ({{ entry.children.length }})</summary>
                          <div v-for="child in entry.children" :key="child.path" class="cleanup-child">
                            <span>{{ child.path }}</span><span>{{ child.directory ? 'Folder' : formatBytesHuman(child.size) }}</span>
                          </div>
                        </details>
                      </div>
                      <span class="cleanup-size">{{ entry.record && !entry.path ? 'Record' : formatBytesHuman(entry.size) }}</span>
                    </div>
                    <el-pagination v-if="filteredEntries(group).length > pageSize" small layout="prev, pager, next"
                      :total="filteredEntries(group).length" :page-size="pageSize" :current-page="pages[group.key] || 1"
                      @current-change="pages[group.key] = $event" />
                  </template>
                </div>
              </section>
            </div>
            <el-empty v-else-if="!result && !error && !loading && !busy" description="No eligible items." :image-size="72" class="cleanup-placeholder" />
          </div>
        </div>
      </el-tab-pane>
      <el-tab-pane label="Auto Cleanup" name="auto" :disabled="busy || saving">
        <div class="cleanup-pane">
          <template v-if="settings && plan">
            <div class="cleanup-overview cleanup-auto-overview">
              <div><strong>Run on Server Startup</strong><div class="cleanup-muted">Runs once after each Server start.</div></div>
              <el-switch v-model="settings.enabled" :disabled="saving" />
            </div>
            <div class="cleanup-scroll">
              <el-alert v-if="error" :title="error" type="error" :closable="false" />
              <div class="cleanup-policies">
                <div v-for="group in plan.groups.filter(group => !group.manual_only)" :key="group.key" class="cleanup-policy">
                  <el-checkbox v-model="settings.categories[group.key].enabled" :disabled="!settings.enabled || saving">{{ group.label }}</el-checkbox>
                  <div class="cleanup-retention"><span class="cleanup-muted">Older than</span>
                    <el-input-number v-model="settings.categories[group.key].days" size="small" :min="Math.max(group.minimum_age_days, group.key === 'notifications' ? 1 : 0)" :max="3650" :disabled="!settings.enabled || !settings.categories[group.key].enabled || saving" />
                    <span class="cleanup-muted">days</span></div>
                </div>
              </div>
              <div class="cleanup-muted cleanup-policy-note">Orphan Artifact files require manual review. Formal files and execution histories are preserved.</div>
            </div>
          </template>
          <div v-else class="cleanup-scroll" v-loading="loading">
            <el-alert v-if="error" :title="error" type="error" :closable="false" />
            <el-empty description="Refresh the cleanup scan to load settings." :image-size="72" class="cleanup-placeholder">
              <el-button size="small" :loading="loading" :disabled="busy || saving" @click="refresh">Refresh</el-button>
            </el-empty>
          </div>
        </div>
      </el-tab-pane>
    </el-tabs>
    <template #footer>
      <div class="cleanup-footer">
        <div v-if="tab === 'now'" class="cleanup-footer-summary">
          <span class="cleanup-muted">{{ selectedIds.length }} selected</span>
          <strong>{{ formatBytesHuman(selectedBytes) }} <span class="cleanup-muted">· {{ selectedRecords }} records</span></strong>
        </div>
        <span v-else class="cleanup-muted">Applies on the next Server start.</span>
        <div class="cleanup-footer-actions">
          <el-button :disabled="busy || saving" @click="visible = false">Close</el-button>
          <el-button v-if="tab === 'now'" type="danger" :loading="busy" :disabled="loading || !selectedIds.length || !!run && run.state === 'running'" @click="clean">Clean</el-button>
          <el-button v-else type="primary" :loading="saving" :disabled="!settings || loading" @click="save">Save</el-button>
        </div>
      </div>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, ref, onBeforeUnmount } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { formatBytesHuman, formatDateTimeLocal } from '../utils/formatters.js'
import { previewCleanup, executeCleanup, getCleanupRun, cancelCleanupRun, saveCleanupSettings } from '../api/serverMaintenanceApi.js'

const props = defineProps({ token: { type: String, required: true } })
const emit = defineEmits(['changed', 'busy'])
const visible = ref(false), tab = ref('now'), plan = ref(null), settings = ref(null)
const selected = ref(new Set()), expanded = ref([]), queries = ref({}), pages = ref({})
const stopping = ref(false), manualScroll = ref(null)
const loading = ref(false), saving = ref(false), busy = ref(false), error = ref(''), result = ref(null), run = ref(null)
const pageSize = 25
let generation = 0
const selectedIds = computed(() => [...selected.value])
const selectedEntries = computed(() => (plan.value?.groups || []).flatMap(g => g.entries).filter(e => selected.value.has(e.id)))
const selectedBytes = computed(() => selectedEntries.value.reduce((n, e) => n + e.size, 0))
const selectedRecords = computed(() => selectedEntries.value.filter(e => e.record).length)
const allSelected = group => group.entries.length > 0 && group.entries.every(e => selected.value.has(e.id))
const partSelected = group => !allSelected(group) && group.entries.some(e => selected.value.has(e.id))
function toggleExpanded(key) { expanded.value = expanded.value.includes(key) ? expanded.value.filter(item => item !== key) : [...expanded.value, key] }
function setSelected(id, checked) { const next = new Set(selected.value); checked ? next.add(id) : next.delete(id); selected.value = next }
function selectGroup(group, checked) { const next = new Set(selected.value); for (const entry of group.entries) checked ? next.add(entry.id) : next.delete(entry.id); selected.value = next }
function filteredEntries(group) { const query = (queries.value[group.key] || '').trim().toLowerCase(); return group.entries.filter(e => `${e.name} ${e.path}`.toLowerCase().includes(query)) }
function pageEntries(group) { const offset = ((pages.value[group.key] || 1) - 1) * pageSize; return filteredEntries(group).slice(offset, offset + pageSize) }
function setBusy(value) { busy.value = value; emit('busy', value) }
async function refresh() {
  if (busy.value || loading.value || saving.value) return
  loading.value = true; error.value = ''
  const id = ++generation
  try {
    const data = await previewCleanup(props.token)
    if (id !== generation) return
    if (!data?.plan_id) throw new Error('Invalid cleanup preview')
    plan.value = data; settings.value = structuredClone(data.settings); selected.value = new Set(); queries.value = {}; pages.value = {}
    // Never preselect records, logs or orphan objects. Explicit user selection is required.
    for (const group of data.groups) if (['agent_build_temp', 'upload_tmp', 'tcp_transfer_residue', 'bootstrap_temp'].includes(group.key)) selectGroup(group, true)
  } catch (e) { if (id === generation) { error.value = e.message; plan.value = null; settings.value = null; selected.value = new Set() } }
  finally { if (id === generation) loading.value = false }
}
async function open() { if (busy.value || saving.value) return; visible.value = true; tab.value = 'now'; result.value = null; run.value = null; await refresh() }
async function clean() {
  if (!plan.value || !selectedIds.value.length || busy.value || loading.value || saving.value) return
  const planId = plan.value.plan_id, ids = selectedIds.value, token = props.token
  const description = `Permanently clean ${ids.length} selected items (${formatBytesHuman(selectedBytes.value)}, ${selectedRecords.value} records)?`
  setBusy(true)
  try { await ElMessageBox.confirm(description, 'Confirm Server Cleanup', { type: 'warning', confirmButtonText: 'Clean' }) }
  catch { setBusy(false); return }
  if (plan.value?.plan_id !== planId || props.token !== token) { setBusy(false); return }
  error.value = ''; result.value = null; run.value = null
  try {
    run.value = await executeCleanup(planId, ids, token)
    if (manualScroll.value) manualScroll.value.scrollTop = 0
    if (!run.value?.run_id) throw new Error('Cleanup acceptance could not be verified. Refresh before trying again.')
    const runId = run.value.run_id
    let failures = 0
    while (run.value.state === 'running') {
      await new Promise(resolve => setTimeout(resolve, 600))
      try {
        const snapshot = await getCleanupRun(runId, token)
        run.value = { ...snapshot, cancel_requested: snapshot.cancel_requested || run.value.cancel_requested }
        failures = 0
      } catch (e) { if (++failures >= 5) throw new Error('Cleanup status unavailable. Server may still be cleaning. Refresh before trying again.') }
    }
    if (run.value.state === 'failed') throw new Error(run.value.error || 'Cleanup failed')
    result.value = run.value.result
  } catch (e) { error.value = e.message }
  finally {
    setBusy(false); selected.value = new Set(); plan.value = null; settings.value = null
    if (manualScroll.value) manualScroll.value.scrollTop = 0
    emit('changed')
  }
}
async function stop() {
  if (stopping.value || run.value?.state !== 'running' || run.value.cancel_requested) return
  const runId = run.value.run_id
  stopping.value = true
  try {
    const snapshot = await cancelCleanupRun(runId, props.token)
    // A delayed cancellation response must not replace newer polling progress or a terminal result.
    if (run.value?.run_id === runId && run.value.state === 'running' && snapshot.cancel_requested) {
      run.value = { ...run.value, cancel_requested: true }
    }
  } catch (e) { ElMessage.error(e.message) }
  finally { stopping.value = false }
}
async function save() {
  if (!settings.value || saving.value || busy.value || loading.value) return
  saving.value = true; error.value = ''
  try { settings.value = await saveCleanupSettings(settings.value, props.token); ElMessage.success('Auto Cleanup settings saved') }
  catch (e) { error.value = e.message }
  finally { saving.value = false }
}
onBeforeUnmount(() => { generation++ })
defineExpose({ open })
</script>

<style scoped>
.cleanup-pane { display:grid; grid-template-rows:auto minmax(0,1fr); height:100%; min-height:0; min-width:0; gap:8px; overflow:hidden; }
.cleanup-pane:has(> .cleanup-scroll:only-child) { grid-template-rows:minmax(0,1fr); }
.cleanup-overview { display:flex; align-items:center; gap:12px; flex:0 0 auto; min-height:0; padding:7px 10px; box-sizing:border-box; border:1px solid var(--el-border-color-lighter); border-radius:10px; background:var(--el-fill-color-light); }
.cleanup-overview > .el-button { margin-left:auto; flex-shrink:0; }
.cleanup-metric { min-width:0; display:flex; flex-direction:row; align-items:baseline; flex-wrap:wrap; gap:3px 8px; }
.cleanup-metric + .cleanup-metric { padding-left:12px; border-left:1px solid var(--el-border-color); }
.cleanup-value { color:var(--el-text-color-primary); font-size:16px; line-height:1.25; font-weight:650; font-variant-numeric:tabular-nums; white-space:nowrap; }
.cleanup-value-small { font-size:15px; }
.cleanup-muted { font-size:12px; color:var(--el-text-color-secondary); line-height:1.5; font-weight:400; }
.cleanup-scroll { flex:1 1 auto; min-height:0; overflow-y:auto; overflow-x:hidden; overscroll-behavior:contain; scrollbar-gutter:stable; padding:0 4px 2px 0; }
.cleanup-scroll > * + * { margin-top:10px; }
.cleanup-groups { display:flex; flex-direction:column; gap:6px; }
.cleanup-group { border:1px solid var(--el-border-color-lighter); border-radius:9px; overflow:hidden; background:var(--el-bg-color); }
.cleanup-group.is-selected { border-color:var(--el-color-primary-light-7); }
.cleanup-group-header { display:flex; align-items:center; gap:10px; padding:0 12px; min-height:49px; }
.cleanup-group-header > .el-checkbox, .cleanup-entry > .el-checkbox { flex:0 0 auto; margin-right:0; }
.cleanup-expand { display:grid; grid-template-columns:minmax(0,1fr) auto 14px; gap:12px; align-items:center; text-align:left; width:100%; min-width:0; align-self:stretch; padding:6px 0; border:0; background:none; color:var(--el-text-color-primary); font:inherit; cursor:pointer; }
.cleanup-expand:hover strong, .cleanup-expand:focus-visible strong { color:var(--el-color-primary); }
.cleanup-group-title { display:flex; flex-direction:column; gap:2px; min-width:0; overflow-wrap:anywhere; }
.cleanup-group-title strong { font-weight:600; line-height:1.35; }
.cleanup-group-count { font-size:12px; color:var(--el-text-color-secondary); line-height:1.4; }
.is-empty .cleanup-size { color:var(--el-text-color-secondary); }
.cleanup-chevron { width:7px; height:7px; border-right:1.5px solid currentColor; border-bottom:1.5px solid currentColor; transform:rotate(-45deg); color:var(--el-text-color-secondary); justify-self:center; transition:transform .15s ease; }
.cleanup-expand[aria-expanded="true"] .cleanup-chevron { transform:rotate(45deg); }
.cleanup-size { white-space:nowrap; font-variant-numeric:tabular-nums; text-align:right; font-size:13px; color:var(--el-text-color-regular); font-weight:550; }
.cleanup-group-body { border-top:1px solid var(--el-border-color-lighter); padding:8px 12px 10px; background:var(--el-fill-color-extra-light); }
.cleanup-entry { display:grid; grid-template-columns:auto minmax(0,1fr) auto; gap:10px; align-items:start; padding:10px 0; border-bottom:1px solid var(--el-border-color-lighter); }
.cleanup-entry:last-child { border-bottom:0; }
.cleanup-entry-main { min-width:0; }
.cleanup-entry-name, .cleanup-path { overflow-wrap:anywhere; }
.cleanup-entry-name { font-weight:500; line-height:1.4; color:var(--el-text-color-primary); }
.cleanup-path { font-size:12px; color:var(--el-text-color-secondary); line-height:1.5; }
.cleanup-entry > .cleanup-size { padding-top:6px; }
.cleanup-search { margin:4px 0; }
.cleanup-hint { padding:5px 0; }
.cleanup-empty-inline { padding:14px 4px; color:var(--el-text-color-secondary); font-size:12px; text-align:center; }
.cleanup-empty-notice { border:1px dashed var(--el-border-color); border-radius:9px; }
.cleanup-children { font-size:12px; margin-top:6px; padding:6px 8px; border-radius:5px; background:var(--el-fill-color-light); }
.cleanup-children summary { cursor:pointer; color:var(--el-color-primary); }
.cleanup-child { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:8px; padding:4px 0; overflow-wrap:anywhere; }
.cleanup-child span:last-child { white-space:nowrap; }
.cleanup-group-body :deep(.el-pagination) { justify-content:flex-end; padding-top:8px; }
.cleanup-auto-overview { justify-content:space-between; }
.cleanup-policies { border:1px solid var(--el-border-color-lighter); border-radius:9px; overflow:hidden; }
.cleanup-policy { display:flex; align-items:center; justify-content:space-between; gap:8px 16px; flex-wrap:wrap; padding:10px 14px; border-bottom:1px solid var(--el-border-color-lighter); }
.cleanup-policy:last-child { border-bottom:0; }
.cleanup-policy :deep(.el-checkbox) { min-width:0; max-width:100%; height:auto; min-height:32px; }
.cleanup-policy :deep(.el-checkbox__label) { white-space:normal; overflow-wrap:anywhere; }
.cleanup-retention { display:flex; align-items:center; gap:7px; margin-left:auto; }
.cleanup-retention :deep(.el-input-number) { width:104px; }
.cleanup-policy-note { padding:4px 2px; }
.cleanup-placeholder { min-height:180px; height:100%; box-sizing:border-box; justify-content:center; }
.cleanup-toolbar { display:flex; align-items:center; justify-content:space-between; gap:8px; flex-wrap:wrap; }
.cleanup-run, .cleanup-result { display:flex; flex-direction:column; gap:8px; padding:14px; border:1px solid var(--el-border-color); border-radius:9px; }
.cleanup-run { background:var(--el-fill-color-light); }
.cleanup-run .el-button { align-self:flex-end; }
.cleanup-result-space { font-size:21px; font-weight:600; font-variant-numeric:tabular-nums; color:var(--el-text-color-primary); }
.cleanup-result a { color:var(--el-color-primary); font-size:13px; }
.cleanup-error { color:var(--el-color-danger); font-size:12px; overflow-wrap:anywhere; }
.cleanup-footer { display:flex; align-items:center; justify-content:space-between; gap:12px; min-height:44px; text-align:left; }
.cleanup-footer-summary { display:flex; flex-direction:column; gap:2px; min-width:0; font-variant-numeric:tabular-nums; overflow-wrap:anywhere; }
.cleanup-footer-summary strong { color:var(--el-text-color-primary); font-weight:600; }
.cleanup-footer-actions { display:flex; gap:8px; flex-shrink:0; }
.cleanup-footer-actions :deep(.el-button + .el-button) { margin-left:0; }
@media (max-width:480px) {
  .cleanup-pane { gap:10px; }
  .cleanup-overview { padding:7px 8px; gap:8px; }
  .cleanup-overview:not(.cleanup-auto-overview) { display:grid; grid-template-columns:minmax(0,1fr) minmax(48px,auto) auto; }
  .cleanup-metric { flex-direction:column; align-items:flex-start; gap:1px; }
  .cleanup-metric:first-child .cleanup-muted { min-height:18px; }
  .cleanup-metric + .cleanup-metric { padding-left:10px; }
  .cleanup-value { font-size:15px; overflow-wrap:anywhere; white-space:normal; }
  .cleanup-value-small { font-size:14px; }
  .cleanup-group-header { padding:0 10px; gap:8px; }
  .cleanup-expand { gap:8px; }
  .cleanup-group-body { padding:6px 10px; }
  .cleanup-entry { gap:7px; }
  .cleanup-policy { padding:8px 10px; }
  .cleanup-retention { margin-left:24px; }
  .cleanup-footer { gap:8px; }
  .cleanup-footer-actions { gap:6px; }
  .cleanup-footer-actions :deep(.el-button) { padding:8px 12px; }
}
@media (max-width:360px) { .cleanup-metric:first-child .cleanup-muted { min-height:36px; } }
</style>

<style>
/* The shell owns its dimensions even when the separately cached app.css is stale.
   The tab content and not the overlay, body or footer is the scroll boundary. */
.server-cleanup-dialog.el-dialog {
  height:min(760px, 86dvh); max-height:calc(100dvh - 24px);
  display:flex; flex-direction:column; box-sizing:border-box; overflow:hidden;
}
.server-cleanup-dialog.el-dialog > .el-dialog__header,
.server-cleanup-dialog.el-dialog > .el-dialog__footer { flex:0 0 auto; }
.server-cleanup-dialog.el-dialog > .el-dialog__body {
  display:flex; flex:1 1 0; flex-direction:column; min-height:0; min-width:0;
  height:auto; overflow:hidden; padding:0;
}
.server-cleanup-dialog .cleanup-tabs.el-tabs {
  display:flex; flex-direction:column; flex:1 1 0; min-height:0; min-width:0; overflow:hidden;
}
.server-cleanup-dialog .cleanup-tabs > .el-tabs__header { flex:0 0 auto; margin:0 0 8px; }
.server-cleanup-dialog .cleanup-tabs > .el-tabs__content { flex:1 1 0; min-height:0; overflow:hidden; }
.server-cleanup-dialog .cleanup-tabs .el-tab-pane { height:100%; min-height:0; overflow:hidden; }
.server-cleanup-dialog.el-dialog > .el-dialog__footer { border-top:1px solid var(--el-border-color-lighter); margin-top:8px; padding-top:8px; }

</style>
