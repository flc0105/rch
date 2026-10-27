import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import vm from 'node:vm'
import {
  loadAllClientInstances,
  loadClientExternalToolCatalog,
  loadClientInstances,
  startClientInstance,
} from '../src/api/externalToolsApi.js'

const response = (data = {}, message = 'ok', code = 0, status = 200) => ({
  ok: status < 400,
  async json() { return { code, message, data } },
})
const deferred = () => {
  let resolve
  const promise = new Promise(done => { resolve = done })
  return { promise, resolve }
}

async function withFetch(fetchStub, run) {
  const original = globalThis.fetch
  globalThis.fetch = fetchStub
  try { await run() } finally { globalThis.fetch = original }
}

// One ClientSession supports one foreground request. SSE can refresh catalog and
// instance lists while a start dialog also refreshes a specific module.
test('same-client catalog, full list and per-tool instance reads never overlap', async () => {
  const first = deferred()
  const second = deferred()
  const called = []
  await withFetch(async url => {
    called.push(url)
    if (called.length === 1) return first.promise
    if (called.length === 2) return second.promise
    return response({ items: [{ id: 'latest' }] })
  }, async () => {
    const catalog = loadClientExternalToolCatalog('windows-client', { platform: 'windows', arch: 'amd64' })
    const all = loadAllClientInstances('windows-client')
    const one = loadClientInstances('windows-client', 'sqlite-web.web')
    await new Promise(resolve => setImmediate(resolve))
    assert.equal(called.length, 1, 'only one foreground read should start')
    first.resolve(response({ items: [] }))
    await catalog
    await new Promise(resolve => setImmediate(resolve))
    assert.equal(called.length, 2, 'second read starts after first completes')
    second.resolve(response({ items: [] }))
    await Promise.all([all, one])
    assert.equal(called.length, 3)
    assert.match(called[0], /\/external-tools\/catalog$/)
    assert.match(called[1], /\/external-tools\/instances$/)
    assert.match(called[2], /\/sqlite-web.web\/instances$/)
  })
})

test('different Clients can refresh independently and a rejected read does not block the next one', async () => {
  const pending = deferred()
  const called = []
  await withFetch(async url => {
    called.push(url)
    if (url.includes('first-client') && called.filter(u => u.includes('first-client')).length === 1) return pending.promise
    return response({ items: [] })
  }, async () => {
    const a = loadClientInstances('first-client', 'sqlite-web.web')
    const nextA = loadAllClientInstances('first-client')
    const b = loadAllClientInstances('second-client')
    await b
    assert.equal(called.length, 2, 'second Client should not wait for first Client')
    pending.resolve(response({}, 'Permission denied', 1, 403))
    await assert.rejects(a, /Permission denied/)
    await nextA
    assert.equal(called.length, 3, 'failed read releases per-client queue')
  })
})

test('busy only causes a bounded retry of read-only instance list', async () => {
  let calls = 0
  await withFetch(async () => {
    calls += 1
    return calls === 1
      ? response({}, 'Client is busy: external_tool_list_instances __json__:abc', 1, 409)
      : response({ items: [{ instance_id: 'default' }] })
  }, async () => {
    const result = await loadClientInstances('busy-client', 'sqlite-web.web')
    assert.equal(calls, 2)
    assert.equal(result.items[0].instance_id, 'default')
  })
})

test('unrelated errors do not retry and side-effecting start commands remain single-shot', async () => {
  const paths = []
  await withFetch(async url => {
    paths.push(url)
    return response({}, 'Client is busy: external_tool_list_instances', 1, 409)
  }, async () => {
    await assert.rejects(startClientInstance('writes-client', 'sqlite-web.web'), /Client is busy/)
    assert.equal(paths.length, 1, 'start must never be automatically retried')
  })
  let calls = 0
  await withFetch(async () => {
    calls += 1
    return response({}, 'Invalid token', 1, 403)
  }, async () => {
    await assert.rejects(loadAllClientInstances('bad-auth-client'), /Invalid token/)
    assert.equal(calls, 1, 'authorization failure should not retry')
  })
})

test('SSE-triggered and manual full refreshes share the same in-flight work', async () => {
  const source = readFileSync(new URL('../src/components/ExternalToolManagerDialog.vue', import.meta.url), 'utf8')
  const script = source.match(/<script>([\s\S]*?)<\/script>/)?.[1]
  assert.ok(script)
  const code = script.replace(/^import\s+[\s\S]*?\s+from\s+['"][^'"]+['"]\s*;?\s*$/gm, '')
    .replace('export default {', 'const component = {') + '\nglobalThis.component = component'
  const context = { ParamFormField: {}, RemoteFilePicker: {}, KeychainPicker: {}, ElMessage: { error(message) { throw new Error(message) } } }
  vm.runInNewContext(code, context, { timeout: 1000 })
  const pending = deferred()
  const steps = []
  const dialog = {
    ...context.component.data(),
    ...context.component.methods,
    visible: true,
    async loadCatalog() { steps.push('catalog'); await pending.promise },
    async refreshInstallStatuses() { steps.push('statuses') },
    async refreshInstances() { steps.push('instances') },
  }
  const initial = dialog.refreshAll()
  const sse = dialog.refreshIfOpen()
  const button = dialog.refreshAll()
  assert.equal(initial, button, 'full refresh requests should coalesce')
  assert.deepEqual(steps, ['catalog'])
  pending.resolve()
  await Promise.all([initial, sse, button])
  assert.deepEqual(steps, ['catalog', 'statuses', 'instances'])
  assert.equal(dialog.loading, false)
  await dialog.refreshAll()
  assert.deepEqual(steps, ['catalog', 'statuses', 'instances', 'catalog', 'statuses', 'instances'])
})
