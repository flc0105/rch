import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import {
  isParamDisabled,
  isParamVisible,
  matchesParamCondition,
  normalizeParamControl,
  normalizeParamSpec,
} from '../src/utils/parameterSchema.js'

const file = path => readFileSync(new URL(path, import.meta.url), 'utf8')

test('button_group stays a select presentation extension', () => {
  const param = normalizeParamSpec({
    name: 'action',
    type: 'select',
    control: 'button_group',
    options: ['start', 'stop'],
    default: 'start',
  })
  assert.equal(param.type, 'select')
  assert.equal(normalizeParamControl(param.control), 'button_group')
  assert.deepEqual(param.options, ['start', 'stop'])

  const source = file('../src/components/ParamFormField.vue')
  assert.match(source, /type === 'select' && control === 'button_group'/)
  assert.match(source, /<el-radio-group[\s\S]*?<el-radio-button/)
  assert.match(source, /<el-select[\s\S]*?v-else-if="type === 'select'"/)
})

test('param conditions support scalar equality, array membership, and AND across fields', () => {
  const values = { kind: 'agent', action: 'install', enabled: true }
  assert.equal(matchesParamCondition({ kind: 'agent' }, values), true)
  assert.equal(matchesParamCondition({ action: ['start', 'install'] }, values), true)
  assert.equal(matchesParamCondition({ kind: 'agent', action: ['install', 'status'] }, values), true)
  assert.equal(matchesParamCondition({ kind: 'daemon', action: 'install' }, values), false)
  assert.equal(matchesParamCondition({ enabled: false }, values), false)
  assert.equal(matchesParamCondition('action == install', values), false)
})

test('visible_when and disabled_when use safe defaults and keep separate semantics', () => {
  const values = { kind: 'agent', action: 'status' }
  assert.equal(isParamVisible({ name: 'plain' }, values), true)
  assert.equal(isParamDisabled({ name: 'plain' }, values), false)
  assert.equal(isParamVisible({ visible_when: { kind: 'agent' } }, values), true)
  assert.equal(isParamVisible({ visible_when: { kind: 'daemon' } }, values), false)
  assert.equal(isParamDisabled({ disabled_when: { action: ['status', 'uninstall'] } }, values), true)
  assert.equal(isParamDisabled({ disabled_when: { action: 'install' } }, values), false)
  assert.equal(isParamVisible({ visible_when: {} }, values), true)
  assert.equal(isParamDisabled({ disabled_when: {} }, values), false)
})

test('all shared parameter form consumers provide current form values', () => {
  for (const path of [
    '../src/components/ScriptRunDialog.vue',
    '../src/components/BackgroundJobStartDialog.vue',
    '../src/components/ExternalToolManagerDialog.vue',
  ]) {
    assert.match(file(path), /<ParamFormField[\s\S]*?:form-values="paramForm"/)
  }

  const field = file('../src/components/ParamFormField.vue')
  assert.match(field, /v-if="isVisible"/)
  assert.match(field, /:disabled="isDisabled"/)
})

test('shared parameter field keeps descriptions below controls and restores button-group leading border', () => {
  const source = file('../src/components/ParamFormField.vue')
  assert.match(source, /\.param-form-field :deep\(\.el-form-item__content\)\s*\{[\s\S]*?display:\s*block;/)
  assert.match(source, /\.param-form-hint\s*\{[\s\S]*?width:\s*100%;[\s\S]*?color:\s*var\(--el-text-color-secondary\);[\s\S]*?font-size:\s*0\.9em;/)
  assert.match(source, /\.param-form-button-group :deep\(\.el-radio-button:first-child \.el-radio-button__inner\)\s*\{[\s\S]*?border-left:\s*1px solid var\(--el-border-color\);/)
  assert.match(source, /\.param-form-button-group :deep\(\.el-radio-button:first-child\.is-active \.el-radio-button__inner\)\s*\{[\s\S]*?border-left-color:\s*var\(--el-color-primary\);/)
})

