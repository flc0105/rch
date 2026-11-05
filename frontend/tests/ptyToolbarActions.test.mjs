import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import { getPtyBufferText } from '../src/utils/ptyText.js'

const source = readFileSync(new URL('../src/components/PtyDialog.vue', import.meta.url), 'utf8')
function makeDialog({ secure = true, readText = async () => 'clipboard', writeText = async () => {}, saveOutput = async () => ({ok:true, json:async () => ({code:0, data:{artifact_id:'A'}})}) } = {}) {
  const messages = []
  const script = source.match(/<script>([\s\S]*?)<\/script>/)?.[1]
  assert.ok(script)
  const code = script.split('\n').filter(line => !/^import /.test(line)).join('\n')
    .replace('export default {', 'const component = {') + '\nglobalThis.component = component'
  const context = {
    window: { isSecureContext: secure }, navigator: { clipboard: { readText, writeText } },
    getPtyBufferText, saveCommandOutputArtifact: saveOutput, setTimeout, clearTimeout, FullScreen: {}, Close: {}, WebSocket: { OPEN: 1 },
    ElMessage: {
      warning: message => messages.push(['warning', message]),
      error: message => messages.push(['error', message]),
      success: message => messages.push(['success', message]),
    },
  }
  vm.runInNewContext(code, context, { timeout: 1000 })
  const options = context.component
  const dialog = { ...options.data(), ...options.methods,
    visible: true, ptySessionId: 'pty-1', ptyTerm: { focus() {} },
    $nextTick(callback) { return Promise.resolve().then(callback) },
  }
  return { dialog, messages, context }
}

function fakeBuffer(rows) {
  return { buffer: { active: {
    length: rows.length,
    getLine(i) { const row = rows[i]; return row && { isWrapped: !!row.wrapped, translateToString: () => row.text } },
  } } }
}

test('toolbar preserves Shell/Switch, places Focus/Paste/Copy inside More and keeps header Close/fullscreen', () => {
  assert.match(source, /<el-dropdown trigger="click" @command="handlePtyMoreCommand">/)
  assert.match(source, /<el-dropdown-item command="focus"[^>]*>Focus<\/el-dropdown-item>/)
  assert.match(source, /<el-dropdown-item command="paste"[^>]*>Paste<\/el-dropdown-item>/)
  assert.match(source, /<el-dropdown-item command="copy"[^>]*>Copy<\/el-dropdown-item>/)
  assert.match(source, /@click="switchPtyShell"/)
  assert.match(source, /aria-label="Close" title="Close"/)
  assert.match(source, /@click="togglePtyFullscreen"/)
  assert.doesNotMatch(source, /<el-button[^>]*\s@click="closePtyDialog"/)
})

test('copy extracts full xterm scrollback as text, merging wrapped display rows', () => {
  assert.equal(getPtyBufferText(null), '')
  const term = fakeBuffer([
    { text: '$ echo very-long-' },
    { text: 'line', wrapped: true },
    { text: '' },
    { text: 'finished' },
    { text: '' },
    { text: '' },
  ])
  assert.equal(getPtyBufferText(term), '$ echo very-long-line\n\nfinished')
})

test('fullscreen toggles and schedules PTY resize without recreating terminal', async () => {
  const { dialog } = makeDialog()
  const term = dialog.ptyTerm
  let resizes = 0
  dialog.schedulePtyResize = () => { resizes++ }
  dialog.togglePtyFullscreen()
  await Promise.resolve()
  assert.equal(dialog.ptyFullscreen, true)
  assert.equal(resizes, 1)
  dialog.togglePtyFullscreen()
  await Promise.resolve()
  assert.equal(dialog.ptyFullscreen, false)
  assert.equal(resizes, 2)
  assert.equal(dialog.ptyTerm, term)
})

test('paste through clipboard uses existing PTY queue; never sends with closed session', async () => {
  const { dialog } = makeDialog({ readText: async () => 'uname -a\n' })
  const queued = []
  dialog.queuePtyInput = text => queued.push(text)
  await dialog.pasteIntoPty()
  assert.equal(queued.join(''), 'uname -a\n')
  assert.equal(dialog.ptyPasteVisible, false)
  dialog.ptySessionId = ''
  await dialog.pasteIntoPty()
  assert.equal(queued.length, 1)
})

test('iOS/non-secure browser uses native paste dialog and explicitly sends its text', async () => {
  const { dialog } = makeDialog({ secure: false })
  const queued = []
  dialog.queuePtyInput = text => queued.push(text)
  await dialog.pasteIntoPty()
  assert.equal(dialog.ptyPasteVisible, true)
  dialog.sendPtyPastedText('你好\n')
  assert.equal(queued.join(''), '你好\n')
  assert.equal(dialog.ptyPasteVisible, false)
  assert.match(source, /Tap and hold here to paste/)
})

test('denied clipboard read falls back to native paste; closed dialog cannot reopen on a late failure', async () => {
  let fail
  const { dialog } = makeDialog({ readText: () => new Promise((_, reject) => { fail = reject }) })
  const pending = dialog.pasteIntoPty()
  dialog.visible = false
  dialog.ptySessionId = ''
  fail(new Error('NotAllowedError'))
  await pending
  assert.equal(dialog.ptyPasteVisible, false)
})

test('copy sends all buffered rows to clipboard, not just visible terminal rows', async () => {
  let copied = ''
  const { dialog, messages } = makeDialog({ writeText: async text => { copied = text } })
  dialog.ptyTerm = fakeBuffer(Array.from({ length: 90 }, (_, i) => ({ text: `line ${i}` })))
  await dialog.copyPtyOutput()
  assert.equal(copied.split('\n').length, 90)
  assert.equal(copied.split('\n').at(-1), 'line 89')
  assert.deepEqual(messages, [['success', 'PTY output copied']])
})

test('paste sends UTF-8 over the existing base64 WS input path', async () => {
  const { dialog } = makeDialog()
  const sent = []
  dialog.sendPtyWs = packet => sent.push(packet)
  dialog.encodePtyInput = text => Buffer.from(text, 'utf8').toString('base64')
  dialog.sendPtyPastedText('echo 你好\n')
  await new Promise(resolve => setTimeout(resolve, 30))
  assert.equal(sent.length, 1)
  assert.equal(sent[0].type, 'input')
  assert.equal(Buffer.from(sent[0].data, 'base64').toString('utf8'), 'echo 你好\n')
})

test('fullscreen schedules and emits the updated terminal dimensions to WS', async () => {
  const { dialog } = makeDialog()
  const sent = []
  dialog.ptyWs = { readyState: 1 }
  dialog.sendPtyWs = message => sent.push(message)
  dialog.ptyTerm = { cols: 148, rows: 41 }
  dialog.ptyFitAddon = { fit() {} }
  dialog.togglePtyFullscreen()
  await new Promise(resolve => setTimeout(resolve, 110))
  assert.equal(sent.length, 1)
  assert.equal(sent[0].type, 'resize')
  assert.equal(sent[0].cols, 148)
  assert.equal(sent[0].rows, 41)
})


test('PTY More saves the entire current terminal buffer through Command Output Artifact API', async () => {
  const requests = []
  const emitted = []
  const { dialog, messages } = makeDialog({ saveOutput: async payload => {
    requests.push(payload)
    return { ok: true, json: async () => ({code: 0, data: {artifact_id: 'saved-pty'}}) }
  } })
  assert.match(source, /<el-dropdown-item command="save-artifact"[^>]*>Save to Artifact<\/el-dropdown-item>/)
  dialog.selectedId = 'client-1'
  dialog.currentConnection = { machine_id: 'machine-1', hostname: 'test-host' }
  dialog.ptyTerm = fakeBuffer([{text: '$ echo hello'}, {text: 'world', wrapped: true}, {text: 'done'}])
  dialog.$emit = (...args) => emitted.push(args)
  await dialog.savePtyOutputArtifact()
  assert.equal(requests.length, 1)
  assert.equal(requests[0].content, '$ echo helloworld\ndone')
  assert.equal(requests[0].client_id, 'client-1')
  assert.equal(requests[0].machine_id, 'machine-1')
  assert.equal(requests[0].source, 'pty_toolbar_action')
  assert.equal(requests[0].category, 'command_output')
  assert.equal(dialog.ptySaving, false)
  assert.equal(emitted[0][0], 'artifact-saved')
  assert.deepEqual(messages, [['success', 'Saved to Command Output']])
})


test('App refreshes an open Artifact Manager after PTY saves output', () => {
  const app = readFileSync(new URL('../src/App.vue', import.meta.url), 'utf8')
  assert.match(app, /:is="dialogComponents\.pty"[\s\S]*?@artifact-saved="refreshArtifactsIfOpen"/)
})
