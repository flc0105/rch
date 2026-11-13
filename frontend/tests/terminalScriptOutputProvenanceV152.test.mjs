import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'
import vm from 'node:vm'

const here = path.dirname(fileURLToPath(import.meta.url))
const readComponent = name => fs.readFileSync(path.join(here, '../src/components', name), 'utf8')
const loadComponent = name => {
  const script = readComponent(name).match(/<script>([\s\S]*?)<\/script>/)?.[1] || ''
  const source = script.replace(/import\s+[\s\S]*?\s+from\s+['"][^'"]+['"]\s*;?/g, '')
  const sandbox = {setTimeout, clearTimeout, TerminalLinkedText: {}, ScriptRunDialog: {}, FileCode2: {}, ElMessage: {warn() {}, error() {}, warning() {}}}
  vm.runInNewContext(source.replace('export default {', 'globalThis.component = {'), sandbox)
  return sandbox.component
}
const bindMethods = (component, context) => {
  for (const [name, method] of Object.entries(component.methods)) context[name] = method.bind(context)
  return context
}

test('actual terminal script exec SSE result retains script path through JSON action and save', () => {
  const component = loadComponent('TerminalOutput.vue')
  const view = bindMethods(component, {
    selectedId: 'client-a', currentConnection: {machine_id: 'machine-a', hostname: 'mac'},
  })
  const realCommand = 'script exec common/recon/list_disks.py'
  const operation = {operation_id: 'op-a', kind: 'command', invocation: {command: realCommand}}
  const lines = [
    {kind:'command', text:`> ${realCommand}`, meta:{operation_id:'op-a', operation}},
    {kind:'default', text:'[{"name":"disk"}]', isJsonMessage:true, jsonText:'[{"name":"disk"}]',
      meta:{operation_id:'op-a', event_type:'output', command_id:111,
        metadata:{script_run:true, script_run_name:'common/recon/list_disks.py'}}},
    {kind:'success', text:'[Command finished]', meta:{operation_id:'op-a', event_type:'completed'}},
  ]
  const blocks = view.buildTerminalBlocksFromLines(lines)
  assert.equal(blocks.length, 1)
  assert.equal(blocks[0].blockType, 'script')
  assert.equal(blocks[0].scriptMeta.script_path, 'common/recon/list_disks.py')
  const actions = view.getTerminalCommandGroupActionItems(lines, 2)
  assert.equal(actions.length, 1)
  assert.equal(actions[0].commandInfo.blockType, 'script')
  assert.equal(actions[0].commandInfo.script_path, 'common/recon/list_disks.py')
  assert.equal(actions[0].commandInfo.source_command, realCommand)
  const block = view.normalizeTerminalJsonSaveBlock(actions[0].commandInfo)
  const body = view.buildTerminalOutputArtifactSaveBody(block, '[{"name":"disk"}]', {
    savedFrom: 'terminal_json_viewer', outputFormat: 'text',
  })
  assert.equal(body.output_kind, 'script')
  assert.equal(body.output_format, 'text')
  assert.equal(body.extra.script_path, 'common/recon/list_disks.py')
  assert.equal(body.source_command, realCommand)
})

test('Server-originated Script start without UI replay still uses task script identity', () => {
  const view = bindMethods(loadComponent('TerminalOutput.vue'), {
    selectedId: 'client-a', currentConnection: {machine_id:'machine-a',hostname:'mac'},
  })
  const operation = {operation_id:'op-b',kind:'script',invocation:{},replay:null}
  const lines = [
    {kind:'command',text:'> [Run Script] list disks',meta:{operation_id:'op-b',operation}},
    {kind:'default',text:'[{"name":"disk"}]',isJsonMessage:true,meta:{operation_id:'op-b',event_type:'output',
      metadata:{script_run:true,script_run_name:'common/recon/list_disks.py'}}},
    {kind:'success',text:'[Command finished]',meta:{operation_id:'op-b',event_type:'completed'}},
  ]
  const block = view.buildTerminalBlocksFromLines(lines)[0]
  assert.equal(block.blockType, 'script')
  assert.equal(block.scriptMeta.script_path, 'common/recon/list_disks.py')
  const body = view.buildTerminalOutputArtifactSaveBody(block, 'output', {savedFrom:'terminal_output'})
  assert.equal(body.output_kind, 'script')
  assert.equal(body.extra.script_path, 'common/recon/list_disks.py')
})

test('Script Library dialog forwards actual Script path into JSON Viewer save context', () => {
  const component = loadComponent('ScriptLibraryDialog.vue')
  const events = []
  const view = bindMethods(component, {
    activeRun: {clientId: 'client-a', scriptPath: 'common/recon/list_disks.py'},
    resultJsonText: '[{"name":"disk"}]',
    $emit: (...args) => events.push(args),
  })
  view.viewResultJson()
  assert.equal(events[0][0], 'open-json')
  assert.equal(events[0][1].jsonCommandInfo.script_path, 'common/recon/list_disks.py')
  const terminal = bindMethods(loadComponent('TerminalOutput.vue'), {
    selectedId: 'client-a', currentConnection: {machine_id:'machine-a',hostname:'mac'},
  })
  const block = terminal.normalizeTerminalJsonSaveBlock(events[0][1].jsonCommandInfo)
  const body = terminal.buildTerminalOutputArtifactSaveBody(block, events[0][1].jsonText, {
    savedFrom: 'terminal_json_viewer', outputFormat: 'text',
  })
  assert.equal(body.output_kind, 'script')
  assert.equal(body.extra.script_path, 'common/recon/list_disks.py')
  assert.equal(body.output_format, 'text')
})

test('JSON Viewer Save uses the original text format and never renames Script to command output', () => {
  const source = readComponent('TerminalOutput.vue')
  assert.match(source, /savedFrom:\s*'terminal_json_viewer',\s*outputFormat:\s*'text'/)
  const backend = fs.readFileSync(path.join(here, '../../backend/server/application/artifact/command_output_artifact_service.py'), 'utf8')
  assert.match(backend, /if kind == 'script':/)
  assert.match(backend, /return build_artifact_filename\('script', ext/)
})
