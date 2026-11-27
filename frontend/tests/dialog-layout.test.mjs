import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
const read = path => readFileSync(new URL(path, import.meta.url), 'utf8')
const cleanup = read('../src/components/ServerCleanupDialog.vue')
const mobile = read('../src/styles/mobileDialogs.css')

test('cleanup has fixed desktop and mobile frames, with independently scrolling tab contents', () => {
  assert.match(cleanup, /class="fixed-dialog server-cleanup-dialog"/)
  assert.match(cleanup, /\.server-cleanup-dialog\.el-dialog\s*\{\s*height:min\(760px, 86dvh\)/)
  assert.match(cleanup, /\.cleanup-scroll\s*\{[^}]*flex:1 1 auto[^}]*min-height:0[^}]*overflow-y:auto/s)
  assert.match(cleanup, /\.server-cleanup-dialog \.cleanup-tabs > \.el-tabs__content\s*\{[^}]*flex:1 1 0[^}]*min-height:0[^}]*overflow:hidden/s)
  assert.match(mobile, /\.server-cleanup-dialog\)\.el-dialog\s*\{[^}]*height: 100dvh !important/s)
  assert.match(cleanup, /<template #footer>\s*<div class="cleanup-footer">/)
})
test('cleanup keeps empty, loading, error, result and policy states in the same frame', () => {
  assert.match(cleanup, /ref="manualScroll" class="cleanup-scroll" v-loading="loading"/)
  assert.match(cleanup, /No matching items\./)
  assert.match(cleanup, /class="cleanup-empty-inline cleanup-empty-notice"/)
  assert.match(cleanup, /<el-empty[^>]+description="No eligible items\."/)
  assert.match(cleanup, /<el-empty description="Refresh the cleanup scan to load settings\."/)
  assert.match(cleanup, /if \(manualScroll\.value\) manualScroll\.value\.scrollTop = 0/)
  assert.match(cleanup, /run\.total \? Math\.round\(run\.processed \* 100 \/ run\.total\) : 0/)
})
test('cleanup owns its flex shell even without the common stylesheet and bounds the tab grid', () => {
  assert.match(cleanup, /align-center append-to-body/)
  assert.match(cleanup, /\.server-cleanup-dialog\.el-dialog\s*\{[^}]*display:flex[^}]*flex-direction:column[^}]*overflow:hidden/s)
  assert.match(cleanup, /\.server-cleanup-dialog\.el-dialog > \.el-dialog__body\s*\{[^}]*flex:1 1 0[^}]*min-height:0[^}]*overflow:hidden/s)
  assert.match(cleanup, /\.cleanup-pane\s*\{[^}]*grid-template-rows:auto minmax\(0,1fr\)/s)
  assert.match(cleanup, /\.cleanup-overview\s*\{[^}]*min-height:0[^}]*padding:7px 10px/s)
})
