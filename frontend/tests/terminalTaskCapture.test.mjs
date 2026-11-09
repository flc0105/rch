import assert from 'node:assert/strict'
import { createTerminalTaskCapture } from '../src/composables/terminalTaskCapture.js'

const captures = createTerminalTaskCapture()
const outputA = [], outputB = [], completed = []
const first = captures.begin({clientId:'client-a', operationId:'op-a', suppress:true,
  onResult:e=>outputA.push(e.text), onComplete:e=>completed.push(e.task_id)})
const second = captures.begin({clientId:'client-a', operationId:'op-b', suppress:true,
  onResult:e=>outputB.push(e.text), onComplete:e=>completed.push(e.task_id)})
const event = (op, task, kind='result', client='client-a') => ({client_id:client, task_id:task,
  command:'echo SAME', metadata:{operation_id:op}, text:`${op}-${kind}`})
assert.equal(captures.route('result', event('op-b','task-b')), true)
assert.equal(captures.route('result', event('op-a','task-a')), true)
assert.equal(captures.route('result', event('op-other','task-other')), false)
assert.equal(captures.route('result', event('op-a','task-a','result','client-b')), false)
assert.equal(captures.route('complete', event('op-b','task-b','complete')), true)
assert.equal(first.bind('task-a'), true)
assert.equal(second.bind('task-b'), true)
assert.deepEqual(outputA,['op-a-result'])
assert.deepEqual(outputB,['op-b-result'])
assert.deepEqual(completed,['task-b'])
assert.equal(captures.route('complete', event('op-a','task-a','complete')), true)
assert.deepEqual(completed,['task-b','task-a'])
assert.equal(captures.route('result',event('op-a','task-a')),false)

const canceled=captures.begin({clientId:'client-a',operationId:'op-c',suppress:true,onResult:()=>{throw Error('canceled')}})
canceled.cancel()
assert.equal(canceled.bind('task-c'),false)
assert.equal(captures.route('result',event('op-c','task-c')),false)

// Events never bind by text alone, even for identical commands.
const pending=captures.begin({clientId:'client-a',operationId:'op-d',suppress:true,onResult:e=>outputB.push(e.text)})
assert.equal(captures.route('result',{client_id:'client-a',task_id:'task-d',command:'echo SAME',text:'without id'}),false)
assert.equal(pending.bind('task-d'),true)
assert.deepEqual(outputB,['op-b-result'])
pending.cancel()
