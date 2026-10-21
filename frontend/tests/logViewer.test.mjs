import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import { test } from 'node:test'

const source = file => readFileSync(new URL(file, import.meta.url), 'utf8')
const component = source('../src/components/LogViewerDialog.vue')
const script = component.match(/<script>([\s\S]*?)<\/script>/)?.[1]
assert.ok(script)
const code = script.replace(/^import\s+[\s\S]*?\s+from\s+['"][^'"]+['"]\s*$/gm, '')
  .replace('export default {', 'const options = {') + '\nglobalThis.options = options'
const context = { RemoteFilePicker: {}, ElMessage: { success() {}, error() {} } }
vm.runInNewContext(code, context)
const { options } = context

function makeViewer() {
  const calls = []
  const pending = []
  const fetch = async (url, opts) => {
    const body = JSON.parse(opts.body || '{}')
    calls.push({ url, body, headers: opts.headers })
    if (url.endsWith('/open')) {
      return new Promise(resolve => pending.push(sessionId => resolve({ ok: true, json: async () => ({ code: 0, data: { monitor_session_id: sessionId } }) })))
    }
    return { ok: true, json: async () => ({ code: 0, data: { ok: true } }) }
  }
  const instance = Object.assign({}, options.data(), options.methods, {
    selectedId: 'selected-client', tabId: 'tab-1',
    $refs: { output: { scrollHeight: 400, scrollTop: 0 } },
    $nextTick: callback => callback(),
  })
  instance.post = async (url, data = {}) => {
    const result = await fetch(url, { body: JSON.stringify(data), headers: { 'X-Tab-Id': instance.tabId } })
    const json = await result.json()
    if (json.code !== 0) throw Error(json.message)
    return json.data
  }
  return { instance, calls, pending }
}
const tick = () => new Promise(resolve => setImmediate(resolve))

test('Toolbox opens Log Viewer empty; only remote file picker starts source selection', () => {
  const { instance, calls } = makeViewer()
  instance.open()
  assert.equal(instance.visible, true)
  assert.equal(instance.path, '')
  assert.equal(instance.activeClientId, 'selected-client')
  assert.equal(instance.streaming, true)
  assert.equal(calls.length, 0)
  assert.match(component, /<RemoteFilePicker[\s\S]*selection-mode="file"/)
  assert.doesNotMatch(component, /server-file|local-file|serverFilePicker/)
})

test('Browse starts at the remote file parent folder, including Windows paths', () => {
  const { instance } = makeViewer()
  for (const [path, expected] of [
    ['/tmp/service.log', '/tmp'],
    ['/service.log', '/'],
    ['C:\\Logs\\service.out', 'C:\\Logs'],
    ['C:\\service.out', 'C:\\'],
    ['', ''],
  ]) {
    instance.path = path
    assert.equal(options.computed.pickerInitialPath.call(instance), expected)
  }
  assert.match(component, /:initial-path="pickerInitialPath"/)
})

test('early SSE log snapshot is buffered until monitor HTTP open returns', async () => {
  const { instance, calls, pending } = makeViewer()
  instance.open({ clientId: 'mac-1', path: '/tmp/output.log', title: 'Watchdog' })
  assert.equal(pending.length, 1)
  instance.handleDeviceMonitorSnapshot({ monitor_session_id: 'unrelated', client_id: 'mac-1', channel: 'log_file', data: { content: 'wrong\n' } })
  instance.handleDeviceMonitorSnapshot({ monitor_session_id: 'log-session-1', client_id: 'mac-1', channel: 'log_file', data: { content: 'first\n', exists: true } })
  assert.equal(instance.content, '')
  pending.shift()('log-session-1')
  await tick()
  assert.equal(instance.sessionId, 'log-session-1')
  assert.equal(instance.content, 'first\n')
  assert.equal(instance.status, 'open')
  assert.equal(calls[0].body.options.path, '/tmp/output.log')
  assert.deepEqual(Array.from(calls[0].body.channels), ['log_file'])
  instance.handleDeviceMonitorSnapshot({ monitor_session_id: 'log-session-1', client_id: 'mac-1', channel: 'log_file', data: { content: 'next\n', exists: true } })
  assert.equal(instance.content, 'first\nnext\n')
  instance.clearView()
  assert.equal(instance.content, '')
  assert.equal(calls.filter(row => /clear|remove/.test(row.url)).length, 0)
  instance.handleDeviceMonitorSnapshot({ monitor_session_id: 'log-session-1', client_id: 'mac-1', channel: 'log_file', data: { reset: true, content: 'new\n', exists: true } })
  assert.match(instance.content, /rotated or truncated/)
  assert.match(instance.content, /new/)
  instance.stopSession()
  await tick()
  assert.equal(calls.filter(row => row.url.endsWith('/close')).length, 1)
})

test('paused viewer uses one-shot remote monitor on Refresh', async () => {
  const { instance, pending, calls } = makeViewer()
  instance.open({ clientId: 'client-b' })
  instance.onFileSelected('/var/log/watchdog.log')
  pending.shift()('stream-1')
  await tick()
  instance.streaming = false // normally set by el-switch v-model
  instance.onStreamingChange(false)
  assert.equal(instance.sessionId, '')
  const refresh = instance.refresh()
  assert.equal(pending.length, 1)
  pending.shift()('stream-2')
  await refresh
  assert.equal(instance.sessionId, 'stream-2')
  instance.handleDeviceMonitorSnapshot({ monitor_session_id: 'stream-2', client_id: 'client-b', channel: 'log_file', data: { content: 'tail', exists: true } })
  await tick()
  assert.equal(instance.content, 'tail')
  assert.equal(instance.sessionId, '')
  assert.equal(instance.streaming, false)
  assert.ok(calls.filter(row => row.url.endsWith('/close')).length >= 2)
})

test('Server source boundary is reserved without local file browsing', () => {
  const { instance } = makeViewer()
  instance.open({ side: 'server', path: '/var/log/server.log' })
  assert.equal(instance.sourceSide, 'server')
  assert.match(instance.error, /not available/)
  assert.equal(instance.sessionId, '')
  assert.match(component, /sourceSide !== 'client'/)
})

test('External Tools / Watchdog forward log source to single App viewer', () => {
  const app = source('../src/App.vue')
  const external = source('../src/components/ExternalToolManagerDialog.vue')
  const info = source('../src/components/ConnectionInfoDialogs.vue')
  const watchdog = source('../src/components/WatchdogInfoPanel.vue')
  assert.match(app, /<LogViewerDialog[\s\S]*ref="logViewerDialogRef"/)
  assert.match(app, /@open-log-viewer="openLogViewerDialog"/)
  assert.match(external, /openInstanceLogs\(row\)[\s\S]*\$emit\('open-log-viewer'/)
  assert.doesNotMatch(external, /logStreamTimer|pollInstanceLog|readClientInstanceLogs/)
  assert.match(info, /<WatchdogInfoPanel[\s\S]*@open-log-viewer/)
  assert.equal((watchdog.match(/class="watchdog-log-link"/g) || []).length, 3)
})
