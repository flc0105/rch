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
assert.ok(template.indexOf('Process Recovery Watchdog') < template.indexOf('<h4>Remote Control Watchdog</h4>'))
assert.ok(template.indexOf('<h4>Remote Control Watchdog</h4>') < template.indexOf('<h4>Local Heartbeat Watchdog</h4>'))
assert.match(source, /watchdog-process-card\s*\{\s*grid-column:\s*1\s*\/\s*-1/)
assert.match(template, /status\.process_recovery_watchdog\.supervisor_pid/)
assert.match(template, /status\.process_recovery_watchdog\.log_path/)
for (const kind of ['process_recovery_watchdog', 'remote_control_watchdog', 'local_heartbeat_watchdog']) {
  assert.match(template, new RegExp(`<code>\\{\\{ status\\.${kind}\\.log_path \\}\\}</code>\\s*<button class="watchdog-log-link"`))
}
assert.match(source, /\.watchdog-log-location code \{ display: inline; \}/)
assert.match(template, /status\.client\.pid/)
assert.match(template, /status\.remote_control_watchdog\.interval_seconds/)
assert.match(template, /status\.local_heartbeat_watchdog\.timeout_seconds/)
assert.match(source, /Lifecycle managed by/)
assert.match(template, /Managed by \${launchdManagerLabel}/)
assert.match(template, /toggleMode\('process_recovery', value\)/)
for (const value of ['remote_control', 'local_heartbeat', 'process_recovery']) {
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
      REMOTE_CONTROL_WATCHDOG_ENABLED: 'remote_control_watchdog',
      LOCAL_HEARTBEAT_WATCHDOG_ENABLED: 'local_heartbeat_watchdog',
      PROCESS_RECOVERY_WATCHDOG_ENABLED: 'process_recovery_watchdog',
    }[key]
    serverStatus[name].enabled = value
    if (name === 'process_recovery_watchdog') serverStatus.process_recovery_watchdog.supervisor_alive = value
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
  client: { id: 'client-123', pid: 123, lifecycle_manager: '', watchdogs_suppressed: false },
  remote_control_watchdog: { enabled: false, worker_pid: null, worker_alive: false, interval_seconds: 5, control_url: '', log_path: '' },
  local_heartbeat_watchdog: { enabled: false, worker_pid: null, worker_alive: false, heartbeat_interval_seconds: 5, timeout_seconds: 15, feeder_alive: false, feeder_thread_name: null, heartbeat_file_path: '', log_path: '' },
  process_recovery_watchdog: { enabled: false, supervisor_pid: null, supervisor_alive: false, poll_interval_seconds: 0.5, log_path: '' },
}
let page = makeState(baseline)
assert.equal(page.healthTone, 'off')
assert.equal(page.enabled, false)
page = makeState({ ...baseline, process_recovery_watchdog: { ...baseline.process_recovery_watchdog, enabled: true, supervisor_alive: true, supervisor_pid: 321 } })
assert.equal(page.enabled, true)
assert.equal(page.healthTone, 'healthy')
assert.equal(page.sharedWorkerEnabled, false)
page = makeState({ ...baseline, process_recovery_watchdog: { ...baseline.process_recovery_watchdog, enabled: true } })
assert.equal(page.healthTone, 'warning')
page = makeState({ ...baseline, remote_control_watchdog: { ...baseline.remote_control_watchdog, enabled: true, worker_alive: true } })
assert.equal(page.healthTone, 'healthy')
assert.equal(page.healthSubtitle, 'Remote Control Watchdog is enabled.')
page = makeState({ ...baseline, remote_control_watchdog: { ...baseline.remote_control_watchdog, enabled: true, worker_alive: true },
  process_recovery_watchdog: { ...baseline.process_recovery_watchdog, enabled: true } })
assert.equal(page.healthTone, 'warning')
page = makeState({
  ...baseline,
  client: { ...baseline.client, lifecycle_manager: 'launchd', watchdogs_suppressed: true },
  remote_control_watchdog: { ...baseline.remote_control_watchdog, configured_enabled: true, suppressed: true },
  local_heartbeat_watchdog: { ...baseline.local_heartbeat_watchdog, configured_enabled: true, suppressed: true },
  process_recovery_watchdog: { ...baseline.process_recovery_watchdog, configured_enabled: true, suppressed: true },
})
assert.equal(page.launchdManaged, true)
page.currentConnection = { launch_source: 'launchagent' }
assert.equal(page.launchdManagerLabel, 'LaunchAgent')
assert.equal(page.healthTitle, 'Lifecycle managed by LaunchAgent')
assert.match(page.healthSubtitle, /LaunchAgent remains the single lifecycle supervisor/)
assert.equal(page.canToggleMode, true)
assert.equal(page.canControl, false)
assert.match(page.actionHint, /disabled while LaunchAgent manages this Client/)
page.currentConnection = { feature_manifest: { watchdog: false } }
assert.equal(page.watchdogSupported, false)
assert.equal(page.canToggleMode, false)
assert.match(page.healthTitle, /unavailable/)
assert.equal((template.match(/v-if="watchdogSupported"/g) || []).length, 3)
assert.match(template, /v-for="action in actions"/)
assert.equal(page.canControl, false)
serverStatus = copy(baseline)
page = makeState(serverStatus)
await page.toggleMode('process_recovery', true)
assert.equal(updates.at(-1).key, 'PROCESS_RECOVERY_WATCHDOG_ENABLED')
assert.equal(page.status.process_recovery_watchdog.enabled, true)
assert.equal(page.status.process_recovery_watchdog.supervisor_alive, true)
await page.toggleMode('process_recovery', false)
assert.equal(page.status.process_recovery_watchdog.enabled, false)
await page.toggleMode('remote_control', true)
assert.equal(updates.at(-1).key, 'REMOTE_CONTROL_WATCHDOG_ENABLED')
await page.toggleMode('local_heartbeat', true)
assert.equal(updates.at(-1).key, 'LOCAL_HEARTBEAT_WATCHDOG_ENABLED')
assert.equal(page.status.local_heartbeat_watchdog.enabled, true)
assert.equal(page.status.local_heartbeat_watchdog.worker_alive, true)
// No old flat representation is accepted as a fallback.
serverStatus = { watchdog_alive: true, process_alive: true }
page = makeState(baseline)
await page.loadStatus()
assert.equal(page.status, null)
assert.equal(page.error, 'Invalid watchdog status response')
console.log('watchdog info panel tests passed')
