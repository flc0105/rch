import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'

const read = path => fs.readFileSync(new URL(path, import.meta.url), 'utf8')

// These tests protect the main mobile feature entry points, not Element Plus internals.
test('Toolbox paginates into a visible 3 x 4 mobile grid and remains desktop 24 per page', () => {
  const src = read('../src/components/ToolboxDialog.vue')
  assert.match(src, /pageSize\(\)\s*\{\s*return this\.mobilePage \? 12 : 24/)
  assert.match(src, /grid-template-columns:\s*repeat\(3, minmax\(0, 1fr\)\)/)
  assert.match(src, /grid-template-rows:\s*repeat\(4, minmax\(0, 1fr\)\)/)
  assert.match(src, /this\.filteredActions\.slice\(start, start \+ this\.pageSize\)/)
})

test('Quick Actions uses a full mobile card view without removing Run/Edit/Delete/Terminal actions', () => {
  const src = read('../src/components/QuickActionsDialog.vue')
  assert.match(src, /class="quick-actions-mobile-list"/)
  assert.match(src, /v-for="row in filteredItems"[^>]*class="quick-actions-mobile-card"/)
  assert.match(src, /requestRun\(row, 'dialog'\)/)
  assert.match(src, /handleRunCommand\(row, command\)/)
  assert.match(src, /openEditDialog\(row\)/)
  assert.match(src, /deleteItem\(row\)/)
  assert.match(src, /@media \(max-width: 768px\)/)
  assert.match(src, /\.quick-actions-table-shell \{ display: none; \}/)
})

test('Documents stacks files and editor on phones; markdown preview has nonzero flex space', () => {
  const src = read('../src/components/DocumentsDialog.vue')
  assert.match(src, /\.documents-dialog \.documents-layout[\s\S]*?flex-direction: column/)
  assert.match(src, /\.documents-dialog \.documents-sidebar \{ flex: 0 0 min\(28dvh, 210px\)/)
  assert.match(src, /\.documents-dialog \.documents-split \{[^}]*grid-template-rows:\s*minmax\(0, 1fr\) minmax\(0, 1fr\)/)
  assert.match(src, /@media \(max-width: 768px\)/)
  assert.match(src, /<article v-if="editing && livePreviewEnabled"/)
})

test('Quick History mobile cards retain full height and actions without horizontal overflow; Activity detail stays full-screen on phones', () => {
  const history = read('../src/components/CommandHistoryDialog.vue')
  assert.match(history, /\.quick-history-mobile-shell \.mobile-file-grid \{[^}]*display: flex;[^}]*flex-direction: column;[^}]*overflow-x: hidden;[^}]*overflow-y: auto;/s)
  assert.match(history, /\.quick-history-mobile-shell \.quick-history-card \{[^}]*flex: 0 0 auto;[^}]*height: auto;[^}]*overflow: visible;/s)
  assert.match(history, /\.quick-history-mobile-shell \.quick-command-label \.ellipsis \{[^}]*white-space: pre-wrap;[^}]*overflow-wrap: anywhere;/s)
  assert.doesNotMatch(history, /\.command-history-overlay \.quick-history-mobile-shell \.mobile-file-card \{[^}]*overflow: hidden;/s)
  const cards = history.match(/class="mobile-file-card quick-history-card"[\s\S]*?<\/el-tab-pane>/)?.[0]
  assert.ok(cards, 'mobile Quick History cards stay in their own list')
  for (const action of ['applyHistoryCommand(row)', 'toggleCommandHistoryPinned(row)', 'moveCommandHistoryPinned(row, \'up\')', 'moveCommandHistoryPinned(row, \'down\')']) {
    assert.ok(cards.includes(action), `mobile card must keep ${action}`)
  }
  const css = read('../src/styles/mobileDialogs.css')
  assert.match(css, /@media \(max-width: 768px\)/)
  for (const cls of ['command-execution-detail-dialog', 'connection-info-dialog', 'agent-builder-dialog', 'agent-outputs-dialog', 'quick-actions-dialog', 'one-liners-dialog', 'script-library-dialog', 'documents-dialog', 'toolbox-dialog', 'remote-files-dialog', 'background-jobs-dialog']) {
    assert.ok(css.includes('.' + cls), cls)
  }
  assert.doesNotMatch(css, /\.execution-interaction/)
  assert.doesNotMatch(css, /\.el-message-box/)
  assert.doesNotMatch(css, /\.drag-upload-dialog/)
  assert.match(read('../src/App.vue'), /import '\.\/styles\/mobileDialogs\.css'/)
})
