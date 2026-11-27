<template>
  <el-dialog v-model="visible" title="Server Cleanup" width="min(860px, 94vw)" append-to-body
    :close-on-click-modal="!busy && !saving" :close-on-press-escape="!busy && !saving" :show-close="!busy && !saving">
    <el-tabs v-model="tab">
      <el-tab-pane label="Clean Now" name="now">
        <div class="cleanup-toolbar">
          <div>
            <strong>{{ plan ? formatBytesHuman(plan.bytes) : '—' }}</strong> available for cleanup
            <div class="cleanup-muted">{{ plan?.records ?? 0 }} records · {{ selectedIds.length }} selected</div>
          </div>
          <el-button :loading="loading" :disabled="busy || saving" @click="refresh">Refresh</el-button>
        </div>
        <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
        <el-alert v-if="plan?.missing_artifacts" :title="`${plan.missing_artifacts} registered Artifact files are missing. Their records are preserved.`" type="warning" :closable="false" />
        <div v-if="plan" class="cleanup-groups" v-loading="loading">
          <section v-for="group in plan.groups" :key="group.key" class="cleanup-group">
                <div class="cleanup-group-header">
                  <button type="button" class="cleanup-expand" :aria-expanded="expanded.includes(group.key)"
                    :aria-label="`${expanded.includes(group.key) ? 'Collapse' : 'Expand'} ${group.label}`"
                    @click="toggleExpanded(group.key)">{{ expanded.includes(group.key) ? '▾' : '▸' }}</button>
                  <el-checkbox :model-value="allSelected(group)" :indeterminate="partSelected(group)"
                    :disabled="busy || !group.entries.length" @click.stop @change="selectGroup(group, $event)" />
                  <strong>{{ group.label }}</strong>
                  <span class="cleanup-group-count">{{ group.count }} items<span v-if="group.records"> · {{ group.records }} records</span></span>
                  <span class="cleanup-size">{{ group.size ? formatBytesHuman(group.size) : '—' }}</span>
                </div>
              <div v-if="expanded.includes(group.key)" class="cleanup-group-body">
              <div v-if="group.error" class="cleanup-error">Scan incomplete: {{ group.error }}</div>
              <div v-if="group.startup_residue" class="cleanup-muted cleanup-hint">Prior Server instance residue. Current-instance resources are protected.</div>
              <div v-if="group.manual_only" class="cleanup-muted cleanup-hint">Manual review only. Files with registered Artifact IDs are preserved.</div>
              <div v-if="group.minimum_age_days" class="cleanup-muted cleanup-hint">Only closed logs at least {{ group.minimum_age_days }} day old are eligible.</div>
              <div v-if="!group.entries.length" class="cleanup-muted cleanup-hint">No eligible items.</div>
              <template v-else>
                <el-input v-if="group.entries.length > 10" v-model="queries[group.key]" clearable size="small" placeholder="Search items…" class="cleanup-search" @input="pages[group.key] = 1" />
                <div v-for="entry in pageEntries(group)" :key="entry.id" class="cleanup-entry">
                  <el-checkbox :model-value="selected.has(entry.id)" :disabled="busy" @change="setSelected(entry.id, $event)" />
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
        <div v-if="busy && run?.state === 'running'" class="cleanup-run">
          <div class="cleanup-toolbar"><strong>Cleaning Server…</strong><span>{{ run.processed }} / {{ run.total }} items</span></div>
          <el-progress :percentage="Math.round(run.processed * 100 / run.total)" :stroke-width="5" />
          <el-button size="small" :disabled="stopping || run.cancel_requested" @click="stop">{{ run.cancel_requested ? 'Stopping…' : 'Stop remaining items' }}</el-button>
        </div>
        <div v-if="result" class="cleanup-result" role="status">
          <strong>Cleanup result</strong>
          <div>{{ formatBytesHuman(result.bytes_freed) }} estimated freed · {{ result.removed_files }} files · {{ result.removed_dirs }} folders · {{ result.removed_records }} records</div>
          <div>{{ result.skipped_count }} skipped · {{ result.stopped_count }} not processed · {{ result.error_count }} errors</div>
          <div v-for="item in result.items.filter(item => item.errors.length)" :key="item.name" class="cleanup-error">{{ item.name }}: {{ item.errors.join('; ') }}</div>
          <a v-if="result.log_url" :href="result.log_url" target="_blank" rel="noopener">View Cleanup Log</a>
        </div>
      </el-tab-pane>
      <el-tab-pane label="Auto Cleanup" name="auto" :disabled="busy">
        <template v-if="settings && plan">
          <div class="cleanup-toolbar"><div><strong>Run on Server Startup</strong><div class="cleanup-muted">Runs once after each Server start.</div></div><el-switch v-model="settings.enabled" /></div>
          <div class="cleanup-policies">
          <div v-for="group in plan.groups.filter(group => !group.manual_only)" :key="group.key" class="cleanup-policy">
            <el-checkbox v-model="settings.categories[group.key].enabled" :disabled="!settings.enabled">{{ group.label }}</el-checkbox>
            <div class="cleanup-retention"><span class="cleanup-muted">Older than</span>
              <el-input-number v-model="settings.categories[group.key].days" size="small" :min="Math.max(group.minimum_age_days, group.key === 'notifications' ? 1 : 0)" :max="3650" :disabled="!settings.enabled || !settings.categories[group.key].enabled" />
              <span class="cleanup-muted">days</span></div>
          </div>
          </div>
          <div class="cleanup-muted cleanup-hint">Orphan Artifact files require manual review. Formal files and execution histories are preserved.</div>
          <el-alert v-if="error" :title="error" type="error" :closable="false" />
        </template>
        <div v-else class="cleanup-muted">Refresh the cleanup scan to load settings.</div>
      </el-tab-pane>
    </el-tabs>
    <template #footer>
      <div class="cleanup-toolbar">
        <span v-if="tab === 'now'" class="cleanup-muted">Selected: {{ formatBytesHuman(selectedBytes) }} · {{ selectedRecords }} records</span>
        <span v-else class="cleanup-muted">Applies on the next Server start.</span>
        <div>
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
const stopping = ref(false)
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
  finally { setBusy(false); selected.value = new Set(); plan.value = null; settings.value = null; emit('changed') }
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
.cleanup-toolbar { display:flex; align-items:center; justify-content:space-between; gap:12px; margin:0 0 12px; flex-wrap:wrap; }
.cleanup-muted { font-size:12px; color:var(--el-text-color-secondary); }
.cleanup-groups { max-height: min(54vh, 520px); overflow:auto; padding-right:4px; }
.cleanup-group { border-bottom:1px solid var(--el-border-color-lighter); }
.cleanup-group-header { display:flex; align-items:center; gap:10px; padding:8px 6px; min-width:0; flex-wrap:wrap; }
.cleanup-expand { background:transparent; border:0; color:var(--el-text-color-secondary); cursor:pointer; padding:4px; font-size:14px; }
.cleanup-group-body { padding:0 10px 10px 20px; }
.cleanup-policies { max-height:min(48vh, 470px); overflow:auto; padding-right:6px; }
.cleanup-group-count { margin-left:auto; color:var(--el-text-color-secondary); font-size:12px; }
.cleanup-size { white-space:nowrap; font-variant-numeric:tabular-nums; min-width:65px; text-align:right; }
.cleanup-entry { display:flex; gap:10px; align-items:flex-start; padding:9px 4px; border-bottom:1px solid var(--el-border-color-lighter); }
.cleanup-entry-main { flex:1; min-width:0; }
.cleanup-entry-name, .cleanup-path { overflow-wrap:anywhere; }
.cleanup-entry-name { font-weight:500; line-height:1.4; }
.cleanup-path { font-size:12px; color:var(--el-text-color-secondary); }
.cleanup-search { margin:8px 0; }
.cleanup-hint { padding:6px 0; }
.cleanup-children { font-size:12px; margin-top:6px; max-height:160px; overflow:auto; }
.cleanup-child { display:flex; justify-content:space-between; gap:8px; overflow-wrap:anywhere; }
.cleanup-child span:last-child { white-space:nowrap; }
.cleanup-policy { display:flex; align-items:center; justify-content:space-between; gap:8px; flex-wrap:wrap; padding:9px 0; border-bottom:1px solid var(--el-border-color-lighter); }
.cleanup-retention { display:flex; align-items:center; gap:7px; }
.cleanup-run, .cleanup-result { padding:12px; border:1px solid var(--el-border-color); border-radius:6px; margin-top:12px; }
.cleanup-run .el-button { margin-top:8px; }
.cleanup-error { color:var(--el-color-danger); font-size:12px; overflow-wrap:anywhere; }
</style>
