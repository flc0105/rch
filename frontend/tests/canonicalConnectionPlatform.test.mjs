import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'

function readComponent(name) {
  return readFileSync(new URL(`../src/components/${name}.vue`, import.meta.url), 'utf8')
}

function componentMethod(componentName, name, params = '') {
  const source = readComponent(componentName)
  const escaped = params.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const match = source.match(new RegExp(`\\n\\s{4}${name}\\(${escaped}\\) \\{([\\s\\S]*?)\\n\\s{4}\\},`))
  assert.ok(match, `${componentName}.${name} method not found`)
  return new Function(...params.split(',').map(part => part.trim()).filter(Boolean), match[1])
}

for (const [component, getter] of [
  ['TerminalToolbar', 'toolboxCurrentPlatform'],
  ['BackgroundJobsDialog', 'resolveCurrentConnectionPlatform'],
  ['ScriptLibraryDialog', 'resolveCurrentConnectionPlatform'],
  ['ExternalToolManagerDialog', 'currentClientPlatform'],
]) {
  test(`${component} consumes connection os_alias instead of guessing from display fields`, () => {
    const resolve = componentMethod(component, getter)
    assert.equal(resolve.call({ currentConnection: { os_alias: 'mac', os_type: 'Windows', os_name: 'Linux' } }), 'mac')
    assert.equal(resolve.call({ currentConnection: { os_alias: 'win', os_type: 'macOS' } }), 'win')
    assert.equal(resolve.call({ currentConnection: { os_type: 'Windows', os_name: 'Linux', platform: 'win' } }), '')
    assert.equal(resolve.call({ currentConnection: null }), '')
  })
}

test('script directory preference follows canonical connection platform', () => {
  const resolve = componentMethod('ScriptLibraryDialog', 'resolvePreferredScriptDirectoryPlatform')
  assert.equal(resolve.call({ currentConnectionPlatform: 'ios', currentConnection: { os_type: 'Windows' } }), 'ios')
  assert.equal(resolve.call({ currentConnectionPlatform: '', currentConnection: { os_name: 'macOS' } }), '')
})

for (const [methodName, argName] of [
  ['getPlatformForConnectionId', 'deviceId'],
  ['getPlatformForMachineId', 'machineId'],
]) {
  test(`external tool ${methodName} uses os_alias for its selected target`, () => {
    const resolve = componentMethod('ExternalToolManagerDialog', methodName, argName)
    const context = {
      currentConnection: { os_alias: 'linux', os_type: 'Windows' },
      currentMachineId: 'machine-1', currentDeviceId: 'device-1',
      normalizeDeviceId: value => value,
      normalizeMachineId: value => value,
      findConnectionById: () => ({ os_alias: 'win', os_type: 'macOS' }),
      findConnectionByMachineId: () => ({ os_alias: 'mac', os_type: 'Windows' }),
    }
    assert.equal(resolve.call(context, '1'), methodName.includes('Machine') ? 'mac' : 'win')
    context.findConnectionByMachineId = () => ({ os_type: 'Windows' })
    context.findConnectionById = () => ({ os_name: 'macOS' })
    assert.equal(resolve.call(context, '1'), '')
  })
}
