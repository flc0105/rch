import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import { test } from 'node:test'

function readComponent(path, globals = {}) {
  const source = readFileSync(new URL(path, import.meta.url), 'utf8')
  const script = source.match(/<script>([\s\S]*?)<\/script>/)?.[1]
  assert.ok(script, `Missing script: ${path}`)
  const code = script.split('\n').filter(line => !/^import /.test(line)).join('\n')
    .replace('export default {', 'const component = {') + '\nglobalThis.component = component'
  const context = { ...globals }
  vm.runInNewContext(code, context, { timeout: 1000 })
  return { source, options: context.component }
}

const settle = () => new Promise(resolve => setImmediate(resolve))

// Reuse the real App method without loading its other unrelated component imports.
function appRemoteFilesHandler() {
  const source = readFileSync(new URL('../src/App.vue', import.meta.url), 'utf8')
  assert.match(source, /<ConnectionInfoDialogs[\s\S]*?@open-remote-files="openRemoteFilesDialog"/)
  const method = source.match(/    openRemoteFilesDialog\(path = ''\) \{[\s\S]*?\n    \},/)?.[0]
  assert.ok(method, 'App must forward an optional initial directory to RemoteFilesDialog')
  return vm.runInNewContext(`({${method}})`).openRemoteFilesDialog
}

test('Dashboard volume click closes Info before Remote Files opens at the mountpoint', async () => {
  const requests = []
  const remote = readComponent('../src/components/RemoteFilesDialog.vue', {
    AbortController, RemotePinsDialog: {}, MoreFilled: {},
    ElMessage: { warning(message) { throw new Error(message) }, error(message) { throw new Error(message) } },
    listRemoteDirectory: async (clientId, { path, page }) => {
      requests.push({ clientId, path, page })
      return {
        ok: true,
        json: async () => ({ code: 0, data: {
          current_path: path || '/home/test', parent_path: '', entries: [],
          pagination: { page: 1, total_pages: 1 }, summary: {},
        } }),
      }
    },
  })
  const remoteDialog = {
    ...remote.options.data(), ...remote.options.methods,
    selectedId: 'client-1',
    $refs: {}, $emit() {},
    loadQuickJumpPaths() {}, loadPinnedQuickJumps() {},
    scrollRemoteMobileFileListToTop() {},
  }
  const openRemoteFilesDialog = appRemoteFilesHandler()
  const app = { $refs: { remoteFilesDialogRef: remoteDialog } }

  const info = readComponent('../src/components/ConnectionInfoDialogs.vue', {
    ElMessage: {}, WatchdogInfoPanel: {}, IosDashboardPanel: {},
    formatBytesHuman() {}, formatDateTimeStandardValue() {},
  })
  assert.match(info.source, /@click="openVolumeFromDashboard\(volume\)"/)
  assert.match(info.source, /@keydown\.enter\.prevent="openVolumeFromDashboard\(volume\)"/)
  assert.match(info.source, /@keydown\.space\.prevent="openVolumeFromDashboard\(volume\)"/)
  const emitHistory = []
  const dashboard = {
    ...info.options.data(), ...info.options.methods,
    infoVisible: true,
    $emit(event, value) {
      emitHistory.push([event, value, this.infoVisible])
      if (event === 'open-remote-files') openRemoteFilesDialog.call(app, value)
    },
  }

  for (const path of ['/Volumes/External Data', 'C:\\', '/']) {
    dashboard.infoVisible = true
    dashboard.openVolumeFromDashboard({ name: 'Drive', mountpoint: path })
    assert.equal(dashboard.infoVisible, false)
    assert.equal(remoteDialog.visible, false, 'Remote Files must wait until the Info close animation completes')
    dashboard.handleInfoDialogClosed()
    await settle()
    assert.equal(remoteDialog.visible, true)
    assert.equal(remoteDialog.remoteFilesCurrentPath, path)
    assert.equal(requests.at(-1).path, path)
    assert.equal(requests.at(-1).clientId, 'client-1')
    assert.equal(requests.at(-1).page, 1)
    remoteDialog.close()
    assert.equal(remoteDialog.visible, false)
  }
  assert.equal(emitHistory.length, 3)
  assert.ok(emitHistory.every(([event, , visible]) => event === 'open-remote-files' && visible === false))

  // No mountpoint: the card has no actionable destination.
  dashboard.infoVisible = true
  dashboard.openVolumeFromDashboard({ name: 'Unknown', mountpoint: '' })
  assert.equal(dashboard.infoVisible, true)
  dashboard.handleInfoDialogClosed()
  assert.equal(emitHistory.length, 3)

  // Ordinary toolbar entry still uses the selected Client's default directory.
  openRemoteFilesDialog.call(app)
  await settle()
  assert.equal(requests.at(-1).path, '')
  assert.equal(remoteDialog.remoteFilesCurrentPath, '/home/test')
  remoteDialog.close()
})

test('Dashboard CPU/Memory handoff still uses original process event', () => {
  const info = readComponent('../src/components/ConnectionInfoDialogs.vue', {
    ElMessage: {}, WatchdogInfoPanel: {}, IosDashboardPanel: {},
    formatBytesHuman() {}, formatDateTimeStandardValue() {},
  })
  const events = []
  const dashboard = {
    ...info.options.data(), ...info.options.methods,
    infoVisible: true, currentConnection: { feature_manifest: { process_monitor: true } },
    $emit(...args) { events.push(args) },
  }
  dashboard.openProcessesFromDashboard('cpu_percent')
  assert.equal(dashboard.infoVisible, false)
  dashboard.handleInfoDialogClosed()
  assert.deepEqual(events, [['open-processes', 'cpu_percent']])
  assert.equal(dashboard.pendingRemoteFilesPath, '')
})
