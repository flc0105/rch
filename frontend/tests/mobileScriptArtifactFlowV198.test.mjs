import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
const read = file => readFileSync(new URL(`../src/components/${file}.vue`, import.meta.url), 'utf8')
const script = read('ScriptLibraryDialog')
const artifact = read('ArtifactDialog')
const events = readFileSync(new URL('../src/composables/useSseStream.js', import.meta.url), 'utf8')

test('mobile-only tree heights are equal and content moves in dialog scroll', () => {
  for (const [source, cssPrefix] of [[script, 'script-library-overlay'], [artifact, 'artifact-overlay']]) {
    const scoped = source.match(/<style>\s*@media \(max-width: 640px\) \{([\s\S]*?)<\/style>/)?.[1]
    assert.ok(scoped, `missing mobile-only overrides for ${cssPrefix}`)
    assert.match(scoped, new RegExp(`\\.${cssPrefix} \\.el-dialog__body \\{[^}]*overflow-y: auto !important;`, 's'))
    assert.match(scoped, /height: 226px !important;/)
    assert.match(scoped, /overflow: visible !important;/)
  }
  assert.ok(script.includes('getDefaultScriptDirectory()'))
  assert.ok(!script.includes('getPreferredScriptDirectoryForCurrentConnection()'))
})

test('Script platform availability checks metadata, never path', () => {
  const check = script.match(/    isScriptSupportedForCurrentConnection\(item\) \{([\s\S]*?)\n    \},/)?.[1]
  assert.ok(check)
  assert.match(check, /metadata\.platforms/)
  assert.doesNotMatch(check, /script_name|\.path|directory/)
})

test('realtime interruption is visible once, recovery is visible', () => {
  assert.match(events, /sseDisconnected: false/)
  assert.match(events, /if \(this\.sseDisconnected\) return;/)
  assert.match(events, /title: 'Realtime connection interrupted'/)
  assert.match(events, /title: 'Realtime connected'/)
})
