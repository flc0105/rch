import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import { mapKeychainPickerValues, normalizeKeychainPicker, normalizeParamSpec } from '../src/utils/parameterSchema.js'

const file = path => readFileSync(new URL(path, import.meta.url), 'utf8')

const loginPasswordParam = normalizeParamSpec({
  name: 'password',
  type: 'password',
  keychain_picker: {
    kind: 'login',
    bindings: { username: 'username', secret_value: 'password' },
  },
})

const secretParam = normalizeParamSpec({
  name: 'api_token',
  type: 'password',
  keychain_picker: { kind: 'secret', bindings: { secret_value: 'api_token' } },
})

test('Keychain Login selection maps username and password as one update object', () => {
  const values = mapKeychainPickerValues(loginPasswordParam, {
    kind: 'login', username: 'demo-user', secret_value: 'demo-password',
  }, [{ name: 'username' }, { name: 'password' }])
  assert.deepEqual(values, { username: 'demo-user', password: 'demo-password' })
})

test('Keychain Secret selection maps only the configured password or token field', () => {
  assert.deepEqual(mapKeychainPickerValues(secretParam, {
    kind: 'secret', secret_value: 'demo-token',
  }, [{ name: 'api_token' }]), { api_token: 'demo-token' })
  assert.equal(mapKeychainPickerValues(secretParam, {
    kind: 'login', secret_value: 'wrong-kind',
  }, [{ name: 'api_token' }]), null)
})

test('invalid picker config hides the affordance and does not partially update fields', () => {
  const invalid = normalizeParamSpec({
    name: 'password', type: 'password',
    keychain_picker: { kind: 'secret', bindings: { username: 'username', secret_value: 'password' } },
  })
  assert.equal(normalizeKeychainPicker(invalid), null)
  assert.equal(mapKeychainPickerValues(invalid, { kind: 'secret', secret_value: 'x' }), null)
})

test('shared password field and all three workflows use the same picker component', () => {
  const field = file('../src/components/ParamFormField.vue')
  assert.match(field, /type === 'password'/)
  assert.match(field, /pick-keychain/)
  assert.match(field, /<Key \/>/)
  assert.match(file('../src/components/KeychainPicker.vue'), /listKeychains\(requestedMachineId\)/)
  assert.match(file('../src/components/KeychainPicker.vue'), /getKeychainCredential\(row\.cred_id\)/)
  assert.doesNotMatch(file('../src/components/KeychainPicker.vue').split('<script>')[0], /secret_value/)
  assert.match(file('../src/components/ScriptLibraryDialog.vue'), /:machine-id="currentConnection\?\.machine_id \|\| ''"/)
  assert.match(file('../src/components/BackgroundJobsDialog.vue'), /:machine-id="currentConnection\?\.machine_id \|\| ''"/)
  assert.match(file('../src/components/ExternalToolManagerDialog.vue'), /:machine-id="selectedTargetMachineId"/)
  for (const path of [
    '../src/components/ScriptRunDialog.vue',
    '../src/components/BackgroundJobStartDialog.vue',
    '../src/components/ExternalToolManagerDialog.vue',
  ]) {
    const source = file(path)
    assert.match(source, /<KeychainPicker/)
    assert.match(source, /@pick-keychain="openKeychainPicker"/)
    assert.match(source, /mapKeychainPickerValues/)
  }
})

test('the selected scope is checked against the machine id before emitting secret values', () => {
  const source = file('../src/components/KeychainPicker.vue')
  assert.match(source, /item\.machine_id !== requestedMachineId/)
  assert.match(source, /item\.kind !== this\.normalizedKind/)
  assert.match(source, /selectSequence/)
  assert.match(source, /async changeScope\(value\) \{\s*this\.selectSequence \+= 1/)
})
