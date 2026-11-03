import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import {
  listKeychains, getKeychainCredential, saveKeychainCredential, deleteKeychainCredential,
} from '../src/api/keychainsApi.js'
import {
  getAgentPlatform, buildAgent, agentDownloadUrl, listAgentOutputs, deleteAgentOutput,
} from '../src/api/agentApi.js'

async function capture(fn) {
  const original = globalThis.fetch
  const response = { ok: true, status: 200 }
  let request
  globalThis.fetch = async (url, options) => {
    request = { url, options }
    return response
  }
  try {
    assert.strictEqual(await fn(), response)
    return request
  } finally {
    globalThis.fetch = original
  }
}

const jsonBody = request => JSON.parse(request.options.body)
const jsonHeader = request => assert.equal(request.options.headers['Content-Type'], 'application/json')

test('keychains list includes machine scope only when selected', async () => {
  assert.equal((await capture(() => listKeychains())).url, '/api/keychains')
  assert.equal((await capture(() => listKeychains('machine/名 &?'))).url,
    '/api/keychains?machine_id=machine%2F%E5%90%8D+%26%3F')
  assert.equal((await capture(() => listKeychains('__shared__'))).url,
    '/api/keychains?machine_id=__shared__')
})

test('keychains get and delete encode the credential id exactly once', async () => {
  const id = 'ID/中文 ?#'
  const item = await capture(() => getKeychainCredential(id))
  assert.equal(item.url, '/api/keychains/ID%2F%E4%B8%AD%E6%96%87%20%3F%23')
  assert.equal(item.options, undefined)
  const deleted = await capture(() => deleteKeychainCredential(id))
  assert.equal(deleted.url, item.url)
  assert.equal(deleted.options.method, 'DELETE')
})

test('keychain create passes entire secret payload in POST JSON', async () => {
  const payload = { machine_id: '__shared__', hostname: 'Shared', kind: 'secret', name: 'API', secret_value: 'α+', note: '' }
  const saved = await capture(() => saveKeychainCredential(payload))
  assert.equal(saved.url, '/api/keychains')
  assert.equal(saved.options.method, 'POST')
  jsonHeader(saved)
  assert.deepEqual(jsonBody(saved), payload)
})

test('keychain update passes complete payload in PUT JSON to scoped ID', async () => {
  const payload = { machine_id: 'machine/1', kind: 'login', name: 'server', username: 'user', secret_value: 'pass', site: '', note: '' }
  const saved = await capture(() => saveKeychainCredential(payload, 'abc/123'))
  assert.equal(saved.url, '/api/keychains/abc%2F123')
  assert.equal(saved.options.method, 'PUT')
  jsonHeader(saved)
  assert.deepEqual(jsonBody(saved), payload)
})

test('agent platform request is shared by Builder and One-liners', async () => {
  const platform = await capture(() => getAgentPlatform())
  assert.equal(platform.url, '/api/agent/platform')
  assert.equal(platform.options, undefined)
})

test('agent build passes full cross-platform payload as POST JSON', async () => {
  const payload = { builder: 'go', target_os: 'win', target_arch: 'amd64', server_host: '10.1.2.3', server_port: 9999, web_port: 8085, server_web_scheme: 'https', server_web_host: '10.1.2.3', source: 'manual' }
  const request = await capture(() => buildAgent(payload))
  assert.equal(request.url, '/api/agent/build')
  assert.equal(request.options.method, 'POST')
  jsonHeader(request)
  assert.deepEqual(jsonBody(request), payload)
})

test('agent download path encodes filename and preserves server-provided URL fallback choice', () => {
  assert.equal(agentDownloadUrl('go client/测试.zip'), '/api/agent/download/go%20client%2F%E6%B5%8B%E8%AF%95.zip')
  const builder = readFileSync(new URL('../src/components/AgentBuilderDialog.vue', import.meta.url), 'utf8')
  assert.match(builder, /data\.download_url \|\| agentDownloadUrl\(data\.file_name\)/)
})

test('agent output list and deletion retain paths and HTTP methods', async () => {
  const list = await capture(() => listAgentOutputs())
  assert.equal(list.url, '/api/agent/outputs')
  assert.equal(list.options, undefined)
  const deletion = await capture(() => deleteAgentOutput('build/测试.zip'))
  assert.equal(deletion.url, '/api/agent/outputs/build%2F%E6%B5%8B%E8%AF%95.zip')
  assert.equal(deletion.options.method, 'DELETE')
})

test('Keychain and Agent request ownership is in domain APIs, not dialogs', () => {
  for (const name of ['KeychainManagerDialog', 'KeychainPicker', 'AgentBuilderDialog', 'AgentOutputsDialog', 'OneLinersDialog']) {
    const source = readFileSync(new URL(`../src/components/${name}.vue`, import.meta.url), 'utf8')
    const script = source.split('<script>')[1].split('</script>')[0]
    assert.doesNotMatch(script, /\bfetch\s*\(/, `${name} should use its feature API`)
  }
  const picker = readFileSync(new URL('../src/components/KeychainPicker.vue', import.meta.url), 'utf8')
  assert.match(picker, /item\.machine_id !== requestedMachineId/)
  assert.match(picker, /item\.kind !== this\.normalizedKind/)
  assert.match(picker, /selectSequence/)
})
