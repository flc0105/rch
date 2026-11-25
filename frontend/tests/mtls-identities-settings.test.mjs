import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = name => readFileSync(new URL(name, import.meta.url), 'utf8')

test('Settings contains explicit Identity initialization, issuance, download and revocation', () => {
  const view = source('../src/components/SettingsDialog.vue')
  const api = source('../src/api/identitiesApi.js')
  assert.match(view, /label="Identities" name="identities"/)
  for (const name of ['initializeIdentity', 'createIdentity', 'downloadIdentity', 'copyIdentityCommand', 'revokeIdentity']) {
    assert.match(view, new RegExp(`${name}\\(`))
  }
  for (const path of ['api/identities', 'api/identities/initialize', 'api/identities/clients']) {
    assert.ok(api.includes(path))
  }
  assert.match(view, /client\.key permissions to 0600/)
  assert.match(view, /identity created/i)
  assert.match(view, /Copy Command<\/el-button>/)
  assert.match(api, /install-command/)
  assert.match(view, /copyTextFallback/)
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

test('Identity layout keeps status, creation, actions, and the shared fixed-height scroll contract', () => {
  const view = source('../src/components/SettingsDialog.vue')
  const identitiesTab = view.split('<el-tab-pane label="Identities" name="identities">')[1]
    .split('<el-tab-pane label="Server" name="server">')[0]
  assert.ok(identitiesTab)
  assert.doesNotMatch(view, /settings-dialog--identities/)
  assert.match(view, /\.identity-panel\s*\{[^}]*flex:\s*0 0 auto\s*;/)
  assert.match(view, /\.settings-dialog\.el-dialog\s*\{[^}]*height:\s*680px\s*;/)
  assert.match(view, /\.settings-dialog\.el-dialog\s*\{[^}]*max-height:\s*calc\(100vh - 32px\)\s*;/)
  assert.match(view, /\.settings-dialog \.el-dialog__body\s*\{[^}]*overflow:\s*hidden\s*;/)
  assert.match(view, /\.settings-dialog \.settings-tab-scroll\s*\{[^}]*height:\s*100%\s*;[^}]*overflow-y:\s*auto\s*;/)
  for (const text of [
    'Server Identity', 'Client Identities', 'Server identity initialized', 'Server identity not initialized',
    'Application-local mTLS trust material.', 'client.key permissions to 0600',
    'Installation identity name', 'Expires ', 'Active', 'Revoked',
  ]) assert.ok(identitiesTab.includes(text), `Identity UI missing: ${text}`)
  for (const action of ['initializeIdentity', 'createIdentity', 'downloadIdentity', 'copyIdentityCommand', 'revokeIdentity']) {
    assert.match(identitiesTab, new RegExp(`@click="${action}(?:\\(|")`))
  }
  assert.match(identitiesTab, /item\.revoked \|\| identityBusy/)
  assert.match(identitiesTab, /role="listitem"/)
  assert.match(view, /@media \(max-width: 760px\)/)
})
