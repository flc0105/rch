import test from 'node:test'
import vm from 'node:vm'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
const read = path => readFileSync(new URL(path, import.meta.url), 'utf8')
const dialog = read('../src/components/ServerCleanupDialog.vue')
const storage = read('../src/components/ServerMaintenanceStorage.vue')
const settings = read('../src/components/SettingsDialog.vue')
const api = read('../src/api/serverMaintenanceApi.js')

test('maintenance retains restart and shutdown and mounts independent storage entries', () => {
  assert.match(settings, /<ServerMaintenanceStorage/)
  assert.match(settings, /confirmServerMaintenance\('restart'\)/)
  assert.match(settings, /confirmServerMaintenance\('shutdown'\)/)
  assert.match(settings, /storageMaintenanceBusy/)
  assert.match(storage, /<ServerCleanupDialog/)
  assert.match(storage, /title="Optimize Database"/)
  assert.match(storage, /reusable_bytes/)
})
test('cleanup dialog groups selectable entries and displays records separately from size', () => {
  assert.match(dialog, /label="Clean Now"/)
  assert.match(dialog, /label="Auto Cleanup"/)
  assert.match(dialog, /selectGroup\(group, \$event\)/)
  assert.match(dialog, /setSelected\(entry.id, \$event\)/)
  assert.match(dialog, /entry.children/)
  assert.match(dialog, /selectedRecords/)
  assert.match(dialog, /missing_artifacts/)
  assert.match(dialog, /Permanently clean/)
})
test('manual cleanup sends only plan and candidate IDs with an admin token', () => {
  assert.match(api, /plan_id: planId, selected_ids: selectedIds/)
  assert.match(api, /Authorization: `Bearer \$\{token\}`/)
  assert.match(dialog, /executeCleanup\(planId, ids, token\)/)
  assert.match(dialog, /cancelCleanupRun/)
  assert.match(dialog, /getCleanupRun/)
  assert.match(dialog, /result.stopped_count/)
})
test('automatic settings exclude manual-only orphan files and database optimization is independent', () => {
  assert.match(dialog, /filter\(group => !group.manual_only\)/)
  assert.match(dialog, /settings.categories\[group.key\].days/)
  assert.match(dialog, /saveCleanupSettings\(settings.value, props.token\)/)
  assert.match(api, /\/api\/server\/maintenance\/database\/optimize/)
  assert.match(storage, /Existing records are kept/)
})


function deferred() {
  let resolve
  const promise = new Promise(r => { resolve = r })
  return { promise, resolve }
}
function loadCleanup(dependencies) {
  const source = dialog.match(/<script setup>([\s\S]*?)<\/script>/)[1].replace(/^import .*$/gm, '')
  return vm.runInNewContext(`(() => { ${source}; return { open, refresh, clean, stop, plan, selected, run, result, busy } })()`, {
    ref: value => ({ value }), computed: get => ({ get value() { return get() } }),
    defineProps: () => ({ token: 'test' }), defineEmits: () => () => {}, defineExpose() {}, onBeforeUnmount() {},
    formatBytesHuman: n => String(n), structuredClone, setTimeout: resolve => resolve(),
    ElMessage: { error() {} }, ...dependencies,
  })
}
test('cleanup confirmation locks the preview and sends exactly the confirmed candidates', async () => {
  const confirm = deferred(), calls = []
  const ui = loadCleanup({ ElMessageBox: { confirm: () => confirm.promise },
    previewCleanup: async () => ({ plan_id: 'original', settings: {}, groups: [] }),
    executeCleanup: async (...args) => { calls.push(args); return { run_id: 'run', state: 'completed', result: {} } },
  })
  await ui.open()
  ui.selected.value = new Set(['first'])
  const work = ui.clean()
  assert.equal(ui.busy.value, true)
  await ui.refresh(); await ui.open()
  ui.selected.value = new Set(['different'])
  confirm.resolve(); await work
  assert.deepEqual(JSON.parse(JSON.stringify(calls)), [['original', ['first'], 'test']])
  assert.equal(ui.busy.value, false)
})
test('late Stop response cannot overwrite a completed cleanup or reset progress', async () => {
  const cancel = deferred()
  const ui = loadCleanup({ cancelCleanupRun: () => cancel.promise })
  ui.run.value = { run_id: 'run', state: 'running', processed: 1 }
  const stopping = ui.stop()
  ui.run.value = { run_id: 'run', state: 'completed', processed: 4 }
  cancel.resolve({ run_id: 'run', state: 'running', processed: 1, cancel_requested: true })
  await stopping
  assert.equal(ui.run.value.state, 'completed')
  assert.equal(ui.run.value.processed, 4)
})
