import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import vm from 'node:vm'

const source = readFileSync(new URL('../src/components/MachineConnectionHistoryDialog.vue', import.meta.url), 'utf8')
const script = source.match(/<script>([\s\S]*?)<\/script>/)?.[1]
const sandbox = {
  formatLaunchMode: (mode, source) => source ? `${mode} (${source})` : ({ide: 'IDE', terminal: 'Terminal', unknown: 'Unknown'}[mode] || mode),
  diffDateTimeMs: () => 0, formatDateTimeStandard: () => '', ElMessage: {},
  getMachineConnectionCommands: async () => ({}), getMachineConnectionHistory: async () => ({}),
}
vm.runInNewContext(script.replace(/^import\s+.*$/gm, '').replace('export default {', 'globalThis.component = {'), sandbox)
const def = sandbox.component
const dialog = Object.assign({}, def.data(), def.methods)
for (const [name, fn] of Object.entries(def.computed)) Object.defineProperty(dialog, name, { get: () => fn.call(dialog) })

test('filter by raw type, regardless of launch source and termination detail', () => {
  dialog.history = { sessions: [
    {client_id:'A', integrity:'High', launch_mode:'ide', launch_source:'pycharm', termination_reason:'client_exit', termination_detail:{summary:'X'}},
    {client_id:'B', integrity:'high', launch_mode:'ide', launch_source:'vscode', termination_reason:'client_exit', termination_detail:{summary:'Y'}},
    {client_id:'C', integrity:'medium', launch_mode:'terminal', launch_source:'bash', termination_reason:'timeout'},
    {client_id:'D', integrity:'', launch_mode:'', termination_reason:''},
  ] }
  assert.deepEqual(Array.from(dialog.launchModeOptions, item => item.label), ['IDE','Terminal','Unknown'])
  assert.equal(dialog.launchModeOptions.filter(item => item.value === 'ide').length, 1)
  dialog.filters.launchMode = 'ide'
  assert.deepEqual(Array.from(dialog.filteredSessions, item => item.client_id), ['A', 'B'])
  dialog.filters.termination = 'client_exit'
  assert.equal(dialog.filteredSessions.length, 2)
  dialog.filters.integrity = 'high'
  assert.equal(dialog.activeFilterCount, 3)
  assert.deepEqual(Array.from(dialog.filteredSessions, item => item.client_id), ['A','B'])
  dialog.clearFilters()
  assert.equal(dialog.filteredSessions.length, 4)
  assert.equal(dialog.activeFilterCount, 0)
  assert.match(source, /:data="filteredSessions"/)
  assert.match(source, /v-for="\(row, index\) in filteredSessions"/)
})
