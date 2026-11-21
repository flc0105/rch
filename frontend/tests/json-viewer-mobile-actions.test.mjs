import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import { JSON_ROW_SOURCE, getJsonRenderModel, normalizeJsonView, resolveJsonViewRowActions } from '../src/utils/terminalJson.js'

const source = readFileSync(new URL('../src/components/TerminalJsonDialog.vue', import.meta.url), 'utf8')
const template = source.match(/<template>([\s\S]*?)<\/template>\s*<script>/)?.[1]
const style = source.match(/<style scoped>([\s\S]*?)<\/style>/)?.[1]
assert.ok(template && style)

const column = template.match(/<el-table-column\s+v-if="tableHasActions"([\s\S]*?)<\/el-table-column>/)?.[0]
assert.ok(column, 'Actions table column exists')
test('small screens default to cards and preserve direct actions', () => {
  assert.match(template, /tableViewMode === 'card'/)
  assert.match(template, /terminal-json-cards/)
  assert.match(template, /cardTitle\(row, index\)/)
  assert.match(template, /resultView\.details/)
  assert.match(template, /getTerminalJsonRowActions\(row\)\.slice\(0, 2\)/)
  assert.match(template, /getTerminalJsonRowActions\(row\)\.slice\(2\)/)
  assert.doesNotMatch(template, /Actions \(\{\{/)
  assert.match(source, /matchMedia\?\.\('\(max-width: 768px\)'\)/)
  assert.doesNotMatch(column, /min-width="200"/)
})

test('desktop retains direct actions and More; long labels can wrap', () => {
  assert.match(column, /getTerminalJsonRowActions\(row\)\.slice\(0, 2\)/)
  assert.match(column, /getTerminalJsonRowActions\(row\)\.slice\(2\)/)
  assert.match(column, />More<\/el-button>/)
  assert.match(style, /\.terminal-json-row-actions\s*\{[^}]*flex-wrap:\s*wrap;/)
  assert.match(style, /\.terminal-json-row-actions :deep\(\.el-button\)\s*\{[^}]*overflow-wrap:\s*anywhere;/)
})

test('table horizontal overflow is left to Element Plus and touch scrolling is enabled', () => {
  assert.doesNotMatch(style, /min-width:\s*max-content/)
  assert.match(style, /\.terminal-json-scroll\s*\{[^}]*overflow:\s*auto;/)
  assert.match(style, /\.terminal-json-table-scroll\s*\{[^}]*touch-action:\s*pan-x pan-y;/)
  assert.match(style, /\.terminal-json-table-scroll :deep\(\.el-scrollbar__wrap\)\s*\{[^}]*-webkit-overflow-scrolling:\s*touch;/)
  assert.doesNotMatch(column, /fixed="right"/)
})

test('all four probe actions remain available and retain confirm/refresh when chosen', () => {
  const actions = [
    { label: 'Increment + Refresh', command: 'pyexec 1', confirm: false, refresh: true },
    { label: 'Increment (No Refresh)', command: 'pyexec 2', confirm: false, refresh: false },
    { label: 'Reset + Confirm', command: 'pyexec 3', confirm: true, refresh: true },
    { label: 'Inspect PID', command: 'getpid', confirm: true, refresh: false },
  ]
  const model = getJsonRenderModel(JSON.stringify([{ counter: 0 }]))
  assert.equal(model.mode, 'table')
  const view = normalizeJsonView({ actions }, model.columns)
  const available = resolveJsonViewRowActions(view, model.rows[0][JSON_ROW_SOURCE])
  assert.equal(available.length, 4)
  for (let index = 0; index < actions.length; index++) {
    assert.equal(available[index].label, actions[index].label)
    assert.equal(available[index].command, actions[index].command)
    assert.equal(available[index].confirm, actions[index].confirm)
    assert.equal(available[index].refresh, actions[index].refresh)
  }
})
