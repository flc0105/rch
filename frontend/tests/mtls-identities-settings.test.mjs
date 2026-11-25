import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = name => readFileSync(new URL(name, import.meta.url), 'utf8')

test('Settings contains explicit Identity initialization, issuance, download and revocation', () => {
  const view = source('../src/components/SettingsDialog.vue')
  const api = source('../src/api/identitiesApi.js')
  assert.match(view, /label="Identities" name="identities"/)
  for (const name of ['initializeIdentity', 'createIdentity', 'downloadIdentity', 'revokeIdentity']) {
    assert.match(view, new RegExp(`${name}\\(`))
  }
  for (const path of ['api/identities', 'api/identities/initialize', 'api/identities/clients']) {
    assert.ok(api.includes(path))
  }
  assert.match(view, /client\.key permissions to 0600/)
  assert.match(view, /identity created/i)
})

test('Build and Bind connection dialogs expose distinct TCP and mTLS options', () => {
  for (const name of ['AgentBuilderDialog.vue', 'ConnectToClientDialog.vue']) {
    const component = source(`../src/components/${name}`)
    assert.match(component, /<el-option label="TCP" value="tcp"/)
    assert.match(component, /<el-option label="mTLS\/TCP" value="mtls_tcp"/)
  }
  const api = source('../src/api/connectionsApi.js')
  assert.match(api, /transport = 'tcp'/)
  assert.match(api, /server_web_base_url: serverWebBaseUrl, name, transport/)
})
