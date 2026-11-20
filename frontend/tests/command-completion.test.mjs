import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import vm from 'node:vm'

const source = readFileSync(new URL('../src/components/CommandInputBar.vue', import.meta.url), 'utf8')
const script = source.match(/<script>([\s\S]*?)<\/script>/)?.[1]
const commonOps = JSON.parse(readFileSync(new URL('../src/config/commonOps.json', import.meta.url), 'utf8'))
assert.ok(script)
const sandbox = {
  TerminalConnectionContext: {}, ElMessage: {}, setTimeout,
  commonOps,
  formatTerminalCancelRequestedLine() {}, formatTerminalCommandFailedLine() {},
}
vm.runInNewContext(script.replace(/^import\s+[\s\S]*?\s+from\s+['"][^'"]+['"]\s*;?\s*$/gm, '')
  .replace('export default {', 'globalThis.component = {'), sandbox)
const m = sandbox.component.methods

const setup = (cursor) => {
  const input = { selectionStart: cursor, setSelectionRange(start, end) { this.selectionStart = start; this.selectionEnd = end } }
  const ctx = {
    ...m,
    $refs: { commandInputRef: { $el: { querySelector: () => input }, focus() {} } },
    selectedId: 'device-1', currentConnection: { machine_id: 'machine', cwd: '/tmp', command_manifest: [
      { name: 'cd', completion: { provider: 'filesystem', kinds: ['directory'] } },
      { name: 'acmd download', completion: [{ provider: 'filesystem', kinds: ['file', 'directory'] }] },
      { name: 'acmd image_info', completion: [{ provider: 'filesystem', kinds: ['file', 'directory'] }] },
      { name: 'acmd sqlite_query', completion: [{ provider: 'filesystem', kinds: ['file', 'directory'] }] },
    ] },
    autocompleteNavigationPreviewActive: false,
    $nextTick: fn => fn(),
  }
  return { ctx, input }
}

const file = (candidatePath, isDir = false) => ({
  name: `download ${candidatePath}`, candidatePath, isDir,
  kind: isDir ? 'directory' : 'file', help: candidatePath, group: 'filesystem', source: 'client_download',
})
const build = (ctx, raw) => ctx.parseExplicitPathCompletionQuery(raw)
const normalize = (ctx, query, list) => list.map(v => ctx.normalizeCommandCompletionCandidate(v, query)).filter(Boolean)

test('selection substitutes only the marker token and preserves suffix and caret', () => {
  const raw = 'myalias --path=@@ --flag remain'
  const caret = raw.indexOf('@@') + 2
  const { ctx, input } = setup(caret)
  const query = build(ctx, raw)
  assert.equal(query.replaceEnd, caret)
  const item = normalize(ctx, query, [file('my notes.txt')])[0]
  assert.equal(item.name, 'myalias --path="my notes.txt" --flag remain')
  ctx.applyAutocompleteCandidateToInput(item)
  assert.equal(ctx.commandText, item.name)
  assert.equal(input.selectionStart, 'myalias --path="my notes.txt"'.length)
  assert.ok(!ctx.commandText.includes('@@'))
})

test('quoted marker preserves surrounding quotes and does not duplicate them', () => {
  for (const [raw, expected] of [
    ['alias --path="@@" --mode fast', 'alias --path="my notes.txt" --mode fast'],
    ["alias --path='@@' --mode fast", "alias --path='my notes.txt' --mode fast"],
  ]) {
    const { ctx } = setup(raw.indexOf('@@') + 2)
    const query = build(ctx, raw)
    const item = normalize(ctx, query, [file('my notes.txt')])[0]
    assert.equal(item.name, expected)
  }
})
