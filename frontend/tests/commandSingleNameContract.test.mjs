import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import vm from 'node:vm'

const vue = readFileSync(new URL('../src/components/CommandInputBar.vue', import.meta.url), 'utf8')
const script = vue.match(/<script>([\s\S]*?)<\/script>/)?.[1]
assert.ok(script)
const javascript = script.replace(/^import\s+[\s\S]*?\s+from\s+['"][^'"]+['"]\s*$/gm, '')
  .replace('export default {', 'const options = {') + '\nglobalThis.options = options'
const globals = { ElMessage: {}, TerminalConnectionContext: {}, formatTerminalCancelRequestedLine() {}, formatTerminalCommandFailedLine() {} }
vm.runInNewContext(javascript, globals, { timeout: 1000 })
const methods = globals.options.methods

function normalize(item) {
  const context = {buildCandidateGroupLabel: methods.buildCandidateGroupLabel, getCandidateTitleText: methods.getCandidateTitleText}
  return methods.normalizeCandidateItem.call(context, item)
}

test('single name is the inserted text for ACMD, builtins and parameters', () => {
  for (const value of ['acmd help', 'script exec ./foo.py', 'mkdir ', 'shell']) {
    const item = normalize({name: value, group: 'client'})
    assert.equal(item.name, value.trim())
    assert.equal(methods.getCandidateInsertText(item), value.trim())
    assert.equal(item.value, value.trim())
    assert.ok(!('template' in item))
  }
})

test('Client completion candidates already contain the full inserted command', () => {
  const context = {
    normalizeCandidateItem: methods.normalizeCandidateItem,
    buildCandidateGroupLabel: methods.buildCandidateGroupLabel,
    getCandidateTitleText: methods.getCandidateTitleText,
  }
  const item = methods.normalizeCommandCompletionCandidate.call(context, {
    name: 'cd /tmp/example', value: 'cd /tmp/example',
    title: 'cd /tmp/example', group: 'filesystem', source: 'client_filesystem',
  }, {})
  assert.equal(item.name, 'cd /tmp/example')
  assert.equal(methods.getCandidateInsertText(item), 'cd /tmp/example')
  assert.equal(item.value, item.name)
  assert.ok(!('template' in item))
})
