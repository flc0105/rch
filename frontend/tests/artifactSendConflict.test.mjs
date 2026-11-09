import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'

const api = readFileSync(new URL('../src/api/artifactsApi.js', import.meta.url), 'utf8')
const dialog = readFileSync(new URL('../src/components/ArtifactDialog.vue', import.meta.url), 'utf8')

test('Artifact send API includes explicit conflict strategy', async () => {
  const requests = []
  const env = {
    jsonRequestOptions: (method, body, headers) => ({ method, body: JSON.stringify(body), headers }),
    fetch: async (url, options) => { requests.push({ url, options }); return { ok: true } },
  }
  const script = api.replace(/^import.*$/gm, '').replace(/^export function /gm, 'function ')
  vm.runInNewContext(`${script}\nglobalThis.send = sendArtifactToClient`, env)
  await env.send('artifact', 'client', '/target')
  await env.send('artifact', 'client', '/target', {}, 'keep_both')
  assert.deepEqual(requests.map(x => JSON.parse(x.options.body).conflict_policy), ['stop','keep_both'])
})

test('Artifact Send to Current Device checks global Ask setting before submitting transfer', () => {
  assert.match(dialog, /import \{ prepareUploadConflict \} from '..\/utils\/remoteFileConflicts.js'/)
  assert.match(dialog, /prepareUploadConflict\(clientId, targetCwd \|\| '\.', displayName\)/)
  assert.match(dialog, /sendArtifactToClient\([\s\S]*?conflictPolicy/)
  assert.match(dialog, /if \(conflictPolicy === false/)
})

test('Artifact Send asks for policy and does not submit when user stops', async () => {
  const tag = dialog.match(/<script>([\s\S]*?)<\/script>/)?.[1]
  assert.ok(tag)
  const sends = []
  const logs = []
  let decision = false
  const env = {
    DragUploadDialog: {},
    ElMessage: { success() {}, error(message) { throw new Error(message) }, warning() {} },
    ElMessageBox: { confirm: async () => {} },
    prepareUploadConflict: async (clientId, dir, file) => {
      logs.push(['inspect', clientId, dir, file])
      return decision
    },
    sendArtifactToClient: async (...args) => {
      sends.push(args)
      return { ok: true, json: async () => ({ code: 0, data: { task_id: 'task-1' } }) }
    },
  }
  vm.runInNewContext(tag.replace(/^import\s+.*$/gm, '').replace('export default {', 'globalThis.component = {'), env)
  const instance = {
    selectedId: 'client-1', currentConnection: { cwd: '/data' },
    getCurrentDeviceCwd: () => '/data', formatArtifactName: () => 'report.bin',
    formatCurrentDeviceLabel: () => 'Device', formatCurrentDeviceCwd: () => '/data',
    buildJsonHeaders: () => ({ 'X-Tab-Id': 'tab' }),
    $emit: (...args) => logs.push(args),
  }
  const send = env.component.methods.sendArtifactToCurrentDevice.bind(instance)
  await send({ artifact_id: 'artifact-1' })
  assert.equal(sends.length, 0)
  assert.deepEqual(logs[0], ['inspect','client-1','/data','report.bin'])
  decision = 'keep_both'
  await send({ artifact_id: 'artifact-1' })
  assert.equal(sends.length, 1)
  assert.equal(sends[0][4], 'keep_both')
  assert.ok(logs.some(call => call[0] === 'set-active-task' && call[2] === 'task-1'))
})
