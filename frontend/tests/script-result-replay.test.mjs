import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import vm from 'node:vm'

import { createTerminalOperation, getTerminalReplayAction } from '../src/utils/terminalOperation.js'
import { selectJsonViewResult } from '../src/utils/terminalJson.js'

// Exercise the Script Library JSON entry point without mounting a browser dialog.
const source = readFileSync(new URL('../src/components/ScriptLibraryDialog.vue', import.meta.url), 'utf8')
const start = source.indexOf('    viewResultJson() {')
const end = source.indexOf('    forwardAppendOutput(', start)
assert.ok(start > 0 && end > start, 'Script Library JSON opener exists')
const method = vm.runInNewContext(`({${source.slice(start, end)}}).viewResultJson`)

test('Script Library JSON result retains exact typed replay from its original run', () => {
  const replay = { type: 'script', script_name: 'common/a',
    script_path: 'common/a.py', script_display_name: 'A',
    execution_mode: 'inproc', output_mode: 'json', params: { limit: 17 } }
  const operation = createTerminalOperation({ kind: 'script', action: 'run', clientId: 'client',
    invocation: { script_name: 'common/a', params: { limit: 17 } }, replay,
    presentation: 'dialog' })
  let emitted
  method.call({
    resultJsonText: '[{"pid":17}]',
    activeRun: { clientId: 'client', scriptPath: 'common/a.py', operation, view: { actions: [{ label: 'Inspect', command: 'getpid' }] } },
    $emit: (_event, data) => { emitted = data },
  })
  assert.equal(emitted.jsonText, '[{"pid":17}]')
  assert.equal(emitted.clientId, 'client')
  assert.equal(emitted.jsonView.actions[0].command, 'getpid')
  assert.equal(emitted.jsonCommandInfo.script_name, 'common/a')
  assert.deepEqual(getTerminalReplayAction(emitted.jsonCommandInfo.operation), replay)
})

test('Script dialog stores a typed replay operation rather than a display path only', () => {
  const dialogBranch = source.slice(source.indexOf("if (presentation === 'dialog')", source.indexOf('async confirmRunScript(')),
    source.indexOf('} else {\n          // Terminal output', source.indexOf('async confirmRunScript(')))
  assert.match(dialogBranch, /operation: createTerminalOperation\(/)
  assert.match(dialogBranch, /replay, presentation: 'dialog'/)
})


test('Script Dialog records exact structured data and view from results', () => {
  const start = source.indexOf('    handleCommandResult(payload = {}) {')
  const end = source.indexOf('    handleCommandComplete(payload = {}) {', start)
  assert.ok(start > 0 && end > start)
  const method = vm.runInNewContext(`({${source.slice(start, end)}}).handleCommandResult`, { selectJsonViewResult })
  const run = { runId: 'r1', clientId: 'c1', output: '', outputChunks: 0, view: null, jsonText: '' }
  const instance = { activeRun: run, resultVisible: true }
  method.call(instance, { client_id: 'c1', text: 'a text projection', metadata: {
    script_run: true, script_run_presentation: 'dialog', script_run_id: 'r1', output_mode: 'collect' },
    result: { data: [{ pid: 7 }], view: { actions: [{ label: 'Kill', command: 'getpid' }] } },
  })
  assert.equal(run.jsonText, '[{"pid":7}]')
  assert.equal(run.view.actions[0].label, 'Kill')
})


test('Script dialog keeps a data/view record when later emit writes ordinary data', () => {
  const start = source.indexOf('    handleCommandResult(payload = {}) {')
  const end = source.indexOf('    handleCommandComplete(payload = {}) {', start)
  const method = vm.runInNewContext(`({${source.slice(start, end)}}).handleCommandResult`, { selectJsonViewResult })
  const instance = { activeRun: { runId: 'r1', clientId: 'c1', output: '', outputChunks: 0, view: null, jsonText: '' }, resultVisible: true }
  const metadata = { script_run: true, script_run_presentation: 'dialog', script_run_id: 'r1', output_mode: 'collect' }
  method.call(instance, { client_id: 'c1', metadata, result: { data: [{ pid: 4 }], view: { actions: [{ label: 'Inspect', command: 'getpid' }] } } })
  method.call(instance, { client_id: 'c1', metadata, result: { data: { finished: true } } })
  assert.equal(instance.activeRun.jsonText, '[{"pid":4}]')
  assert.equal(instance.activeRun.view.actions[0].label, 'Inspect')
})
