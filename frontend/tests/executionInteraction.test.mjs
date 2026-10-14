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
state.enqueue({interaction_id:'force-plan',kind:'preview',message:'Stop process', preview:{
    switches:[{key:'force',label:'Force termination',default:false}],summary:[],columns:[],rows:[],details:[]
}})
assert.equal(state.switchValues.force,false,'force defaults off')
state.switchValues.force = true
await state.submit(true)
assert.equal(calls[3].body.approved,true)
assert.equal(calls[3].body.value.force,true,'force switch is sent in approval value')
state.enqueue({interaction_id:'force-rejected',kind:'preview',message:'Stop process', preview:{
    switches:[{key:'force',label:'Force termination',default:false}],summary:[],columns:[],rows:[],details:[]
}})
state.switchValues.force = true
await state.submit(false)
assert.equal(calls[4].body.value,undefined,'rejection must not send switch values')
state.enqueue({interaction_id:'force-default-on',kind:'preview',message:'Stop process', preview:{
    switches:[{key:'force',label:'Force termination',default:true}],summary:[],columns:[],rows:[],details:[]
}})
assert.equal(state.switchValues.force,true,'-9 preview must initialize force ON')
state.switchValues.force = false
await state.submit(true)
assert.equal(calls[5].body.value.force,false,'UI can override -9 default to ordinary SIGTERM')
assert.ok(sfc.includes('<el-switch'), 'preview must render switch')
await state.reloadPending('tab-A')
assert.equal(state.current.interaction_id,'recovered')
state.resolved({interaction_id:'recovered'})
assert.equal(state.current,null)
console.log('executionInteraction UI behavior passed')
