import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { isJsonContainerText, findJsonOutput } from '../src/utils/terminalJson.js'

const source = (path) => readFileSync(new URL(path, import.meta.url), 'utf8')
const activityVue = source('../src/components/CommandHistoryDialog.vue')
const mobileCss = source('../src/styles/mobileDialogs.css')
const previewVue = source('../src/components/ExecutionInteractionDialog.vue')
const jsonVue = source('../src/components/TerminalJsonDialog.vue')

// Load the real method from the component rather than reimplementing its algorithm.
const begin = activityVue.indexOf('    buildCommandExecutionSummary(item) {')
const end = activityVue.indexOf('    formatCommandExecutionRecordText(text) {', begin)
assert.ok(begin !== -1 && end > begin)
const method = activityVue.slice(begin, end).trim().replace(/,\s*$/, '')
const buildCommandExecutionSummary = Function(`return ({ ${method} }).buildCommandExecutionSummary`)()

test('Activity summary uses final streamed line, including across records', () => {
  const item = { kind: 'command', status: 'success', result: { output_records: [
    { text: 'first\nsecond' }, { text: 'third\nlast\n\n' }, { text: '\n' },
  ] } }
  assert.equal(buildCommandExecutionSummary.call({ isActivityProblem: () => false }, item), 'last')
  assert.equal(buildCommandExecutionSummary.call({ isActivityProblem: () => false }, { ...item, kind: 'script' }), 'last')
  assert.equal(buildCommandExecutionSummary.call({ isActivityProblem: () => false }, { ...item, kind: 'job' }), 'last')
  assert.equal(buildCommandExecutionSummary.call({ isActivityProblem: () => false }, { kind: 'command', status: 'success', result: { output_records: [] } }), 'Completed')
})

test('Empty array has no View JSON action but remains valid displayed text', () => {
  assert.equal(isJsonContainerText('[]'), false)
  assert.equal(isJsonContainerText(' [  ] '), false)
  assert.equal(findJsonOutput('[]'), null)
  assert.equal(isJsonContainerText('[{"a":1}]'), true)
  assert.equal(isJsonContainerText('{"a":1}'), true)
})

test('Only phone viewports enlarge preview and JSON viewer', () => {
  assert.match(previewVue, /interaction-preview-dialog/)
  assert.match(jsonVue, /terminal-json-dialog/)
  assert.match(mobileCss, /@media\s*\(max-width:\s*768px\)/)
  assert.match(mobileCss, /100dvh\s*!important/)
  assert.match(mobileCss, /interaction-preview-dialog/)
  assert.match(mobileCss, /terminal-json-dialog/)
})
