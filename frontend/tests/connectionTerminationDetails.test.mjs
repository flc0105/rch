import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'

const dialog = readFileSync(new URL('../src/components/MachineConnectionHistoryDialog.vue', import.meta.url), 'utf8')

test('Connection History preserves State, but removes redundant Disconnect detail', () => {
  assert.match(dialog, /sessionStatusText\(scope\.row\)/)
  assert.match(dialog, /if \(row\?\.connection_state === 'interrupted'\) return 'interrupted'/)
  assert.doesNotMatch(dialog, /disconnect_reason|<span class="label">Disconnect<\/span>/)
})

test('Connection History combines existing cause and optional details into Termination', () => {
  assert.match(dialog, /scope\.row\.termination_reason \|\| hasTerminationDetail\(scope\.row\)/)
  assert.match(dialog, /formatEndReason\(scope\.row\.termination_reason\)/)
  assert.match(dialog, /terminationDetailText\(scope\.row\)/)
  assert.match(dialog, /scope\.row\.termination_detail\.traceback/)
  assert.match(dialog, /<span class="label">Termination<\/span>/)
  assert.doesNotMatch(dialog, /Termination cause|Termination details/)
  for (const label of [
    'Server requested disconnect', 'Client exit', 'Client restart', 'Client update',
    'Client paused', 'Connection lost', 'Transport error', 'Timeout', 'Unexpected disconnect', 'Client error',
  ]) {
    assert.ok(dialog.includes(label), `missing reason ${label}`)
  }
})

