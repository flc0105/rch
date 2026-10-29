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
  assert.match(source, /Copy Path/)
  assert.match(source, /v-if="isLogFilePath\(row\.path\)"/)
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

test('.log action opens existing Log Viewer for selected Client, paths copy without alteration', async () => {
  const copied = []
  const emitted = []
  const { component, source } = loadProcess({
    window: { isSecureContext: true },
    navigator: { clipboard: { writeText: async path => copied.push(path) } },
    ElMessage: { success: text => copied.push(text), error: text => { throw new Error(text) } },
  })
  const dialog = { ...component.methods, selectedId: 'target-client', $emit: (...args) => emitted.push(args) }
  const path = 'C:\\Users\\方良辰\\data\\run.LOG'
  assert.equal(dialog.isLogFilePath(path), true)
  assert.equal(dialog.isLogFilePath('run.log.1'), false)
  dialog.viewOpenFileLog(path)
  dialog.viewOpenFileLog('foo.txt')
  assert.equal(emitted.length, 1)
  assert.deepEqual(JSON.parse(JSON.stringify(emitted[0])), ['open-log-viewer', { clientId: 'target-client', path }])
  await dialog.copyOpenFilePath(path)
  assert.equal(copied[0], path)
  const app = readFileSync(new URL('../src/App.vue', import.meta.url), 'utf8')
  assert.match(app, /ref="processDialogRef"[\s\S]*?@open-log-viewer="openLogViewerDialog"/)
  assert.match(source, /@click="viewOpenFileLog\(row\.path\)"/)
})
