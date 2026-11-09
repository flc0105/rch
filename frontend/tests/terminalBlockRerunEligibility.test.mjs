import assert from 'node:assert/strict'
import { test } from 'node:test'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import { canRerunTerminalSource } from '../src/utils/terminalRerun.js'
import { getTerminalReplayAction } from '../src/utils/terminalOperation.js'

const terminal = readFileSync(new URL('../src/components/TerminalOutput.vue', import.meta.url), 'utf8')
const template = terminal.match(/<template>([\s\S]*?)<\/template>\s*<script>/)?.[1] || ''
const js = terminal.match(/<script>([\s\S]*?)<\/script>/)?.[1] || ''
const sandbox = { canRerunTerminalSource, getTerminalReplayAction, TerminalLinkedText: {},
  ElMessage: { warning: () => { throw new Error('non-runnable block must exit quietly') } },
}
vm.runInNewContext(js.replace(/^import\s+[\s\S]*?\s+from\s+['"][^'"]+['"]\s*$/gm, '').replace('export default {', 'globalThis.component = {'), sandbox)
const component = sandbox.component

function blockFor(command, meta = {}) {
  const context = {}
  for (const [name, fn] of Object.entries(component.methods)) context[name] = fn.bind(context)
  const line = { kind: 'command', text: `> ${command}`, meta }
  const block = { commandLine: {line}, bodyLines: [], lines: [{line}], commandText: command }
  return { context, block: {...block, ...context.buildTerminalBlockModel(block)} }
}

function check(command, meta, allowed, type) {
  const { context, block } = blockFor(command, meta)
  assert.equal(block.blockType, type)
  assert.equal(context.canRerunTerminalBlock(block), allowed)
  const emitted = []
  context.$emit = (...args) => emitted.push(args)
  context.rerunTerminalBlock(block)
  assert.equal(emitted.length, allowed ? 1 : 0)
  if (allowed) assert.equal(emitted[0][0], 'rerun-terminal-block')
}

const commandOperation = (command) => ({
  operation_id: '00000000-0000-4000-8000-000000000001', kind: 'command', action: 'invoke',
  replay: { type: 'command', command },
})
const scriptOperation = (scriptName) => ({
  operation_id: '00000000-0000-4000-8000-000000000002', kind: 'script', action: 'run',
  replay: { type: 'script', script_name: scriptName, params: { a: 1 } },
})

test('Run again and Copy command derive from explicit replay data only', () => {
  assert.match(template, /command="rerun-command"\s+:disabled="!canRerunTerminalBlock\(block\)"/)
  check('[Artifact Send] demo -> MacBook', {operation:{operation_id:'a',kind:'transfer',replay:null}}, false, 'remote_upload')
  check('[Remote Upload] demo', {operation:{operation_id:'b',kind:'transfer',replay:null}}, false, 'remote_upload')
  check('alias', {operation:{operation_id:'c',kind:'alias',replay:null}}, false, 'quick_action')
  check('alias', {operation:{operation_id:'d',kind:'alias',client_id:'mac-1',
    replay:{type:'alias',alias:'cwd',platform:'mac',arguments:[]}}}, true, 'quick_action')
  check('[Run Script] unknown', {}, false, 'command')
  check('[Remote Upload] untyped', {}, false, 'command')
  check('echo plain', {}, false, 'command')
  check('pwd', {operation:commandOperation('pwd')}, true, 'command')
  check('echo [Artifact Send]', {operation:commandOperation('echo [Artifact Send]')}, true, 'command')
  check('[Run Script] demo', {operation:scriptOperation('demo')}, true, 'script')
  check('[Artifact Send] arbitrary', {operation:commandOperation('[Artifact Send] arbitrary')}, true, 'command')
})

test('producers create structured operations instead of terminal_block_type', () => {
  const artifact = readFileSync(new URL('../src/components/ArtifactDialog.vue', import.meta.url), 'utf8')
  const quick = readFileSync(new URL('../src/components/QuickActionsDialog.vue', import.meta.url), 'utf8')
  assert.match(artifact, /createTerminalOperation\(\{ kind: 'transfer'/)
  assert.match(quick, /createTerminalOperation\(\{[\s\S]*kind: 'alias'/)
  assert.doesNotMatch(artifact, /terminal_block_type: 'artifact_send'/)
  assert.doesNotMatch(quick, /terminal_block_type: 'quick_action'/)
})
