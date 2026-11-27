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
  const open = method(readFileSync(new URL('../src/composables/useRemoteFileOperations.js', import.meta.url), 'utf8'), 'openRemotePtyHere')
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


test('PTY More Clear waits for pending output, preserves the cursor line and leaves the session alone', () => {
  const clear = method(ptySource, 'clearPtyOutput')
  const dispatch = method(ptySource, 'handlePtyMoreCommand')
  const events = []
  const pending = []
  const term = {
    lines: ['old output'], cursorX: 0,
    write(text, done) { pending.push([text, done]) },
    clear() {
      events.push('clear')
      this.lines = this.lines.slice(-1)
    },
    clearSelection() { events.push('selection') },
  }
  const dialog = {
    ptyTerm: term, ptySessionId: 'live', ptySeq: 27,
    clearPtyOutput: clear, focusPtyInput() { events.push('focus') },
    queuePtyInput() { assert.fail('Clear must not send remote input') },
  }
  assert.match(ptySource, /<el-dropdown-item command="clear" :disabled="!ptyTerm">Clear<\/el-dropdown-item>/)
  term.write('user@host:~$ echo pending')
  dispatch.call(dialog, 'clear')
  term.write('new output')
  assert.deepEqual(pending.map(item => item[0]), ['user@host:~$ echo pending', '', 'new output'])
  assert.deepEqual(events, [])
  term.lines.push(pending[0][0])
  term.cursorX = pending[0][0].length
  pending[1][1]()
  assert.deepEqual(events, ['clear', 'selection', 'focus'])
  assert.deepEqual(term.lines, ['user@host:~$ echo pending'])
  assert.equal(term.cursorX, pending[0][0].length)
  term.lines.push(pending[2][0])
  assert.deepEqual(term.lines, ['user@host:~$ echo pending', 'new output'])
  assert.equal(dialog.ptySessionId, 'live')
  assert.equal(dialog.ptySeq, 27)
  dispatch.call(dialog, 'clear')
  dialog.ptyTerm = null
  pending[3][1]()
  dispatch.call(dialog, 'clear')
  assert.deepEqual(events, ['clear', 'selection', 'focus'])
  assert.equal(pending.length, 4)
})

// Model the absolute cursor coordinates emitted by a Windows console. This
// exercises the component's ordering and escape sequences, not native ConPTY.
for (const backend of ['ConPTY', 'WinPTY']) {
  for (const cursorY of [0, 2, 4]) {
    test(`PTY ${backend} Clear preserves cursor row ${cursorY} and handles subsequent absolute positioning`, () => {
      const clear = method(ptySource, 'clearPtyOutput')
      const write = method(ptySource, 'writePtyOutput')
      const pending = []
      const events = []
      const term = {
        cols: 20, rows: 5, modes: { originMode: false },
        buffer: { active: { cursorX: 3, cursorY } },
        screen: Array.from({ length: 5 }, (_, i) => i === cursorY ? 'C:>' : 'old output'),
        history: ['old history'],
        write(text, done) { pending.push([text, done]) },
        clear() { assert.fail('Windows must not relocate the cursor') },
        clearSelection() { events.push('selection') },
      }
      const dialog = {
        ptyTerm: term, ptyBackend: backend, ptySessionId: 'live', ptyClearPending: null,
        focusPtyInput() { events.push('focus') },
        queuePtyInput() { assert.fail('Clear must not send remote input') },
      }
      clear.call(dialog)
      write.call(dialog, 'first new output')
      clear.call(dialog) // Repeated click must not interleave a second erase.
      assert.equal(pending.length, 1)
      pending[0][1]()
      write.call(dialog, 'second new output')
      assert.equal(pending.length, 2)
      const expected = '\x1b[3J' +
        (cursorY > 0 ? `\x1b[${cursorY};20H\x1b[1J` : '') +
        (cursorY < 4 ? `\x1b[${cursorY + 2};1H\x1b[0J` : '') +
        `\x1b[${cursorY + 1};4H`
      assert.equal(pending[1][0], expected)
      for (const match of expected.matchAll(/\x1b\[([\d;]+)([HJ])/g)) {
        const [n, col] = match[1].split(';').map(Number)
        const cursor = term.buffer.active
        if (match[2] === 'H') {
          cursor.cursorY = n - 1
          cursor.cursorX = col - 1
        } else if (n === 3) {
          term.history = []
        } else if (n === 1) {
          for (let i = 0; i <= cursor.cursorY; i++) term.screen[i] = ''
        } else if (n === 0) {
          for (let i = cursor.cursorY; i < term.rows; i++) term.screen[i] = ''
        }
      }
      assert.deepEqual(term.history, [])
      assert.equal(term.screen[cursorY], 'C:>')
      assert.ok(term.screen.every((line, i) => i === cursorY || line === ''))
      assert.equal(term.buffer.active.cursorY, cursorY)
      assert.equal(term.buffer.active.cursorX, 3)
      // The remote console writes on the original row, directly after the prompt.
      term.screen[cursorY] += 'dir'
      assert.equal(term.screen[cursorY], 'C:>dir')
      pending[1][1]()
      assert.deepEqual(pending.slice(2).map(([text]) => text), ['first new output', 'second new output'])
      assert.deepEqual(events, ['selection', 'focus'])
      assert.equal(dialog.ptyClearPending, null)
    })
  }
}

for (const [originMode, cursorX] of [[true, 3], [false, 20]]) {
  test(`PTY Windows Clear avoids changing special cursor state (${originMode}, ${cursorX})`, () => {
    const clear = method(ptySource, 'clearPtyOutput')
    const pending = []
    const term = {
      cols: 20, rows: 5, modes: { originMode },
      buffer: { active: { cursorX, cursorY: 2 } },
      write(text, done) { pending.push([text, done]) },
      clearSelection() {},
    }
    const dialog = { ptyTerm: term, ptyBackend: 'ConPTY', ptySessionId: 'live', focusPtyInput() {} }
    clear.call(dialog)
    pending[0][1]()
    assert.equal(pending[1][0], '\x1b[3J')
    pending[1][1]()
    assert.equal(dialog.ptyClearPending, null)
  })
}

test('PTY Windows Clear does not apply a stale callback after the session is replaced', () => {
  const clear = method(ptySource, 'clearPtyOutput')
  const reset = method(ptySource, 'clearPtyTerminal')
  const pending = []
  const term = { write(text, done) { pending.push([text, done]) }, clear() {}, reset() {} }
  const dialog = { ptyTerm: term, ptyBackend: 'ConPTY', ptySessionId: 'old', focusPtyInput() { assert.fail('stale callback') } }
  clear.call(dialog)
  reset.call(dialog)
  dialog.ptySessionId = 'new'
  pending[0][1]()
  assert.equal(pending.length, 1)
  assert.equal(dialog.ptyClearPending, null)
})
