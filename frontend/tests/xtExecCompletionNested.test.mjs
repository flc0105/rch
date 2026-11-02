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

test('xt completion selects the nested context instead of obsolete xt info/run prefixes', () => {
  const ctx = { buildCommandCompletionCandidateCacheKey: (...args) => args.join(':'), buildXtCommandCompletionQuery: methods.buildXtCommandCompletionQuery }
  const build = (input) => methods.buildXtCommandCompletionQuery.call(ctx, input, input.slice(3))
  assert.equal(build('xt ').requestInput, 'xt ')
  assert.equal(build('xt exec ').requestInput, 'xt exec ')
  assert.equal(build('xt exec info p').requestInput, 'xt exec info ')
  assert.equal(build('xt exec which p').requestInput, 'xt exec which ')
  assert.equal(build('xt exec ffmpeg -version').requestInput, 'xt exec ')
  assert.equal(build('xt exec info p').cacheKey, 'xt:exec:info')
  assert.equal(build('xt package install f').requestInput, 'xt package install ')
  assert.equal(build('xt package list --json').requestInput, 'xt package ')
  assert.equal(build('xt module list f').requestInput, 'xt module list ')
  assert.equal(build('xt instance create frp.frpc').requestInput, 'xt instance create ')
  assert.equal(build('xt instance logs frp.frpc office-frpc -f').requestInput, 'xt instance logs ')
  assert.equal(build('xt instance logs frp.frpc office-frpc -f').cacheKey, 'xt:instance:logs')
})
