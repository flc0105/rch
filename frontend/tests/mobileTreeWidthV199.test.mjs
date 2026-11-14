import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const read = name => readFileSync(new URL(`../src/components/${name}.vue`, import.meta.url), 'utf8')
const mobile = source => source.match(/<style>\s*@media \(max-width: 640px\) \{([\s\S]*?)<\/style>\s*$/)?.[1]

test('Script tree keeps the original single-column grid and mobile page scrolling', () => {
  const content = read('ScriptLibraryDialog')
  const css = mobile(content)
  assert.ok(css)
  assert.match(css, /grid-template-columns: minmax\(0, 1fr\)/)
  assert.match(css, /grid-template-rows: 226px auto/)
  assert.doesNotMatch(css, /display: flex !important;\s*flex-direction: column !important/)
  assert.match(css, /\.script-library-overlay \.el-dialog__body \{[^}]*overflow-y: auto/)
  assert.match(css, /\.script-library-overlay \.script-library-tree \{[^}]*height: 226px/)
  assert.match(css, /\.script-library-overlay \.script-library-directory \{[^}]*min-width: 0/)
})

test('Artifact tree scrolls with the page without stretching the file list horizontally', () => {
  const content = read('ArtifactDialog')
  const css = mobile(content)
  assert.ok(css)
  assert.match(css, /\.artifact-overlay \.el-dialog__body \{[^}]*overflow-y: auto/)
  assert.match(css, /\.artifact-overlay \.artifact-folder-sidebar \{[^}]*height: 226px/)
  assert.match(css, /\.artifact-overlay \.artifact-main-panel \{[^}]*min-width: 0/)
  assert.doesNotMatch(css, /\.artifact-overlay \.mobile-file-list-shell,[\s\S]*?flex: 0 0 auto !important/)
  assert.match(content, /\.artifact-main-panel \{[\s\S]*?flex: 1 1 0;/)
})
