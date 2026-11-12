import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import { test } from 'node:test'

const read = path => readFileSync(new URL(path, import.meta.url), 'utf8')
const source = read('../src/components/MachineConnectionHistoryDialog.vue')
const script = source.match(/<script>([\s\S]*?)<\/script>/)?.[1]
const calls = []
const context = {
  getMachineConnectionHistory: async (machine, options) => {
    calls.push({ machine, ...options })
    return { sessions: [{ client_id: 'target-Z', activity_count: 3 }], has_more: false, activity_count: 3 }
  },
  getMachineConnectionCommands: async () => ({ items: [] }),
  ElMessage: { error(error) { throw Error(error) } },
  clearTimeout() {}, setTimeout() { return 17 },
}
vm.runInNewContext(script.replace(/^import\s+.*$/gm, '').replace('export default {', 'globalThis.component = {'), context)
const component = context.component
const dialog = Object.assign({}, component.data(), component.methods)
Object.defineProperty(dialog, 'sessions', { get() { return component.computed.sessions.call(dialog) } })

test('Server-side Client ID search participates in pagination and machine totals remain unchanged', async () => {
  dialog.machineId = 'machine-1'
  dialog.clientSearch = 'target'
  await dialog.loadHistory()
  assert.equal(calls[0].clientIdSearch, 'target')
  assert.equal(calls[0].offset, 0)
  assert.equal(dialog.history.activity_count, 3)
  assert.equal(dialog.sessions[0].activity_count, 3)
  dialog.clientSearch = ''
  await dialog.loadHistory()
  assert.equal(calls[1].clientIdSearch, '')
})

test('History UI derives state from disconnected_at, simplifies details, and integrates Load More', () => {
  assert.equal(dialog.sessionStatusText({ disconnected_at: '' }), 'online')
  assert.equal(dialog.sessionStatusText({ disconnected_at: '2026-11-11T11:00:00Z' }), 'offline')
  assert.equal(dialog.sessionStatusTagType({ disconnected_at: '' }), 'success')
  assert.equal(dialog.sessionStatusTagType({ disconnected_at: 'x' }), 'info')
  assert.equal(dialog.formatListener({listener_name: 'Main', listener_port: 9090}), 'Main')
  assert.equal(dialog.formatOs({os_name: 'macOS', os_ver: '15.0', os_type: 'Windows'}), 'macOS 15.0')
  assert.equal(dialog.formatOs({os_type: 'Windows'}), '-')
  assert.match(source, /v-model="clientSearch"/)
  assert.match(source, /class="machine-history-table-load-more"/)
  assert.doesNotMatch(source, /<span class="label">(?:Hostname|cwd)<\/span>/)
  assert.doesNotMatch(source, /history\.tracking_started_at|\.connection_state/)
})
