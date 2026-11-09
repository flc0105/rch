import { createTerminalOperation, operationHeaders } from '../src/utils/terminalOperation.js'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import vm from 'node:vm'

const source = readFileSync(new URL('../src/components/RemoteFilesDialog.vue', import.meta.url), 'utf8')
const script = source.match(/<script>([\s\S]*?)<\/script>/)?.[1]
const calls = []
const ordering = []
const messages = []
const sandbox = {
  ElMessage: { success: text => messages.push(text), error: text => messages.push(text) },
  ElMessageBox: {}, RemotePinsDialog: {}, RemoteZipPeekDialog: {}, MoreFilled: {},
  formatBytesValue: () => 0, createTerminalOperation, operationHeaders,
  sendCommand: async (...args) => { ordering.push('send'); calls.push(args); return { task_id: 'task-cd' } },
  uploadRemoteFileToClient: async () => ({}),
}
vm.runInNewContext(script.replace(/^import\s+.*$/gm, '').replace('export default {', 'globalThis.component = {'), sandbox)
const options = sandbox.component
const events = []
const instance = Object.assign({}, options.data(), options.methods, {
  visible: true, remoteFilesClientId: 'client-A', selectedId: 'client-A', remoteFilesCurrentPath: 'C:\\Users\\Test User',
  getTabScopedHeaders: () => ({ 'X-Tab-Id': 'tab-1' }),
  $emit: (...args) => { if (args[0] === 'append-output') ordering.push('echo'); events.push(args) },
})

test('desktop/mobile toolbar and folder More all submit cd on active connection', async () => {
  assert.equal((source.match(/command="set_cwd"/g) || []).length, 5)
  assert.match(source, /v-if="row\.is_dir" command="set_cwd"/)
  await instance.handleRemoteToolbarMoreCommand('set_cwd')
  await instance.handleRemoteMobileToolsCommand('set_cwd')
  await instance.handleRemoteMoreAction('set_cwd', { is_dir: true, path: 'C:\\Other Folder' })
  await instance.handleRemoteMobileListAction('set_cwd', { is_dir: true, path: 'C:\\Other Folder' })
  assert.deepEqual(Array.from(calls, item => item[1]), [
    'cd C:\\Users\\Test User', 'cd C:\\Users\\Test User',
    'cd C:\\Other Folder', 'cd C:\\Other Folder',
  ])
  assert.deepEqual(ordering, ['echo', 'send', 'echo', 'send', 'echo', 'send', 'echo', 'send'])
  assert.equal(calls[0][0], 'client-A')
  assert.equal(calls[0][2]['X-Tab-Id'], 'tab-1')
  assert.match(calls[0][2]['X-RCH-Operation-ID'], /^[0-9a-f-]{36}$/)
  const startEvents = events.filter(item => item[0] === 'append-output')
  assert.equal(startEvents.length, 4)
  assert.ok(startEvents.every(item => item[4]?.operation?.operation_id))
  const starts = events.filter(item => item[0] === 'set-active-task')
  assert.equal(starts.length, 4)
  assert.equal(starts[0][5], startEvents[0][4].operation.operation_id)
  assert.ok(events.some(item => item[0] === 'set-active-task' && item[2] === 'task-cd'))
  assert.ok(messages.includes('CWD change submitted'))
})

test('file and parent row never submit CWD, stale context does not update UI', async () => {
  const prev = calls.length
  await instance.handleRemoteMoreAction('set_cwd', { is_dir: false, path: 'a.txt' })
  await instance.handleRemoteMoreAction('set_cwd', { is_dir: true, is_parent_entry: true, path: '..' })
  await instance.setRemoteDirectoryAsCwd('abc\nevil')
  assert.equal(calls.length, prev)
})
