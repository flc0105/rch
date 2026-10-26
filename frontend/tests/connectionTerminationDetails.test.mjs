import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'

const dialog = readFileSync(new URL('../src/components/MachineConnectionHistoryDialog.vue', import.meta.url), 'utf8')

test('Connection History keeps original state tags and Disconnect detail', () => {
  assert.match(dialog, /sessionStatusText\(scope\.row\)/)
  assert.match(dialog, /if \(row\?\.connection_state === 'interrupted'\) return 'interrupted'/)
  assert.match(dialog, /\{\{ scope\.row\.disconnect_reason \|\| '-' \}\}/)
  assert.match(dialog, /<span class="label">Disconnect<\/span>/)
})

test('Connection History renders reason summary and traceback inside expanded details', () => {
  assert.match(dialog, /v-if="scope\.row\.termination_reason"/)
  assert.match(dialog, /formatEndReason\(scope\.row\.termination_reason\)/)
  assert.match(dialog, /scope\.row\.error_diagnostics\.summary/)
  assert.match(dialog, /scope\.row\.error_diagnostics\.traceback/)
  assert.match(dialog, /hasErrorDiagnostics\(scope\.row\)/)
  for (const label of [
    'Server requested disconnect', 'Client exit', 'Client restart', 'Client update',
    'Connection lost', 'Transport error', 'Timeout', 'Unexpected disconnect', 'Client error',
  ]) {
    assert.ok(dialog.includes(label), `missing reason ${label}`)
  }
})

test('normal shutdown has a single cause and no repeated diagnostics', () => {
  assert.match(dialog, /Termination cause/)
  assert.match(dialog, /Error diagnostics/)
  assert.doesNotMatch(dialog, /<span class="label">Details<\/span>/)
  assert.doesNotMatch(dialog, /<span class="label">Reason<\/span>/)
})
