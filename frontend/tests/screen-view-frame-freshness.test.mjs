import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'

const renderer = readFileSync(new URL('../src/components/screen/KeyframeDeltaScreenRenderer.vue', import.meta.url), 'utf8')
const script = renderer.split('<script>')[1].split('</script>')[0]
const component = vm.runInNewContext(`(() => {
  ${script.replace('export default', 'const component =')}
  return component
})()`, {})

function createCanvas() {
  const draws = []
  return {
    width: 0,
    height: 0,
    draws,
    getContext() {
      return {
        clearRect() {},
        drawImage(image) { draws.push(image.label || 'base') },
      }
    },
  }
}

function createRenderer() {
  const waiting = []
  const canvas = createCanvas()
  const state = {
    ...component.data(),
    $refs: { canvas },
    baseCanvas: createCanvas(),
  }
  for (const [name, method] of Object.entries(component.methods)) {
    state[name] = method.bind(state)
  }
  state.decodeJpeg = frame => new Promise((resolve, reject) => waiting.push({ frame, resolve, reject }))
  return { state, waiting, canvas }
}

function keyframe(seq) {
  return { frame_type: 'keyframe', seq, frame: `key${seq}`, width: 100, height: 100 }
}

function delta(seq, baseSeq) {
  return {
    frame_type: 'delta', seq, base_seq: baseSeq, frame: `delta${seq}`,
    width: 100, height: 100, patch_x: 1, patch_y: 2,
    patch_width: 20, patch_height: 20,
  }
}

async function tick() { await Promise.resolve(); await Promise.resolve(); await Promise.resolve() }

function finish(waiting, index = 0) {
  const job = waiting[index]
  assert.ok(job, `pending decode ${index} exists`)
  job.resolve({ label: job.frame })
}

test('only newest pending delta is decoded; keyframe is retained for latest patch', async () => {
  const { state, waiting, canvas } = createRenderer()
  const pending = state.applyFrame(keyframe(1))
  for (let seq = 2; seq <= 30; seq++) state.applyFrame(delta(seq, 1))
  assert.equal(state.pendingDelta.seq, 30)
  assert.equal(waiting.length, 1)
  finish(waiting)
  await tick()
  assert.equal(waiting.length, 2)
  assert.equal(waiting[1].frame, 'delta30')
  finish(waiting, 1)
  assert.equal(await pending, true)
  assert.equal(state.baseSeq, 1)
  assert.equal(state.renderedSeq, 30)
  assert.deepEqual(canvas.draws.slice(-2), ['base', 'delta30'])
})

test('new keyframe supersedes obsolete delta decoding and keeps its new delta', async () => {
  const { state, waiting, canvas } = createRenderer()
  const first = state.applyFrame(keyframe(1))
  finish(waiting)
  await first
  const obsolete = state.applyFrame(delta(2, 1))
  state.applyFrame(keyframe(4))
  state.applyFrame(delta(5, 4))
  assert.equal(state.pendingKeyframe.seq, 4)
  assert.equal(state.pendingDelta.seq, 5)
  finish(waiting, 1)
  await tick()
  assert.equal(waiting[2].frame, 'key4')
  finish(waiting, 2)
  await tick()
  assert.equal(waiting[3].frame, 'delta5')
  finish(waiting, 3)
  await obsolete
  assert.equal(state.baseSeq, 4)
  assert.equal(state.renderedSeq, 5)
  assert.equal(canvas.draws.includes('delta2'), false)
  assert.equal(canvas.draws.at(-1), 'delta5')
})

test('reset abandons previous decode and allows fresh session', async () => {
  const { state, waiting, canvas } = createRenderer()
  const old = state.applyFrame(keyframe(1))
  state.reset()
  const fresh = state.applyFrame(keyframe(1))
  finish(waiting)
  await old
  assert.equal(canvas.draws.length, 0)
  finish(waiting, 1)
  assert.equal(await fresh, true)
  assert.equal(state.baseSeq, 1)
  assert.deepEqual(canvas.draws, ['base'])
})

test('duplicate keyframes, old deltas and failed JPEG decode do not block updates', async () => {
  const { state, waiting } = createRenderer()
  const first = state.applyFrame(keyframe(1))
  assert.equal(await state.applyFrame(keyframe(1)), false)
  waiting[0].reject(new Error('invalid jpg'))
  assert.equal(await first, false)
  const next = state.applyFrame(keyframe(3))
  await tick()
  finish(waiting, 1)
  assert.equal(await next, true)
  assert.equal(await state.applyFrame(delta(2, 1)), false)
  assert.equal(state.baseSeq, 3)
})

// Also guard ordering at the UI boundary: send the last pending move first.
test('screen UI flushes pending pointer movement before discrete mouse actions', () => {
  const screen = readFileSync(new URL('../src/components/ScreenViewDialog.vue', import.meta.url), 'utf8')
  assert.match(screen, /const interval = 16/)
  for (const action of ['mouse_down', 'mouse_up', 'mouse_wheel']) {
    assert.match(screen, new RegExp(`this\\.flushPointerMove\\(\\)\\s+this\\.sendScreenInput\\(\\{\\s+action: '${action}'`))
  }
})


test('Screen View ignores late WebSocket frames and old renderer completions after restart', () => {
  const screen = readFileSync(new URL('../src/components/ScreenViewDialog.vue', import.meta.url), 'utf8')
  assert.match(screen, /ws\.onmessage = \(event\) => \{\s+if \(this\.screenWs !== ws\) return/)
  assert.match(screen, /ws\.onclose = \(\) => \{\s+if \(this\.screenWs !== ws\) return/)
  assert.match(screen, /if \(epoch !== this\.frameEpoch\) return/ )
  assert.match(screen, /@rendered="recordRenderedFrame"/)
  assert.match(screen, /if \(this\.screenEnded \|\| seq <= this\.lastRenderedSeq\) return\s+this\.frameReady = true/)
  assert.match(screen, /if \(sessionId !== this\.screenSessionId \|\| this\.userClosing \|\| this\.screenWsReady\) return/)
})

test('continuous incoming deltas do not starve presentation and only prior patch is restored', async () => {
  const { state, waiting, canvas } = createRenderer()
  const calls = []
  canvas.getContext = () => ({ clearRect() {}, drawImage(...args) { calls.push(args) } })
  const first = state.applyFrame(keyframe(1))
  finish(waiting)
  await first
  const active = state.applyFrame(delta(2, 1))
  state.applyFrame(delta(3, 1))
  finish(waiting, 1)
  await tick()
  assert.equal(state.renderedSeq, 2, 'decoded frame displayed despite newer pending frame')
  state.applyFrame({...delta(4, 1), patch_x: 40})
  finish(waiting, 2)
  await tick()
  assert.equal(state.renderedSeq, 3)
  finish(waiting, 3)
  await active
  assert.equal(state.renderedSeq, 4)
  const restores = calls.filter(args => args.length === 9)
  assert.equal(restores.length, 2)
  assert.deepEqual(restores[0].slice(1), [1, 2, 20, 20, 1, 2, 20, 20])
  assert.equal(calls.at(-1)[1], 40)
})

test('rapid successive keyframes still display decoded frames', async () => {
  const { state, waiting } = createRenderer()
  const active = state.applyFrame(keyframe(1))
  state.applyFrame(keyframe(2))
  finish(waiting)
  await tick()
  assert.equal(state.renderedSeq, 1)
  state.applyFrame(keyframe(3))
  finish(waiting, 1)
  await tick()
  assert.equal(state.renderedSeq, 2)
  finish(waiting, 2)
  await active
  assert.equal(state.renderedSeq, 3)
})

test('Full JPEG keeps one active load and only the newest pending frame', () => {
  const source = readFileSync(new URL('../src/components/screen/FullJpegScreenRenderer.vue', import.meta.url), 'utf8')
  const code = source.split('<script>')[1].split('</script>')[0]
  const full = vm.runInNewContext(`(() => { ${code.replace('export default', 'const c =')}; return c })()`, { performance: { now: () => 100 } })
  const rendered = []
  const state = {...full.data(), $emit: (_, packet) => rendered.push(packet.seq)}
  for (const [name, method] of Object.entries(full.methods)) state[name] = method.bind(state)
  const offer = seq => { state.seq = seq; state.src = `jpeg-${seq}`; full.watch.seq.handler.call(state) }
  offer(1); offer(2); offer(3)
  assert.equal(state.currentSeq, 1)
  assert.equal(state.pending.seq, 3)
  state.finishFrame(true)
  assert.equal(state.currentSeq, 3)
  offer(4); state.finishFrame(false)
  assert.equal(state.currentSeq, 4)
  state.finishFrame(true)
  assert.deepEqual(rendered, [1, 4])
})

test('performance panel measures completed frames and stops sampling on close', async () => {
  const source = readFileSync(new URL('../src/components/ScreenViewDialog.vue', import.meta.url), 'utf8')
  const code = source.split('<script>')[1].split('</script>')[0].replace(/^import .*$/gm, '')
  let now = 0, timer, cleared = false
  const viewer = vm.runInNewContext(`(() => { ${code.replace('export default', 'const c =')}; return c })()`, {
    Close: {}, FullScreen: {}, WarningFilled: {}, FullJpegScreenRenderer: {}, KeyframeDeltaScreenRenderer: {},
    performance: { now: () => now }, window: {
      setInterval(fn) { timer = fn; return 1 }, clearInterval() { cleared = true },
    },
  })
  const state = {...viewer.data(), visible: true, screenEnded: false}
  for (const [name, method] of Object.entries(viewer.methods)) state[name] = method.bind(state)
  await state.handleMoreCommand('performance')
  assert.equal(state.performanceVisible, true)
  state.performanceWindow.received = 4
  state.recordRenderedFrame({seq: 1, duration: 3})
  state.recordRenderedFrame({seq: 4, duration: 5})
  state.recordRenderedFrame({seq: 3, duration: 6}) // stale result
  now = 1000; timer()
  assert.equal(state.browserPerformance.receiveFps, 4)
  assert.equal(state.browserPerformance.renderFps, 2)
  assert.equal(state.browserPerformance.renderMs, 4)
  assert.equal(state.browserPerformance.skipped, 2)
  await state.handleMoreCommand('performance')
  assert.equal(state.performanceVisible, false)
  assert.equal(state.performanceWindow, null)
  assert.equal(cleared, true)
})
