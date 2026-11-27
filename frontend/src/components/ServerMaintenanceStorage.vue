<template>
  <div class="server-maintenance-row">
    <div>
      <div class="server-maintenance-title">Server Cleanup</div>
      <div class="settings-note settings-note-inline" role="status">{{ summaryText }}</div>
    </div>
    <div class="storage-actions">
      <el-button size="small" :loading="loading" :disabled="disabled || busy" @click="refresh">Refresh</el-button>
      <el-button :disabled="disabled || busy || !token" @click="cleanupDialog.open()">Clean…</el-button>
    </div>
  </div>
  <div class="server-maintenance-row">
    <div>
      <div class="server-maintenance-title">Optimize Database</div>
      <div class="settings-note settings-note-inline">{{ database ? `${formatBytesHuman(database.reusable_bytes)} reusable database space` : 'Reclaim unused SQLite storage.' }}</div>
    </div>
    <el-button :disabled="disabled || busy || !token" @click="openDatabase">Optimize…</el-button>
  </div>
  <ServerCleanupDialog ref="cleanupDialog" :token="token" @changed="refresh" @busy="setBusy" />
  <el-dialog v-model="databaseVisible" title="Optimize Database" width="min(500px, 94vw)" append-to-body
    :close-on-click-modal="!optimizing" :close-on-press-escape="!optimizing" :show-close="!optimizing">
    <div v-loading="databaseLoading" class="database-panel">
      <p>Reclaim unused pages in the Server database. Existing records are kept. Run when Server activity is low.</p>
      <dl v-if="database" class="database-stats">
        <dt>Database file</dt><dd>{{ formatBytesHuman(database.database_bytes) }}</dd>
        <dt>Write-ahead log</dt><dd>{{ formatBytesHuman(database.wal_bytes) }}</dd>
        <dt>Reusable pages</dt><dd>{{ formatBytesHuman(database.reusable_bytes) }}</dd>
        <dt>Free disk space</dt><dd>{{ formatBytesHuman(database.disk_free_bytes) }}</dd>
      </dl>
      <el-alert v-if="databaseError" :title="databaseError" type="error" :closable="false" />
      <el-alert v-if="optimization" :title="`Optimization completed · ${formatBytesHuman(optimization.bytes_reclaimed)} reclaimed${optimization.checkpoint_busy ? ' · WAL checkpoint busy' : ''}`" type="success" :closable="false" />
    </div>
    <template #footer>
      <el-button :disabled="optimizing" @click="databaseVisible = false">Close</el-button>
      <el-button type="primary" :loading="optimizing" :disabled="databaseLoading || !database" @click="optimize">Optimize</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { ElMessageBox } from 'element-plus'
import { getAuthorizationInfo } from '../api/authApi.js'
import { getCleanupSummary, getDatabaseSpace, optimizeDatabase } from '../api/serverMaintenanceApi.js'
import { formatBytesHuman } from '../utils/formatters.js'
import ServerCleanupDialog from './ServerCleanupDialog.vue'
const props = defineProps({ active: Boolean, disabled: Boolean })
const emit = defineEmits(['busy'])
const token = ref(''), summary = ref(null), summaryError = ref(''), loading = ref(false), busy = ref(false)
const database = ref(null), databaseVisible = ref(false), databaseLoading = ref(false), databaseError = ref(''), optimizing = ref(false), optimization = ref(null)
const cleanupDialog = ref(null)
const summaryText = computed(() => summaryError.value || (summary.value ? `${formatBytesHuman(summary.value.bytes)} · ${summary.value.records} records${summary.value.incomplete ? ' · Partial scan' : ''}` : 'Calculating cleanup size…'))
function setBusy(value) { busy.value = value; emit('busy', value) }
async function refresh() {
  if (loading.value) return
  loading.value = true; summaryError.value = ''
  try {
    token.value = String((await getAuthorizationInfo())?.api_token || '').trim()
    if (!token.value) throw new Error('Administrator API Token unavailable')
    const [cleanup, db] = await Promise.allSettled([getCleanupSummary(token.value), getDatabaseSpace(token.value)])
    if (cleanup.status === 'fulfilled') summary.value = cleanup.value
    else summaryError.value = cleanup.reason.message
    if (db.status === 'fulfilled') database.value = db.value
  } catch (e) { summaryError.value = e.message }
  finally { loading.value = false }
}
async function openDatabase() {
  if (busy.value || databaseLoading.value) return
  databaseVisible.value = true; databaseError.value = ''; optimization.value = null; databaseLoading.value = true
  try { database.value = await getDatabaseSpace(token.value) }
  catch (e) { database.value = null; databaseError.value = e.message }
  finally { databaseLoading.value = false }
}
async function optimize() {
  if (busy.value || optimizing.value || databaseLoading.value || !database.value || !token.value) return
  const confirmedToken = token.value
  optimizing.value = true; setBusy(true)
  try { await ElMessageBox.confirm('Optimize the Server database now? Database writes may temporarily wait.', 'Optimize Database', { confirmButtonText: 'Optimize', type: 'warning' }) }
  catch { optimizing.value = false; setBusy(false); return }
  if (token.value !== confirmedToken) { optimizing.value = false; setBusy(false); return }
  databaseError.value = ''; optimization.value = null
  try { optimization.value = await optimizeDatabase(confirmedToken); database.value = optimization.value.after }
  catch (e) { databaseError.value = e.message }
  finally { optimizing.value = false; setBusy(false) }
}
watch(() => props.active, value => { if (value) refresh() }, { immediate: true })
</script>

<style scoped>
.storage-actions { display:flex; gap:8px; flex-shrink:0; }
.storage-actions :deep(.el-button + .el-button) { margin-left:0; }
.database-panel p { margin:0 0 16px; color:var(--el-text-color-secondary); }
.database-stats { display:grid; grid-template-columns:1fr auto; gap:12px; margin-bottom:16px; }
.database-stats dd { margin:0; text-align:right; font-variant-numeric:tabular-nums; }
</style>
