import assert from 'node:assert/strict'
import test from 'node:test'
import {readFileSync} from 'node:fs'
import vm from 'node:vm'

const source = readFileSync(new URL('../src/components/AgentBuilderDialog.vue', import.meta.url), 'utf8')
const script = source.match(/<script>([\s\S]*?)<\/script>/)?.[1]
const AGENT_BUILDER = {PYTHON:'python', GO:'go', GO_LOADER:'go_loader'}
const cmp = vm.runInNewContext(`(${script.replace(/^import .*$/gm,'').replace('export default','')})`,
  {AGENT_BUILDER, window:{location:{hostname:'192.168.1.10',protocol:'http:'}}})

function buildPayload(builder, mode, transport) {
  const ctx = {agentForm:{...cmp.data().agentForm, builder, connection_mode:mode,
    server_host:'192.168.1.10',server_port:19444,web_port:8085,
    listener_id:'mtls-listener',server_transport:transport,
    bind_host:'0.0.0.0',bind_port:19445}}
  return cmp.methods.buildAgentPayload.call(ctx)
}

test('Go binary and Go Loader support Bind TCP/mTLS without redundant Reverse transport', () => {
  assert.match(source, /<el-form-item label="Connection">/)
  for (const builder of ['go','go_loader']) {
    for (const transport of ['tcp','mtls_tcp']) {
      const bind=buildPayload(builder,'bind',transport)
      assert.equal(bind.connection_mode,'bind')
      assert.equal(bind.server_transport,transport)
      assert.equal(bind.bind_host,'0.0.0.0')
      assert.equal(bind.bind_port,19445)
      assert.equal(bind.listener_id,'')
      assert.ok(!Object.hasOwn(bind,'server_port'))
      assert.equal(Object.hasOwn(bind,'server_web_host'),builder==='go_loader')
      assert.equal(Object.hasOwn(bind,'web_port'),builder==='go_loader')
      const reverse=buildPayload(builder,'reverse',transport)
      assert.equal(reverse.listener_id,'mtls-listener')
      assert.equal(reverse.server_port,19444)
      assert.ok(!Object.hasOwn(reverse,'server_transport'))
    }
  }
  assert.match(source,/isGoLoaderBuilder" label="Web Port"/)
})


test('Build Agent radio modes retain valid template bindings when switching to Bind', () => {
  const template = source.split('<script>')[0]
  // Options API imports are not automatically visible in a Vue template.
  assert.doesNotMatch(template, /AGENT_BUILDER\./)
  assert.equal(typeof cmp.computed.isGoLoaderBuilder, 'function')

  for (const builder of ['python', 'go', 'go_loader']) {
    for (const mode of ['reverse', 'bind']) {
      const context = {agentForm:{connection_mode:mode, builder}}
      context.isGoLoaderBuilder = cmp.computed.isGoLoaderBuilder.call(context)
      for (const label of ['Server IP', 'Web Port']) {
        const condition = template.match(new RegExp(`v-if="([^"]+)" label="${label}"`))?.[1]
        assert.ok(condition, `missing condition for ${label}`)
        const visible = vm.runInNewContext(
          `(function () { with(this) { return (${condition}) } }).call(scope)`,
          {scope:context},
        )
        assert.equal(visible, mode === 'reverse' || builder === 'go_loader', `${builder} ${mode} ${label}`)
      }
    }
  }
})
