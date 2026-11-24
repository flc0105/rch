import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'

const source = readFileSync(new URL('../src/components/ScreenViewDialog.vue', import.meta.url), 'utf8')
const script = source.split('<script>')[1].split('</script>')[0].replace(/^import .*$/gm, '')
function createViewer({ standalone = false, pollScreenView = async () => ({status: 'open'}) } = {}) {
  const messages = [], timers = new Map(), sockets = []
  let nextTimer = 1
  class WebSocket {
    static OPEN = 1
    constructor() { this.readyState = 1; sockets.push(this) }
    close() { this.readyState = 3; this.onclose?.() }
    send() {}
  }
  const window = {
    addEventListener() {}, removeEventListener() {}, clearTimeout() {},
    setInterval(fn) { const id = nextTimer++; timers.set(id, fn); return id },
    clearInterval(id) { timers.delete(id) },
  }
  const component = vm.runInNewContext(`(() => { ${script.replace('export default', 'const component =')}; return component })()`, {
    Close: {}, FullScreen: {}, WarningFilled: {}, FullJpegScreenRenderer: {}, KeyframeDeltaScreenRenderer: {},
    ElMessage: { error: message => messages.push(message) }, screenViewApi: { pollScreenView },
    window, WebSocket, webSocketUrl: path => path,
  })
  const state = { ...component.data(), standalone, currentConnection: null, visible: true,
    screenSessionId: 'session-1', screenWsPath: '/ws', screenWsReady: true,
    screenStatus: 'open', frameReady: true, frameStrategy: 'full_jpeg', frameSeq: 1,
    frameSrc: 'data:image/jpeg;base64,old', controlEnabled: true, $refs: {},
  }
  for (const [name, method] of Object.entries(component.methods)) state[name] = method.bind(state)
  for (const [name, getter] of Object.entries(component.computed)) Object.defineProperty(state, name, {get: getter.bind(state)})
  return { state, messages, timers, sockets }
}
const tick = async () => { await Promise.resolve(); await Promise.resolve(); await Promise.resolve() }
const frame = (seq = 2) => ({type: 'frames', status: 'open', seq, frame_strategy: 'full_jpeg',
  control_enabled: true, frames: [{strategy: 'full_jpeg', frame: 'fresh', seq}]})

for (const standalone of [false, true]) {
  test(`terminal status preserves last frame, stops input and ignores late frames (standalone=${standalone})`, () => {
    const { state } = createViewer({standalone})
    state.applyScreenPayload({type: 'status', status: 'closed', error: 'Client disconnected', control_enabled: false})
    assert.equal(state.screenInterrupted, true)
    assert.equal(state.screenEnded, true)
    assert.equal(state.controlAvailable, false)
    assert.equal(state.controlEnabled, false)
    assert.equal(state.frameSrc, 'data:image/jpeg;base64,old')
    state.applyScreenPayload(frame())
    assert.equal(state.screenStatus, 'closed')
    assert.equal(state.frameSrc, 'data:image/jpeg;base64,old')
  })
  test(`control permission error does not imply a disconnected screen (standalone=${standalone})`, () => {
    const {state, messages} = createViewer({standalone})
    state.applyScreenPayload({...frame(), control_enabled: false, control_error: 'Screen control paused: Windows would not allow the target window permissions to be checked.'})
    assert.equal(state.screenInterrupted, false)
    assert.equal(state.controlEnabled, false)
    assert.equal(state.frameSrc, 'data:image/jpeg;base64,fresh')
    assert.equal(messages.length, standalone ? 0 : 1)
    assert.match(state.controlError, /Windows/)
  })
}

test('WebSocket loss immediately flags frozen image; successful fresh HTTP frame clears only preview warning', async () => {
  const {state, sockets, timers} = createViewer({pollScreenView: async () => ({status: 'open', control_enabled: true})})
  state.openScreenSocket()
  const ws = sockets[0]
  ws.onopen()
  ws.onerror()
  ws.onclose()
  assert.equal(state.screenInterrupted, true)
  assert.equal(state.controlEnabled, false)
  assert.equal(timers.size, 1)
  await tick()
  assert.equal(state.screenInterrupted, true)
  assert.equal(state.controlEnabled, false)
  state.applyScreenPayload(frame())
  assert.equal(state.screenInterrupted, false)
  assert.equal(state.controlEnabled, false)
  assert.equal(state.frameSrc, 'data:image/jpeg;base64,fresh')
})

test('failed HTTP fallback after server restart keeps terminal interruption visible', async () => {
  const {state, timers} = createViewer({pollScreenView: async () => {throw new Error('Failed to fetch')}})
  state.handleScreenSocketLoss()
  assert.equal(state.screenInterrupted, true)
  await tick()
  assert.equal(state.screenStatus, 'error')
  assert.equal(state.screenError, 'Failed to fetch')
  assert.equal(state.frameReady, true)
  assert.equal(timers.size, 0)
})

test('late failed fallback cannot overwrite restarted session and polls do not overlap', async () => {
  let reject, calls = 0
  const {state, timers} = createViewer({pollScreenView: () => {calls++; return new Promise((_, fail) => {reject = fail})}})
  state.handleScreenSocketLoss()
  const poll = [...timers.values()][0]
  poll(); poll()
  assert.equal(calls, 1)
  state.stopFallbackPolling()
  state.screenSessionId = 'session-2'
  state.screenStatus = 'opening'
  state.screenStreamInterrupted = false
  reject(new Error('old request failed'))
  await tick()
  assert.equal(state.screenStatus, 'opening')
  assert.equal(state.screenInterrupted, false)
})

test('intentional close does not start fallback or interruption', () => {
  const {state, timers} = createViewer()
  state.userClosing = true
  state.handleScreenSocketLoss()
  assert.equal(state.screenInterrupted, false)
  assert.equal(timers.size, 0)
})

test('standalone permission notice is isolated and interruption covers either renderer', () => {
  assert.match(source, /<el-alert\s+v-if="controlError && !standalone"/)
  assert.match(source, /v-if="standalone && controlError && controlError !== dismissedControlError && !screenInterrupted"/)
  assert.match(source, /@click="dismissedControlError = controlError"/)
  assert.match(source, /v-if="frameReady && screenInterrupted" class="screen-view-interruption"/)
  assert.match(source, /Showing the last received frame\. Remote control is unavailable\./)
})
