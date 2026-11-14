import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
const read = name => fs.readFileSync(new URL('../src/components/' + name, import.meta.url), 'utf8')
const css = fs.readFileSync(new URL('../src/styles/mobileDialogs.css', import.meta.url), 'utf8')

test('Fullscreen result/detail dialogs have viewport CSS and are portaled out of parent dialogs', () => {
  for (const name of ['QuickActionsDialog.vue', 'ScriptLibraryDialog.vue', 'ConnectionInfoDialogs.vue',
    'CommandExecutionDetailDialog.vue', 'BackgroundJobDetailDialog.vue', 'BackgroundJobMessageDialog.vue', 'ScriptRunDialog.vue', 'TerminalJsonDialog.vue']) {
    const src = read(name)
    assert.match(src, /rch-result-detail-fullscreen/, name)
    assert.match(src, /append-to-body/, name)
  }
  assert.match(css, /body \.el-dialog\.rch-result-detail-fullscreen \{[^}]*width: 100vw !important;[^}]*height: 100dvh !important;[^}]*margin: 0 !important;/s)
})

test('Mobile Remote Files list excludes directory size and its separator without changing file rows', () => {
  const src = read('RemoteFilesDialog.vue')
  assert.match(src, /<div v-if="row.is_parent_entry \|\| row.modified_at \|\| !row.is_dir" class="remote-mobile-file-row-meta">\s*<template v-if="!row\.is_dir">\{\{ formatBytes\(row\.size\) \}\} · <\/template>/)
  assert.match(src, /row\.is_dir \? '-' : formatBytes\(row\.size\)/)
})

// Real WebSocket behavior: a second mount in the same tab resumes commands from
// the server-side replay buffer, rather than resetting the cursor on page refresh.
test('Command websocket keeps tab cursor across page refresh and replays missed results', async () => {
  const storage = new Map()
  const previous = { window: globalThis.window, WebSocket: globalThis.WebSocket, sessionStorage: globalThis.sessionStorage }
  const sockets = []
  class WebSocketFake {
    static CONNECTING = 0
    static OPEN = 1
    static CLOSED = 3
    constructor(url) { this.url = url; sockets.push(this) }
    close() {}
    emit(item) { this.onmessage({ data: JSON.stringify(item) }) }
  }
  try {
    globalThis.window = { location: { href: 'http://localhost:5173/', port: '5173' } }
    globalThis.WebSocket = WebSocketFake
    globalThis.sessionStorage = { getItem: k => storage.get(k) ?? null, setItem: (k,v) => storage.set(k,v) }
    const { openWebEventStream } = await import('../src/api/streamApi.js')
    let count = 0
    const first = openWebEventStream('tab-1')
    first.addEventListener('command_result', () => { count++ })
    sockets[0].emit({ event: 'stream_cursor', cursor: 19, epoch: 'server-boot-1' })
    sockets[0].emit({ event: 'command_result', cursor: 20, data: { text: 'row-20' } })
    assert.equal(count, 1)
    first.close()
    const second = openWebEventStream('tab-1')
    assert.match(sockets[1].url, /after=20&epoch=server-boot-1/)
    let resumed = ''
    second.addEventListener('command_result', e => { resumed = JSON.parse(e.data).text })
    sockets[1].emit({ event: 'command_result', cursor: 21, data: { text: 'row-21' } })
    sockets[1].emit({ event: 'stream_cursor', cursor: 21, epoch: 'server-boot-1' })
    assert.equal(resumed, 'row-21')
    second.close()
  } finally {
    for (const [name, value] of Object.entries(previous)) {
      if (value === undefined) delete globalThis[name]
      else globalThis[name] = value
    }
  }
})
