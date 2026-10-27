import assert from 'node:assert/strict'
import { test } from 'node:test'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import vm from 'node:vm'
import { buildTerminalOutputJson, buildTerminalOutputText } from '../src/utils/terminalOutputExport.js'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const terminalOutput = readFileSync(resolve(root, 'src/components/TerminalOutput.vue'), 'utf8')
const toolbar = readFileSync(resolve(root, 'src/components/TerminalToolbar.vue'), 'utf8')

test('plain-text export copies the complete terminal line transcript', () => {
  assert.equal(buildTerminalOutputText([
    { text: '> pwd', kind: 'command' },
    { text: '/home/demo' },
    { text: '' },
    { text: '[Success]' },
  ]), '> pwd\n/home/demo\n\n[Success]')
  assert.equal(buildTerminalOutputText([]), '')
})

test('JSON export contains command/result and only includes timing metadata already available', () => {
  assert.deepEqual(buildTerminalOutputJson([
    { hasCommand: false, command: '', result: 'background notice', metadata: [] },
    { hasCommand: true, command: 'pwd', result: '/home/demo', time: '2026-10-27T09:00:00', duration_ms: 12 },
    { hasCommand: true, command: 'whoami', result: 'demo' },
  ]), [
    { command: 'pwd', result: '/home/demo', time: '2026-10-27T09:00:00', duration_ms: 12 },
    { command: 'whoami', result: 'demo' },
  ])
})

test('Terminal Actions exposes grouped clear, copy, and Artifact actions', () => {
  assert.match(toolbar, /@command="handleTerminalActionsCommand"/)
  for (const command of ['clear', 'bottom', 'copy-output', 'copy-json', 'save-output-text', 'save-output-json']) {
    assert.match(toolbar, new RegExp(`command="${command}"`))
  }
  assert.match(terminalOutput, /copyAllTerminalOutput\(format = 'text'\)/)
  assert.match(terminalOutput, /saveAllTerminalOutputArtifact\(format = 'text'\)/)
  assert.match(terminalOutput, /findTerminalBlockMetaValue\(block, \['started_at', 'created_at', 'timestamp', 'finished_at'\]\)/)
})

test('Terminal Actions dispatches each menu item to the existing toolbar events', () => {
  const script = toolbar.match(/<script>([\s\S]*?)<\/script>/)?.[1]
  assert.ok(script)
  const js = script
    .replace(/^import\s+[\s\S]*?\s+from\s+['"][^'"]+['"]\s*$/gm, '')
    .replace('export default {', 'const options = {') + '\nglobalThis.options = options'
  const sandbox = { ToolboxDialog: {} }
  vm.runInNewContext(js, sandbox, { timeout: 1000 })
  const emitted = []
  const context = { $emit: (...args) => emitted.push(args) }
  for (const command of ['clear', 'bottom', 'copy-output', 'copy-json', 'save-output-text', 'save-output-json']) {
    sandbox.options.methods.handleTerminalActionsCommand.call(context, command)
  }
  assert.deepEqual(emitted, [
    ['clear'],
    ['bottom'],
    ['copy-terminal-output'],
    ['copy-terminal-json'],
    ['save-terminal-output'],
    ['save-terminal-json'],
  ])
})
