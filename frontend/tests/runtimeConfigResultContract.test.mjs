import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = readFileSync(new URL('../src/components/ConnectionInfoDialogs.vue', import.meta.url), 'utf8')

test('runtime configuration GET reads the structured result data and retains editor fields', () => {
  assert.match(source, /this\.applyRuntimeConfigPayload\(json\.data\.data\)/)
  assert.match(source, /this\.runtimeConfigItems = Array\.isArray\(data\.items\)/)
})

test('Configuration UI refetches the full GET schema after both mutations', () => {
  const save = source.split('async saveRuntimeConfigEditorItem() {')[1].split('async resetRuntimeConfigEditorItem() {')[0]
  const reset = source.split('async resetRuntimeConfigEditorItem() {')[1].split('</script>')[0]
  for (const section of [save, reset]) {
    assert.match(section, /await this\.loadRuntimeConfig\(this\.selectedId\)/)
    assert.doesNotMatch(section, /this\.applyRuntimeConfigPayload\(json\.data\)/)
  }
})
