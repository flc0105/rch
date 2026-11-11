import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import {test} from 'node:test'
import vm from 'node:vm'
import {displayAgentBuilder, AGENT_BUILDER} from '../src/data/agentBuilderTypes.js'

const output = readFileSync(new URL('../src/components/AgentOutputsDialog.vue', import.meta.url), 'utf8')
const app = readFileSync(new URL('../src/App.vue', import.meta.url), 'utf8')
const script = output.split('<script>')[1].split('</script>')[0]
const context = {displayAgentBuilder, AGENT_BUILDER, module: {exports: {}}, File: {}, FileArchive: {}, FileTerminal: {}, MoreFilled: {}}
vm.runInNewContext(script.replace(/^import\s+.*?\n/gm, '').replace('export default', 'module.exports ='), context)
const definition = context.module.exports
const rows = [
  {builder:'python', file_name:'python_20261106_175125_749854.zip', listener_id:'l1',listener_name:'Primary',size:123},
  {builder:'go',file_name:'rchclient_go_mac_arm64_20261106_175136_0e8ae4f2',listener_id:'l2',listener_name:'Secondary',size:456},
  {builder:'go_loader',file_name:'go_loader_win_amd64_20261106_175136_aab233.exe',listener_id:'l1',listener_name:'Primary',size:789},
]
function state() {return {...definition.data(), outputs: rows}}

test('new Artifact-style Agent Outputs layout has no vertical borders, uses icons/links and includes Listener', () => {
  const template = output.split('<script>')[0]
  assert.match(template, /label="Listener"/)
  assert.doesNotMatch(template, /label="OS"/)
  assert.doesNotMatch(template, /<el-table\s[^>]*\sborder(?:\s|>)/s)
  assert.match(template, /<FileArchiveIcon v-if="isArchiveOutput/)
  assert.match(template, /<FileTerminalIcon v-else-if="isExecutableOutput/)
  assert.match(template, /class="table-action-link"/)
  assert.match(template, /v-model="outputSearch"/)
  assert.match(template, /v-model="outputListenerFilter"/)
  assert.match(app, /command="agent-outputs">Agent Outputs/)
  assert.match(app, /command === 'agent-outputs'\) return this\.openAgentOutputsDialog\(\)/)
})

test('builder options come from available records while names use canonical mapping', () => {
  const s=state()
  assert.deepEqual([...definition.computed.builderOptions.call(s)],['go','go_loader','python'])
  assert.equal(displayAgentBuilder('python'),'Python Bundle')
  assert.equal(displayAgentBuilder('go'),'Go')
  assert.equal(displayAgentBuilder('go_loader'),'Go Loader')
  assert.equal(definition.methods.isArchiveOutput('build.zip'),true)
  assert.equal(definition.methods.isExecutableOutput('client.exe','go'),true)
  assert.equal(definition.methods.isExecutableOutput('metadata.json',''),false)
})

test('listener and search filter all operate over the same real records', () => {
  const s=state()
  assert.deepEqual(JSON.parse(JSON.stringify(definition.computed.listenerOptions.call(s))),[
    {id:'l1',name:'Primary'},{id:'l2',name:'Secondary'},
  ])
  s.outputListenerFilter='l1';s.outputSearch='loader'
  assert.deepEqual(Array.from(definition.computed.filteredOutputs.call(s),x=>x.builder),['go_loader'])
  s.outputSearch='';s.outputBuilderFilter='python'
  assert.deepEqual(Array.from(definition.computed.filteredOutputs.call(s),x=>x.builder),['python'])
})
