import assert from 'node:assert/strict'
import { test } from 'node:test'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import { buildTerminalOutputJson, buildTerminalOutputText } from '../src/utils/terminalOutputExport.js'
import { canRerunTerminalSource } from '../src/utils/terminalRerun.js'
import { getTerminalReplayAction } from '../src/utils/terminalOperation.js'

function makeView(full, visible, runtime = {}) {
  const source = readFileSync(new URL('../src/components/TerminalOutput.vue', import.meta.url), 'utf8')
  const script = source.match(/<script>([\s\S]*?)<\/script>/)?.[1]
  assert.ok(script)
  const mocks = { TerminalLinkedText:{}, canRerunTerminalSource, getTerminalReplayAction,
    buildTerminalOutputJson, buildTerminalOutputText, TERMINAL_HISTORY: { scrollEdgePx: 160, bottomTolerancePx: 60 },
    isTerminalCommandFinishedText: text => String(text).startsWith('[Command finished]'),
    saveCommandOutputArtifact: async () => ({ ok:true }),
    ElMessage: { warning:()=>{}, success:()=>{}, error:error=>{throw new Error(error)} },
    ...(runtime.window ? { window: runtime.window } : {}),
    copyTextFallback: runtime.copyTextFallback || (() => {}),
  }
  vm.runInNewContext(script.replace(/^import\s+[\s\S]*?\s+from\s+['"][^'"]+['"]\s*;?\s*$/gm, '')
    .replace('export default {', 'globalThis.component = {'), mocks)
  const options = mocks.component
  const view = { ...options.data(), lines: visible, selectedId: 'device-1', currentConnection: {}, artifacts: [],
    historyReader: async () => full }
  for (const [name, fn] of Object.entries(options.methods)) view[name] = fn.bind(view)
  Object.defineProperty(view, 'terminalBlocks', { get: () => options.computed.terminalBlocks.call(view) })
  return view
}

const operation = { operation_id: 'op-99', kind: 'command', client_id: 'device-1',
  replay: { type:'command', command:'echo full' } }
const rows = [
  { text: '> echo full', kind: 'command', meta: { operation }, __terminalSeq: 0 },
  ...Array.from({length: 1200}, (_,i) => ({text:`output-${i}`, kind:'default',
    meta: {operation_id:'op-99', event_type:'output'}, __terminalSeq:i+1})),
  { text: '[Command finished] echo full (Success)', kind: 'success',
    meta: {operation_id:'op-99',event_type:'completed'}, __terminalSeq: 1201 },
]

test('toolbar Copy Text and Copy JSON include all hidden rows', async () => {
  const view = makeView(rows, rows.slice(-15))
  const copied = []
  view.copyTextToClipboard = async text => copied.push(text)
  await view.copyAllTerminalOutput('text')
  await view.copyAllTerminalOutput('json')
  assert.match(copied[0], /output-0/)
  assert.match(copied[0], /output-1199/)
  const json = JSON.parse(copied[1])
  assert.equal(json.length, 1)
  assert.equal(json[0].command, 'echo full')
  assert.match(json[0].result, /output-0/)
  assert.match(json[0].result, /output-1199/)
})

test('inline Copy and Save resolve full command even if command header is hidden', async () => {
  const view = makeView(rows, rows.slice(-20))
  const [partial] = view.terminalBlocks
  assert.equal(partial.commandLine, null)
  assert.equal(view.canUseTerminalBlockActions(partial), true)
  const clipboard = [], saved = []
  view.copyTextToClipboard = async text => clipboard.push(text)
  view.saveTerminalOutputArtifactBody = async body => saved.push(body)
  await view.copyTerminalBlockOutput(partial)
  await view.saveTerminalBlockOutput(partial)
  assert.match(clipboard[0], /output-0/)
  assert.match(clipboard[0], /output-1199/)
  assert.match(saved[0].content, /output-0/)
  assert.match(saved[0].content, /output-1199/)
  assert.equal(saved[0].source_command, 'echo full')
})

test('toolbar Save as Text and JSON Artifact uses complete history', async () => {
  const view = makeView(rows, rows.slice(-6))
  const saved = []
  view.saveTerminalOutputArtifactBody = async body => saved.push(body)
  await view.saveAllTerminalOutputArtifact('text')
  await view.saveAllTerminalOutputArtifact('json')
  assert.equal(saved.length, 2)
  assert.match(saved[0].content, /output-0/)
  assert.match(saved[0].content, /output-1199/)
  assert.equal(saved[0].output_format, 'text')
  assert.equal(saved[1].output_format, 'json')
  assert.match(JSON.parse(saved[1].content)[0].result, /output-0/)
})


test('toolbar JSON includes output rows without the command operation ID', async () => {
  const source = [
    { text: '> job ps', kind: 'command', meta: { operation }, __terminalSeq: 0 },
    { text: 'job_name example_monitor', kind: 'default', meta: { operation_id: 'legacy-output' }, __terminalSeq: 1 },
    { text: '[Command finished] job ps (Success)', kind: 'success', meta: { operation_id: 'legacy-output', event_type: 'completed' }, __terminalSeq: 2 },
  ]
  const view = makeView(source, source)
  const exported = JSON.parse((await view.getCompleteTerminalToolbarOutput('json')).content)
  assert.equal(exported.length, 1)
  assert.equal(exported[0].command, 'job ps')
  assert.equal(exported[0].result, 'job_name example_monitor')
  const saved = []
  view.saveTerminalOutputArtifactBody = async body => saved.push(body)
  await view.saveAllTerminalOutputArtifact('json')
  assert.equal(JSON.parse(saved[0].content)[0].result, 'job_name example_monitor')
})

test('non-secure mobile toolbar Copy reads visible content within the tap', async () => {
  const copied = []
  const view = makeView(rows, rows, {
    window: { isSecureContext: false },
    copyTextFallback: text => copied.push(text),
  })
  view.getCompleteTerminalToolbarOutput = async () => {
    throw new Error('History must not be read before mobile clipboard fallback')
  }
  await view.copyAllTerminalOutput('text')
  await view.copyAllTerminalOutput('json')
  assert.match(copied[0], /output-1199/)
  const entries = JSON.parse(copied[1])
  assert.equal(entries[0].command, 'echo full')
  assert.match(entries[0].result, /output-1199/)
})
