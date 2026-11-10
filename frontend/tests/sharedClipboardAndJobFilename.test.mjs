import assert from 'node:assert/strict'
import {test} from 'node:test'
import {normalizeServerJobFilename} from '../src/utils/jobFilename.js'
import {copyTextFallback} from '../src/utils/clipboard.js'

test('Server Job filename normalization shared by editor and modules', () => {
  for (const [input, output] of [
    ['', 'new_job.py'], ['  foo  ', 'foo.py'], ['\\Team\\Task.PY', 'Team/Task.PY'],
    ['/a/b.py', 'a/b.py'], ['a/b.json', 'a/b.json.py'],
  ]) assert.equal(normalizeServerJobFilename(input), output)
  assert.equal(normalizeServerJobFilename('', 'blank.py'), 'blank.py')
})

test('clipboard fallback copies text and always removes textarea (success, rejection, exception)', () => {
  const oldDocument = globalThis.document
  const calls = []
  let result = true
  let throws = false
  const textarea = {
    value: '', style: {}, setAttribute() {}, focus() {calls.push('focus')},
    select() {calls.push('select')}, setSelectionRange(start, end) {calls.push([start, end])},
  }
  globalThis.document = {
    createElement() {return textarea},
    body: {appendChild() {calls.push('append')}, removeChild() {calls.push('remove')}},
    execCommand() {if (throws) throw Error('clipboard blocked'); return result},
  }
  try {
    copyTextFallback('a b')
    assert.equal(textarea.value, 'a b')
    assert.deepEqual(calls.at(-1), 'remove')
    result = false
    assert.throws(() => copyTextFallback('again'), /Fallback copy failed/)
    assert.deepEqual(calls.at(-1), 'remove')
    throws = true
    assert.throws(() => copyTextFallback('oops'), /clipboard blocked/)
    assert.deepEqual(calls.at(-1), 'remove')
  } finally {
    globalThis.document = oldDocument
  }
})
