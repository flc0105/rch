import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { TOOLBAR_ACTION_CATALOG, normalizeToolbarPreferences } from '../src/data/toolbarPreferences.js'
import { listTunnelInstances, createTunnelInstance, editTunnelInstance, removeTunnelInstance, runTunnelInstance } from '../src/api/tunnelsApi.js'

const read = (path) => readFileSync(new URL(`../src/${path}`, import.meta.url), 'utf8')

test('Toolbox, More and dialog lazy-loader share one Tunnel action identifier', () => {
  const toolbar = read('components/TerminalToolbar.vue')
  const app = read('App.vue')
  const dialog = read('components/TunnelManagerDialog.vue')
  const action = TOOLBAR_ACTION_CATALOG.filter(item => item.id === 'tunnels')
  assert.equal(action.length, 1)
  assert.equal(action[0].label, 'Tunnel')
  assert.match(toolbar, /tunnels: 'open-tunnels'/)
  assert.match(toolbar, /'tunnels',\s*'log-viewer'/)
  assert.match(app, /@open-tunnels="openTunnelManagerDialog"/)
  assert.match(app, /tunnels: \(\) => import\('\.\/components\/TunnelManagerDialog\.vue'\)/)
  assert.match(app, /tunnels: 'tunnelManagerDialogRef'/)
  assert.match(app, /tunnels: null/)
  assert.match(dialog, /<el-dialog v-model="visible" title="Tunnel Manager"/)
  assert.match(dialog, /\bSave &amp; Start\b/)
  assert.match(dialog, /operate\(item, 'restart'\)/)
  const preferences = normalizeToolbarPreferences({ toolbar: ['remote-files'], more: [] })
  assert.equal([...preferences.toolbar, ...preferences.more].filter(id => id === 'tunnels').length, 1)
})

test('typed Tunnel API sends structured JSON and uses encoded names, not terminal text', async () => {
  const captured = []
  const original = globalThis.fetch
  globalThis.fetch = async (url, options = {}) => {
    captured.push({ url, options })
    return { ok: true, json: async () => ({ code: 0, data: { ok: true } }) }
  }
  try {
    await listTunnelInstances('bind-id')
    await createTunnelInstance('bind-id', { name: 'web', listen_port: 18085, target_port: 8085 })
    await editTunnelInstance('bind-id', 'web', { target_port: 8086 })
    await runTunnelInstance('bind-id', 'web', 'restart')
    await removeTunnelInstance('bind-id', 'web')
    assert.deepEqual(captured.map(row => row.options.method || 'GET'), ['GET', 'POST', 'PUT', 'POST', 'DELETE'])
    assert.equal(captured[1].url, '/api/connections/bind-id/tunnels')
    assert.equal(JSON.parse(captured[1].options.body).listen_port, 18085)
    assert.equal(captured[3].url, '/api/connections/bind-id/tunnels/web/restart')
    assert.equal(captured[4].url, '/api/connections/bind-id/tunnels/web')
  } finally {
    globalThis.fetch = original
  }
})

test('Manager operates by instance ID, refreshes after actions and cleans polling on close', () => {
  const dialog = read('components/TunnelManagerDialog.vue')
  assert.match(dialog, /const requestId = \+\+this\.requestSerial/)
  assert.match(dialog, /requestId === this\.requestSerial && this\.targetId === clientId/)
  assert.match(dialog, /window\.clearInterval\(this\.pollTimer\)/)
  assert.match(dialog, /:disabled="item\.status !== 'stopped'"/)
  assert.match(dialog, /runTunnelInstance\(clientId, item\.name, action\)/)
  assert.match(dialog, /createTunnelInstance\(clientId, \{ name, \.\.\.config \}\)/)
})


test('mobile Tunnel Manager fits viewport and copy works without secure clipboard API', () => {
  const dialog = read('components/TunnelManagerDialog.vue')
  assert.match(dialog, /width: 100vw !important/)
  assert.match(dialog, /max-height: calc\(100dvh - 85px\)/)
  assert.match(dialog, /copyTextFallback\(address\)/)
  assert.match(dialog, /const clientId = this\.targetId/)
})
