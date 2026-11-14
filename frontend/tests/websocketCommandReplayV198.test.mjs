import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import vm from 'node:vm'

function makeClient() {
  const source = readFileSync(new URL('../src/api/streamApi.js', import.meta.url), 'utf8')
    .replace('import.meta.env?.DEV', 'true')
    .replace(/^export /gm, '')
  const sockets = []
  const retries = []
  class Socket {
    static CONNECTING = 0
    static OPEN = 1
    static CLOSED = 3
    constructor(url) { this.url = url; sockets.push(this) }
    close() {}
    incoming(item) { this.onmessage?.({ data: JSON.stringify(item) }) }
  }
  const sandbox = {
    WebSocket: Socket,
    window: { location: { href: 'http://example.invalid:15173/' } },
    URL,
    console,
    setTimeout: callback => { retries.push(callback); return retries.length },
    clearTimeout: () => {},
  }
  vm.runInNewContext(source + '\nglobalThis.stream = openWebEventStream', sandbox)
  return { open: sandbox.stream, sockets, retries }
}

test('reconnect requests only missed command events and delivers them once', () => {
  const { open, sockets, retries } = makeClient()
  const stream = open('tab-123')
  const results = []
  stream.addEventListener('command_result', payload => results.push(JSON.parse(payload.data).text))
  stream.addEventListener('command_complete', payload => results.push(JSON.parse(payload.data).task_id))
  sockets[0].onopen()
  sockets[0].incoming({ event: 'stream_cursor', cursor: 0, epoch: 'server-1' })
  sockets[0].incoming({ event: 'command_result', cursor: 1, id: '1',
    data: { text: 'pwd output', task_id: 'first' } })
  sockets[0].onclose()
  assert.equal(retries.length, 1)
  retries.shift()()
  assert.match(sockets[1].url, /^ws:\/\/example\.invalid:15173\/ws\/events\?tab_id=tab-123&after=1&epoch=server-1$/)
  sockets[1].onopen()
  sockets[1].incoming({ event: 'command_result', cursor: 2, id: '2',
    data: { text: 'job list rows', task_id: 'second' } })
  sockets[1].incoming({ event: 'command_complete', cursor: 3, id: '3',
    data: { task_id: 'second', success: true } })
  sockets[1].incoming({ event: 'stream_cursor', cursor: 3, epoch: 'server-1' })
  assert.deepEqual(results, ['pwd output', 'job list rows', 'second'])
  sockets[1].onclose()
  retries.shift()()
  assert.match(sockets[2].url, /after=3&epoch=server-1/)
  stream.close()
})

test('cursor handshake enables replay even before first result', () => {
  const { open, sockets, retries } = makeClient()
  const stream = open('tab-456')
  sockets[0].onopen()
  sockets[0].incoming({ event: 'stream_cursor', cursor: 0, epoch: 'server-2' })
  sockets[0].onclose()
  retries.shift()()
  assert.match(sockets[1].url, /after=0&epoch=server-2/)
  stream.close()
})
