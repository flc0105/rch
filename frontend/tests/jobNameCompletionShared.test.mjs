import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'

const source = readFileSync(new URL('../src/components/CommandInputBar.vue', import.meta.url), 'utf8')
const body = source.match(/    parseCommandCompletionCandidateQuery\(queryString\) \{([\s\S]*?)\n    \},/)?.[1]
assert.ok(body)
const parse = vm.runInNewContext(`(function(queryString){${body}\n})`)
const context = {
  selectedId: 'client-A',
  buildCommandCompletionCandidateCacheKey: (name, key) => `${name}:${key}`,
  resolveFileSystemCompletionRule: () => null,
}
for (const action of ['start', 'stop', 'status', 'logs']) {
  const parsed = parse.call(context, `job ${action} al`)
  assert.equal(parsed.requestInput, `job ${action} `)
  assert.equal(parsed.cacheKey, `job:job ${action} `)
  assert.equal(parsed.commandName, 'job')
}
assert.equal(parse.call(context, 'job st').requestInput, 'job ')
assert.equal(parse.call(context, 'job stop be').cacheKey, 'job:job stop ')
assert.equal(parse.call(context, 'job status be').cacheKey, 'job:job status ')
console.log('Web Job completion context uses the same generic provider boundary')
