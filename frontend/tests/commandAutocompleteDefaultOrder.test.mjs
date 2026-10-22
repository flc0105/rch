import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import vm from 'node:vm'

const source = readFileSync(new URL('../src/components/CommandInputBar.vue', import.meta.url), 'utf8')
const script = source.match(/<script>([\s\S]*?)<\/script>/)?.[1]
assert.ok(script)
const javascript = script.replace(/^import\s+[\s\S]*?\s+from\s+['"][^'"]+['"]\s*$/gm, '')
  .replace('export default {', 'const options = {') + '\nglobalThis.options = options'
const globals = { ElMessage: {}, formatTerminalCancelRequestedLine() {}, formatTerminalCommandFailedLine() {} }
vm.runInNewContext(javascript, globals, { timeout: 1000 })
const methods = globals.options.methods

const candidate = (group, name, source = 'client') => ({ group, name, template: name, source })

test('blank input sorts by actual common_ops group after acmd, and alphabetically within groups', () => {
  const items = [
    candidate('history', 'xt ffmpeg', 'history'),
    candidate('file', 'zip'), candidate('shell', 'pwd'),
    candidate('maintenance', 'update'), candidate('common_ops', 'rmdir', 'common_ops'),
    candidate('', 'my_alias', 'alias'), candidate('shell', 'cd'),
    candidate('acmd', 'acmd z'), candidate('server', 'job', 'server'),
    candidate('file', 'cat'), candidate('maintenance', 'clean'),
    candidate('execution', 'run'), candidate('common_ops', 'mkdir', 'common_ops'),
    candidate('runtime', 'watchdog'), candidate('history', 'cd /tmp', 'history'),
    candidate('transfer', 'download'), candidate('system', 'uptime'),
    candidate('network', 'ifconfig'), candidate('privilege', 'run_elevated'),
    candidate('media', 'screenshot'), candidate('automation', 'keyboard_send'),
    candidate('python', 'piplist'), candidate('session', 'kill_instance'),
  ]
  const sorted = methods.sortDefaultCommandCandidates(items)
  assert.deepEqual(Array.from(sorted, item => item.name), [
    'cd', 'pwd', 'run', 'kill_instance', 'uptime', 'ifconfig', 'run_elevated',
    'screenshot', 'cat', 'zip', 'keyboard_send', 'download', 'watchdog',
    'clean', 'update', 'piplist', 'acmd z', 'mkdir', 'rmdir', 'job',
    'my_alias', 'cd /tmp', 'xt ffmpeg',
  ])
  assert.equal(items[0].name, 'xt ffmpeg', 'sorting must not mutate cached candidates')
})

test('unrecognized groups stay before pinned history, with group name as deterministic tie-breaker', () => {
  const items = [candidate('history', 'pin', 'history'), candidate('experimental', 'z'),
    candidate('server', 'help', 'server'), candidate('other', 'b'), candidate('experimental', 'a')]
  assert.deepEqual(Array.from(methods.sortDefaultCommandCandidates(items), item => item.name),
    ['help', 'a', 'z', 'b', 'pin'])
})

test('only the empty top-level command list is re-ordered; typed-query filtering is unchanged', async () => {
  const input = [candidate('file', 'shell_more'), candidate('shell', 'shell'), candidate('shell', 'shell_stream')]
  const calls = []
  const context = {
    commandCandidates: input,
    getAutocompleteCandidateQueryString: q => q,
    setAutocompleteCandidateItems: () => {},
    parseVariableCompletionQuery: () => null,
    parseCommandCompletionCandidateQuery: () => null,
    ensureCommandCandidatesLoaded: async () => {},
    sortDefaultCommandCandidates: methods.sortDefaultCommandCandidates,
    filterCandidatesByTitle: (items, keyword) => items.filter(item => item.name.includes(keyword)),
  }
  await methods.queryCommandCandidates.call(context, '', list => calls.push(Array.from(list, item => item.name)))
  await methods.queryCommandCandidates.call(context, 'shell', list => calls.push(Array.from(list, item => item.name)))
  assert.deepEqual(calls, [['shell', 'shell_stream', 'shell_more'],
    ['shell_more', 'shell', 'shell_stream']])
})

test('common_ops remains the canonical group name, with no command_ops alias', () => {
  const source = readFileSync(new URL('../src/components/CommandInputBar.vue', import.meta.url), 'utf8')
  assert.match(source, /'python', 'acmd', 'common_ops', 'server', 'alias'/)
  assert.doesNotMatch(source, /command_ops|maintainance/)
  assert.deepEqual(Array.from(methods.sortDefaultCommandCandidates([
    candidate('server', 'job'), candidate('common_ops', 'hostname'), candidate('acmd', 'acmd'),
  ]), item => item.group), ['acmd', 'common_ops', 'server'])
})
