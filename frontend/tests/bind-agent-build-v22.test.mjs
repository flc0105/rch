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
  assert.equal(bind.server_transport, 'tcp')
  assert.ok(!Object.hasOwn(bind, 'server_web_host'))
  assert.ok(!Object.hasOwn(bind, 'server_web_scheme'))
  assert.ok(!Object.hasOwn(bind, 'web_port'))
  assert.ok(!Object.hasOwn(bind, 'server_host'))
  assert.ok(!Object.hasOwn(bind, 'server_port'))
  instance.agentForm.connection_mode = 'reverse'
  assert.equal(cmp.methods.buildAgentPayload.call(instance).listener_id, 'tcp-default')
  assert.equal(cmp.methods.buildAgentPayload.call(instance).server_host, '192.168.1.10')
  assert.equal(cmp.methods.buildAgentPayload.call(instance).server_port, 9999)
  assert.ok(!Object.hasOwn(cmp.methods.buildAgentPayload.call(instance), 'server_transport'))
  assert.match(read('../src/components/AgentBuilderDialog.vue'), /v-if="agentForm.connection_mode === 'bind'" label="Listen Port"/)
  assert.match(read('../src/components/AgentBuilderDialog.vue'), /v-if="agentForm.connection_mode !== 'bind' \|\| isGoLoaderBuilder" label="Server IP"/)
  const source = read('../src/components/AgentBuilderDialog.vue')
  assert.doesNotMatch(source, /label="Protocol"|selectedListener\.protocol_build_label/)
  assert.match(source, /:label="`\$\{item.name\} · \$\{item.protocol_label\} :\$\{item.port\}`"/)
})

test('One-liners emit matching Bind/Reverse bootstrap request fields for Python and PowerShell', () => {
  const { terminalOneLiners } = awaitImportTemplate()
  const cmp = component('../src/components/OneLinersDialog.vue', {})
  const obj = { selectedListenerId: 'tcp-default', listeners: [{ id: 'tcp-default', port: 9999 }],
    serverForm: { serverHost: '192.168.1.10', serverPort: '9999', webPort: '8085' },
    connectionMode: 'bind', bindHost: '0.0.0.0', bindPort: '9443', bindTransport: 'mtls_tcp' }
  for (const item of terminalOneLiners) {
    const bind = cmp.methods.renderOneLinerCode.call(obj, item.code)
    assert.match(bind, /connection_mode/)
    assert.match(bind, /bind_host/)
    assert.match(bind, /server_transport/)
    assert.match(bind, /mtls_tcp/)
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
    assert.doesNotMatch(reverse, /server_transport/)
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
  const start = source.indexOf('class="one-liners-config-row"')
  const end = source.indexOf('<div\n        v-if="!normalizedOneLiners.length"', start)
  assert.ok(start >= 0 && end > start)
  const controls = source.slice(start, end)
  for (const label of ['Connection', 'Listen IP', 'Listen Port', 'Web Port']) {
    assert.ok(controls.includes(label), label)
  }
  assert.doesNotMatch(controls, /Bootstrap Web (?:IP|Port)|Client Listen (?:IP|Port)|Web port/)
  for (const label of ['Server IP', 'Web Port']) {
    assert.ok(controls.includes(`<span>${label}</span>`), label)
  }
  assert.ok(controls.includes('Transport'))
  assert.match(controls, /v-model="bindTransport"/)
  assert.match(controls, /value="mtls_tcp"/)
  assert.doesNotMatch(source, /one-liners-mode-row/)
  assert.match(controls, /connectionMode === 'bind' \? 'config-bind' : listeners.length \? 'config-reverse' : 'config-reverse-manual'/)
  assert.match(source, /grid-template-areas: "connection server-host web-port transport bind-host bind-port"/)
  assert.match(source, /grid-template-areas: "connection listener server-host server-port web-port"/)
  assert.match(source, /grid-template-areas: "connection server-host server-port web-port"/)
  assert.match(source, /@container \(max-width: 760px\)[\s\S]*?"connection server-host web-port"\s*"transport bind-host bind-port"/)
  assert.match(source, /@container \(max-width: 440px\)[\s\S]*?repeat\(2, minmax\(0, 1fr\)\)/)
  assert.doesNotMatch(source, /grid-template-columns: repeat\(auto-fit, minmax\(140px, 1fr\)\)/)
  assert.match(source, /width="860px"\s+top="7vh"/)
  assert.match(source, /class="fixed-dialog one-liners-dialog"/)
})


test('Bind One-liner defaults to TCP and Reverse mTLS keeps listener ID only', () => {
  const cmp = component('../src/components/OneLinersDialog.vue', { terminalOneLiners: [] })
  const defaults = cmp.data.call({ getDefaultServerForm: () => ({ serverHost: '192.0.2.2', serverPort: '9999', webPort: '8085' }) })
  assert.equal(defaults.bindTransport, 'tcp')
  const ctx = { selectedListenerId: 'mtls-1', listeners: [{ id: 'mtls-1', protocol: 'mtls_tcp', port: 19998 }],
    serverForm: { serverHost: '192.0.2.2', serverPort: '19998', webPort: '8085' },
    connectionMode: 'bind', bindHost: '0.0.0.0', bindPort: '9443', bindTransport: defaults.bindTransport }
  const bind = cmp.methods.renderOneLinerCode.call(ctx, 'json={{bootstrap_payload_python}}')
  assert.doesNotMatch(bind, /server_transport/)
  assert.doesNotMatch(bind, /listener_id/)
  ctx.connectionMode = 'reverse'
  const reverse = cmp.methods.renderOneLinerCode.call(ctx, 'json={{bootstrap_payload_python}}')
  assert.match(reverse, /'listener_id':'mtls-1'/)
  assert.doesNotMatch(reverse, /server_transport/)
})


test('Go Client and Go Loader retain Bind selection and mode-specific Web endpoint', () => {
  const cmp = component('../src/components/AgentBuilderDialog.vue', {
    AGENT_BUILDER, window: { location: { hostname: '192.168.1.20', protocol: 'http:' } },
  })
  for (const builder of [AGENT_BUILDER.GO, AGENT_BUILDER.GO_LOADER]) {
    const instance = {
      agentForm: { ...cmp.data().agentForm, builder, connection_mode: 'bind',
        server_host: '192.168.1.20', web_port: 8085, bind_host: '0.0.0.0', bind_port: 19445,
        server_transport: 'mtls_tcp' },
      getDefaultAgentTargetArch: cmp.methods.getDefaultAgentTargetArch,
    }
    cmp.methods.applyAgentBuilderRules.call(instance)
    assert.equal(instance.agentForm.connection_mode, 'bind', `${builder} switched away from Bind`)
    const payload = cmp.methods.buildAgentPayload.call(instance)
    assert.equal(payload.connection_mode, 'bind')
    assert.equal(payload.server_transport, 'mtls_tcp')
    assert.equal(payload.bind_port, 19445)
    assert.equal(payload.listener_id, '')
    assert.ok(!Object.hasOwn(payload, 'server_host'))
    assert.ok(!Object.hasOwn(payload, 'server_port'))
    if (builder === AGENT_BUILDER.GO_LOADER) {
      assert.equal(payload.server_web_host, '192.168.1.20')
      assert.equal(payload.web_port, 8085)
    } else {
      assert.ok(!Object.hasOwn(payload, 'server_web_host'))
      assert.ok(!Object.hasOwn(payload, 'web_port'))
    }
    instance.agentForm.connection_mode = 'reverse'
    instance.agentForm.listener_id = 'mtls-listener'
    const reverse = cmp.methods.buildAgentPayload.call(instance)
    assert.equal(reverse.listener_id, 'mtls-listener')
    assert.ok(!Object.hasOwn(reverse, 'server_transport'))
  }
  const source = read('../src/components/AgentBuilderDialog.vue')
  assert.match(source, /<el-form-item label="Connection">/)
  assert.match(source, /v-if="agentForm.connection_mode !== 'bind' \|\| isGoLoaderBuilder" label="Web Port"/)
})
