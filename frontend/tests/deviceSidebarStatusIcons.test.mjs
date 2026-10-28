import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const source = readFileSync(resolve(dirname(fileURLToPath(import.meta.url)), '../src/components/DeviceSidebar.vue'), 'utf8')
assert.match(source, /import \{ ClockAlert, ShieldPlus \} from '@lucide\/vue'/)
assert.match(source, /<ClockAlert\s+v-if="getConnectionDisplayState\(item\) === 'online' && item.client_revision_state === 'outdated'"/)
assert.match(source, /<ShieldPlus\s+v-if="getConnectionDisplayState\(item\) === 'online' && isElevated\(item\)"/)
assert.doesNotMatch(source, /<CaretTop\s*\/>/)
const block = source.match(/isElevated\(item\) \{([\s\S]*?)\n    \},/)
assert.ok(block)
const isElevated = new Function('item', block[1])
for (const integrity of ['High', 'System', 'Protected', 'Root', 'Root (via sudo)']) {
  assert.equal(isElevated({ integrity }), true, integrity)
}
for (const integrity of ['Low', 'Medium', 'Medium High', 'User', 'N/A', '?', 'Unknown', '', null]) {
  assert.equal(isElevated({ integrity }), false, String(integrity))
}
console.log('DeviceSidebar subtle status icon tests passed')
