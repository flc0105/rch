import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import vm from 'node:vm'

const source = readFileSync(new URL('../src/components/CommandInputBar.vue', import.meta.url), 'utf8')
const content = source.match(/<script>([\s\S]*?)<\/script>/)?.[1]
const js = content.replace(/^import\s+[\s\S]*?\s+from\s+['"][^'"]+['"]\s*$/gm, '')
  .replace('export default {', 'const options = {') + '\nglobalThis.options = options'
const sandbox = { ElMessage: {}, TerminalConnectionContext: {} }
vm.runInNewContext(js, sandbox, { timeout: 2000 })
const host = { selectedId: 'client-1', currentConnection: { machine_id: 'machine-1', cwd: '/' },
  commandText: '', getCurrentConnectionCwd: () => '/' }
for (const [name, method] of Object.entries(sandbox.options.methods)) host[name] = method.bind(host)

for (const [typed, expected, remote] of [
  ['config set ', 'config set ', true],
  ['config set --key ', 'config set --key ', true],
  ['config reset SCRIPT_', 'config reset ', true],
  ['script view ', 'script view ', false],
  ['script view --name ', 'script view --name ', false],
  ['script exec test/misc', 'script exec ', false],
  ['script exec --name test/misc', 'script exec --name ', false],
  ['job start ', 'job start ', false],
  ['job start --name ', 'job start --name ', false],
  ['job status --name ', 'job status --name ', false],
]) {
  test(`${typed} sends actionable completion context`, () => {
    const result = host.parseCommandCompletionCandidateQuery(typed)
    assert.ok(result, `missing route for ${typed}`)
    assert.equal(result.requestInput, expected)
    assert.equal(result.requiresRemoteClient, remote)
  })
}

test('named and positional candidates cannot contaminate each other cache', () => {
  const positional = host.parseCommandCompletionCandidateQuery('config set ')
  const named = host.parseCommandCompletionCandidateQuery('config set --key ')
  assert.notEqual(positional.cacheKey, named.cacheKey)
  const script1 = host.parseCommandCompletionCandidateQuery('script exec ')
  const script2 = host.parseCommandCompletionCandidateQuery('script exec --name ')
  assert.notEqual(script1.cacheKey, script2.cacheKey)
})

test('config and script completion candidates match typed values', () => {
  const entries = [
    ['config set SCRIPT_', 'config set SCRIPT_DEFAULT_TIMEOUT'],
    ['config set --key SCRIPT_', 'config set --key SCRIPT_DEFAULT_TIMEOUT'],
    ['script view test/', 'script view test/misc/script_mode_probe'],
    ['script exec --name test/', 'script exec --name test/misc/script_mode_probe'],
  ]
  for (const [query, candidate] of entries) {
    const result = host.filterCommandCompletionCandidates(
      [{ name: candidate, title: candidate, value: candidate }],
      host.parseCommandCompletionCandidateQuery(query),
    )
    assert.equal(result.length, 1, query)
  }
})
