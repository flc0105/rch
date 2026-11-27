import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import * as parameterSchema from '../src/utils/parameterSchema.js'
import * as presentation from '../src/utils/externalToolPresentation.js'
import * as formatters from '../src/utils/formatters.js'

const read = path => readFileSync(new URL(`../src/${path}`, import.meta.url), 'utf8')
const deferred = () => {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
const flush = () => new Promise(resolve => setImmediate(resolve))
const plain = value => JSON.parse(JSON.stringify(value))

// Execute the actual Options API code with mocked network/UI boundaries; no Vue runtime needed.
function options(path, api = {}, additional = {}) {
  let source = read(path)
  if (path.endsWith('.vue')) source = source.split('<script>')[1].split('</script>')[0]
  const imports = [...source.matchAll(/^import (\w+) from .*\.vue['"]$/gm)].map(x => x[1])
  const sandbox = {
    ...parameterSchema, ...presentation, ...formatters,
    ...Object.fromEntries(imports.map(name => [name, {}])),
    ElMessage: { error() {}, success() {}, warning() {} },
    ElMessageBox: { confirm: async () => {}, prompt: async () => ({value: 'preset'}) },
    externalToolsApi: api,
    console: {info() {}}, copyTextFallback() {}, ...additional,
  }
  source = source.replace(/^import .*$/gm, '').replace('export default {', '({') + ')'
  return vm.runInNewContext(source, sandbox, {filename: path})
}
function mount(parts, initial = {}) {
  const ctx = {...initial}
  for (const part of parts) Object.assign(ctx, part.data?.call(ctx))
  for (const part of parts) {
    for (const [name, fn] of Object.entries(part.methods || {})) ctx[name] = fn.bind(ctx)
    for (const [name, fn] of Object.entries(part.computed || {})) Object.defineProperty(ctx, name, {get: fn.bind(ctx), configurable: true})
  }
  return ctx
}
const runPath = 'components/ExternalToolRunDialog.vue'
const catalogPath = 'composables/useExternalToolCatalog.js'
const instancesPath = 'composables/useExternalToolInstances.js'
const targetPath = 'composables/useExternalToolTarget.js'
const managerPath = 'components/ExternalToolManagerDialog.vue'
const targetA = {clientId: 'client-a', machineId: 'machine-a', platform: 'mac', arch: 'arm64', label: 'A'}
const targetB = {clientId: 'client-b', machineId: 'machine-b', platform: 'linux', arch: 'amd64', label: 'B'}
const moduleItem = {id: 'example.module', execution: 'daemon', binary: 'x', package_binaries: {x: {launcher: {type: 'interpreter'}}}, params: [{name: 'path', type: 'remote_file', default: '/initial'}]}
function runContext(api, initial = {}) {
  return mount([options(runPath, api)], {$emit() {}, getTabScopedHeaders: extra => ({...extra, tab: 'test'}), ...initial})
}

test('Run dialog pins the same target for launcher, preview, pickers and execution', async () => {
  const calls = [], events = []
  const ctx = runContext({
    loadExternalToolParamPresets: async () => ({items: []}),
    resolveClientLauncher: async (...args) => { calls.push(['launcher', ...args]); return {executable: '/bin/test'} },
    previewClientInstanceCommand: async (...args) => { calls.push(['preview', ...args]); return {shell_command: 'example', instance_id: 'test'} },
  }, {
    $emit: (...args) => events.push(args),
    executeRun: async (...args) => { calls.push(['run', ...args]) },
  })
  ctx.open(moduleItem, targetA)
  await flush()
  ctx.openRemoteFilePicker({name: 'path', type: 'remote_file'})
  ctx.handleRemoteFileSelected('/selected')
  assert.equal(ctx.paramForm.path, '/selected')
  assert.equal(ctx.target.clientId, 'client-a')
  assert.equal(ctx.target.machineId, 'machine-a')
  await ctx.previewStartCommand()
  await ctx.confirmStart()
  assert.equal(calls[0][1], 'client-a')
  assert.equal(calls[1][1], 'client-a')
  assert.equal(calls[2][3].clientId, 'client-a')
  assert.equal(calls[2][2].path, '/selected')
  assert.equal(events[0][1].subtitle, 'A / test')
  assert.equal(ctx.startDialogVisible, false)
  assert.match(read(runPath), /:selected-id="target\.clientId/)
  assert.match(read(runPath), /:machine-id="target\.machineId/)
})

test('late preset and launcher responses for the same module cannot overwrite a reopened form', async () => {
  const oldPreset = deferred(), newPreset = deferred(), oldLauncher = deferred(), newLauncher = deferred()
  let p = 0, l = 0
  const ctx = runContext({
    loadExternalToolParamPresets: () => [oldPreset, newPreset][p++].promise,
    resolveClientLauncher: () => [oldLauncher, newLauncher][l++].promise,
  })
  ctx.open(moduleItem, targetA)
  ctx.open(moduleItem, targetB)
  newPreset.resolve({items: [{preset_id: 'new'}]})
  newLauncher.resolve({executable: '/new'})
  await flush()
  oldPreset.resolve({items: [{preset_id: 'old'}]})
  oldLauncher.resolve({executable: '/old'})
  await flush()
  assert.equal(ctx.target.clientId, 'client-b')
  assert.equal(ctx.paramPresets[0].preset_id, 'new')
  assert.equal(ctx.launcherExecutable, '/new')
  assert.equal(ctx.presetLoading, false)
  assert.equal(ctx.launcherResolving, false)
})

test('closing a running oneshot does not reset a new form; result is still reported', async () => {
  const run = deferred(), events = []
  const ctx = runContext({loadExternalToolParamPresets: async () => ({items: []})}, {
    executeRun: () => run.promise,
    $emit: (...args) => events.push(args),
  })
  const oneshot = {id: 'example.once', execution: 'oneshot', params: []}
  ctx.open(oneshot, targetA)
  const pending = ctx.confirmStart()
  ctx.open(oneshot, targetB)
  run.resolve({success: true, stdout: 'done'})
  await pending
  assert.equal(ctx.startDialogVisible, true)
  assert.equal(ctx.target.clientId, 'client-b')
  assert.equal(events[0][0], 'show-result')
  assert.equal(events[0][2].stdout, 'done')
})

test('package cache and uninstall confirmations keep the original client target', async () => {
  for (const action of ['clearPackageCache', 'uninstallPackage']) {
    const confirmation = deferred(), entered = deferred(), calls = []
    const ctx = mount([options(catalogPath, {}, {ElMessageBox: {confirm: () => { entered.resolve(); return confirmation.promise }}})])
    let selected = 'client-a'
    Object.assign(ctx, {
      canUsePackageAction: () => true,
      getActionDeviceId: () => selected,
      getPackageTargetMachineId: () => 'machine-a',
      getPackageTargetConnectionIds: () => [selected],
      normalizeDeviceId: id => id || '',
      hasRunningInstancesForPackage: () => false,
      loadAllClientInstances: async () => {},
      getPlatformForConnectionId: () => 'mac',
      getArchForConnectionId: () => 'arm64',
      logExternalToolTarget() {},
      clearClientPackageCache: async (_, id) => calls.push(id),
      uninstallClientTool: async (_, id) => calls.push(id),
      loadClientCatalogStatuses: async () => {},
    })
    const pending = ctx[action]({id: 'package'})
    await entered.promise
    selected = 'client-b'
    confirmation.resolve()
    await pending
    assert.deepEqual(calls, ['client-a'])
  }
})

test('manager composes domain state once, keeps refresh coalescing and external entry points', async () => {
  const catalog = options(catalogPath), instances = options(instancesPath), target = options(targetPath)
  const manager = options(managerPath, {}, {useExternalToolCatalog: catalog, useExternalToolInstances: instances, useExternalToolTarget: target})
  const ctx = mount([target, catalog, instances, manager], {
    selectedId: 'client-a', currentConnection: {client_id: 'client-a', machine_id: 'machine-a', os_alias: 'mac', arch: 'arm64'},
    connections: [{client_id: 'client-a', machine_id: 'machine-a', os_alias: 'mac', arch: 'arm64'}],
    machineAliasMap: {},
  })
  ctx.deviceFilter = 'machine-a'
  assert.equal(ctx.selectedTargetClientId, 'client-a')
  const gate = deferred(), calls = []
  ctx.loadCatalog = () => { calls.push('catalog'); return gate.promise }
  ctx.refreshInstallStatuses = async () => calls.push('statuses')
  ctx.refreshInstances = async () => calls.push('instances')
  const a = ctx.refreshAll(), b = ctx.refreshAll()
  assert.equal(a, b)
  gate.resolve()
  await a
  assert.deepEqual(calls, ['catalog', 'statuses', 'instances'])
  for (const method of ['open', 'openFromNotification', 'isOpen', 'refreshIfOpen', 'loadRemoteFilePickerDirectory']) assert.equal(typeof ctx[method], 'function')
  const received = []
  ctx.$refs = {runDialogRef: {open: (...args) => received.push(args), loadRemoteFilePickerDirectory: path => path}}
  ctx.openStartDialog({id: 'x'})
  assert.equal(received[0][1].clientId, 'client-a')
  assert.equal(ctx.loadRemoteFilePickerDirectory('/abc'), '/abc')
})

test('module list is shared by desktop and mobile; presentation components do not call APIs', () => {
  const packages = read('components/ExternalToolPackagesPanel.vue')
  assert.equal((packages.match(/<ExternalToolModulesPanel\b/g) || []).length, 2)
  assert.match(packages, /external-tool-package-mobile-modules/)
  assert.match(packages, /external-tool-package-detail-section/)
  for (const name of ['PackagesPanel', 'ModulesPanel', 'InstancesPanel']) {
    const source = read(`components/ExternalTool${name}.vue`)
    assert.doesNotMatch(source, /externalToolsApi|useSseStream/)
  }
  const instances = read('components/ExternalToolInstancesPanel.vue')
  assert.match(instances, /external-tool-instance-table-shell/)
  assert.match(instances, /external-tool-instance-card-shell/)
  assert.match(instances, /\$emit\('logs', row\)/)
  assert.match(read(managerPath), /@upload-started="forwardRemoteUploadStarted"/)
})
