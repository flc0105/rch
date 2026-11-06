import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import vm from 'node:vm'

const source = readFileSync(new URL('../src/components/CommandInputBar.vue', import.meta.url), 'utf8')
const script = source.match(/<script>([\s\S]*?)<\/script>/)?.[1]
assert.ok(script)
const sandbox = {
  ElMessage: { success() {}, warning() {} }, TerminalConnectionContext: {},
  getCommandCandidates: async () => [
    { name: 'edit', help: 'Remote command', source: 'client', group: 'file' },
    { name: 'shell', source: 'client', group: 'execution' },
  ],
  getCommandHistory: async () => [],
}
vm.runInNewContext(script.replace(/^import\s+[\s\S]*?\s+from\s+['"][^'"]+['"]\s*;?\s*$/gm, '')
  .replace('export default {', 'globalThis.component = {'), sandbox)
const methods = sandbox.component.methods

test('Web local edit and clear appear in frontend group ahead of remote names', async () => {
  const ctx = {
    ...methods,
    selectedId: 'client-1', currentConnection: { client_id: 'client-1', machine_id: 'machine-1' },
    commandCandidates: [], commandCandidatesLoadedFor: '',
  }
  await ctx.loadCommandCandidatesInternal('client-1')
  const edit = ctx.commandCandidates.filter(item => item.name === 'edit')
  const clear = ctx.commandCandidates.filter(item => item.name === 'clear')
  assert.equal(edit.length, 1)
  assert.equal(edit[0].group, 'frontend')
  assert.equal(edit[0].source, 'frontend')
  assert.equal(clear.length, 1)
  assert.equal(clear[0].source, 'frontend')
  assert.ok(ctx.commandCandidates.some(item => item.name === 'shell'))
})

test('local completion entries invoke existing frontend actions', () => {
  const actions = []
  const ctx = {
    ...methods, selectedId: 'client-1', commandText: 'edit config.json',
    $emit: (...args) => actions.push(args),
  }
  assert.equal(ctx.handleLocalFrontendCommand('edit config.json'), true)
  assert.equal(actions[0][0], 'edit-remote-file')
  assert.equal(ctx.handleLocalFrontendCommand('clear'), true)
  assert.equal(actions[1][0], 'clear-output')
})
