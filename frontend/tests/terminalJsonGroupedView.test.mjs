import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'
import vm from 'node:vm'

const here = dirname(fileURLToPath(import.meta.url))
const source = readFileSync(resolve(here, '../src/components/TerminalJsonDialog.vue'), 'utf8')
const template = source.match(/<template>([\s\S]*?)<\/template>\s*<script>/)?.[1]
const script = source.match(/<script>([\s\S]*?)<\/script>/)?.[1]
assert.ok(template && script, 'Terminal JSON template and script must exist')
assert.match(template, /displayMode === 'grouped' && !isTerminalJsonRawView/)
assert.match(template, /v-for="group in groupedSections"/)
assert.match(template, /v-for="item in group.items"/)
assert.match(template, /terminal-json-grouped-title/)
assert.match(template, /terminal-json-grouped-label/)
assert.match(template, /terminal-json-grouped-value/)
assert.match(source, /\.terminal-json-grouped-row\s*\{[\s\S]*?grid-template-columns:\s*180px minmax\(0, 1fr\)/)
for (const originalControl of ['Copy Raw', 'Raw View', 'Render View', 'Save to Artifact']) {
  assert.ok(template.includes(originalControl), `${originalControl} remains available`)
}
assert.ok(template.indexOf("displayMode === 'table'") < template.indexOf("displayMode === 'grouped'"))
assert.ok(template.indexOf("displayMode === 'grouped'") < template.indexOf("displayMode === 'flat'"))

const messages = []
const sandbox = { ElMessage: {
  success: value => messages.push(['success', value]),
  error: value => messages.push(['error', value]),
  warning: value => messages.push(['warning', value]),
} }
vm.runInNewContext(script.replace(/^import \{ ElMessage \} from 'element-plus'\s*/m, '')
  .replace('export default {', 'globalThis.component = {'), sandbox)
const component = sandbox.component

function makeViewer() {
  const emitted = []
  const viewer = { ...component.data(), $emit: (...args) => emitted.push(args) }
  for (const [name, method] of Object.entries(component.methods)) viewer[name] = method.bind(viewer)
  for (const [name, getter] of Object.entries(component.computed)) {
    Object.defineProperty(viewer, name, { get: () => getter.call(viewer) })
  }
  return { viewer, emitted }
}
function openViewer(value) {
  const result = makeViewer()
  result.viewer.open({ isJsonMessage: true, jsonText: JSON.stringify(value) })
  return result
}

const watchdog = {
  client: { id: 'abc', pid: 123 },
  remote_watchdog: { enabled: true, interval_seconds: 5, worker_pid: 2345 },
  local_watchdog: { enabled: false, timeout_seconds: 10 },
  process_watchdog: { supervisor_pid: 3456, supervisor_alive: true },
}
let { viewer, emitted } = openViewer(watchdog)
assert.equal(viewer.displayMode, 'grouped')
assert.equal(viewer.hasTerminalJsonRenderView, true)
assert.equal(viewer.groupedSections.length, 4)
assert.deepEqual(Array.from(viewer.groupedSections, g => g.key), Object.keys(watchdog))
assert.equal(viewer.groupedSections[0].items[1].value, '123')
assert.equal(viewer.groupedSections[1].items[0].value, 'true')
assert.equal(viewer.groupedSections[2].items[0].value, 'false')
assert.equal(viewer.groupedSections[3].items[0].label, 'supervisor_pid')
assert.equal(viewer.flatRows.length, 0)
assert.equal(viewer.tableRows.length, 0)
viewer.toggleTerminalJsonViewMode()
assert.equal(viewer.isTerminalJsonRawView, true)
assert.match(viewer.formattedRawText, /"remote_watchdog": \{/)
viewer.toggleTerminalJsonViewMode()
assert.equal(viewer.isTerminalJsonRawView, false)
viewer.saveTerminalJsonToArtifact()
assert.equal(emitted[0][0], 'save-json-output')
assert.equal(emitted[0][1].content, JSON.stringify(watchdog))
emitted[0][1].onDone()
assert.equal(viewer.savingJsonArtifact, false)
viewer.reset()
assert.equal(viewer.groupedSections.length, 0)
assert.equal(viewer.displayMode, 'raw')

// Deep values do not become nested groups: their unchanged Flat formatter outputs JSON strings.
;({ viewer } = openViewer({ first: { detail: { platform: 'macOS' }, list: [1, { x: 2 }], empty: null, yes: false }, second: { count: 0 } }))
assert.equal(viewer.displayMode, 'grouped')
assert.equal(viewer.groupedSections[0].items[0].value, '{"platform":"macOS"}')
assert.equal(viewer.groupedSections[0].items[1].value, '[1,{"x":2}]')
assert.equal(viewer.groupedSections[0].items[2].value, '')
assert.equal(viewer.groupedSections[0].items[3].value, 'false')

for (const value of [
  [{ id: 1 }, { id: 2 }],
  { one: { a: 1 } },
  { one: { a: 1 }, two: 'not a group' },
  { one: { a: 1 }, two: [1, 2] },
  { one: { a: 1 }, two: null },
  { one: { a: 1 }, two: {} },
  { one: {}, two: {} },
  { a: 1, b: true },
  {},
]) {
  const { viewer: other } = openViewer(value)
  assert.notEqual(other.displayMode, 'grouped', JSON.stringify(value))
  assert.equal(other.groupedSections.length, 0)
}
// Existing table and flat paths retain their behavior, including nested Flat values.
;({ viewer } = openViewer([{ a: 1, b: 'first' }, { b: 'second', a: 2 }]))
assert.equal(viewer.displayMode, 'table')
assert.equal(viewer.tableRows.length, 2)
;({ viewer } = openViewer({ client_id: 'abc', detail: { pid: 42 } }))
assert.equal(viewer.displayMode, 'flat')
assert.equal(viewer.flatRows[1].value, '{"pid":42}')
;({ viewer } = openViewer([1, 2]))
assert.equal(viewer.displayMode, 'raw')
assert.equal(viewer.hasTerminalJsonRenderView, false)

console.log('Terminal JSON Grouped view tests passed')
