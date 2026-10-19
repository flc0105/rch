import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'
import vm from 'node:vm'

const here = dirname(fileURLToPath(import.meta.url))
const source = readFileSync(resolve(here, '../src/components/WatchdogInfoPanel.vue'), 'utf8')
const template = source.slice(source.indexOf('<template>') + '<template>'.length, source.indexOf('<script>')).replace(/<\/template>\s*$/, '')
const script = source.match(/<script>([\s\S]*?)<\/script>/)?.[1]
assert.ok(template && script, 'Watchdog panel template and script must exist')
assert.ok(template.indexOf('Process recovery') < template.indexOf('<h4>Remote control</h4>'))
assert.ok(template.indexOf('<h4>Remote control</h4>') < template.indexOf('<h4>Local recovery</h4>'))
assert.match(source, /watchdog-process-card\s*\{\s*grid-column:\s*1\s*\/\s*-1/)
assert.match(template, /status\.process_watchdog\.supervisor_pid/)
assert.match(template, /status\.process_watchdog\.log_path/)
assert.match(template, /status\.client\.pid/)
assert.match(template, /status\.remote_watchdog\.interval_seconds/)
assert.match(template, /status\.local_watchdog\.timeout_seconds/)
assert.match(template, /toggleMode\('process', value\)/)
for (const value of ['remote', 'local', 'process']) {
  assert.match(template, new RegExp(`toggleMode\\('${value}', value\\)`))
}

const updates = []
let serverStatus
const copy = value => JSON.parse(JSON.stringify(value))
const sandbox = {
  ElMessage: { success() {}, warning(message) { throw new Error(message) }, error(message) { throw new Error(message) } },
  ElMessageBox: {},
  getWatchdogStatus: async () => copy(serverStatus),
  getHttpControlActions: async () => [],
  queueHttpControlAction: async () => {},
  updateRuntimeConfig: async (_clientId, key, value) => {
    updates.push({ key, value })
    const name = {
      REMOTE_HTTP_WATCHDOG_ENABLED: 'remote_watchdog',
      LOCAL_WATCHDOG_ENABLED: 'local_watchdog',
      PROCESS_WATCHDOG_ENABLED: 'process_watchdog',
    }[key]
    serverStatus[name].enabled = value
    if (name === 'process_watchdog') serverStatus.process_watchdog.supervisor_alive = value
    else serverStatus[name].worker_alive = value
  },
}
vm.runInNewContext(
  script.replace(/import\s+\{[\s\S]*?\}\s+from\s+['"][^'"]+['"]/g, '')
    .replace('export default {', 'globalThis.component = {'),
  sandbox,
)
const component = sandbox.component
function makeState(status) {
  const instance = { ...component.data(), clientId: 'client-123', currentConnection: {}, status: copy(status) }
  for (const [name, fn] of Object.entries(component.methods)) instance[name] = fn.bind(instance)
  for (const [name, getter] of Object.entries(component.computed)) {
    Object.defineProperty(instance, name, { get: () => getter.call(instance) })
  }
  return instance
}
const baseline = {
  client: { id: 'client-123', pid: 123 },
  remote_watchdog: { enabled: false, worker_pid: null, worker_alive: false, interval_seconds: 5, control_url: '', log_path: '' },
  local_watchdog: { enabled: false, worker_pid: null, worker_alive: false, heartbeat_interval_seconds: 5, timeout_seconds: 15, feeder_alive: false, feeder_thread_name: null, heartbeat_file_path: '', log_path: '' },
  process_watchdog: { enabled: false, supervisor_pid: null, supervisor_alive: false, poll_interval_seconds: 0.5, log_path: '' },
}
let page = makeState(baseline)
assert.equal(page.healthTone, 'off')
assert.equal(page.enabled, false)
page = makeState({ ...baseline, process_watchdog: { ...baseline.process_watchdog, enabled: true, supervisor_alive: true, supervisor_pid: 321 } })
assert.equal(page.enabled, true)
assert.equal(page.healthTone, 'healthy')
assert.equal(page.legacyEnabled, false)
page = makeState({ ...baseline, process_watchdog: { ...baseline.process_watchdog, enabled: true } })
assert.equal(page.healthTone, 'warning')
page = makeState({ ...baseline, remote_watchdog: { ...baseline.remote_watchdog, enabled: true, worker_alive: true } })
assert.equal(page.healthTone, 'healthy')
assert.equal(page.healthSubtitle, 'Remote control is enabled.')
page = makeState({ ...baseline, remote_watchdog: { ...baseline.remote_watchdog, enabled: true, worker_alive: true },
  process_watchdog: { ...baseline.process_watchdog, enabled: true } })
assert.equal(page.healthTone, 'warning')
serverStatus = copy(baseline)
page = makeState(serverStatus)
await page.toggleMode('process', true)
assert.equal(updates.at(-1).key, 'PROCESS_WATCHDOG_ENABLED')
assert.equal(page.status.process_watchdog.enabled, true)
assert.equal(page.status.process_watchdog.supervisor_alive, true)
await page.toggleMode('process', false)
assert.equal(page.status.process_watchdog.enabled, false)
await page.toggleMode('remote', true)
assert.equal(updates.at(-1).key, 'REMOTE_HTTP_WATCHDOG_ENABLED')
await page.toggleMode('local', true)
assert.equal(updates.at(-1).key, 'LOCAL_WATCHDOG_ENABLED')
assert.equal(page.status.local_watchdog.enabled, true)
assert.equal(page.status.local_watchdog.worker_alive, true)
// No old flat representation is accepted as a fallback.
serverStatus = { watchdog_alive: true, process_alive: true }
page = makeState(baseline)
await page.loadStatus()
assert.equal(page.status, null)
assert.equal(page.error, 'Invalid watchdog status response')
console.log('watchdog info panel tests passed')
