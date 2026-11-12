import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'

const source = readFileSync(new URL('../src/components/ConnectionInfoDialogs.vue', import.meta.url), 'utf8')

test('Basic Info shows chassis type from the selected connection with unknown fallback', () => {
  assert.match(source, /\{ label: 'Chassis Type', value: conn\.chassis_type \|\| 'unknown' \}/)
  assert.match(source, /\{ label: 'Model', value: conn\.model \}/)
})
