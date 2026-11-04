import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'

const script = readFileSync(new URL('../src/components/AgentBuilderDialog.vue', import.meta.url), 'utf8')
  .split('<script>')[1].split('</script>')[0]
  .replace(/\bimport\s+[\s\S]*?\sfrom\s*['"][^'"]+['"]\s*;?/g, '')
  .replace('export default', 'module.exports =')
const context = { module: { exports: {} }, window: { location: { hostname: 'example.org', protocol: 'http:' } } }
vm.runInNewContext(script, context)
const component = context.module.exports

function state(builder, listenerId) {
  return {
    agentForm: { builder, listener_id: listenerId, server_host: 'example.org', server_port: 9999, web_port: 8085, target_os: 'mac', target_arch: 'arm64' },
    listeners: [{id:'lan',name:'Local',protocol:'tcp',port:9999,supported_builders:null,protocol_label:'TCP'}, {id:'secure',name:'Public',protocol:'tls_tcp',port:9443,supported_builders:['bundle'],protocol_label:'TLS/TCP'}],
  }
}

test('Bundle builder can choose TCP or TLS listeners', () => {
  const s=state('bundle','secure')
  assert.deepEqual(Array.from(component.computed.compatibleListeners.call(s), x => x.id), ['lan','secure'])
  component.methods.applyListener.call(s)
  assert.equal(s.agentForm.server_port,9443)
  assert.equal(component.methods.buildAgentPayload.call(s).listener_id,'secure')
})

test('Go builders see only TCP listeners', () => {
  for(const builder of ['go','go_loader','pyinstaller']) {
    const s=state(builder,'lan')
    assert.deepEqual(Array.from(component.computed.compatibleListeners.call(s), x => x.id), ['lan'])
  }
})

test('Builder compatibility follows protocol metadata rather than protocol names', () => {
  const s=state('bundle','secure')
  s.listeners.push({id:'future', name:'Future', protocol:'custom', port:8080, supported_builders:['bundle']})
  assert.deepEqual(Array.from(component.computed.compatibleListeners.call(s), x => x.id), ['lan','secure','future'])
  s.agentForm.builder='go'
  assert.deepEqual(Array.from(component.computed.compatibleListeners.call(s), x => x.id), ['lan'])
})
