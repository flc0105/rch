import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
const read = name => fs.readFileSync(new URL('../src/components/' + name, import.meta.url), 'utf8')

test('Quick Action result dialog is fullscreen while chooser is unchanged', () => {
  const body = read('QuickActionsDialog.vue')
  assert.match(body, /<el-dialog\s+v-model="resultVisible"[\s\S]*?fullscreen[\s\S]*?>/)
})
test('Script Run in Dialog result is fullscreen without changing main library', () => {
  const body = read('ScriptLibraryDialog.vue')
  assert.match(body, /<el-dialog\s+v-model="resultVisible"[\s\S]*?fullscreen[\s\S]*?>/)
})
test('Info card value viewer and Activity record details are fullscreen', () => {
  assert.match(read('ConnectionInfoDialogs.vue'), /<el-dialog\s+v-model="valueVisible"[\s\S]*?fullscreen/)
  assert.match(read('CommandExecutionDetailDialog.vue'), /<el-dialog\s+[\s\S]*?fullscreen/)
})
test('Job details and messages are fullscreen', () => {
  for (const name of ['BackgroundJobDetailDialog.vue', 'BackgroundJobMessageDialog.vue']) {
    assert.match(read(name), /<el-dialog[\s\S]*?fullscreen/, name)
  }
})
test('Activity Summary prefers completed event text, not last streamed JSON bracket', () => {
  const source = read('CommandHistoryDialog.vue')
  const begin = source.indexOf('buildCommandExecutionSummary(item) {')
  const end = source.indexOf('formatCommandExecutionRecordText(', begin)
  assert.ok(begin >= 0 && end > begin)
  const method = source.slice(begin, end)
  assert.match(method, /find\(event => event\?\.event_type === 'completed'\)/)
  assert.match(method, /String\(completed\.message \|\| ''\)\.trim\(\)/)
  assert.match(method, /text\.length <= 256/)
})
