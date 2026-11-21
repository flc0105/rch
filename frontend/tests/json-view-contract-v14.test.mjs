import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { JSON_ROW_SOURCE, getJsonRenderModel, normalizeJsonView, resolveJsonViewRowActions } from '../src/utils/terminalJson.js'

const read = file => readFileSync(new URL(file, import.meta.url), 'utf8')
const dialog = read('../src/components/TerminalJsonDialog.vue')
const sse = read('../src/composables/useSseStream.js')
const wire = JSON.stringify([{ id: 101, name: 'O\'Brien', state: 'ready', note: 'long', owner: 'qa' }])
const view = {
  titleField: 'name', columns: [{ field: 'id', width: 88 }, { field: 'state', minWidth: 150 }],
  details: ['note', 'owner'],
  actions: [
    { label: 'Delete', command: 'acmd view_probe --delete {id}', refresh: true },
    { label: 'Inspect', command: 'acmd view_probe --inspect {id}', confirm: false },
    { label: 'Read Name', command: 'acmd ps --name {name}' },
  ],
}

test('result metadata selects primary columns, Card title, Details, and all actions', () => {
  const model = getJsonRenderModel(wire)
  const p = normalizeJsonView(view, model.columns)
  assert.equal(p.titleField, 'name')
  assert.deepEqual(p.columns.map(col => col.prop), ['id', 'state'])
  assert.equal(p.columns[0].width, 88)
  assert.equal(p.columns[1].minWidth, 150)
  assert.deepEqual(p.details, ['note', 'owner'])
  assert.equal(model.rows[0][JSON_ROW_SOURCE].id, 101)
  const actions = resolveJsonViewRowActions(p, model.rows[0][JSON_ROW_SOURCE])
  assert.equal(actions.length, 3)
  assert.equal(actions[0].command, 'acmd view_probe --delete 101')
  assert.equal(actions[0].refresh, true)
  assert.equal(actions[1].confirm, false)
  assert.equal(actions[2].command, "acmd ps --name 'O'\\''Brien'")
})

test('missing or complex bindings suppress unsafe actions and cannot execute arbitrary text', () => {
  const p = normalizeJsonView({ actions: [
    { label: 'Missing', command: 'getpid {not_here}' },
    { label: 'Bad', command: 'getpid {object}' },
    { label: 'Safe', command: 'getpid --name {name}' },
  ] }, [{ prop: 'name' }])
  assert.deepEqual(resolveJsonViewRowActions(p, { name: 'hello', object: { x: 1 } }).map(action => action.label), ['Safe'])
  const malicious = resolveJsonViewRowActions(p, { name: 'x; getpid', object: null })
  assert.equal(malicious.length, 1)
  assert.equal(malicious[0].command, "getpid --name 'x; getpid'")
})

test('desktop table/card, mobile default card, compact row actions and Details are in existing Viewer', () => {
  assert.match(dialog, /tableViewMode === 'card'/)
  assert.match(dialog, /matchMedia\?\.\('\(max-width: 768px\)'\)/)
  assert.match(dialog, /type="expand"/)
  assert.match(dialog, /v-for="column in tableColumns"\s*:key="column\.prop"/)
  assert.match(dialog, /:width="column.width \|\| undefined"/)
  assert.match(dialog, /:min-width="column.minWidth/)
  assert.match(dialog, /getTerminalJsonRowActions\(row\)\.slice\(0, 2\)/)
  assert.match(dialog, /getTerminalJsonRowActions\(row\)\.slice\(2\)/)
  assert.doesNotMatch(dialog, /fixed="right"/)
  assert.doesNotMatch(dialog, /Actions \(\{\{/)
})

test('raw Result view travels through the existing SSE line metadata, and replay replaces it', () => {
  assert.match(sse, /item\.result\?\.view/)
  assert.match(dialog, /line\.meta\?\.resultView/)
  assert.match(dialog, /payload\.result\?\.data/)
  assert.match(dialog, /selectJsonViewResult\(this\.refreshRun\.selected, payload\.result\)/)
  assert.match(dialog, /this\.viewMetadata = updatedView \|\| \{\}/)
})


test('deleting the last row keeps an empty typed table and a valid JSON result', () => {
  const model = getJsonRenderModel('[]', view)
  assert.equal(model.mode, 'table')
  assert.equal(model.rows.length, 0)
  assert.deepEqual(model.columns.map(col => col.prop), ['id', 'state'])
})
