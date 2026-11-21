import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import { JSON_ROW_ACTIONS, getJsonRenderModel } from '../src/utils/terminalJson.js'

const source = readFileSync(new URL('../src/components/TerminalJsonDialog.vue', import.meta.url), 'utf8')
const template = source.match(/<template>([\s\S]*?)<\/template>\s*<script>/)?.[1]
const style = source.match(/<style scoped>([\s\S]*?)<\/style>/)?.[1]
assert.ok(template && style)

const column = template.match(/<el-table-column\s+v-if="tableHasActions"([\s\S]*?)<\/el-table-column>/)?.[0]
assert.ok(column, 'Actions table column exists')
const mobile = column.match(/<el-dropdown\s+v-if="getTerminalJsonRowActions\(row\)\.length"([\s\S]*?)<\/el-dropdown>/)?.[0]
assert.ok(mobile, 'a mobile dropdown is available for every actionable row')

test('narrow Actions column exposes every action via one reachable menu', () => {
  assert.match(column, /fixed="right"/)
  assert.match(mobile, /class="terminal-json-row-actions-mobile"/)
  assert.match(mobile, /trigger="click"/)
  assert.match(mobile, /Actions \(\{\{ getTerminalJsonRowActions\(row\)\.length \}\}\)/)
  assert.match(mobile, /v-for="\(action, index\) in getTerminalJsonRowActions\(row\)"/)
  assert.match(mobile, /@command="index => confirmTableAction\(getTerminalJsonRowActions\(row\)\[index\]\)"/)
  assert.doesNotMatch(mobile, /\.slice\(/, 'mobile menu must not hide any actions')
  assert.match(style, /@media \(max-width: 768px\) \{[\s\S]*?\.terminal-json-row-actions-inline\s*\{\s*display:\s*none;/)
  assert.match(style, /@media \(max-width: 768px\) \{[\s\S]*?\.terminal-json-row-actions-mobile\s*\{\s*display:\s*inline-flex;/)
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
  assert.match(style, /:global\(\.terminal-json-actions-popper \.el-dropdown-menu__item\)\s*\{[^}]*overflow-wrap:\s*anywhere;/)
})

test('all four probe actions remain available and retain confirm/refresh when chosen', () => {
  const actions = [
    { label: 'Increment + Refresh', command: 'pyexec 1', confirm: false, refresh: true },
    { label: 'Increment (No Refresh)', command: 'pyexec 2', confirm: false, refresh: false },
    { label: 'Reset + Confirm', command: 'pyexec 3', confirm: true, refresh: true },
    { label: 'Inspect PID', command: 'getpid', confirm: true, refresh: false },
  ]
  const model = getJsonRenderModel(JSON.stringify([{ counter: 0, _actions: actions }]))
  assert.equal(model.mode, 'table')
  const available = model.rows[0][JSON_ROW_ACTIONS]
  assert.equal(available.length, 4)
  for (let index = 0; index < actions.length; index++) {
    assert.equal(available[index].label, actions[index].label)
    assert.equal(available[index].command, actions[index].command)
    assert.equal(available[index].confirm, actions[index].confirm)
    assert.equal(available[index].refresh, actions[index].refresh)
  }
})
