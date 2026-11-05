import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'

const read = name => readFileSync(new URL('../src/components/' + name, import.meta.url), 'utf8')
const previewSource = read('PreviewDialog.vue')
const remoteSource = read('RemoteFilesDialog.vue')
const wrapperSource = read('RemoteZipPeekDialog.vue')
const panelSource = read('ArchivePreviewPanel.vue')
const artifactApi = readFileSync(new URL('../src/api/artifactsApi.js', import.meta.url), 'utf8')

function evaluate(script, vars) {
  const body = script.match(/<script>([\s\S]*?)<\/script>/)?.[1]
  assert.ok(body)
  const code = body.replace(/^import\s+[^\n]*\n/gm, '').replace('export default {', 'globalThis.component = {')
  vm.runInNewContext(code, vars)
  return vars.component
}

function instance(component) {
  const instance = { ...component.data(), $refs: {}, $nextTick: async () => {} }
  for (const [name, fn] of Object.entries(component.methods)) instance[name] = fn.bind(instance)
  return instance
}

test('ZIP is a PreviewDialog type and uses artifact ZIP APIs without creating a Monaco model', async () => {
  let requests = []
  let loaded = 0
  const options = evaluate(previewSource, {
    ArchivePreviewPanel: {}, PreviewImageInfoDialog: {}, FullScreen: {}, Close: {},
    inspectArtifactZip: id => { requests.push(['inspect', id]); return {} },
    readArtifactZipEntry: (id, entry) => { requests.push(['read', id, entry]); return {} },
    ElMessage: { error(message) { throw new Error(message) } },
  })
  const dialog = instance(options)
  dialog.$refs.archivePreviewRef = {async loadArchive() { loaded++ }}
  dialog.resetPreviewState = function () { this.previewType = 'unknown' }
  await dialog.loadPreviewPayload(async () => ({ok: true, json: async () => ({code: 0, data: {type:'archive', name:'x.zip', artifact_id:'artifact-1'}})}))
  assert.equal(dialog.previewType, 'archive')
  assert.equal(loaded, 1)
  dialog.archiveInspect()
  dialog.archiveReadEntry('nested/a.txt')
  assert.deepEqual(requests, [['inspect', 'artifact-1'], ['read', 'artifact-1', 'nested/a.txt']])
  assert.match(previewSource, /v-else-if="previewType === 'archive'"/)
  assert.match(artifactApi, /\/zip-peek'/)
  assert.match(artifactApi, /\/zip-entry'/)
})

test('Remote ZIP enters PreviewDialog and uses client peek; existing Clipboard ZIP wrapper stays', async () => {
  const calls = []
  const options = evaluate(previewSource, {
    ArchivePreviewPanel: {}, PreviewImageInfoDialog: {}, FullScreen: {}, Close: {},
    inspectRemoteZip: (client, path) => { calls.push(['peek', client, path]); return {} },
    readRemoteZipEntry: (client, path, entry) => { calls.push(['entry', client, path, entry]); return {} },
    ElMessage: { error(message) { throw new Error(message) }, warning(message) { throw new Error(message) } },
  })
  const dialog = instance(options)
  dialog.selectedId = 'client-1'
  dialog.$refs.archivePreviewRef = {async loadArchive() { calls.push(['render']) }}
  dialog.resetPreviewState = function () { this.previewType = 'unknown' }
  await dialog.previewRemoteEntry({name:'bundle.ZIP', path:'/home/bundle.ZIP', client_id:'client-1'})
  assert.equal(dialog.previewType, 'archive')
  dialog.archiveInspect()
  dialog.archiveReadEntry('pkg/config')
  assert.deepEqual(calls, [
    ['render'], ['peek', 'client-1', '/home/bundle.ZIP'],
    ['entry', 'client-1', '/home/bundle.ZIP', 'pkg/config'],
  ])
  assert.doesNotMatch(remoteSource, /<RemoteZipPeekDialog/)
  assert.match(remoteSource, /this\.\$emit\('preview',/)
  assert.match(wrapperSource, /<ArchivePreviewPanel/)
  assert.match(read('ClipboardDialog.vue'), /<RemoteZipPeekDialog/)
})

test('shared ZIP component uses same bounded entry reader with provider functions', async () => {
  let inspections = 0
  const options = evaluate(panelSource, { formatBytesValue: value => `${value} bytes` })
  const panel = instance(options)
  panel.inspect = async () => ({ok:true, json:async () => ({code:0, data: {
    tree:[{path:'src', is_dir:true, children:[]}], name:'x.zip', entry_count:1,
  }})})
  panel.readEntry = async entry => { inspections++; return {ok:true, json:async () => ({code:0, data:{type:'text', content:entry}})} }
  await panel.loadArchive()
  assert.equal(panel.archiveInfo.name, 'x.zip')
  await panel.handleTreeNodeClick({path:'src/test', entry_name:'src/test', is_dir:false})
  assert.equal(panel.entryContent, 'src/test')
  assert.equal(inspections, 1)
})
