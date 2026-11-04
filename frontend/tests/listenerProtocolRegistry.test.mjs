import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'

const vue = readFileSync(new URL('../src/components/ListenerManagerDialog.vue', import.meta.url), 'utf8')
const script = vue.split('<script>')[1].split('</script>')[0]
  .replace(/\bimport\s+[\s\S]*?\sfrom\s*['"][^'"]+['"]\s*;?/g, '')
  .replace('export default', 'module.exports =')
const context = {
  module: { exports: {} },
  listListenerProtocols: () => 'protocols',
  listListeners: () => 'listeners',
}
vm.runInNewContext(script, context)
const component = context.module.exports

test('Listener manager obtains available protocol choices from registered Server definitions', async () => {
  const state = {
    ...component.data(),
    requestResponse: async name => name === 'protocols' ? [
      {id: 'tcp', label: 'TCP', notice: ''},
      {id: 'tls_tcp', label: 'TLS/TCP', notice: 'A self-signed certificate is generated once. Bundle agents pin its fingerprint.'},
    ] : [{id:'tcp-default', protocol:'tcp', protocol_label:'TCP', port:9999}],
  }
  await component.methods.load.call(state)
  assert.equal(state.protocols.length, 2)
  assert.equal(state.listeners.length, 1)
  state.form.protocol = 'tls_tcp'
  assert.equal(component.computed.selectedProtocol.call(state).label, 'TLS/TCP')
  assert.equal(component.computed.selectedProtocol.call(state).notice,
    'A self-signed certificate is generated once. Bundle agents pin its fingerprint.')
  assert.match(vue, /v-for="protocol in protocols"/)
})
