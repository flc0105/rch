import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createTerminalTaskCapture } from '../src/composables/terminalTaskCapture.js'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const registry = createTerminalTaskCapture()
const actionOutput = []
const actionCompleted = []
const action = registry.begin({
  clientId: 'client-A', command: 'echo action', suppress: true,
  onResult: payload => actionOutput.push(payload.text),
  onComplete: payload => actionCompleted.push(payload.task_id),
})
// SSE can beat the HTTP command response; hold the events until task_id is known.
assert.equal(registry.route('result', {client_id:'client-A',command:'echo action',task_id:'task-a',text:'alpha'}), true)
assert.equal(registry.route('complete', {client_id:'client-A',command:'echo action',task_id:'task-a'}), true)
assert.equal(actionOutput.length, 0)
assert.equal(registry.route('result', {client_id:'client-B',command:'echo action',task_id:'other',text:'wrong client'}), false)
assert.equal(registry.route('result', {client_id:'client-A',command:'echo other',task_id:'other',text:'wrong command'}), false)
assert.equal(action.bind('task-a'), true)
assert.deepEqual(actionOutput, ['alpha'])
assert.deepEqual(actionCompleted, ['task-a'])
assert.equal(registry.route('result', {client_id:'client-A',command:'echo action',task_id:'task-a',text:'late'}), false)

const refreshed = []
const finished = []
const run = registry.begin({
  clientId:'client-A',command:'',
  onResult: payload => refreshed.push(payload.text),
  onComplete: payload => finished.push(payload.task_id),
})
// Another task's output may be temporarily buffered but must never be forwarded.
assert.equal(registry.route('result', {client_id:'client-A',command:'different',task_id:'other',text:'ignore'}),false)
assert.equal(registry.route('result', {client_id:'client-A',command:'script-run',task_id:'script-1',text:'[{'}),false)
assert.equal(run.bind('script-1'),true)
assert.deepEqual(refreshed,['[{'])
assert.equal(registry.route('result', {client_id:'client-A',command:'other',task_id:'other',text:'ignore too'}),false)
assert.equal(registry.route('result', {client_id:'client-A',command:'script-run',task_id:'script-1',text:'}]'}),false)
assert.equal(registry.route('complete', {client_id:'client-A',command:'script-run',task_id:'script-1'}),false)
assert.deepEqual(refreshed,['[{','}]'])
assert.deepEqual(finished,['script-1'])

const cancelledOutput=[]
const cancelled=registry.begin({clientId:'client-A', command:'echo stop', suppress:true,
  onResult: payload => cancelledOutput.push(payload.text)})
cancelled.cancel()
assert.equal(cancelled.bind('discarded'),false)
assert.equal(registry.route('result',{client_id:'client-A',command:'echo stop',task_id:'discarded',text:'none'}),false)
assert.equal(cancelledOutput.length,0)

// An earlier unbound capture must not steal a later bound dialog task.
const shadow=registry.begin({clientId:'client-A',command:'',onResult:()=>{}})
const action2=registry.begin({clientId:'client-A',command:'echo dialog',suppress:true,
  onResult: payload=>actionOutput.push(payload.text),onComplete: payload=>actionCompleted.push(payload.task_id)})
action2.bind('task-b')
assert.equal(registry.route('result',{client_id:'client-A',task_id:'other',command:'echo dialog',text:'unrelated'}),false)
assert.equal(registry.route('result',{client_id:'client-A',task_id:'task-b',text:'bravo'}),true)
assert.equal(registry.route('complete',{client_id:'client-A',task_id:'task-b'}),true)
assert.deepEqual(actionOutput,['alpha','bravo'])
shadow.cancel()

const route = readFileSync(resolve(root, '../backend/server/web/routes/command_execution.py'), 'utf8')
const api = readFileSync(resolve(root,'src/api/connectionsApi.js'),'utf8')
const sse = readFileSync(resolve(root,'src/composables/useSseStream.js'),'utf8')
assert.doesNotMatch(route, /result_action_presentation|result_action_run_id|json_viewer_refresh_run_id/)
assert.doesNotMatch(api, /result_action_presentation|result_action_run_id|json_viewer_refresh_run_id/)
assert.doesNotMatch(sse, /handledByResultActionDialog|json_viewer_refresh_run_id/)
assert.match(sse, /routeTerminalTaskCapture\?\.\('result', payload\)/)
assert.match(sse, /routeTerminalTaskCapture\?\.\('complete', payload\)/)
console.log('task_id based task capture and SSE race tests passed')
