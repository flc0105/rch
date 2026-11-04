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
  AddListenerDialog: {},
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
  assert.match(vue, /<AddListenerDialog /)
  const addSource = readFileSync(new URL('../src/components/AddListenerDialog.vue', import.meta.url), 'utf8')
  assert.match(addSource, /v-for="protocol in protocols"/)
  assert.match(addSource, /<template #footer>/)
  assert.match(addSource, /:close-on-click-modal="true"/)
})

test('Add listener is an independent dialog with protocol-specific notice and submit', async () => {
  const source = readFileSync(new URL('../src/components/AddListenerDialog.vue', import.meta.url), 'utf8')
  const script = source.split('<script>')[1].split('</script>')[0]
    .replace(/\bimport\s+[\s\S]*?\sfrom\s*['"][^'"]+['"]\s*;?/g, '')
    .replace('export default', 'module.exports =')
  let created = null
  const context = {
    module: {exports: {}},
    ElMessage: {warning() { throw new Error('unexpected validation warning') }, success() {}, error(e) { throw e }},
    createListener: async form => {
      created = { ...form }
      return { ok: true, json: async () => ({ code: 0, data: {} }) }
    },
  }
  vm.runInNewContext(script, context)
  const dialog = context.module.exports
  const state = { ...dialog.data(), protocols: [
    {id:'tcp', label:'TCP', notice:''},
    {id:'tls_tcp', label:'TLS/TCP', notice:'Pinned certificate'},
  ], $emit(event) { assert.equal(event, 'created') } }
  dialog.methods.open.call(state)
  state.form.name = 'Public'
  state.form.protocol = 'tls_tcp'
  state.form.port = 9443
  assert.equal(dialog.computed.selectedProtocol.call(state).notice, 'Pinned certificate')
  await dialog.methods.create.call(state)
  assert.equal(created.protocol, 'tls_tcp')
  assert.equal(created.port, 9443)
  assert.equal(state.visible, false)
  assert.match(source, /append-to-body/)
  assert.match(source, /height: 100dvh !important/)
})
