import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'
import vm from 'node:vm'

const here = dirname(fileURLToPath(import.meta.url))
const source = readFileSync(resolve(here, '../src/components/ExecutionInteractionDialog.vue'), 'utf8')
assert.match(source, /current.kind === 'select'/)
assert.match(source, /<el-select/)
assert.match(source, /current.kind === 'secret' \? 'password'/)
const componentSource = source.match(/<script>([\s\S]*?)<\/script>/)?.[1]
const calls = []
const sandbox = {
    answerInteraction: async (id, body) => { calls.push({id, body}) },
    listPendingInteractions: async () => [],
    console,
}
vm.runInNewContext(componentSource.replace(/^import\s+.*?from\s+.*?\n/gm, '').replace('export default {', 'globalThis.component = {'), sandbox)
const component = sandbox.component
const state = {...component.data()}
Object.defineProperty(state, 'current', {get() {return this.queue[0] || null}})
for (const [name, fn] of Object.entries(component.methods)) state[name] = fn.bind(state)
state.enqueue({interaction_id:'pick', kind:'select', options:['safe','delete'], message:'Select'})
await state.submit(true)
assert.equal(calls.length, 0, 'Empty selection must never approve')
assert.match(state.errorText, /Choose/)
state.selectedValue = 'delete'
await state.submit(true)
assert.equal(calls.length, 1)
assert.equal(calls[0].body.value, 'delete')
assert.equal(state.queue.length, 0)
state.enqueue({interaction_id:'secret', kind:'secret', message:'Secret'})
state.inputValue = 'not-for-logs'
await state.submit(false)
assert.equal(calls[1].body.value, undefined)
assert.equal(state.inputValue, '')
console.log('advancedExecutionInteraction UI tests passed')
