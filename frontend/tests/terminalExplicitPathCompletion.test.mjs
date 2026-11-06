import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import vm from 'node:vm'

const source = readFileSync(new URL('../src/components/CommandInputBar.vue', import.meta.url), 'utf8')
const script = source.match(/<script>([\s\S]*?)<\/script>/)?.[1]
assert.ok(script)
const sandbox = {
  TerminalConnectionContext: {}, ElMessage: {}, setTimeout,
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
    selectedId: 'device-1', currentConnection: { machine_id: 'machine', cwd: '/tmp' },
    autocompleteNavigationPreviewActive: false,
    $nextTick: fn => fn(),
  }
  return { ctx, input }
}

const file = (candidatePath, isDir = false) => ({
  name: `download ${candidatePath}`, candidatePath, isDir,
  kind: isDir ? 'directory' : 'file', help: candidatePath, group: 'filesystem', source: 'client_download',
})
const candidates = [file('docs', true), file('Downloads', true), file('note.txt'), file('my notes.txt')]
const build = (ctx, raw) => ctx.parseExplicitPathCompletionQuery(raw)
const normalize = (ctx, query, list = candidates) => list.map(v => ctx.normalizeCommandCompletionCandidate(v, query)).filter(Boolean)

test('only @@ is an explicit marker in any command, alias or named option', () => {
  for (const raw of ['anything @@', 'myalias --path=@@', 'shell echo "@@"', 'custom @@/Users/f']) {
    const { ctx } = setup(raw === 'shell echo "@@"' ? raw.length - 1 : raw.length)
    const query = build(ctx, raw)
    assert.ok(query, raw)
    assert.equal(query.requestInput.startsWith('download '), true)
    assert.equal(query.fileSystemCompletionMode, undefined)
  }
  for (const raw of ['echo foo@@', 'echo \\@@', 'echo hello']) {
    const { ctx } = setup(raw.length)
    assert.equal(build(ctx, raw), null, raw)
  }
})

test('@@ mixes directory and file suggestions; legacy suffixes have no type-specific behavior', () => {
  for (const [raw, expected] of [
    ['cmd @@', ['docs', 'Downloads', 'note.txt', 'my notes.txt']],
    ['cmd @@do', ['docs', 'Downloads']],
    ['cmd @@no', ['note.txt']],
  ]) {
    const { ctx } = setup(raw.length)
    const query = build(ctx, raw)
    const output = ctx.filterCommandCompletionCandidates(normalize(ctx, query), query)
    assert.deepEqual(Array.from(output, item => item.displayText), expected, raw)
  }
  for (const legacy of ['@@d:', '@@f:']) {
    const { ctx } = setup(('cmd ' + legacy).length)
    const query = build(ctx, 'cmd ' + legacy)
    assert.equal(query.pathPrefix, legacy.slice(2))
    assert.equal(query.fileSystemCompletionMode, undefined)
  }
})

test('nested paths reuse the existing provider with directory-level caching', () => {
  const raw = 'anycmd --option @@docs/re'
  const { ctx } = setup(raw.length)
  const query = build(ctx, raw)
  assert.equal(query.requestInput, 'download docs/')
  assert.ok(query.cacheKey.includes('explicit_path'))
  assert.ok(query.cacheKey.endsWith('docs'))
  const output = normalize(ctx, query, [file('docs/readme.txt'), file('docs/report.pdf'), file('docs/zoo.txt')])
  assert.deepEqual(Array.from(ctx.filterCommandCompletionCandidates(output, query), item => item.displayText),
    ['docs/readme.txt', 'docs/report.pdf'])
})

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

test('caret-in-middle queries replace active path only and preserve text after cursor', () => {
  const raw = 'custom --file @@doc/index.txt --other 1'
  const caret = raw.indexOf('@@doc') + '@@doc'.length
  const { ctx } = setup(caret)
  const query = build(ctx, raw)
  assert.equal(query.pathPrefix, 'doc')
  assert.equal(query.replaceEnd, raw.indexOf(' --other'))
  const item = normalize(ctx, query, [file('documentation')])[0]
  assert.equal(item.name, 'custom --file documentation --other 1')
})

test('escaped path arguments preserve whitespace, shell symbols, and Windows backslashes', () => {
  const { ctx } = setup(0)
  assert.equal(ctx.quoteExplicitPathCandidate('one two.txt', ''), '"one two.txt"')
  assert.equal(ctx.quoteExplicitPathCandidate('/tmp/price$20', ''), '"/tmp/price\\$20"')
  assert.equal(ctx.quoteExplicitPathCandidate('C:\\A Folder\\file.txt', ''), '"C:\\\\A Folder\\\\file.txt"')
  assert.equal(ctx.quoteExplicitPathCandidate("one's file", "'"), String.raw`one'\''s file`)
})

test('async provider request routes only through read-only directory and path proxies', async () => {
  const raw = 'myalias @@'
  const { ctx } = setup(raw.length)
  const query = build(ctx, raw)
  const captured = []
  sandbox.getCommandCompletions = async (clientId, request) => { captured.push([clientId, request]); return {items:[file('note.txt')]} }
  const mock = { ...ctx,
    commandCompletionCandidatesByContext: {}, commandCompletionCandidatesLoadPromises: {},
    hasRunningWebTask: false,
    normalizeCandidateItem: m.normalizeCandidateItem,
  }
  // The component method calls its imported helper, not a dynamic property.
  const output = await mock.loadCommandCompletionCandidatesForContext(query)
  assert.equal(output.length, 1)
  assert.equal(output[0].displayText, 'note.txt')
  assert.equal(captured.length, 1)
  assert.equal(captured[0][0], 'device-1')
  assert.equal(captured[0][1].raw_input, 'download ')
})

test('cached results regenerate their insertion for the newest input within the same directory', () => {
  const first = 'alias --file @@do --other'
  const next = 'different --file @@doc --other'
  const { ctx, input } = setup(first.indexOf('@@do') + '@@do'.length)
  const q1 = build(ctx, first)
  const cached = normalize(ctx, q1, [file('docs', true)])
  input.selectionStart = next.indexOf('@@doc') + '@@doc'.length
  const q2 = build(ctx, next)
  assert.equal(q1.cacheKey, q2.cacheKey)
  const results = ctx.filterCommandCompletionCandidates(cached, q2)
  assert.equal(results[0].name, 'different --file @@docs/ --other')
})

test('arrow-preview keeps the original cursor for markers before later arguments', () => {
  const raw = 'alias --file @@ --suffix'
  const { ctx } = setup(raw.indexOf('@@') + 2)
  const query = build(ctx, raw)
  const item = normalize(ctx, query, [file('abc.txt')])[0]
  ctx.autocompleteCandidateItems = [item]
  ctx.autocompleteCandidateQueryText = raw
  ctx.commandText = raw
  assert.equal(ctx.previewAutocompleteCandidateByArrowKey('ArrowDown'), true)
  assert.equal(ctx.getCommandInputCursorPosition(raw), raw.indexOf('@@') + 2)
  ctx.commitAutocompleteNavigationPreview()
  assert.equal(ctx.commandText, 'alias --file abc.txt --suffix')
})

test('Windows path quoting keeps native backslash separators', () => {
  const { ctx } = setup(0)
  ctx.currentConnection.os_type = 'Windows'
  assert.equal(ctx.quoteExplicitPathCandidate('C:\\Program Files\\app.exe', ''), '"C:\\Program Files\\app.exe"')
})

test('pasted quoted marker also completes when cursor is after its closing quote', () => {
  const raw = 'somealias "@@"'
  const { ctx } = setup(raw.length)
  const query = build(ctx, raw)
  assert.ok(query)
  assert.equal(query.pathPrefix, '')
  const item = normalize(ctx, query, [file('my notes.txt')])[0]
  assert.equal(item.name, 'somealias "my notes.txt"')
})


test('selecting nested directories preserves the marker until a file is chosen', () => {
  const { ctx, input } = setup('anyalias --path=@@/Us --verbose'.indexOf('@@/Us') + '@@/Us'.length)
  const raw = 'anyalias --path=@@/Us --verbose'
  const first = build(ctx, raw)
  const users = normalize(ctx, first, [file('/Users', true)])[0]
  assert.equal(users.name, 'anyalias --path=@@/Users/ --verbose')
  assert.equal(users.continueAutocomplete, true)
  ctx.applyAutocompleteCandidateToInput(users)
  assert.equal(input.selectionStart, 'anyalias --path=@@/Users/'.length)

  let query = build(ctx, ctx.commandText)
  assert.equal(query.requestInput, 'download /Users/')
  const flc = normalize(ctx, query, [file('/Users/flc', true)])[0]
  ctx.applyAutocompleteCandidateToInput(flc)
  assert.equal(ctx.commandText, 'anyalias --path=@@/Users/flc/ --verbose')

  query = build(ctx, ctx.commandText)
  assert.equal(query.requestInput, 'download /Users/flc/')
  const desktop = normalize(ctx, query, [file('/Users/flc/Desktop', true)])[0]
  ctx.applyAutocompleteCandidateToInput(desktop)
  assert.equal(ctx.commandText, 'anyalias --path=@@/Users/flc/Desktop/ --verbose')

  query = build(ctx, ctx.commandText)
  assert.equal(query.requestInput, 'download /Users/flc/Desktop/')
  const finalFile = normalize(ctx, query, [file('/Users/flc/Desktop/aa.txt')])[0]
  ctx.applyAutocompleteCandidateToInput(finalFile)
  assert.equal(ctx.commandText, 'anyalias --path=/Users/flc/Desktop/aa.txt --verbose')
  assert.equal(finalFile.continueAutocomplete, false)
  assert.ok(!ctx.commandText.includes('@@'))
})

test('a directory can be finalized using the current-directory choice', () => {
  const raw = 'myalias --directory @@/Users/flc/ --flag'
  const { ctx, input } = setup(raw.indexOf(' --flag'))
  const query = build(ctx, raw)
  const choices = ctx.filterCommandCompletionCandidates(normalize(ctx, query, [file('/Users/flc/Desktop', true)]), query)
  assert.equal(choices[0].help, 'Use this directory')
  assert.equal(choices[0].name, 'myalias --directory /Users/flc/ --flag')
  assert.equal(choices[1].name, 'myalias --directory @@/Users/flc/Desktop/ --flag')
  ctx.applyAutocompleteCandidateToInput(choices[0])
  assert.equal(ctx.commandText, 'myalias --directory /Users/flc/ --flag')
  assert.equal(input.selectionStart, 'myalias --directory /Users/flc/'.length)
})

test('directory navigation preserves quoted paths with spaces and continues querying', () => {
  const raw = 'alias --path=@@/Users/Fl --other'
  const { ctx, input } = setup(raw.indexOf(' --other'))
  const initial = build(ctx, raw)
  const folder = normalize(ctx, initial, [file('/Users/Fl C', true)])[0]
  assert.equal(folder.name, 'alias --path="@@/Users/Fl C/" --other')
  ctx.applyAutocompleteCandidateToInput(folder)
  assert.equal(input.selectionStart, 'alias --path="@@/Users/Fl C/'.length)
  const next = build(ctx, ctx.commandText)
  assert.equal(next.pathPrefix, '/Users/Fl C/')
  assert.equal(next.requestInput, 'download /Users/Fl C/')
  const selected = normalize(ctx, next, [file('/Users/Fl C/data.txt')])[0]
  ctx.applyAutocompleteCandidateToInput(selected)
  assert.equal(ctx.commandText, 'alias --path="/Users/Fl C/data.txt" --other')
})

test('Windows path navigation retains backslash separators and finishes on file', () => {
  const raw = 'alias --file @@C:\\Us'
  const { ctx } = setup(raw.length)
  ctx.currentConnection.os_type = 'Windows'
  const query = build(ctx, raw)
  const candidate = normalize(ctx, query, [file('C:\\Users', true)])[0]
  assert.equal(candidate.name, 'alias --file @@C:\\Users\\')
  ctx.applyAutocompleteCandidateToInput(candidate)
  const next = build(ctx, ctx.commandText)
  assert.equal(next.requestInput, 'download C:\\Users\\')
  const final = normalize(ctx, next, [file('C:\\Users\\hello.txt')])[0]
  assert.equal(final.name, 'alias --file C:\\Users\\hello.txt')
})

test('directory selection triggers autocomplete refresh without requiring another marker', async () => {
  const raw = 'alias @@/Us'
  const { ctx } = setup(raw.length)
  let refreshed = ''
  ctx.$refs.commandInputRef.activated = false
  ctx.$refs.commandInputRef.getData = value => { refreshed = value }
  const query = build(ctx, raw)
  const directory = normalize(ctx, query, [file('/Users', true)])[0]
  ctx.applyAutocompleteCandidateToInput(directory)
  await new Promise(resolve => setTimeout(resolve, 10))
  assert.equal(ctx.$refs.commandInputRef.activated, true)
  assert.equal(refreshed, 'alias @@/Users/')
})

test('arrow preview commit continues browsing directories and keeps marker', () => {
  const raw = 'alias --path=@@/Us --flag'
  const { ctx, input } = setup(raw.indexOf(' --flag'))
  const query = build(ctx, raw)
  const folder = normalize(ctx, query, [file('/Users', true)])[0]
  ctx.autocompleteCandidateItems = [folder]
  ctx.autocompleteCandidateQueryText = raw
  ctx.commandText = raw
  assert.equal(ctx.previewAutocompleteCandidateByArrowKey('ArrowDown'), true)
  assert.equal(ctx.commandText, 'alias --path=@@/Users/ --flag')
  ctx.commitAutocompleteNavigationPreview()
  assert.equal(input.selectionStart, 'alias --path=@@/Users/'.length)
  assert.equal(ctx.commandText, 'alias --path=@@/Users/ --flag')
})


test('intermediate quoted paths decode shell escapes before remote lookup', () => {
  const raw = 'alias @@/tmp/pr'
  const { ctx, input } = setup(raw.length)
  const first = build(ctx, raw)
  const folder = normalize(ctx, first, [file('/tmp/price$20', true)])[0]
  assert.equal(folder.name, 'alias "@@/tmp/price\\$20/"')
  ctx.applyAutocompleteCandidateToInput(folder)
  assert.equal(input.selectionStart, 'alias "@@/tmp/price\\$20/'.length)
  const next = build(ctx, ctx.commandText)
  assert.equal(next.pathPrefix, '/tmp/price$20/')
  assert.equal(next.requestInput, 'download /tmp/price$20/')
})


test('Windows directory containing spaces remains navigable inside quotes', () => {
  const raw = 'alias @@C:\\Pro --flag'
  const { ctx, input } = setup(raw.indexOf(' --flag'))
  ctx.currentConnection.os_type = 'Windows'
  const folder = normalize(ctx, build(ctx, raw), [file('C:\\Program Files', true)])[0]
  ctx.applyAutocompleteCandidateToInput(folder)
  assert.equal(ctx.commandText, 'alias "@@C:\\Program Files\\" --flag')
  assert.equal(input.selectionStart, 'alias "@@C:\\Program Files\\'.length)
  const next = build(ctx, ctx.commandText)
  assert.ok(next)
  assert.equal(next.requestInput, 'download C:\\Program Files\\')
})


test('real select and blur lifecycle reopens Inbox with its children instead of the old entry', async () => {
  const raw = 'allow_exec @@I'
  const { ctx, input } = setup(raw.length)
  ctx.commandText = raw
  ctx.commandCompletionCandidatesByContext = {}
  ctx.commandCompletionCandidatesLoadPromises = {}
  ctx.hasRunningWebTask = false
  ctx.waitForCommandCompletionDebounce = async () => true
  const calls = []
  sandbox.getCommandCompletions = async (_clientId, payload) => {
    calls.push(payload.raw_input)
    if (payload.raw_input === 'download Inbox/') {
      return { items: [file('Inbox/Nested', true), file('Inbox/aa.txt')] }
    }
    if (payload.raw_input === 'download Inbox/Nested/') {
      return { items: [file('Inbox/Nested/next.txt')] }
    }
    return { items: [file('Inbox', true)] }
  }
  const autocomplete = ctx.$refs.commandInputRef
  autocomplete.activated = false
  autocomplete.suggestions = []
  autocomplete.getData = value => {
    // Element Plus only shows the returned candidates when activated.
    ctx.queryCommandCandidates(value, items => {
      autocomplete.suggestions = items
      autocomplete.visible = !!autocomplete.activated && items.length > 0
    })
  }
  const first = normalize(ctx, build(ctx, raw), [file('Inbox', true)])[0]
  // Element Plus emits model update, then select, then clears the old list.
  ctx.handleCommandTextUpdate(first.value)
  ctx.handleCandidateSelect(first)
  autocomplete.activated = false
  autocomplete.suggestions = []
  await new Promise(resolve => setTimeout(resolve, 25))
  assert.equal(ctx.commandText, 'allow_exec @@Inbox/')
  assert.equal(autocomplete.activated, true)
  assert.equal(autocomplete.visible, true)
  assert.ok(calls.includes('download Inbox/'))
  assert.deepEqual(Array.from(autocomplete.suggestions, item => item.displayText), [
    'Inbox/', 'Inbox/Nested', 'Inbox/aa.txt',
  ])
  assert.equal(input.selectionStart, 'allow_exec @@Inbox/'.length)

  const nested = autocomplete.suggestions.find(item => item.displayText === 'Inbox/Nested')
  ctx.handleCommandTextUpdate(nested.value)
  ctx.handleCandidateSelect(nested)
  autocomplete.activated = false
  autocomplete.suggestions = []
  await new Promise(resolve => setTimeout(resolve, 25))
  assert.equal(ctx.commandText, 'allow_exec @@Inbox/Nested/')
  assert.equal(autocomplete.visible, true)
  assert.ok(calls.includes('download Inbox/Nested/'))
  const final = autocomplete.suggestions.find(item => item.displayText === 'Inbox/Nested/next.txt')
  assert.ok(final)
  ctx.handleCommandTextUpdate(final.value)
  ctx.handleCandidateSelect(final)
  assert.equal(ctx.commandText, 'allow_exec Inbox/Nested/next.txt')
})

test('an older explicit request cannot replace suggestions for the newly selected folder', async () => {
  const oldText = 'allow_exec @@I'
  const newText = 'allow_exec @@Inbox/'
  const { ctx, input } = setup(newText.length)
  ctx.commandText = newText
  input.selectionStart = newText.length
  ctx.buildCommandCompletionCandidates = async () => [file('Inbox', true)]
  let invoked = false
  await ctx.queryCommandCandidates(oldText, () => { invoked = true })
  assert.equal(invoked, false)
})

test('directory refresh supports Element Plus exposed activated ref and ignores stale text', async () => {
  const raw = 'myalias @@In'
  const { ctx } = setup(raw.length)
  const autocomplete = ctx.$refs.commandInputRef
  autocomplete.activated = { value: false }
  const requested = []
  autocomplete.getData = value => requested.push(value)
  const selected = normalize(ctx, build(ctx, raw), [file('Inbox', true)])[0]
  ctx.applyAutocompleteCandidateToInput(selected)
  await new Promise(resolve => setTimeout(resolve, 10))
  assert.equal(autocomplete.activated.value, true)
  assert.deepEqual(requested, ['myalias @@Inbox/'])

  autocomplete.activated.value = false
  ctx.applyAutocompleteCandidateToInput(normalize(ctx, build(ctx, ctx.commandText), [file('Inbox/Nested', true)])[0])
  // A user edit before the deferred refresh must supersede the old request.
  ctx.commandText = 'myalias --other'
  await new Promise(resolve => setTimeout(resolve, 10))
  assert.deepEqual(requested, ['myalias @@Inbox/'])
  assert.equal(autocomplete.activated.value, false)
})

test('right-arrow directory commit clears prior third-item selection before next ArrowDown', () => {
  const raw = 'alias @@t'
  const { ctx } = setup(raw.length)
  const highlighted = []
  ctx.$refs.commandInputRef.highlight = index => highlighted.push(index)
  ctx.commandText = raw
  const first = build(ctx, raw)
  ctx.autocompleteCandidateItems = normalize(ctx, first, [
    file('temp', true), file('tiles', true), file('test', true),
  ])
  ctx.autocompleteCandidateQueryText = raw
  for (let i = 0; i < 3; i++) assert.equal(ctx.previewAutocompleteCandidateByArrowKey('ArrowDown'), true)
  assert.equal(ctx.autocompleteNavigationIndex, 2)
  assert.equal(ctx.commandText, 'alias @@test/')
  ctx.commitAutocompleteNavigationPreview()
  assert.equal(ctx.autocompleteNavigationIndex, -1)
  assert.equal(ctx.autocompleteCandidateQueryText, '')
  assert.equal(highlighted.at(-1), -1)

  const nextQuery = build(ctx, ctx.commandText)
  const nextItems = ctx.filterCommandCompletionCandidates(normalize(ctx, nextQuery, [
    file('test/folder', true), file('test/a.txt'), file('test/b.txt'),
  ]), nextQuery)
  ctx.setAutocompleteCandidateItems(nextItems, ctx.commandText)
  assert.equal(ctx.autocompleteNavigationIndex, -1)
  assert.equal(ctx.previewAutocompleteCandidateByArrowKey('ArrowDown'), true)
  assert.equal(ctx.autocompleteNavigationIndex, 0)
  assert.equal(ctx.commandText, 'alias test/') // "Use this directory" is first in this level
})

test('clicking a directory also resets the Element Plus highlight and next level selection', () => {
  const raw = 'alias @@tes'
  const { ctx } = setup(raw.length)
  const highlighted = []
  ctx.$refs.commandInputRef.highlight = index => highlighted.push(index)
  ctx.commandText = raw
  const selected = normalize(ctx, build(ctx, raw), [file('test', true)])[0]
  ctx.autocompleteNavigationIndex = 2
  ctx.applyAutocompleteCandidateToInput(selected)
  assert.equal(ctx.autocompleteNavigationIndex, -1)
  assert.equal(highlighted.at(-1), -1)
  assert.equal(ctx.commandText, 'alias @@test/')
})

test('keyboard can descend from a relative directory into a file and finish without marker', () => {
  const { ctx } = setup('alias @@tes'.length)
  ctx.commandText = 'alias @@tes'
  let query = build(ctx, ctx.commandText)
  let children = normalize(ctx, query, [file('test', true)])
  ctx.setAutocompleteCandidateItems(children, ctx.commandText)
  assert.equal(ctx.previewAutocompleteCandidateByArrowKey('ArrowDown'), true)
  ctx.commitAutocompleteNavigationPreview()
  assert.equal(ctx.commandText, 'alias @@test/')

  query = build(ctx, ctx.commandText)
  children = ctx.filterCommandCompletionCandidates(normalize(ctx, query, [file('test/folder', true)]), query)
  ctx.setAutocompleteCandidateItems(children, ctx.commandText)
  // "Use this directory" occupies the first row; folder is the second.
  ctx.previewAutocompleteCandidateByArrowKey('ArrowDown')
  ctx.previewAutocompleteCandidateByArrowKey('ArrowDown')
  ctx.commitAutocompleteNavigationPreview()
  assert.equal(ctx.commandText, 'alias @@test/folder/')

  query = build(ctx, ctx.commandText)
  children = ctx.filterCommandCompletionCandidates(normalize(ctx, query, [file('test/folder/file.txt')]), query)
  ctx.setAutocompleteCandidateItems(children, ctx.commandText)
  ctx.previewAutocompleteCandidateByArrowKey('ArrowDown')
  ctx.previewAutocompleteCandidateByArrowKey('ArrowDown')
  ctx.commitAutocompleteNavigationPreview()
  assert.equal(ctx.commandText, 'alias test/folder/file.txt')
})

test('remote refresh after third-item right-arrow selection starts next level unhighlighted', async () => {
  const raw = 'alias @@te'
  const { ctx } = setup(raw.length)
  ctx.commandText = raw
  ctx.hasRunningWebTask = false
  ctx.commandCompletionCandidatesByContext = {}
  ctx.commandCompletionCandidatesLoadPromises = {}
  ctx.waitForCommandCompletionDebounce = async () => true
  const autocomplete = ctx.$refs.commandInputRef
  autocomplete.highlightedIndex = -1
  autocomplete.highlight = index => { autocomplete.highlightedIndex = index }
  autocomplete.getData = value => ctx.queryCommandCandidates(value, suggestions => {
    autocomplete.suggestions = suggestions
  })
  sandbox.getCommandCompletions = async (_clientId, payload) => payload.raw_input === 'download '
    ? { items: [file('team', true), file('temp', true), file('test', true)] }
    : { items: [file('test/a.txt'), file('test/folder', true)] }

  await new Promise(resolve => ctx.queryCommandCandidates(raw, () => resolve()))
  ctx.previewAutocompleteCandidateByArrowKey('ArrowDown')
  ctx.previewAutocompleteCandidateByArrowKey('ArrowDown')
  ctx.previewAutocompleteCandidateByArrowKey('ArrowDown')
  assert.equal(ctx.autocompleteNavigationIndex, 2)
  ctx.commitAutocompleteNavigationPreview()
  await new Promise(resolve => setTimeout(resolve, 25))
  assert.equal(ctx.commandText, 'alias @@test/')
  assert.equal(autocomplete.suggestions.length, 3) // current directory, subdirectory and file
  assert.equal(ctx.autocompleteNavigationIndex, -1)
  assert.equal(autocomplete.highlightedIndex, -1)
  ctx.previewAutocompleteCandidateByArrowKey('ArrowDown')
  assert.equal(ctx.autocompleteNavigationIndex, 0)
  assert.equal(ctx.commandText, 'alias test/')
})
