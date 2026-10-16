import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'
import vm from 'node:vm'

const here = dirname(fileURLToPath(import.meta.url))
const sfc = readFileSync(resolve(here, '../src/components/ExecutionInteractionDialog.vue'), 'utf8')
assert.match(sfc, /v-if="current\.preview\.row_details\?\.length" type="expand"/)
assert.match(sfc, /<pre v-if="rowDetail\(\$index\)" class="plan-detail-content">/)
assert.match(sfc, /<el-collapse v-if="current\.preview\.details\?\.length"/)
assert.match(sfc, /current\.preview\.row_ids\?\.length/)
const source = sfc.match(/<script>([\s\S]*?)<\/script>/)?.[1]
const calls = []
const sandbox = { answerInteraction: async (id, body) => { calls.push(body) },
                  listPendingInteractions: async () => [], console }
vm.runInNewContext(source.replace(/^import\s+.*?from\s+.*?\n/gm, '')
  .replace('export default {', 'globalThis.component = {'), sandbox)
const state = { ...sandbox.component.data() }
Object.defineProperty(state, 'current', { get() { return this.queue[0] || null } })
for (const [name, fn] of Object.entries(sandbox.component.methods)) state[name] = fn.bind(state)
state.enqueue({interaction_id:'with-details',kind:'preview',preview:{
    row_ids:['1','2'], rows:[{name:'Alpha'}, {name:'Beta'}],
    row_details:[{row_id:'2',content:'Beta-1\nBeta-2'}],
    details:[{title:'Warnings',content:'Permission denied'}]
}})
assert.equal(state.rowDetail(0),'')
assert.equal(state.rowDetail(1),'Beta-1\nBeta-2')
state.toggleRow('2',false)
assert.equal(state.rowDetail(1),'Beta-1\nBeta-2')
await state.submit(true)
assert.equal(JSON.stringify(calls[0].value.selected_rows),JSON.stringify(['1']))
state.enqueue({interaction_id:'plain',kind:'preview',preview:{rows:[],columns:[],details:[]}})
assert.equal(state.rowDetail(0),'')
await state.submit(true)
assert.equal(calls[1].value,undefined)
console.log('previewRowDetails optional UI behavior passed')
