import assert from 'node:assert/strict'
import { test } from 'node:test'
import { readFileSync } from 'node:fs'

const base = new URL('../src/', import.meta.url)
const mobile = readFileSync(new URL('styles/mobileDialogs.css', base), 'utf8')
const preview = readFileSync(new URL('components/PreviewDialog.vue', base), 'utf8')
const terminal = readFileSync(new URL('components/TerminalOutput.vue', base), 'utf8')

test('mobile Job detail scroll owns its full page instead of clipping at a fixed inner body', () => {
  assert.match(mobile, /\.background-job-detail-dialog\.el-dialog > \.el-dialog__body\s*\{[^}]*overflow-y: auto !important/s)
  assert.match(mobile, /\.background-job-detail-dialog \.fixed-dialog-body\s*\{[^}]*height: auto !important;[^}]*overflow: visible !important/s)
})

test('Preview title can shrink without hiding fullscreen or close controls', () => {
  assert.match(preview, /\.preview-dialog-title\s*\{[^}]*min-width: 0;[^}]*text-overflow: ellipsis;[^}]*white-space: nowrap/s)
  assert.match(preview, /class="preview-header-actions"/)
  assert.match(preview, /aria-label="Close"/)
  assert.match(preview, /aria-label="previewFullscreen \? 'Exit Fullscreen' : 'Fullscreen'"/)
})

test('nonsecure mobile copy does not await History before invoking fallback clipboard', () => {
  assert.match(terminal, /window\.isSecureContext === false[\s\S]*?const output = this\.getTerminalToolbarOutput\(format\)[\s\S]*?copyTextFallback\(output\.content\)/)
})
