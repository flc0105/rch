import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import { test } from 'node:test'

const read = path => readFileSync(new URL(path, import.meta.url), 'utf8')
const parent = read('../src/components/ConnectionInfoDialogs.vue')
const child = read('../src/components/IosDashboardPanel.vue')
const script = parent.match(/<script>([\s\S]*?)<\/script>/)?.[1]
const context = { IosDashboardPanel: {}, WatchdogInfoPanel: {}, ElMessage: {}, formatBytesHuman() {}, formatDateTimeStandardValue() {} }
vm.runInNewContext(script.split('\n').filter(line => !/^import /.test(line)).join('\n').replace('export default {', 'const options = {') + '\nglobalThis.options = options', context)
const options = context.options

test('iOS uses separate Dashboard view and its own monitor channel', async () => {
  assert.match(parent, /<IosDashboardPanel\s+v-if="currentConnection\?\.os_alias === 'ios'"/)
  assert.match(parent, /<template v-else>[\s\S]*Device Dashboard/)
  assert.match(child, /iOS Dashboard/)
  assert.match(parent, /\? \['ios_dashboard'\] : \['system', 'storage', 'network', 'battery'\]/)
  let requested
  const dialog = Object.assign({}, options.data(), options.methods, {
    currentConnection: { os_alias: 'ios' }, selectedId: 'ios1', tabId: 't1', infoVisible: true, activeTab: 'dashboard',
    monitorSessionId: '', monitorStarting: false,
  })
  context.fetch = async (url, init) => {
    requested = JSON.parse(init.body)
    return { ok: true, json: async () => ({ code: 0, data: { monitor_session_id: 'session-ios' } }) }
  }
  try {
    await dialog.startDeviceMonitor()
    assert.deepEqual(Array.from(requested.channels), ['ios_dashboard'])
    assert.equal(dialog.monitorSessionId, 'session-ios')
    dialog.handleDeviceMonitorSnapshot({ monitor_session_id: 'session-ios', client_id: 'ios1', channel: 'ios_dashboard', data: { thermal: 'Nominal' } })
    assert.equal(dialog.monitorChannels.ios_dashboard.thermal, 'Nominal')
  } finally { delete context.fetch }
})

test('desktop Dashboard subscribes to its original four channels', async () => {
  const dialog = Object.assign({}, options.data(), options.methods, {
    currentConnection: { os_alias: 'mac' }, selectedId: 'mac1', tabId: 't1', infoVisible: true, activeTab: 'dashboard',
    monitorSessionId: '', monitorStarting: false,
  })
  let channels
  context.fetch = async (_, init) => {
    channels = JSON.parse(init.body).channels
    return { ok: true, json: async () => ({ code: 0, data: { monitor_session_id: 'session-mac' } }) }
  }
  try {
    await dialog.startDeviceMonitor()
    assert.deepEqual(Array.from(channels), ['system', 'storage', 'network', 'battery'])
  } finally { delete context.fetch }
})

test('iOS Dashboard displays memory usage, separate display, audio volume and isolated library counts', () => {
  assert.match(child, /<div class="ios-metric-label">System Memory<\/div>/)
  assert.match(child, /:percentage="bounded\(memory.percent\)"/)
  assert.match(child, /bytes\(memory.used\).*bytes\(memory.total\)/)
  assert.match(child, /<h3>Hardware<\/h3>[\s\S]*<span>Thermal<\/span>/)
  assert.match(child, /<h3>Display<\/h3>[\s\S]*<span>Resolution<\/span>/)
  assert.match(child, /<span>Volume<\/span><strong>\{\{ percent\(audio.volume_percent\) \}\}/)
  assert.match(child, /<h3>Library<\/h3>[\s\S]*count\(library.photos\)[\s\S]*count\(library.music\)[\s\S]*count\(library.contacts\)/)
  const script = child.match(/<script>([\s\S]*?)<\/script>/)[1]
  const ctx = {}
  vm.runInNewContext(script.replace('export default {', 'const component = {') + '\nglobalThis.component = component', ctx)
  assert.equal(ctx.component.methods.percent(null), '—')
  assert.equal(ctx.component.methods.count(null), '—')
  assert.equal(ctx.component.methods.count(-1), '—')
  assert.equal(ctx.component.methods.count(0), '0')
  assert.equal(ctx.component.methods.bounded(105), 100)
})


test('iOS storage formats tested volume keys in decimal GB independently of system memory', () => {
  const script = child.match(/<script>([\s\S]*?)<\/script>/)[1]
  const context = {}
  vm.runInNewContext(script.replace('export default {', 'const component = {') + '\nglobalThis.component = component', context)
  const { storageBytes, bytes } = context.component.methods
  assert.equal(storageBytes(17_435_592_029), '17.4 GB')
  assert.equal(storageBytes(127_308_177_408), '127.3 GB')
  assert.equal(storageBytes(null), '—')
  assert.equal(bytes(1024 ** 3), '1.0 GB')
  assert.match(child, /disk\.total > 0 && disk\.free != null/)
})
