import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'
import vm from 'node:vm'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const source = readFileSync(resolve(root, 'src/components/CommandInputBar.vue'), 'utf8')
const matches = {}
for (const name of ['parseCommandCompletionCandidateQuery', 'buildJobCommandCompletionQuery']) {
  const match = source.match(new RegExp(`    ${name}\\(rawText, argumentText\\) \\{([\\s\\S]*?)\\n    \\},`))
  if (name === 'parseCommandCompletionCandidateQuery') {
    const parser = source.match(/    parseCommandCompletionCandidateQuery\(queryString\) \{([\s\S]*?)\n    \},/)
    assert.ok(parser)
    matches[name] = vm.runInNewContext(`(function(queryString){${parser[1]}\n})`)
  } else {
    assert.ok(match)
    matches[name] = vm.runInNewContext(`(function(rawText, argumentText){${match[1]}\n})`)
  }
}
const context = {
  selectedId: 'client-A',
  buildCommandCompletionCandidateCacheKey: (name, key) => `${name}:${key}`,
  buildJobCommandCompletionQuery: matches.buildJobCommandCompletionQuery,
  parseCommandCompletionCandidateQuery: matches.parseCommandCompletionCandidateQuery,
  resolveFileSystemCompletionRule: () => null,
}
for (const action of ['start', 'stop', 'status', 'logs']) {
  const input = `job ${action} al`
  const parsed = context.parseCommandCompletionCandidateQuery(input)
  assert.equal(parsed.requestInput, `job ${action} `)
  assert.equal(parsed.cacheKey, `job:${action}`)
  assert.equal(parsed.commandName, 'job')
}
assert.equal(context.parseCommandCompletionCandidateQuery('job st').requestInput, 'job ')
assert.equal(context.parseCommandCompletionCandidateQuery('job stop be').cacheKey, 'job:stop')
assert.equal(context.parseCommandCompletionCandidateQuery('job status be').cacheKey, 'job:status')
console.log('Web Job name completion shares command-completions provider by subcommand')
