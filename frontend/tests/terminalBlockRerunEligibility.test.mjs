import assert from 'node:assert/strict'
import { test } from 'node:test'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import { canRerunTerminalSource } from '../src/utils/terminalRerun.js'
import { isTerminalRemoteUploadText, TERMINAL_RUN_SCRIPT_PREFIX } from '../src/composables/terminalMarkers.js'

const terminal = readFileSync(new URL('../src/components/TerminalOutput.vue', import.meta.url), 'utf8')
const template = terminal.match(/<template>([\s\S]*?)<\/template>\s*<script>/)?.[1] || ''
const js = terminal.match(/<script>([\s\S]*?)<\/script>/)?.[1] || ''
const sandbox = { canRerunTerminalSource, isTerminalRemoteUploadText, TERMINAL_RUN_SCRIPT_PREFIX, TerminalLinkedText: {},
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

test('Run again disabled in dropdown when block has no supported replay path', () => {
  assert.match(template, /command="rerun-command"\s+:disabled="!canRerunTerminalBlock\(block\)"/)
  check('[Artifact Send] test -> MacBook (abc) :: /Users/demo', {}, false, 'artifact_send')
  check('[Artifact Send] test -> MacBook', {terminal_block_type:'artifact_send'}, false, 'artifact_send')
  check('[Remote Upload] test -> /tmp', {}, false, 'remote_upload')
  check('shortcut --foo', {terminal_block_type:'quick_action'}, false, 'quick_action')
  check('shortcut --foo', {metadata:{quick_action:true}}, false, 'quick_action')
  check('[Run Script] demo', {}, false, 'script')
  check('', {}, false, 'command')
  check('echo hello', {terminal_block_type:'custom_action'}, false, 'custom_action')
})

test('Run again preserved for actual commands and scripts with source metadata', () => {
  check('pwd', {}, true, 'command')
  check('cd /tmp', {}, true, 'command')
  check('echo [Artifact Send]', {}, true, 'command')
  check('[Run Script] demo', {terminal_block_type:'script', script_name:'demo', params:{a:1}}, true, 'script')
})

test('producers attach structured metadata to non-command terminal entries', () => {
  const artifact = readFileSync(new URL('../src/components/ArtifactDialog.vue', import.meta.url), 'utf8')
  const quickActions = readFileSync(new URL('../src/components/QuickActionsDialog.vue', import.meta.url), 'utf8')
  assert.match(artifact, /\[Artifact Send\][\s\S]{0,180}terminal_block_type: 'artifact_send'/)
  assert.match(quickActions, /append-output[^\n]+terminal_block_type: 'quick_action'/)
})
