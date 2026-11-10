import assert from 'node:assert/strict'
import { test } from 'node:test'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import { TERMINAL_HISTORY } from '../src/data/terminalHistoryConfig.js'
import { trimTerminalWindow } from '../src/utils/terminalHistoryStore.js'

function loadOptions(path, context) {
  const source = readFileSync(new URL(path, import.meta.url), 'utf8')
  const script = source.includes('<script>') ? source.split('<script>')[1].split('</script>')[0] : source
  const sandbox = { ...context }
  vm.runInNewContext(script.replace(/^import\s+[\s\S]*?\s+from\s+['"][^'"]+['"]\s*;?\s*$/gm, '')
    .replace('export default {', 'globalThis.component = {'), sandbox)
  return sandbox.component
}

const config = { TERMINAL_HISTORY, trimTerminalWindow, console, ElMessage: { error() {} } }
const makeRows = (from, to) => Array.from({ length: to - from }, (_, i) => ({
  text: `history-${from + i}`, __terminalSeq: from + i, meta: {}, kind: 'default',
}))

function makeHost({ top = 0, from = 400, to = 600, readBefore = async () => makeRows(200, 400) } = {}) {
  const options = loadOptions('../src/composables/useTerminalOutput.js', config)
  const element = { scrollTop: top, scrollHeight: 10000, clientHeight: 500 }
  const restores = []
  const terminal = {
    captureScrollAnchor: () => ({ scrollTop: element.scrollTop, scrollHeight: element.scrollHeight }),
    restoreScrollAnchor: (_anchor, opts) => restores.push({ ...opts }),
    terminalScrollElement: () => element,
  }
  const host = { ...options.data(), selectedId: 'dev',
    $refs: { terminalOutputRef: terminal }, $nextTick: async () => {},
    _terminalHistory: { readBefore, readAfter: async () => { throw Error('unexpected readAfter') } },
    outputs: { dev: makeRows(from, to) },
    terminalViewStates: { dev: { hasOlder: true, hasNewer: false, loading: false, follow: false } },
  }
  for (const [name, method] of Object.entries(options.methods)) host[name] = method.bind(host)
  return { host, element, restores }
}

async function settle(host) {
  for (let i = 0; i < 12; i++) {
    await new Promise(resolve => setTimeout(resolve, 0))
    if (!host.terminalViewStates.dev.loading) return
  }
  assert.equal(host.terminalViewStates.dev.loading, false, 'history read should settle')
}

test('at the physical top, load only the adjacent older page; never jump to first record', async () => {
  const { host, element, restores } = makeHost()
  host.handleTerminalScroll({ atTop: true, atAbsoluteTop: true, atBottom: false })
  await settle(host)
  assert.equal(host.outputs.dev[0].__terminalSeq, 200)
  assert.equal(host.outputs.dev.at(-1).__terminalSeq, 599)
  assert.equal(host.terminalViewStates.dev.hasOlder, true)
  assert.equal(restores.length, 1)
  assert.equal(restores[0].revealOlder, true)
  assert.equal(element.scrollTop, 0) // Host mock does not move the DOM; real anchor tested below.
})

test('approaching the top without reaching zero prefetches adjacent rows and retains reading anchor', async () => {
  const { host, restores } = makeHost({ top: 95 })
  host.handleTerminalScroll({ atTop: true, atBottom: false })
  await settle(host)
  assert.equal(host.outputs.dev[0].__terminalSeq, 200)
  assert.equal(restores.length, 1)
  assert.equal(restores[0].revealOlder, false)
})

test('1000 to 500: two normal upward page loads remain contiguous and do not seek record 1', async () => {
  const reads = []
  const { host, element } = makeHost({ from: 800, to: 1000, readBefore: async (_id, cursor) => {
    reads.push(cursor)
    return makeRows(cursor - 200, cursor)
  } })
  element.scrollTop = 80
  host.handleTerminalScroll({ atTop: true, atBottom: false })
  await settle(host)
  assert.equal(host.outputs.dev[0].__terminalSeq, 600)
  assert.equal(host.outputs.dev.at(-1).__terminalSeq, 999)
  element.scrollTop = 0
  host.handleTerminalScroll({ atTop: true, atAbsoluteTop: true, atBottom: false })
  await settle(host)
  assert.deepEqual(reads, [800, 600])
  assert.equal(host.outputs.dev[0].__terminalSeq, 400)
  assert.equal(host.outputs.dev.at(-1).__terminalSeq, 999)
  assert.ok(host.outputs.dev.some(row => row.__terminalSeq === 500))
  assert.equal(host.outputs.dev.length, 600)
  assert.equal(host.terminalViewStates.dev.hasOlder, true)
})

test('reaching zero while an older read is in-flight never queues an earliest-page jump', async () => {
  let release
  const { host, element, restores } = makeHost({ top: 100, readBefore: async () =>
    new Promise(resolve => { release = () => resolve(makeRows(200, 400)) }) })
  const first = host.loadTerminalHistory('older')
  element.scrollTop = 0
  host.handleTerminalScroll({ atTop: true, atAbsoluteTop: true, atBottom: false })
  release()
  await first
  assert.equal(host.outputs.dev[0].__terminalSeq, 200)
  assert.equal(host.outputs.dev.at(-1).__terminalSeq, 599)
  assert.equal(restores.length, 1)
  assert.equal(restores[0].scrollDelta, -100)
  assert.equal(restores[0].revealOlder, true)
  assert.equal(host.terminalViewStates.dev.pendingTopJump, undefined)
})

test('top intersection trigger initiates loading without another scroll or wheel event', () => {
  const viewport = { scrollTop: 0, scrollHeight: 10000, clientHeight: 500 }
  const edge = {}
  const reports = []
  let callback
  const observer = { observe: observed => assert.equal(observed, edge), disconnect() {} }
  const options = loadOptions('../src/components/TerminalOutput.vue', {
    TERMINAL_HISTORY, TerminalLinkedText: {}, console,
    IntersectionObserver: function (handler, settings) {
      assert.equal(settings.root, viewport)
      callback = handler
      return observer
    },
  })
  const view = { $refs: { terminalOutputRef: viewport, terminalHistoryTopEdge: edge },
    $emit: (name, data) => reports.push([name, data]) }
  for (const [name, fn] of Object.entries(options.methods)) view[name] = fn.bind(view)
  view.setupTerminalHistoryEdgeObserver()
  callback([{ isIntersecting: true }])
  assert.equal(reports.length, 1)
  assert.equal(reports[0][0], 'terminal-scroll')
  assert.equal(reports[0][1].atTop, true)
  assert.equal(reports[0][1].atAbsoluteTop, undefined)
})

test('anchor follows a stable output row even when its entire command block changes height', () => {
  const options = loadOptions('../src/components/TerminalOutput.vue', {
    TERMINAL_HISTORY, TerminalLinkedText: {}, console,
  })
  const scroll = { scrollTop: 100, scrollHeight: 4000, clientHeight: 500,
    getBoundingClientRect: () => ({ top: 0, bottom: 500 }) }
  let rowY = 160
  const row = { getBoundingClientRect: () => ({ top: rowY - scroll.scrollTop,
    bottom: rowY - scroll.scrollTop + 25 }), getAttribute: () => '500' }
  const view = { $refs: { terminalOutputRef: {
    querySelectorAll: selector => selector === '[data-terminal-seq]' ? [row] : [],
  } } }
  for (const [name, fn] of Object.entries(options.methods)) view[name] = fn.bind(view)
  view.terminalScrollElement = () => scroll
  const anchor = view.captureScrollAnchor()
  assert.equal(anchor.seq, '500')
  // Simulate a reader scrolling 30px while storage reads, then prepending 800px
  // to the same large operation block. The source row must stay at the same
  // relative position (60 - 30) rather than jumping by the block height.
  scroll.scrollTop += 30
  rowY += 800
  scroll.scrollHeight += 800
  view.restoreScrollAnchor(anchor, { scrollDelta: 30 })
  assert.equal(scroll.scrollTop, 930)
  assert.equal(row.getBoundingClientRect().top, 30)
})

test('a direct top drag exposes nearby older content without snapping to first history page', () => {
  const options = loadOptions('../src/components/TerminalOutput.vue', {
    TERMINAL_HISTORY, TerminalLinkedText: {}, console,
  })
  const scroll = { scrollTop: 0, scrollHeight: 4000, clientHeight: 500,
    getBoundingClientRect: () => ({ top: 0, bottom: 500 }) }
  let rowY = 10
  const row = { getBoundingClientRect: () => ({ top: rowY - scroll.scrollTop,
    bottom: rowY - scroll.scrollTop + 20 }), getAttribute: () => '500' }
  const view = { $refs: { terminalOutputRef: { querySelectorAll: () => [row] } } }
  for (const [name, fn] of Object.entries(options.methods)) view[name] = fn.bind(view)
  view.terminalScrollElement = () => scroll
  const anchor = view.captureScrollAnchor()
  rowY += 800
  scroll.scrollHeight += 800
  view.restoreScrollAnchor(anchor, { revealOlder: true })
  assert.ok(scroll.scrollTop > 500, `scrollTop must stay adjacent, got ${scroll.scrollTop}`)
  assert.ok(scroll.scrollTop < 800, `scrollTop should reveal only nearby previous lines, got ${scroll.scrollTop}`)
  assert.ok(row.getBoundingClientRect().top > 0)
  assert.ok(row.getBoundingClientRect().top < scroll.clientHeight)
})

test('edge wheel only requests older pages for upward gestures while already near top', () => {
  const options = loadOptions('../src/components/TerminalOutput.vue', {
    TERMINAL_HISTORY, TerminalLinkedText: {}, console,
  })
  const viewport = { scrollTop: 0, scrollHeight: 9000, clientHeight: 500 }
  const requests = []
  const view = { $refs: { terminalOutputRef: viewport }, $emit: (...args) => requests.push(args) }
  for (const [name, fn] of Object.entries(options.methods)) view[name] = fn.bind(view)
  view.handleTerminalEdgeWheel({ deltaY: 10 })
  assert.equal(requests.length, 0)
  view.handleTerminalEdgeWheel({ deltaY: -10 })
  assert.equal(requests.length, 1)
  assert.equal(requests[0][1].atTop, true)
  assert.equal(requests[0][1].atBottom, false)
  viewport.scrollTop = 800
  view.handleTerminalEdgeWheel({ deltaY: -10 })
  assert.equal(requests.length, 1)
})

test('paging downward keeps the old render window until the new tail state is ready', async () => {
  const options = loadOptions('../src/composables/useTerminalOutput.js', config)
  let releaseTail
  let tailReadStarted
  const tailStarted = new Promise(resolve => { tailReadStarted = resolve })
  const before = makeRows(200, 800)
  const refreshed = makeRows(800, 1000)
  const restores = []
  const host = { ...options.data(), selectedId: 'dev',
    $refs: { terminalOutputRef: {
      terminalScrollElement: () => ({ scrollTop: 9500, scrollHeight: 10000, clientHeight: 500 }),
      captureScrollAnchor: () => ({ scrollTop: 9500, scrollHeight: 10000, seq: '790', top: 0 }),
      restoreScrollAnchor: (...args) => restores.push(args),
    } },
    $nextTick: async () => {},
    outputs: { dev: before },
    terminalViewStates: { dev: { hasOlder: true, hasNewer: true, loading: false, follow: false } },
    _terminalHistory: {
      readAfter: async () => refreshed,
      readBefore: async (_id, cursor) => {
        assert.equal(cursor, Infinity)
        tailReadStarted()
        return new Promise(resolve => { releaseTail = () => resolve([refreshed.at(-1)]) })
      },
    },
  }
  for (const [name, method] of Object.entries(options.methods)) host[name] = method.bind(host)
  const job = host.loadTerminalHistory('newer')
  await tailStarted
  assert.strictEqual(host.outputs.dev, before, 'never paint the new tail before restoring the reading anchor')
  assert.equal(restores.length, 0)
  releaseTail()
  await job
  assert.equal(restores.length, 1)
  assert.equal(host.outputs.dev.at(-1).__terminalSeq, 999)
  assert.equal(host.terminalViewStates.dev.hasNewer, false)
})

test('an in-flight downward tail read cannot restore history cleared in the meantime', async () => {
  const options = loadOptions('../src/composables/useTerminalOutput.js', config)
  let releaseTail
  let tailReadStarted
  const tailStarted = new Promise(resolve => { tailReadStarted = resolve })
  const before = makeRows(200, 800)
  const view = { hasOlder: true, hasNewer: true, follow: false, loading: false }
  let restores = 0
  const host = { ...options.data(), selectedId: 'dev',
    outputs: { dev: before }, terminalViewStates: { dev: view },
    $refs: { terminalOutputRef: {
      captureScrollAnchor: () => ({ scrollTop: 1000, scrollHeight: 1200 }),
      terminalScrollElement: () => ({ scrollTop: 1000, scrollHeight: 1200 }),
      restoreScrollAnchor: () => { restores++ },
    } },
    $nextTick: async () => {},
    _terminalHistory: {
      readAfter: async () => makeRows(800, 1000),
      readBefore: async () => {
        tailReadStarted()
        return new Promise(resolve => { releaseTail = () => resolve(makeRows(999, 1000)) })
      },
    },
  }
  for (const [name, method] of Object.entries(options.methods)) host[name] = method.bind(host)
  const paging = host.loadTerminalHistory('newer')
  await tailStarted
  host.outputs.dev = [] // Simulates Clear's immediate render-window reset.
  host.terminalViewStates.dev = { hasOlder: false, hasNewer: false, follow: true, loading: false }
  releaseTail()
  await paging
  assert.equal(host.outputs.dev.length, 0)
  assert.equal(restores, 0)
})
