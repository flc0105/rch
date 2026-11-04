import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import { test } from 'node:test'

function loadProcess(options = {}) {
  const source = readFileSync(new URL('../src/components/ProcessDialogs.vue', import.meta.url), 'utf8')
  const script = source.match(/<script>([\s\S]*?)<\/script>/)?.[1]
  assert.ok(script)
  const code = script.split('\n').filter(line => !/^import /.test(line)).join('\n')
    .replace('export default {', 'const component = {') + '\nglobalThis.component = component'
  const context = {
    ElMessage: { success: () => {}, error: () => {} },
    ElMessageBox: {}, sortProcessRows: () => [],
    ...options,
  }
  vm.runInNewContext(code, context, { timeout: 1000 })
  return { component: context.component, source }
}

test('Open Files uses regular Element Plus table and keeps show-more', () => {
  const { component, source } = loadProcess()
  assert.match(source, /<el-table\s+[^>]*:data="visibleOpenFiles"/)
  assert.match(source, /label="Path"/)
  assert.match(source, /label="FD"/)
  const openFilesSection = source.match(/<section class="process-detail-section process-open-files-section">([\s\S]*?)<\/section>/)?.[1]
  assert.ok(openFilesSection)
  assert.doesNotMatch(openFilesSection, /label="Actions"|Copy Path|View Log/)
  assert.ok(!('copyOpenFilePath' in component.methods))
  assert.ok(!('viewOpenFileLog' in component.methods))
  assert.ok(!('isLogFilePath' in component.methods))
  assert.match(source, /openFilesHiddenCount > 0 \|\| openFilesExpanded/)
  const dialog = { processDetail: { open_files: Array.from({ length: 12 }, (_, index) => ({ path: `${index}.txt` })) }, openFilesExpanded: false }
  assert.equal(component.computed.visibleOpenFiles.call(dialog).length, 10)
  assert.equal(component.computed.openFilesHiddenCount.call(dialog), 2)
  dialog.openFilesExpanded = true
  assert.equal(component.computed.visibleOpenFiles.call(dialog).length, 12)
  assert.equal(component.computed.openFilesHiddenCount.call(dialog), 0)
})

test('PID 0 opens detail monitoring while negative and absent PIDs are rejected', async () => {
  const { component } = loadProcess()
  const opened = []
  const dialog = {
    ...component.data(), ...component.methods,
    selectedId: 'client-1',
    stopProcessDetailMonitor: async () => {},
    startProcessDetailMonitor: async pid => { opened.push(pid) },
  }
  await dialog.openProcessDetail(0)
  assert.equal(dialog.processDetailDialogVisible, true)
  assert.equal(dialog.processDetailPid, 0)
  assert.equal(opened[0], 0)
  await dialog.openProcessDetail(-1)
  await dialog.openProcessDetail(undefined)
  await dialog.openProcessDetail('')
  assert.equal(opened.length, 1)
})

test('Open Files no longer declares a log viewer emitter or actions', () => {
  const { component, source } = loadProcess()
  const app = readFileSync(new URL('../src/App.vue', import.meta.url), 'utf8')
  assert.deepEqual(Array.from(component.emits || []), [])
  assert.doesNotMatch(source, /copyOpenFilePath|viewOpenFileLog|isLogFilePath|copyOpenFilePathFallback/)
  const processDialog = app.match(/ref="processDialogRef"([\s\S]*?)\/>/)?.[1]
  assert.ok(processDialog)
  assert.doesNotMatch(processDialog, /open-log-viewer/)
  assert.match(app, /ref="connectionInfoDialogRef"[\s\S]*?@open-log-viewer="openLogViewerDialog"/)
})
