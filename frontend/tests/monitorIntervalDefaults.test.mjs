import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const components = [
  'ConnectionInfoDialogs.vue',
  'ProcessDialogs.vue',
  'LogViewerDialog.vue',
]

test('monitoring views use shared Python defaults rather than passing intervals', () => {
  for (const name of components) {
    const source = readFileSync(new URL(`../src/components/${name}`, import.meta.url), 'utf8')
    assert.doesNotMatch(source, /\bintervals\s*:/, `${name} must not duplicate monitor defaults`)
  }
  const protocol = readFileSync(
    new URL('../../backend/core/protocol/monitor.py', import.meta.url), 'utf8',
  )
  assert.match(protocol, /MONITOR_DEFAULT_INTERVALS\s*=\s*\{/)
})
