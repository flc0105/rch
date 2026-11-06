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
  assert.equal(results[0].name, 'different --file docs --other')
})

test('file arrow selection immediately replaces @@ and preserves later arguments', () => {
  const raw = 'alias --file @@ --suffix'
  const { ctx, input } = setup(raw.indexOf('@@') + 2)
  const query = build(ctx, raw)
  const item = normalize(ctx, query, [file('abc.txt')])[0]
  ctx.autocompleteCandidateItems = [item]
  ctx.autocompleteCandidateQueryText = raw
  ctx.commandText = raw
  assert.equal(ctx.previewAutocompleteCandidateByArrowKey('ArrowDown'), true)
  assert.equal(ctx.commandText, 'alias --file abc.txt --suffix')
  assert.equal(input.selectionStart, 'alias --file abc.txt'.length)
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



const typeAtCaret = (ctx, input, value) => {
  const cursor = input.selectionStart
  const nextText = ctx.commandText.slice(0, cursor) + value + ctx.commandText.slice(cursor)
  ctx.handleCommandTextUpdate(nextText)
  input.selectionStart = cursor + value.length
}

test('choosing a directory inserts it without @@ or a slash and is immediately runnable', () => {
  const raw = 'allow_exec @@I'
  const { ctx, input } = setup(raw.length)
  const folder = normalize(ctx, build(ctx, raw), [file('Inbox', true)])[0]
  let requested = 0
  ctx.$refs.commandInputRef.getData = () => { requested++ }
  ctx.applyAutocompleteCandidateToInput(folder)
  assert.equal(ctx.commandText, 'allow_exec Inbox')
  assert.equal(input.selectionStart, 'allow_exec Inbox'.length)
  assert.equal(ctx.parseExplicitPathCompletionQuery(ctx.commandText), null)
  assert.equal(requested, 0)
  assert.equal(ctx.explicitPathContinuation.path, 'Inbox')
  assert.ok(!ctx.commandText.includes('@@'))
})

test('only manually typed slash loads the next level; selecting a file ends completion', () => {
  const raw = 'allow_exec @@I'
  const { ctx, input } = setup(raw.length)
  ctx.applyAutocompleteCandidateToInput(normalize(ctx, build(ctx, raw), [file('Inbox', true)])[0])
  typeAtCaret(ctx, input, '/')
  assert.equal(ctx.commandText, 'allow_exec Inbox/')
  let query = build(ctx, ctx.commandText)
  assert.equal(query.requestInput, 'download Inbox/')
  assert.equal(query.pathPrefix, 'Inbox/')
  const items = ctx.filterCommandCompletionCandidates(normalize(ctx, query, [
    file('Inbox/Nested', true), file('Inbox/a.txt'),
  ]), query)
  assert.deepEqual(Array.from(items, item => item.displayText), ['Inbox/Nested', 'Inbox/a.txt'])
  assert.ok(items.every(item => item.help !== 'Use this directory'))
  ctx.applyAutocompleteCandidateToInput(items[0])
  assert.equal(ctx.commandText, 'allow_exec Inbox/Nested')
  assert.equal(build(ctx, ctx.commandText), null)
  typeAtCaret(ctx, input, '/')
  query = build(ctx, ctx.commandText)
  assert.equal(query.requestInput, 'download Inbox/Nested/')
  ctx.applyAutocompleteCandidateToInput(normalize(ctx, query, [file('Inbox/Nested/next.txt')])[0])
  assert.equal(ctx.commandText, 'allow_exec Inbox/Nested/next.txt')
  assert.equal(ctx.explicitPathContinuation, null)
})

test('manually entering / after selection works for absolute paths and option suffixes', () => {
  const raw = 'myalias --path=@@/Us --verbose'
  const { ctx, input } = setup(raw.indexOf(' --verbose'))
  ctx.applyAutocompleteCandidateToInput(normalize(ctx, build(ctx, raw), [file('/Users', true)])[0])
  assert.equal(ctx.commandText, 'myalias --path=/Users --verbose')
  assert.equal(build(ctx, ctx.commandText), null)
  typeAtCaret(ctx, input, '/')
  let query = build(ctx, ctx.commandText)
  assert.equal(query.requestInput, 'download /Users/')
  typeAtCaret(ctx, input, 'fl')
  query = build(ctx, ctx.commandText)
  assert.equal(query.pathPrefix, '/Users/fl')
  assert.equal(query.requestInput, 'download /Users/')
  ctx.applyAutocompleteCandidateToInput(normalize(ctx, query, [file('/Users/flc', true)])[0])
  assert.equal(ctx.commandText, 'myalias --path=/Users/flc --verbose')
})

test('selection inside quoted option stays inside quotes and can descend with slash', () => {
  const raw = 'alias --path="@@/Users/Fl" --other'
  const { ctx, input } = setup(raw.indexOf('" --other'))
  ctx.applyAutocompleteCandidateToInput(normalize(ctx, build(ctx, raw), [file('/Users/Fl C', true)])[0])
  assert.equal(ctx.commandText, 'alias --path="/Users/Fl C" --other')
  assert.equal(input.selectionStart, 'alias --path="/Users/Fl C'.length)
  typeAtCaret(ctx, input, '/')
  const query = build(ctx, ctx.commandText)
  assert.equal(query.pathPrefix, '/Users/Fl C/')
  assert.equal(query.requestInput, 'download /Users/Fl C/')
  ctx.applyAutocompleteCandidateToInput(normalize(ctx, query, [file('/Users/Fl C/note.txt')])[0])
  assert.equal(ctx.commandText, 'alias --path="/Users/Fl C/note.txt" --other')
})

test('automatically added quotes for a directory with spaces allow manual slash inside', () => {
  const raw = 'alias @@/tmp/my'
  const { ctx, input } = setup(raw.length)
  ctx.applyAutocompleteCandidateToInput(normalize(ctx, build(ctx, raw), [file('/tmp/my folder', true)])[0])
  assert.equal(ctx.commandText, 'alias "/tmp/my folder"')
  assert.equal(input.selectionStart, 'alias "/tmp/my folder'.length)
  typeAtCaret(ctx, input, '/')
  const query = build(ctx, ctx.commandText)
  assert.equal(query.pathPrefix, '/tmp/my folder/')
  ctx.applyAutocompleteCandidateToInput(normalize(ctx, query, [file('/tmp/my folder/a.txt')])[0])
  assert.equal(ctx.commandText, 'alias "/tmp/my folder/a.txt"')
})

test('shell-metacharacter directory prefix decodes before requesting next level', () => {
  const raw = 'alias @@/tmp/pr'
  const { ctx, input } = setup(raw.length)
  ctx.applyAutocompleteCandidateToInput(normalize(ctx, build(ctx, raw), [file('/tmp/price$20', true)])[0])
  assert.equal(ctx.commandText, 'alias "/tmp/price\\$20"')
  typeAtCaret(ctx, input, '/')
  assert.equal(build(ctx, ctx.commandText).requestInput, 'download /tmp/price$20/')
})

test('Windows paths use manually typed backslash to continue into subdirectories', () => {
  const raw = 'alias --file @@C:\\Us'
  const { ctx, input } = setup(raw.length)
  ctx.currentConnection.os_type = 'Windows'
  ctx.applyAutocompleteCandidateToInput(normalize(ctx, build(ctx, raw), [file('C:\\Users', true)])[0])
  assert.equal(ctx.commandText, 'alias --file C:\\Users')
  assert.equal(build(ctx, ctx.commandText), null)
  typeAtCaret(ctx, input, '\\')
  const query = build(ctx, ctx.commandText)
  assert.equal(query.requestInput, 'download C:\\Users\\')
  ctx.applyAutocompleteCandidateToInput(normalize(ctx, query, [file('C:\\Users\\hello.txt')])[0])
  assert.equal(ctx.commandText, 'alias --file C:\\Users\\hello.txt')
})

test('Windows quoted path with spaces is completed without extra trailing slash', () => {
  const raw = 'alias @@C:\\Pro --flag'
  const { ctx, input } = setup(raw.indexOf(' --flag'))
  ctx.currentConnection.os_type = 'Windows'
  ctx.applyAutocompleteCandidateToInput(normalize(ctx, build(ctx, raw), [file('C:\\Program Files', true)])[0])
  assert.equal(ctx.commandText, 'alias "C:\\Program Files" --flag')
  typeAtCaret(ctx, input, '\\')
  assert.equal(build(ctx, ctx.commandText).requestInput, 'download C:\\Program Files\\')
})

test('arrow preview + right arrow commits directory without separator or immediate refresh', () => {
  const raw = 'alias @@te'
  const { ctx, input } = setup(raw.length)
  const highlighted = []
  const autocomplete = ctx.$refs.commandInputRef
  autocomplete.highlight = index => highlighted.push(index)
  let autoRequests = 0
  autocomplete.getData = () => { autoRequests++ }
  ctx.commandText = raw
  ctx.autocompleteCandidateItems = normalize(ctx, build(ctx, raw), [
    file('team', true), file('temp', true), file('test', true),
  ])
  ctx.autocompleteCandidateQueryText = raw
  for (let i = 0; i < 3; i++) ctx.previewAutocompleteCandidateByArrowKey('ArrowDown')
  assert.equal(ctx.commandText, 'alias @@test')
  assert.equal(input.selectionStart, 'alias @@test'.length)
  ctx.commitAutocompleteNavigationPreview()
  assert.equal(ctx.commandText, 'alias test')
  assert.equal(ctx.autocompleteNavigationIndex, -1)
  assert.equal(highlighted.at(-1), -1)
  assert.equal(autoRequests, 0)
  typeAtCaret(ctx, input, '/')
  const query = build(ctx, ctx.commandText)
  assert.equal(query.requestInput, 'download test/')
  ctx.setAutocompleteCandidateItems(normalize(ctx, query, [file('test/folder', true)]), ctx.commandText)
  ctx.previewAutocompleteCandidateByArrowKey('ArrowDown')
  ctx.commitAutocompleteNavigationPreview()
  assert.equal(ctx.commandText, 'alias test/folder')
})

test('cached old directory candidates are discarded after explicit typed slash', async () => {
  const old = 'allow_exec @@I'
  const { ctx, input } = setup(old.length)
  ctx.applyAutocompleteCandidateToInput(normalize(ctx, build(ctx, old), [file('Inbox', true)])[0])
  typeAtCaret(ctx, input, '/')
  ctx.commandText = 'allow_exec Inbox/'
  input.selectionStart = ctx.commandText.length
  ctx.buildCommandCompletionCandidates = async () => [file('Inbox', true)]
  let emitted = false
  await ctx.queryCommandCandidates(old, () => { emitted = true })
  assert.equal(emitted, false)
})

test('continuation does not leak into edited commands or later file selections', () => {
  const raw = 'alias @@do'
  const { ctx, input } = setup(raw.length)
  ctx.applyAutocompleteCandidateToInput(normalize(ctx, build(ctx, raw), [file('docs', true)])[0])
  ctx.commandText = 'alias --other'
  input.selectionStart = ctx.commandText.length
  assert.equal(build(ctx, ctx.commandText), null)
  ctx.commandText = 'alias docs'
  input.selectionStart = ctx.commandText.length
  assert.equal(build(ctx, ctx.commandText), null) // no separator even on restored text
  typeAtCaret(ctx, input, '/')
  const query = build(ctx, ctx.commandText)
  assert.ok(query)
  ctx.applyAutocompleteCandidateToInput(normalize(ctx, query, [file('docs/notes.txt')])[0])
  assert.equal(ctx.explicitPathContinuation, null)
})

test('a real command completion request after manual / uses the remote download provider', async () => {
  const raw = 'allow_exec @@I'
  const { ctx, input } = setup(raw.length)
  ctx.selectedId = 'client-1'
  ctx.hasRunningWebTask = false
  ctx.commandCompletionCandidatesByContext = {}
  ctx.commandCompletionCandidatesLoadPromises = {}
  ctx.waitForCommandCompletionDebounce = async () => true
  ctx.commandText = raw
  const picked = normalize(ctx, build(ctx, raw), [file('Inbox', true)])[0]
  ctx.handleCommandTextUpdate(picked.name)
  ctx.handleCandidateSelect(picked)
  typeAtCaret(ctx, input, '/')
  const calls = []
  sandbox.getCommandCompletions = async (clientId, request) => {
    calls.push([clientId, request.raw_input])
    return { items: [file('Inbox/Nested', true), file('Inbox/aa.txt')] }
  }
  const items = await new Promise(resolve => ctx.queryCommandCandidates(ctx.commandText, resolve))
  assert.deepEqual(calls, [['client-1', 'download Inbox/']])
  assert.deepEqual(Array.from(items, item => item.displayText), ['Inbox/Nested', 'Inbox/aa.txt'])
  assert.ok(items.every(item => !item.name.includes('@@')))
})

test('mouse selection then repeated manual separators reuses new directory context', () => {
  const raw = 'anyalias @@te --other'
  const { ctx, input } = setup(raw.indexOf(' --other'))
  const first = normalize(ctx, build(ctx, raw), [file('test', true)])[0]
  ctx.handleCandidateSelect(first)
  assert.equal(ctx.commandText, 'anyalias test --other')
  assert.equal(build(ctx, ctx.commandText), null)
  typeAtCaret(ctx, input, '/')
  let q = build(ctx, ctx.commandText)
  ctx.handleCandidateSelect(normalize(ctx, q, [file('test/folder', true)])[0])
  assert.equal(ctx.commandText, 'anyalias test/folder --other')
  typeAtCaret(ctx, input, '/')
  q = build(ctx, ctx.commandText)
  ctx.handleCandidateSelect(normalize(ctx, q, [file('test/folder/file.txt')])[0])
  assert.equal(ctx.commandText, 'anyalias test/folder/file.txt --other')
})

test('continuation requires a leading separator and matches its original option context', () => {
  const raw = 'alias --dir=@@do --mode safe'
  const { ctx, input } = setup(raw.indexOf(' --mode'))
  ctx.handleCandidateSelect(normalize(ctx, build(ctx, raw), [file('docs', true)])[0])
  assert.equal(ctx.commandText, 'alias --dir=docs --mode safe')
  ctx.commandText = 'alias --dir=docs/sub --mode altered'
  input.selectionStart = 'alias --dir=docs/sub'.length
  assert.equal(build(ctx, ctx.commandText), null)
  ctx.commandText = 'alias --dir=docs-extra --mode safe'
  input.selectionStart = 'alias --dir=docs-extra'.length
  assert.equal(build(ctx, ctx.commandText), null)
  ctx.commandText = 'alias --dir=docs/sub --mode safe'
  input.selectionStart = 'alias --dir=docs/sub'.length
  assert.equal(build(ctx, ctx.commandText).requestInput, 'download docs/')
})

test('an unrelated direct directory argument is not silently treated as explicit completion', () => {
  const raw = 'myalias @@dir'
  const { ctx, input } = setup(raw.length)
  ctx.handleCandidateSelect(normalize(ctx, build(ctx, raw), [file('directory', true)])[0])
  ctx.commandText = 'myalias different/'
  input.selectionStart = ctx.commandText.length
  assert.equal(build(ctx, ctx.commandText), null)
  ctx.commandText = 'myalias directory/'
  input.selectionStart = ctx.commandText.length
  assert.equal(build(ctx, ctx.commandText).requestInput, 'download directory/')
})

test('standard cd directory selection still returns the directory without a trailing slash', () => {
  const { ctx } = setup(0)
  const query = {
    fileSystemProxyCommand: 'cd',
    fileSystemTargetCommand: 'cd',
  }
  const selected = ctx.normalizeFileSystemCompletionCandidate(file('docs', true), query)
  assert.equal(selected.name, 'cd docs')
})

test('editing away from the selected directory expires the continuation context', () => {
  const raw = 'alias @@do'
  const { ctx, input } = setup(raw.length)
  ctx.handleCandidateSelect(normalize(ctx, build(ctx, raw), [file('docs', true)])[0])
  assert.ok(ctx.explicitPathContinuation)
  ctx.handleCommandTextUpdate('alias something-else')
  assert.equal(ctx.explicitPathContinuation, null)
  ctx.handleCommandTextUpdate('alias docs/')
  input.selectionStart = ctx.commandText.length
  assert.equal(build(ctx, ctx.commandText), null)
})

test('switching the selected remote client resets pending path continuation', () => {
  const raw = 'alias @@do'
  const { ctx } = setup(raw.length)
  ctx.handleCandidateSelect(normalize(ctx, build(ctx, raw), [file('docs', true)])[0])
  assert.ok(ctx.explicitPathContinuation)
  ctx.clearCommandCompletionCandidateCache = () => {}
  ctx.reloadCommandCandidates = () => {}
  sandbox.component.watch.selectedId.handler.call(ctx, 'client-2', 'client-1')
  assert.equal(ctx.explicitPathContinuation, null)
})


test('ls @@Desk keeps marker while navigating, slash opens Desktop children, right arrow alone commits', () => {
  const raw = 'ls @@Desk'
  const { ctx, input } = setup(raw.length)
  const candidates = normalize(ctx, build(ctx, raw), [file('Desktop', true)])
  ctx.commandText = raw
  ctx.autocompleteCandidateItems = candidates
  ctx.autocompleteCandidateQueryText = raw
  const key = (name) => {
    const event = { key: name, prevented: false, stopped: false,
      preventDefault() { this.prevented = true }, stopPropagation() { this.stopped = true } }
    ctx.handleCommandInputKeydown(event)
    return event
  }

  assert.equal(key('ArrowDown').prevented, true)
  assert.equal(ctx.commandText, 'ls @@Desktop')
  assert.equal(input.selectionStart, 'ls @@Desktop'.length)
  assert.equal(build(ctx, ctx.commandText).pathPrefix, 'Desk') // preview uses original query until edited

  // Typing / edits the previewed path rather than confirming it; @@ remains.
  typeAtCaret(ctx, input, '/')
  assert.equal(ctx.commandText, 'ls @@Desktop/')
  assert.equal(ctx.autocompleteNavigationPreviewActive, false)
  const nextQuery = build(ctx, ctx.commandText)
  assert.equal(nextQuery.requestInput, 'download Desktop/')
  const nextItems = normalize(ctx, nextQuery, [file('Desktop/Documents', true), file('Desktop/note.txt')])
  ctx.autocompleteCandidateItems = nextItems
  ctx.autocompleteCandidateQueryText = ctx.commandText
  assert.equal(key('ArrowDown').prevented, true)
  assert.equal(ctx.commandText, 'ls @@Desktop/Documents')
  assert.equal(input.selectionStart, 'ls @@Desktop/Documents'.length)
  assert.equal(key('ArrowRight').prevented, true)
  assert.equal(ctx.commandText, 'ls Desktop/Documents')
  assert.equal(input.selectionStart, 'ls Desktop/Documents'.length)
  assert.equal(ctx.explicitPathContinuation.path, 'Desktop/Documents')
})

test('file paths commit on arrow selection while directories alone preserve @@', () => {
  const raw = 'allow_exec @@a'
  const { ctx, input } = setup(raw.length)
  const choices = normalize(ctx, build(ctx, raw), [
    file('assets', true), file('archive.txt'),
  ])
  ctx.commandText = raw
  ctx.autocompleteCandidateItems = choices
  ctx.autocompleteCandidateQueryText = raw

  assert.equal(ctx.previewAutocompleteCandidateByArrowKey('ArrowDown'), true)
  assert.equal(ctx.commandText, 'allow_exec @@assets')
  assert.equal(input.selectionStart, 'allow_exec @@assets'.length)

  assert.equal(ctx.previewAutocompleteCandidateByArrowKey('ArrowDown'), true)
  assert.equal(ctx.commandText, 'allow_exec archive.txt')
  assert.equal(input.selectionStart, 'allow_exec archive.txt'.length)
  assert.equal(ctx.explicitPathContinuation ?? null, null)
  ctx.commitAutocompleteNavigationPreview()
  assert.equal(ctx.commandText, 'allow_exec archive.txt')
})

test('quoted file path chosen by keyboard or mouse commits directly, leaving other args intact', () => {
  const raw = 'custom --path=@@/Users/Fl --other'
  const candidatePath = '/Users/Fl C/notes.txt'
  const caret = raw.indexOf(' --other')
  const { ctx, input } = setup(caret)
  const [candidate] = normalize(ctx, build(ctx, raw), [file(candidatePath)])
  ctx.commandText = raw
  ctx.autocompleteCandidateItems = [candidate]
  ctx.autocompleteCandidateQueryText = raw
  assert.equal(ctx.previewAutocompleteCandidateByArrowKey('ArrowDown'), true)
  assert.equal(ctx.commandText, 'custom --path="/Users/Fl C/notes.txt" --other')
  assert.equal(input.selectionStart, 'custom --path="/Users/Fl C/notes.txt"'.length)
  assert.equal(ctx.explicitPathContinuation ?? null, null)

  const second = setup(caret)
  const [item] = normalize(second.ctx, build(second.ctx, raw), [file(candidatePath)])
  second.ctx.commandText = raw
  second.ctx.handleCandidateSelect(item)
  assert.equal(second.ctx.commandText, 'custom --path="/Users/Fl C/notes.txt" --other')
  assert.equal(second.ctx.explicitPathContinuation, null)
})

test('right-arrow confirmation and mouse selection remove @@ but passive arrow preview does not', () => {
  const raw = 'ls @@Desk'
  const { ctx } = setup(raw.length)
  const [candidate] = normalize(ctx, build(ctx, raw), [file('Desktop', true)])
  ctx.commandText = raw
  ctx.autocompleteCandidateItems = [candidate]
  ctx.autocompleteCandidateQueryText = raw
  ctx.previewAutocompleteCandidateByArrowKey('ArrowDown')
  assert.equal(ctx.commandText, 'ls @@Desktop')
  ctx.commitAutocompleteNavigationPreview()
  assert.equal(ctx.commandText, 'ls Desktop')

  const second = setup(raw.length)
  const [item] = normalize(second.ctx, build(second.ctx, raw), [file('Desktop', true)])
  second.ctx.commandText = raw
  second.ctx.handleCandidateSelect(item)
  assert.equal(second.ctx.commandText, 'ls Desktop')
})

test('previewing quoted and middle-of-command directories preserves marker and caret', () => {
  for (const [raw, candidatePath, expectedPreview, expectedFinal] of [
    ['myalias --path=@@/Users/Fl --verbose', '/Users/Fl C', 'myalias --path="@@/Users/Fl C" --verbose', 'myalias --path="/Users/Fl C" --verbose'],
    ['myalias --path="@@/Users/Fl" --verbose', '/Users/Fl C', 'myalias --path="@@/Users/Fl C" --verbose', 'myalias --path="/Users/Fl C" --verbose'],
  ]) {
    const pos = raw.indexOf(' --verbose') - (raw.includes('"@@') ? 1 : 0)
    const { ctx, input } = setup(pos)
    const [item] = normalize(ctx, build(ctx, raw), [file(candidatePath, true)])
    ctx.commandText = raw
    ctx.autocompleteCandidateItems = [item]
    ctx.autocompleteCandidateQueryText = raw
    ctx.previewAutocompleteCandidateByArrowKey('ArrowDown')
    assert.equal(ctx.commandText, expectedPreview)
    const caret = input.selectionStart
    assert.equal(expectedPreview[caret], '"')
    typeAtCaret(ctx, input, '/')
    assert.match(ctx.commandText, /@@\/Users\/Fl C\//)
    assert.equal(build(ctx, ctx.commandText).requestInput, 'download /Users/Fl C/')
    // Commit via fresh candidate after restoring the original list, not by slash typing.
    const again = setup(pos)
    const [fresh] = normalize(again.ctx, build(again.ctx, raw), [file(candidatePath, true)])
    again.ctx.commandText = raw
    again.ctx.handleCandidateSelect(fresh)
    assert.equal(again.ctx.commandText, expectedFinal)
  }
})

test('Windows preview retains @@ until commit and backslash can descend', () => {
  const raw = 'cmd --file @@C:\\Us --flag'
  const { ctx, input } = setup(raw.indexOf(' --flag'))
  ctx.currentConnection.os_type = 'Windows'
  const [item] = normalize(ctx, build(ctx, raw), [file('C:\\Users', true)])
  ctx.commandText = raw
  ctx.autocompleteCandidateItems = [item]
  ctx.autocompleteCandidateQueryText = raw
  ctx.previewAutocompleteCandidateByArrowKey('ArrowDown')
  assert.equal(ctx.commandText, 'cmd --file @@C:\\Users --flag')
  typeAtCaret(ctx, input, '\\')
  assert.equal(ctx.commandText, 'cmd --file @@C:\\Users\\ --flag')
  assert.equal(build(ctx, ctx.commandText).requestInput, 'download C:\\Users\\')
})

test('arrow-preview + typed / refreshes actual next-level remote candidates rather than the old list', async () => {
  const raw = 'ls @@Desk'
  const { ctx, input } = setup(raw.length)
  ctx.commandText = raw
  ctx.autocompleteCandidateItems = normalize(ctx, build(ctx, raw), [file('Desktop', true)])
  ctx.autocompleteCandidateQueryText = raw
  ctx.commandCompletionCandidatesByContext = {}
  ctx.commandCompletionCandidatesLoadPromises = {}
  ctx.waitForCommandCompletionDebounce = async () => true
  ctx.previewAutocompleteCandidateByArrowKey('ArrowDown')
  assert.equal(ctx.commandText, 'ls @@Desktop')
  typeAtCaret(ctx, input, '/')
  const requests = []
  sandbox.getCommandCompletions = async (clientId, params) => {
    requests.push([clientId, params.raw_input])
    return { items: [file('Desktop/notes.txt'), file('Desktop/Projects', true)] }
  }
  const returned = await new Promise(resolve => ctx.queryCommandCandidates(ctx.commandText, resolve))
  assert.deepEqual(requests, [['device-1', 'download Desktop/']])
  assert.deepEqual(Array.from(returned, item => item.displayText), ['Desktop/notes.txt', 'Desktop/Projects'])
  assert.equal(returned[0].previewName, 'ls Desktop/notes.txt')
  assert.equal(returned[0].name, 'ls Desktop/notes.txt')
})
