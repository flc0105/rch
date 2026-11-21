import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import vm from 'node:vm'

const read = name => readFileSync(new URL(`../src/components/${name}.vue`, import.meta.url), 'utf8')
const ptySource = read('PtyDialog')
const pinsSource = read('RemotePinsDialog')
const filesSource = read('RemoteFilesDialog')
const inputSource = read('CommandInputBar')

function method(source, name, sandbox = {}) {
  const match = source.match(new RegExp(`^    (?:async )?${name}\\([^\\n]*\\) \\{[\\s\\S]*?^    },`, 'm'))
  assert.ok(match, `${name} exists as a component method`)
  return vm.runInNewContext(`({${match[0]}})`, sandbox)[name]
}

test('PTY sends requested remote cwd through the existing open API', async () => {
  const requests = []
  const openPtySession = method(ptySource, 'openPtySession', {
    ElMessage: () => {},
    fetch: async (url, options) => {
      requests.push({ url, body: JSON.parse(options.body) })
      return { ok: true, json: async () => ({code: 0, data: {pty_session_id: 'new', ws_path: '/ws/new'}}) }
    },
  })
  const dialog = {
    selectedId: 'dev/1', ptyLoading: false, ptyInitialCwd: 'C:\\Work Dir\\報告',
    ptySeq: 0, closePtySocket() {}, resetPtyInputQueue() {}, clearPtyTerminal() {},
    buildJsonHeaders: () => ({'Content-Type':'application/json'}),
    fitPtyTerminalAndGetSize: () => ({cols: 90, rows: 30}),
    openPtySocket() {}, syncPtyShellFromSession() {}, focusPtyInput() {}, schedulePtyResize() {},
  }
  await openPtySession.call(dialog, '')
  assert.equal(requests[0].url, '/api/connections/dev%2F1/pty/open')
  assert.deepEqual(requests[0].body, {cols:90, rows:30, shell:'', cwd:'C:\\Work Dir\\報告'})
})

test('PTY dialog defaults to selected Client cwd and accepts an explicit path', async () => {
  const open = method(ptySource, 'open', { ElMessage: { warning() {}, error() {} } })
  const dialog = {
    selectedId: 'dev', currentConnection: { cwd: '/home/client' },
    ptyLoading: false, ptyClosing: false, $nextTick: async () => {},
    initPtyTerminal() {}, async openPtySession() {},
  }
  await open.call(dialog)
  assert.equal(dialog.ptyInitialCwd, '/home/client')
  await open.call(dialog, '/mnt/Space Dir')
  assert.equal(dialog.ptyInitialCwd, '/mnt/Space Dir')
})

test('frontend pty command runs locally and does not submit a remote command', () => {
  const handlerSource = inputSource.match(/^    handleLocalFrontendCommand\(command\) \{[\s\S]*?^},/m)[0]
  const send = vm.runInNewContext(`({${handlerSource}})`, { ElMessage: { warning() {}, success() {} } }).handleLocalFrontendCommand
  const emitted = []
  const dialog = { commandText: 'pty', $emit: (...args) => emitted.push(args) }
  assert.equal(send.call(dialog, 'pty'), true)
  assert.deepEqual(emitted, [['open-pty']])
  assert.equal(dialog.commandText, '')
})

test('Pinned Paths More dispatches the existing browser actions', () => {
  const handle = method(pinsSource, 'handlePinnedMore')
  const emitted = []
  const dialog = { $emit: (...args) => emitted.push(args) }
  for (const command of ['copy_path', 'set_cwd', 'open_pty']) {
    handle.call(dialog, command, { path: '/Users/demo/Space Dir' })
  }
  assert.deepEqual(emitted, [
    ['copy-path', '/Users/demo/Space Dir'],
    ['set-cwd', '/Users/demo/Space Dir'],
    ['open-pty', '/Users/demo/Space Dir'],
  ])
})

test('Remote File Browser forwards directory PTY actions for the selected client only', () => {
  const open = method(filesSource, 'openRemotePtyHere')
  const emitted = []
  const dialog = {
    remoteFilesClientId: 'device-a', selectedId: 'device-a',
    $emit: (...args) => emitted.push(args),
  }
  open.call(dialog, '/tmp/a b')
  dialog.selectedId = 'device-b'
  open.call(dialog, '/tmp/should-not-run')
  assert.deepEqual(emitted, [['open-pty','/tmp/a b']])
  assert.match(filesSource, /@open-pty="openRemotePtyHere"/)
  assert.match(filesSource, /@set-cwd="setRemoteDirectoryAsCwd"/)
})

test('mobile pinned paths are cards; desktop actions remain present', () => {
  assert.match(pinsSource, /remote-pins-mobile-cards/)
  assert.match(pinsSource, /remote-pins-desktop-table/)
  assert.match(pinsSource, /@media \(max-width: 768px\)/)
  assert.equal((pinsSource.match(/command="open_pty"/g) || []).length, 2)
})
