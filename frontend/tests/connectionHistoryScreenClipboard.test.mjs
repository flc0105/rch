import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import { test } from 'node:test'

const read = path => readFileSync(new URL(path, import.meta.url), 'utf8')
function optionsFrom(path, globals = {}) {
  const vue = read(path)
  const script = vue.match(/<script>([\s\S]*?)<\/script>/)?.[1]
  assert.ok(script)
  const js = script.replace(/^import\s+[\s\S]*?\s+from\s+['"][^'"]+['"]\s*$/gm, '')
    .replace('export default {', 'const options = {') + '\nglobalThis.options = options'
  const context = { ...globals }
  vm.runInNewContext(js, context, { timeout: 1000 })
  return { vue, options: context.options }
}

test('Connection History dialog has fixed-height internal scrolling, simplified Activity rows and unchanged load-more', () => {
  const { vue } = optionsFrom('../src/components/MachineConnectionHistoryDialog.vue')
  assert.match(vue, /modal-class="machine-connection-history-overlay"/)
  assert.match(vue, /\.machine-connection-history-overlay \.el-dialog\s*\{[\s\S]*?height: 78vh;/)
  assert.match(vue, /\.machine-connection-history-overlay \.el-dialog__body\s*\{[\s\S]*?overflow: hidden;/)
  assert.match(vue, /\.machine-history-body\s*\{[\s\S]*?overflow: auto;/)
  assert.match(vue, /<el-table-column label="Activity"/)
  assert.match(vue, /commandScope\.row\.summary/)
  assert.match(vue, /loadSessionCommands\(scope\.row, true\)/)
  assert.match(vue, /Total Activities/)
})

test('Connection History keeps all main columns visible with adaptive widths and ellipsis', () => {
  const { vue } = optionsFrom('../src/components/MachineConnectionHistoryDialog.vue')
  const fixed = [['#', 64], ['State', 100], ['Duration', 96], ['Activities', 110]]
  for (const [label, width] of fixed) {
    assert.ok(vue.includes(`<el-table-column label="${label}" width="${width}"`), `${label} width`)
  }
  const flexible = [['client_id', 136], ['Online', 96], ['Offline', 96]]
  for (const [label, minimum] of flexible) {
    assert.ok(vue.includes(`<el-table-column label="${label}" min-width="${minimum}"`), `${label} flexible minimum`)
  }
  assert.match(vue, /<el-table-column type="expand" width="40">/)
  assert.match(vue, /label="Online"[^>]*show-overflow-tooltip/)
  assert.match(vue, /label="Offline"[^>]*show-overflow-tooltip/)
  assert.match(vue, /:deep\(\.machine-history-table \.cell\)\s*\{\s*overflow: hidden;\s*text-overflow: ellipsis;\s*white-space: nowrap;/)
  assert.ok(40 + fixed.reduce((sum, [, width]) => sum + width, 0) + flexible.reduce((sum, [, width]) => sum + width, 0) < 800,
    'minimum width leaves all columns available in the dialog')
  assert.doesNotMatch(vue, /label="client_id" width="334"/)
  assert.match(vue, /label="#" width="64" class-name="machine-history-index-column"/)
})

test('Connection History shows an empty-state immediately for zero activities and shortens cwd label', () => {
  const { vue, options } = optionsFrom('../src/components/MachineConnectionHistoryDialog.vue')
  assert.match(vue, /<span class="label">cwd<\/span>/)
  assert.doesNotMatch(vue, /Current \/ last cwd/)
  assert.match(vue, /v-else-if="!scope\.row\.command_loading && \(scope\.row\.command_loaded \|\| !Number\(scope\.row\.command_count \|\| 0\)\)"/)
  assert.match(vue, /No activities/)
  let requests = 0
  const empty = { client_id: 'empty', command_count: 0, command_loaded: false, command_loading: false }
  options.methods.handleSessionExpand.call({ loadSessionCommands() { requests++ } }, empty, [empty])
  assert.equal(requests, 0, 'empty session should not request records')
})

test('Connection History session pagination keeps one summary row per activity', async () => {
  const calls = []
  const { options } = optionsFrom('../src/components/MachineConnectionHistoryDialog.vue', {
    ElMessage: { error: (message) => { throw new Error(message) } },
    getMachineConnectionHistory: async () => ({ sessions: [ { client_id: 'c1', command_count: 2 } ] }),
    getMachineConnectionCommands: async (_machine, _client, query) => {
      calls.push({ ...query })
      return calls.length === 1
        ? { items: [{ activity_id: 'one', kind: 'remote_files', summary: 'Rename' }], has_more: true, next_cursor: 'page2' }
        : { items: [{ activity_id: 'two', kind: 'external_tool', summary: 'Run ffmpeg' }], has_more: false, next_cursor: '' }
    },
    diffDateTimeMs: () => 1000,
    formatDateTimeStandard: x => x,
  })
  const dialog = Object.assign({}, options.data(), options.methods, { machineId: 'm1' })
  Object.defineProperty(dialog, 'sessions', { get() { return options.computed.sessions.call(dialog) } })
  await dialog.loadHistory()
  const session = dialog.sessions[0]
  await dialog.loadSessionCommands(session)
  assert.equal(session.commands[0].summary, 'Rename')
  assert.equal(session.command_has_more, true)
  await dialog.loadSessionCommands(session, true)
  assert.deepEqual(Array.from(session.commands, x => x.summary), ['Rename', 'Run ffmpeg'])
  assert.equal(session.command_has_more, false)
  assert.equal(calls[1].cursor, 'page2')
  assert.equal(dialog.activityKindLabel('external_tool'), 'External Tool')
})

test('Screen View Clipboard button opens Get and hover menu jumps straight to Get/Send tab', () => {
  const { vue, options } = optionsFrom('../src/components/ScreenViewDialog.vue', {
    ElMessage: {}, Close: {}, FullScreen: {}, screenViewApi: {}, FullJpegScreenRenderer: {}, KeyframeDeltaScreenRenderer: {},
  })
  assert.match(vue, /<el-dropdown trigger="hover" placement="bottom-start" @command="handleClipboardCommand"[^>]*>/)
  assert.match(vue, /@click="\$emit\('open-clipboard', 'get'\)"/)
  assert.match(vue, /<el-dropdown-item command="get">Get<\/el-dropdown-item>/)
  assert.match(vue, /<el-dropdown-item command="send">Send<\/el-dropdown-item>/)
  const emitted = []
  const dialog = { $emit: (...args) => emitted.push(args) }
  options.methods.handleClipboardCommand.call(dialog, 'get')
  options.methods.handleClipboardCommand.call(dialog, 'send')
  options.methods.handleClipboardCommand.call(dialog, 'other')
  assert.deepEqual(emitted, [['open-clipboard', 'get'], ['open-clipboard', 'send']])
  assert.match(read('../src/App.vue'), /<ScreenViewDialog[\s\S]*?@open-clipboard="openClipboardDialog"/)
  assert.match(read('../src/App.vue'), /openClipboardDialog\(tab = 'get'\)\s*\{\s*return this\.\$refs\.clipboardDialogRef\?\.open\(tab\)/)
})
