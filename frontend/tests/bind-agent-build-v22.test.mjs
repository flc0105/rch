import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'

const read = file => readFileSync(new URL(file, import.meta.url), 'utf8')
function component(file, context = {}) {
  const source = read(file)
  const script = source.match(/<script>([\s\S]*?)<\/script>/)?.[1]
  assert.ok(script)
  return vm.runInNewContext(`(${script.replace(/^import .*$/gm, '').replace('export default', '')})`, context)
}
const AGENT_BUILDER = { PYTHON: 'python', GO: 'go', GO_LOADER: 'go_loader' }

test('Build Agent submits a Bind default with Client listen IP/port and no Listener', () => {
  const cmp = component('../src/components/AgentBuilderDialog.vue', { AGENT_BUILDER, window: { location: { hostname: '192.168.1.10', protocol: 'http:' } } })
  const instance = { agentForm: { ...cmp.data().agentForm, builder: 'python', connection_mode: 'bind',
    server_host: '192.168.1.10', server_port: 9999, web_port: 8085, listener_id: 'tcp-default',
    bind_host: '0.0.0.0', bind_port: 9443 } }
  const bind = cmp.methods.buildAgentPayload.call(instance)
  assert.equal(bind.connection_mode, 'bind')
  assert.equal(bind.listener_id, '')
  assert.equal(bind.bind_host, '0.0.0.0')
  assert.equal(bind.bind_port, 9443)
  assert.ok(!Object.hasOwn(bind, 'server_web_host'))
  assert.ok(!Object.hasOwn(bind, 'server_web_scheme'))
  assert.ok(!Object.hasOwn(bind, 'web_port'))
  assert.ok(!Object.hasOwn(bind, 'server_host'))
  assert.ok(!Object.hasOwn(bind, 'server_port'))
  instance.agentForm.connection_mode = 'reverse'
  assert.equal(cmp.methods.buildAgentPayload.call(instance).listener_id, 'tcp-default')
  assert.equal(cmp.methods.buildAgentPayload.call(instance).server_host, '192.168.1.10')
  assert.equal(cmp.methods.buildAgentPayload.call(instance).server_port, 9999)
  assert.match(read('../src/components/AgentBuilderDialog.vue'), /v-if="agentForm.connection_mode === 'bind'" label="Listen Port"/)
  assert.match(read('../src/components/AgentBuilderDialog.vue'), /v-if="agentForm.connection_mode !== 'bind'" label="Server IP"/)
})

test('One-liners emit matching Bind/Reverse bootstrap request fields for Python and PowerShell', () => {
  const { terminalOneLiners } = awaitImportTemplate()
  const cmp = component('../src/components/OneLinersDialog.vue', {})
  const obj = { selectedListenerId: 'tcp-default', listeners: [{ id: 'tcp-default', port: 9999 }],
    serverForm: { serverHost: '192.168.1.10', serverPort: '9999', webPort: '8085' },
    connectionMode: 'bind', bindHost: '0.0.0.0', bindPort: '9443' }
  for (const item of terminalOneLiners) {
    const bind = cmp.methods.renderOneLinerCode.call(obj, item.code)
    assert.match(bind, /connection_mode/)
    assert.match(bind, /bind_host/)
    assert.match(bind, /web_host/)
    assert.match(bind, /9443/)
    assert.doesNotMatch(bind, /['"` ]server_port['"` ]*:/)
    assert.doesNotMatch(bind, /['"` ]server_host['"` ]*:/)
    assert.ok(!bind.includes('{{'))
    obj.connectionMode = 'reverse'
    const reverse = cmp.methods.renderOneLinerCode.call(obj, item.code)
    assert.doesNotMatch(reverse, /connection_mode/)
    assert.match(reverse, /server_port/)
    assert.match(reverse, /server_host/)
    assert.doesNotMatch(reverse, /bind_host/)
    assert.ok(!reverse.includes('{{'))
    obj.connectionMode = 'bind'
  }
})

function awaitImportTemplate() {
  const code = read('../src/data/terminalOneLiners.js').replace('export const terminalOneLiners', 'const terminalOneLiners')
  return vm.runInNewContext(`(() => { ${code}; return { terminalOneLiners }; })()`)
}

test('One-liners mode and Bind inputs stay within the existing configuration card', () => {
  const source = read('../src/components/OneLinersDialog.vue')
  const start = source.indexOf('<div class="one-liners-config-row">')
  const end = source.indexOf('<div\n        v-if="!normalizedOneLiners.length"', start)
  assert.ok(start >= 0 && end > start)
  const controls = source.slice(start, end)
  for (const label of ['Connection', 'Client Listen IP', 'Client Listen Port', 'Web port']) {
    assert.ok(controls.includes(label), label)
  }
  assert.ok(controls.includes('Bootstrap Web IP'))
  assert.doesNotMatch(source, /one-liners-mode-row/)
  assert.match(source, /grid-template-columns: repeat\(auto-fit, minmax\(140px, 1fr\)\)/)
})
