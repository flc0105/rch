import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import vm from 'node:vm'

const source = readFileSync(new URL('../src/components/CommandInputBar.vue', import.meta.url), 'utf8')
const script = source.match(/<script>([\s\S]*?)<\/script>/)?.[1]
assert.ok(script)
const sandbox = { TerminalConnectionContext: {}, ElMessage: {}, formatTerminalCancelRequestedLine() {}, formatTerminalCommandFailedLine() {} }
vm.runInNewContext(script.replace(/^import\s+[\s\S]*?\s+from\s+['"][^'"]+['"]\s*;?\s*$/gm, '').replace('export default {', 'globalThis.component = {'), sandbox)
const methods = sandbox.component.methods

test('xt nested contexts reach the registered provider without frontend xt branches', () => {
  const ctx = {
    selectedId: 'test-client',
    resolveFileSystemCompletionRule: () => null,
    buildCommandCompletionCandidateCacheKey: (...args) => args.join(':'),
  }
  const build = input => methods.parseCommandCompletionCandidateQuery.call(ctx, input)
  assert.equal(build('xt ').requestInput, 'xt ')
  assert.equal(build('xt exec ').requestInput, 'xt exec ')
  assert.equal(build('xt exec info p').requestInput, 'xt exec info ')
  assert.equal(build('xt exec which p').requestInput, 'xt exec which ')
  assert.equal(build('xt package install f').requestInput, 'xt package install ')
  assert.equal(build('xt package list --json').requestInput, 'xt package list ')
  assert.equal(build('xt module list f').requestInput, 'xt module list ')
  assert.equal(build('xt instance create frp.frpc').requestInput, 'xt instance create ')
  assert.equal(build('xt instance logs frp.frpc office-frpc -f').requestInput, 'xt instance logs frp.frpc office-frpc ')
  assert.ok(!source.includes('buildXtCommandCompletionQuery('))
})
