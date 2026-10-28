import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import { test } from 'node:test'

const source = readFileSync(new URL('../src/components/IosDashboardPanel.vue', import.meta.url), 'utf8')
const script = source.match(/<script>([\s\S]*?)<\/script>/)?.[1]
const context = {}
vm.runInNewContext(script.replace('export default {', 'const component = {') + '\nglobalThis.component = component', context)

test('iOS Dashboard status badge follows desktop layout and uses 5 s channel cadence', () => {
  assert.doesNotMatch(source, /5 s refresh/)
  assert.match(source, /ios-dashboard-live-badge/)
  assert.match(source, /\{\{ updatedText \}\}/)
  const options = context.component
  const live = { status: 'live', error: '', intervalMs: 5000 }
  live.displayState = options.computed.displayState.call(live)
  assert.equal(options.computed.displayLabel.call(live), 'LIVE · 5 s')
  live.intervalMs = 500
  assert.equal(options.computed.displayLabel.call(live), 'LIVE · 500 ms')
  const failed = { status: 'live', error: 'monitor failed' }
  failed.displayState = options.computed.displayState.call(failed)
  assert.equal(options.computed.displayLabel.call(failed), 'ERROR')
})


test('iOS monitor badge receives the normalized interval from the server open response', () => {
  const parent = readFileSync(new URL('../src/components/ConnectionInfoDialogs.vue', import.meta.url), 'utf8')
  assert.match(parent, /:interval-ms="monitorIntervalMs"/)
  assert.match(parent, /json\.data\?\.intervals\?\.ios_dashboard/)
})
