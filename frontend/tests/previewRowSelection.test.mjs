import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'
import vm from 'node:vm'

const here = dirname(fileURLToPath(import.meta.url))
const sfc = readFileSync(resolve(here, '../src/components/ExecutionInteractionDialog.vue'), 'utf8')
assert.match(sfc, /row_ids\?\.length/)
assert.match(sfc, /<el-checkbox/)
const source = sfc.match(/<script>([\s\S]*?)<\/script>/)?.[1]
const calls = []
const sandbox = { answerInteraction: async (id, body) => { calls.push(body) },
                  listPendingInteractions: async () => [], console }
vm.runInNewContext(source.replace(/^import\s+.*?from\s+.*?\n/gm, '')
  .replace('export default {', 'globalThis.component = {'), sandbox)
const state = { ...sandbox.component.data() }
Object.defineProperty(state, 'current', { get() { return this.queue[0] || null } })
for (const [name, fn] of Object.entries(sandbox.component.methods)) state[name] = fn.bind(state)
const plan = { row_ids: ['one', 'two'], columns: [{key:'name',label:'Name'}],
               rows: [{name:'One'}, {name:'Two'}] }
state.enqueue({interaction_id:'select',kind:'preview',preview:plan})
assert.equal(JSON.stringify(state.selectedRowIds), JSON.stringify(['one','two']))
state.toggleRow('one', false)
await state.submit(true)
assert.equal(JSON.stringify(calls[0].value.selected_rows), JSON.stringify(['two']))
state.enqueue({interaction_id:'empty',kind:'preview',preview:plan})
state.toggleAllRows(false)
await state.submit(true)
assert.equal(JSON.stringify(calls[1].value.selected_rows), JSON.stringify([]))
state.enqueue({interaction_id:'reject',kind:'preview',preview:plan})
await state.submit(false)
assert.equal(calls[2].value, undefined)
state.enqueue({interaction_id:'both',kind:'preview',preview:{...plan,
    switches:[{key:'force',label:'Force',default:false}]}})
state.switchValues.force = true
state.toggleRow('two',false)
await state.submit(true)
assert.equal(calls[3].value.force,true)
assert.equal(JSON.stringify(calls[3].value.selected_rows), JSON.stringify(['one']))
state.enqueue({interaction_id:'plain',kind:'preview',preview:{columns:[],rows:[]}})
await state.submit(true)
assert.equal(calls[4].value,undefined)
console.log('previewRowSelection UI behavior passed')
