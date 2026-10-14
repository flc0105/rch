import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'
import vm from 'node:vm'

const here = dirname(fileURLToPath(import.meta.url))
const sfc = readFileSync(resolve(here, '../src/components/ExecutionInteractionDialog.vue'), 'utf8')
const moduleSource = sfc.match(/<script>([\s\S]*?)<\/script>/)?.[1]
assert.ok(moduleSource, 'Vue script must exist')
const calls = []
const ctx = {
    answerInteraction: async (id, body) => { calls.push({id,body}); return {status:'answered'} },
    listPendingInteractions: async () => [{interaction_id:'recovered',kind:'confirm',message:'Recovered'}],
    console,
}
const code = moduleSource.replace(/^import\s+.*?from\s+.*?\n/gm, '').replace('export default {', 'globalThis.component = {')
vm.runInNewContext(code, ctx)
const component = ctx.component
const state = {...component.data(), ...component.methods}
state.current = null
Object.defineProperty(state, 'current', {get() {return this.queue[0] || null}})
for (const method of Object.keys(component.methods)) state[method] = component.methods[method].bind(state)

state.enqueue({interaction_id:'first',kind:'confirm',message:'Approve'})
state.enqueue({interaction_id:'first',kind:'confirm',message:'Approve'})
assert.equal(state.queue.length,1,'SSE duplicate cannot open two dialogs')
await state.submit(true)
assert.equal(calls[0].body.approved,true)
assert.equal(state.queue.length,0)
state.enqueue({interaction_id:'second',kind:'secret',message:'Secret'})
state.inputValue = 'private-value'
await state.submit(false)
assert.equal(calls[1].body.approved,false)
assert.equal(calls[1].body.value,undefined,'rejection must not send private value')
assert.equal(state.inputValue,'')
state.enqueue({interaction_id:'plan',kind:'preview',message:'Review',preview:{summary:[],columns:[],rows:[],details:[]}})
await state.submit(true)
assert.equal(calls[2].body.approved,true)
assert.equal(calls[2].body.value,undefined,'preview approval must not send input value')
assert.ok(sfc.includes('<el-table'), 'structured preview must render table')
assert.ok(sfc.includes('<el-descriptions'), 'structured preview must render summary')
assert.ok(sfc.includes('<el-collapse'), 'preview details must be expandable')
await state.reloadPending('tab-A')
assert.equal(state.current.interaction_id,'recovered')
state.resolved({interaction_id:'recovered'})
assert.equal(state.current,null)
console.log('executionInteraction UI behavior passed')
