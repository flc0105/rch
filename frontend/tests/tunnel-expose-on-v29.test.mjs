import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = readFileSync(new URL('../src/components/TunnelManagerDialog.vue', import.meta.url), 'utf8')

test('Tunnel Toolbox retains original instance fields and adds one Expose on selector', () => {
  assert.match(source, /label="Expose on"/)
  assert.match(source, /<el-option label="Client" value="client" \/>/)
  assert.match(source, /<el-option label="Server" value="server" \/>/)
  for (const name of ['listen_host', 'listen_port', 'target_host', 'target_port']) {
    assert.match(source, new RegExp(`v-model="form\\.${name}"`))
  }
  assert.match(source, /const config = \{ expose_on, listen_host, listen_port, target_host, target_port \}/)
  assert.match(source, /item\.expose_on === 'server' \? 'Server' : 'Client'/)
  assert.match(source, /item\.expose_on === 'server' \? 'Client' : 'Server'/)
  assert.match(source, /details\.expose_on === 'server'/)
  assert.match(source, /operate\(item, 'restart'\)/)
  assert.match(source, /Save &amp; Start/)
})

// A shared RCH listener supplies all independent Tunnel TCP connections.
test('Tunnel form no longer offers a dedicated channel port', () => {
  assert.doesNotMatch(source, /channel_port|Shared Channel Port|9444/)
})
