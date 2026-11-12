import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { test } from 'node:test'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const view = readFileSync(resolve(root, 'src/components/SettingsDialog.vue'), 'utf8')
const api = readFileSync(resolve(root, 'src/api/serverMaintenanceApi.js'), 'utf8')
const server = readFileSync(resolve(root, '../backend/run_web.py'), 'utf8')
const routes = readFileSync(resolve(root, '../backend/server/web/routes/server_maintenance.py'), 'utf8')

function settingsMethod({ confirm, status, perform, authorization = async () => ({ api_token: 'admin-test-token' }), delay = fn => fn() }) {
  const script = view.match(/<script>([\s\S]*?)<\/script>/)?.[1]
  assert.ok(script)
  const source = script.replace(/import\s+(?:\{[\s\S]*?\}|[\w$]+)\s+from\s+['"][^'"]+['"]\s*;?/g, '')
    .replace('export default', 'return ')
  const messages = []
  const component = new Function('ElMessage', 'ElMessageBox', 'getServerMaintenance',
    'performServerMaintenance', 'getAuthorizationInfo', 'setTimeout', source)(
    { success: text => messages.push(['success', text]), error: text => messages.push(['error', text]) },
    { confirm }, status, perform, authorization, delay,
  )
  const state = { maintenanceAction: '', maintenanceStatus: '' }
  return { run: action => component.methods.confirmServerMaintenance.call(state, action), state, messages }
}

test('Settings shows Server maintenance in its own tab without saving preferences', () => {
  assert.match(view, /<el-tab-pane label="Server" name="server">/)
  assert.match(view, /Server Maintenance/)
  assert.match(view, /<div v-if="activeTab !== 'server'" class="settings-footer">/)
  assert.match(view, /confirmServerMaintenance\('restart'\)/)
  assert.match(view, /confirmServerMaintenance\('shutdown'\)/)
  assert.match(api, /apiData\('\/api\/server\/maintenance'/)
  assert.match(api, /jsonRequestOptions\('POST', \{\}, \{/)
  assert.match(api, /Authorization: `Bearer \${adminToken}`/)
  assert.match(view, /await getAuthorizationInfo\(\)/)
})

test('Server Maintenance API sends admin Bearer token for GET and POST', async () => {
  const captured = []
  const script = api.replace(/import\s+.*\n/, '').replace(/export const/g, 'const')
  const impl = new Function('apiData', 'jsonRequestOptions', `${script}\nreturn { getServerMaintenance, performServerMaintenance }`)(
    async (url, options) => { captured.push([url, options]); return {} },
    (method, body, headers) => ({ method, body, headers }),
  )
  await impl.getServerMaintenance('admin-secret')
  await impl.performServerMaintenance('restart', 'admin-secret')
  assert.equal(captured[0][0], '/api/server/maintenance')
  assert.equal(captured[0][1].headers.Authorization, 'Bearer admin-secret')
  assert.equal(captured[1][0], '/api/server/restart')
  assert.equal(captured[1][1].method, 'POST')
  assert.equal(captured[1][1].headers.Authorization, 'Bearer admin-secret')
})

test('Canceled confirmation does not send a lifecycle request', async () => {
  let calls = 0
  const { run, state } = settingsMethod({ confirm: async () => { throw new Error('cancel') },
    status: async () => { calls++ }, perform: async () => { calls++ } })
  await run('shutdown')
  assert.equal(calls, 0)
  assert.equal(state.maintenanceAction, '')
})

test('Shutdown confirmation only requests action once and stays disabled once accepted', async () => {
  const calls = []
  const { run, state } = settingsMethod({ confirm: async () => {},
    status: async () => { throw new Error('Unexpected status call') },
    perform: async (action, token) => { calls.push([action, token]) } })
  await run('shutdown')
  assert.deepEqual(calls, [['shutdown', 'admin-test-token']])
  assert.equal(state.maintenanceAction, 'shutdown')
  assert.match(state.maintenanceStatus, /shutdown requested/i)
  await run('shutdown')
  assert.deepEqual(calls, [['shutdown', 'admin-test-token']])
})

test('Restart requires a new server instance, not just an accepted HTTP request', async () => {
  let calls = 0
  const { run, state, messages } = settingsMethod({ confirm: async () => {},
    status: async token => { assert.equal(token, 'admin-test-token'); return { instance_id: ++calls < 3 ? 'old' : 'new' } },
    perform: async (action, token) => { assert.equal(action, 'restart'); assert.equal(token, 'admin-test-token') } })
  await run('restart')
  assert.equal(calls, 3)
  assert.equal(state.maintenanceStatus, 'Server restarted.')
  assert.equal(state.maintenanceAction, '')
  assert.deepEqual(messages, [['success', 'Server restarted']])
})

test('Rejected maintenance restores actionable controls and shows error', async () => {
  const { run, state, messages } = settingsMethod({ confirm: async () => {},
    status: async () => ({ instance_id: 'old' }),
    perform: async () => { throw new Error('Stop active file transfers') } })
  await run('restart')
  assert.equal(state.maintenanceAction, '')
  assert.equal(state.maintenanceStatus, 'Stop active file transfers')
  assert.deepEqual(messages, [['error', 'Stop active file transfers']])
})

test('Missing administrator token stops maintenance before sending a request', async () => {
  let requests = 0
  const { run, state } = settingsMethod({ confirm: async () => {},
    authorization: async () => ({ api_token: '' }),
    status: async () => { requests++ }, perform: async () => { requests++ } })
  await run('restart')
  assert.equal(requests, 0)
  assert.equal(state.maintenanceAction, '')
  assert.match(state.maintenanceStatus, /API Token unavailable/)
})

test('Administrator token is read once per Settings action', async () => {
  let reads = 0
  const tokens = []
  const { run } = settingsMethod({ confirm: async () => {},
    authorization: async () => { reads++; return { api_token: 'token-123' } },
    status: async token => { tokens.push(token); return { instance_id: tokens.length < 4 ? 'old' : 'new' } },
    perform: async (action, token) => { tokens.push(token) } })
  await run('restart')
  assert.equal(reads, 1)
  assert.deepEqual(tokens, ['token-123', 'token-123', 'token-123', 'token-123'])
})

test('Only run_web executes os.execv after ordered socket cleanup', () => {
  assert.match(server, /http_server\.server_close\(\)/)
  assert.match(server, /server\.listener_manager\.stop_all\(\)/)
  assert.match(server, /ws_thread\.join\(/)
  assert.match(server, /os\.execv\(sys\.executable, \[sys\.executable, entry, \*sys\.argv\[1:\]\]\)/)
  assert.match(routes, /response\.call_on_close\(lifecycle\.activate\)/)
  assert.match(routes, /return auth\.has_valid_static_token\(\)/)
  assert.doesNotMatch(routes, /same.origin|Sec-Fetch-Site|Referer|Origin/)
})
