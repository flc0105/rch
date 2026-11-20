import assert from 'node:assert/strict'
import test from 'node:test'
import { openWebEventStream } from '../src/api/streamApi.js'

function installGlobal(t, key, value) {
  const original = Object.getOwnPropertyDescriptor(globalThis, key)
  Object.defineProperty(globalThis, key, { configurable: true, writable: true, value })
  t.after(() => {
    if (original) Object.defineProperty(globalThis, key, original)
    else delete globalThis[key]
  })
}

test('a reconnect resumes the last delivered event and ignores the old socket', (t) => {
  const sockets = []
  const retries = new Map()
  const storage = new Map()
  class Socket {
    static CONNECTING = 0
    static OPEN = 1
    static CLOSED = 3
    constructor(url) {
      this.url = new URL(url)
      sockets.push(this)
    }
    sendFromServer(event) {
      this.onmessage({ data: JSON.stringify(event) })
    }
    close() {}
  }

  installGlobal(t, 'WebSocket', Socket)
  installGlobal(t, 'window', { location: new URL('https://rch.example:8085/') })
  installGlobal(t, 'sessionStorage', {
    getItem: key => storage.get(key),
    setItem: (key, value) => storage.set(key, value),
  })
  t.mock.method(globalThis, 'setTimeout', callback => {
    const id = Symbol('reconnect')
    retries.set(id, callback)
    return id
  })
  t.mock.method(globalThis, 'clearTimeout', id => retries.delete(id))

  const stream = openWebEventStream('tab/test')
  const received = []
  stream.addEventListener('command_result', event => received.push(JSON.parse(event.data).text))
  const [initial] = sockets
  initial.onopen()
  initial.sendFromServer({ event: 'stream_cursor', cursor: 0, epoch: 'server' })
  initial.sendFromServer({ event: 'command_result', cursor: 1, data: { text: 'first' } })
  initial.onclose()

  assert.equal(retries.size, 1)
  const [resumeId, resume] = retries.entries().next().value
  retries.delete(resumeId)
  resume()
  const resumed = sockets[1]
  assert.equal(resumed.url.origin, 'wss://rch.example:8086')
  assert.equal(resumed.url.searchParams.get('tab_id'), 'tab/test')
  assert.equal(resumed.url.searchParams.get('after'), '1')
  assert.equal(resumed.url.searchParams.get('epoch'), 'server')
  resumed.onopen()
  initial.sendFromServer({ event: 'command_result', cursor: 2, data: { text: 'old socket' } })
  resumed.sendFromServer({ event: 'command_result', cursor: 2, data: { text: 'second' } })
  assert.deepEqual(received, ['first', 'second'])
  assert.deepEqual(JSON.parse(storage.get('rch_command_stream_cursor:tab/test')), { cursor: 2, epoch: 'server' })

  resumed.onclose()
  stream.close()
  assert.equal(retries.size, 0)
  assert.equal(stream.readyState, Socket.CLOSED)
})
