import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = readFileSync(new URL('../src/components/ExternalToolManagerDialog.vue', import.meta.url), 'utf8')

test('external tools get architecture only from canonical connection arch', () => {
  assert.match(source, /currentClientArch\(\)\s*\{\s*return this\.normalizeArch\(this\.currentConnection\?\.arch \|\| ''\)/)
  assert.match(source, /getArchForMachineId\(machineId\)[\s\S]*?return this\.normalizeArch\(conn\?\.arch \|\| ''\)/)
  assert.match(source, /getArchForConnectionId\(deviceId\)[\s\S]*?return this\.normalizeArch\(conn\?\.arch \|\| ''\)/)
  for (const obsolete of ['cpu_arch', 'machine_arch', 'conn?.architecture']) {
    assert.equal(source.includes(obsolete), false, `unexpected alias: ${obsolete}`)
  }
})
