import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const detail = readFileSync(new URL('../src/components/CommandExecutionDetailDialog.vue', import.meta.url), 'utf8')
const sse = readFileSync(new URL('../src/composables/useSseStream.js', import.meta.url), 'utf8')

test('Activity Result viewer opens raw stored events and does not replace Output Records', () => {
  assert.match(detail, /Output Records/)
  assert.match(detail, /entry\.result\?\.result_events\s*\|\|\s*\[\]/)
  assert.match(detail, /openFullValue\('Result',\s*JSON\.stringify\(/)
  assert.match(detail, />\s*Result\s*<\/el-button>/)
  assert.match(detail, /outputSortOrder\s*===\s*'desc'/)
  assert.match(detail, /record\.text/)
})

test('SSE subscriber retains complete result alongside existing terminal text', () => {
  assert.match(sse, /result:\s*item\.result\s*\|\|\s*payload\.result/)
  assert.match(sse, /command_result_batch/)
})
