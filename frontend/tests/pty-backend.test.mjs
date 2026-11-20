import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import vm from 'node:vm'

const source = readFileSync(new URL('../src/components/PtyDialog.vue', import.meta.url), 'utf8')
const socket = source.match(/^    openPtySocket\(\) \{[\s\S]+?^    },/m)[0]
const status = source.match(/^    statusText\(\) \{[\s\S]+?^    },/m)[0]

for (const [backend, type] of [['WinPTY', 'status'], ['ConPTY', 'output'], ['', 'status']]) {
  test(`PTY status and toast use the reported backend (${backend || 'unspecified'})`, () => {
    const messages = []
    const methods = vm.runInNewContext(`({${socket}${status}})`, {
      WebSocket: class {},
      ElMessage: options => messages.push(options.message),
      console,
    })
    const dialog = {
      ...methods,
      ptyWsPath: '/ws/pty',
      ptyBackend: '',
      ptySeq: 0,
      buildPtyWsUrl: () => 'ws://localhost/ws/pty',
      closePtySocket() { this.ptyWs = null },
    }
    dialog.openPtySocket()
    dialog.ptyWs.onmessage({ data: JSON.stringify({ type: 'status', status: 'opening' }) })
    assert.equal(dialog.statusText(), 'opening')
    assert.deepEqual(messages, [])

    const opened = { type, status: 'open', chunks: [] }
    if (backend) opened.backend = backend
    dialog.ptyWs.onmessage({ data: JSON.stringify(opened) })
    dialog.ptyWs.onmessage({ data: JSON.stringify(opened) })

    assert.equal(dialog.statusText(), backend ? `open · ${backend}` : 'open')
    assert.deepEqual(messages, [backend ? `PTY connected (${backend})` : 'PTY connected'])
  })
}
