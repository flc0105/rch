import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'

const component = readFileSync(new URL('../src/components/ConnectionInfoDialogs.vue', import.meta.url), 'utf8')

function computedNumberBound(name, item) {
  const match = component.match(new RegExp(`\\n    ${name}\\(\\) \\{([\\s\\S]*?)\\n    \\},`))
  assert.ok(match, `missing ${name} computed property`)
  const compute = new Function(match[1])
  return compute.call({ runtimeConfigEditorItem: item })
}

const min = item => computedNumberBound('runtimeConfigEditorNumberMin', item)
const max = item => computedNumberBound('runtimeConfigEditorNumberMax', item)

// The server serializes absent min/max metadata as JSON null.
// Element Plus must receive undefined rather than Number(null) = 0.
test('unbounded numeric runtime config does not collapse to zero', () => {
  for (const item of [
    { value: 30, value_type: 'integer', min_value: null, max_value: null },
    { value: 75, value_type: 'integer', min_value: undefined, max_value: undefined },
    { value: 2.5, value_type: 'float', min_value: '', max_value: '' },
  ]) {
    assert.equal(min(item), undefined)
    assert.equal(max(item), undefined)
    const clamped = Math.max(min(item) ?? -Infinity, Math.min(item.value, max(item) ?? Infinity))
    assert.equal(clamped, item.value)
  }
})

test('explicit zero and nonzero numeric limits are preserved', () => {
  assert.equal(min({ min_value: 0 }), 0)
  assert.equal(max({ max_value: 0 }), 0)
  assert.equal(min({ min_value: '10' }), 10)
  assert.equal(max({ max_value: 100 }), 100)
  assert.equal(min({ min_value: 'not-a-number' }), undefined)
  assert.equal(max({ max_value: Infinity }), undefined)
})

test('runtime config number editor binds its input to computed limits', () => {
  assert.match(component, /v-else-if="runtimeConfigEditorItem\.value_type === 'integer'"[\s\S]*?:min="runtimeConfigEditorNumberMin"[\s\S]*?:max="runtimeConfigEditorNumberMax"/)
  assert.match(component, /v-else-if="runtimeConfigEditorItem\.value_type === 'float'"[\s\S]*?:min="runtimeConfigEditorNumberMin"[\s\S]*?:max="runtimeConfigEditorNumberMax"/)
})
