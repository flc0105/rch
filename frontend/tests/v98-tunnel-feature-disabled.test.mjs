import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import vm from 'node:vm'

const source = readFileSync(new URL('../src/components/TerminalToolbar.vue', import.meta.url), 'utf8')
const body = source.match(/\bisActionAvailable\(actionId\)\s*\{([\s\S]*?)\n\s*\},/)?.[1]
assert.ok(body, 'isActionAvailable() must exist')
const check = vm.runInNewContext(`(function(actionId) {${body}\n})`)

test('Tunnel toolbar entry follows Client feature manifest without changing other actions', () => {
  const unavailable = { currentConnection: { feature_manifest: { tunnel: false, remote_files: true } } }
  assert.equal(check.call(unavailable, 'tunnels'), false)
  assert.equal(check.call(unavailable, 'remote-files'), true)
  const enabled = { currentConnection: { feature_manifest: { tunnel: true } } }
  assert.equal(check.call(enabled, 'tunnels'), true)
})
