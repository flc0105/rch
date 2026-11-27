import assert from 'node:assert/strict'
import test from 'node:test'
import {readFileSync} from 'node:fs'
import vm from 'node:vm'

const source = readFileSync(new URL('../src/components/AgentOutputsDialog.vue', import.meta.url), 'utf8')
const script = source.match(/<script>([\s\S]*?)<\/script>/)?.[1]
const template = source.split('<script>')[0]
const AGENT_BUILDER = {PYTHON:'python', GO:'go', GO_LOADER:'go_loader'}
const component = vm.runInNewContext(`(${script.replace(/^import .*$/gm, '').replace('export default', '')})`, {
  AGENT_BUILDER, File:()=>{}, FileArchive:()=>{}, FileTerminal:()=>{}, Clock3:()=>{}, Cpu:()=>{}, Download:()=>{}, Ellipsis:()=>{}, HardDrive:()=>{}, Info:()=>{}, Link:()=>{}, ListFilter:()=>{}, Monitor:()=>{}, Network:()=>{}, RefreshCw:()=>{}, Tag:()=>{}, Trash2:()=>{}, Wrench:()=>{},
  displayAgentBuilder: kind => ({python:'Python Bundle', go:'Go',go_loader:'Go Loader'}[kind] || kind),
  formatDateTimeStandard: value => value,
  formatBytes: value => `${value} bytes`,
})

const sample = (mode, builder='go') => ({
  file_name:'agent.exe', builder, build_version:'go_2026_x',
  connection_mode:mode, transport:'mtls_tcp', listener_name:'Main', listener_id:'L1',
  target_os:'win',target_arch:'amd64', build_origin:'manual',
  endpoint_ip:mode === 'reverse' ? '192.168.1.2' : '0.0.0.0',
  endpoint_port:mode === 'reverse' ? 9998 : 9443,
  web_ip:'192.168.1.2',web_port:8085,build_time:'2026-11-25',size:1024,
})
function context(row) {return {...component.methods, agentOutputInfoItem:row,
  formatAgentSourceText:component.methods.formatAgentSourceText,
  formatAgentOutputInfoValue:component.methods.formatAgentOutputInfoValue,
  formatOutputDateTime:component.methods.formatOutputDateTime,
  formatOutputBytes:component.methods.formatOutputBytes}}
function info(row) {return component.computed.formattedAgentOutputInfoRows.call(context(row))}

test('desktop table keeps only requested data columns and existing actions', () => {
  const labels = [...template.matchAll(/<el-table-column\s+label="([^"]+)"/g)].map(m => m[1])
  assert.deepEqual(labels, ['Filename','Connection','Transport','Size','Actions'])
  for (const control of ['Download','Delete','Info','Build Agent','Refresh']) assert.match(template, new RegExp(control))
  assert.match(template, /type="selection"/)
})

test('filters only Builder and Mode; mobile summary mirrors table', () => {
  assert.match(template,/v-model="outputBuilderFilter"/)
  assert.match(template,/v-model="outputModeFilter"/)
  assert.doesNotMatch(template,/outputSearch|outputListenerFilter|Filter listener|Filter search/)
  assert.doesNotMatch(template,/agent-output-mobile-tags/)
  const filtered = component.computed.filteredOutputs
  const outputs = [sample('bind'),sample('reverse'),sample('reverse','python')]
  assert.equal(filtered.call({outputs,outputBuilderFilter:'go',outputModeFilter:'reverse'}).length,1)
  assert.equal(filtered.call({outputs,outputBuilderFilter:'',outputModeFilter:'bind'}).length,1)
  for (const label of ['Connection','Transport','Size']) assert.match(template,new RegExp(`agent-output-mobile-meta-label">${label}<`))
  assert.doesNotMatch(template,/agent-output-mobile-meta-label">(?:Version|Build Time|Listener)< /)
})

test('Info shows requested fields and only valid conditional fields', () => {
  const reverse = info(sample('reverse'))
  assert.deepEqual(Array.from(reverse, row => row.label), [
    'File Name','Version','Builder','Connection Mode','Transport','Listener',
    'Target OS','Target Arch','Build Origin','Connect To','Web URL','Build Time','Size',
  ])
  assert.equal(reverse.find(row => row.label === 'Version').value, 'go_2026_x')
  assert.equal(reverse.filter(row => row.label === 'Version').length, 1)
  assert.equal(reverse.find(row => row.label === 'Connect To').value,'192.168.1.2:9998')
  assert.equal(reverse.find(row => row.label === 'Web URL').value, '192.168.1.2:8085')
  const bind = info(sample('bind'))
  assert.equal(bind.find(row => row.label === 'Listen On').value,'0.0.0.0:9443')
  assert.ok(!bind.some(row => ['Listener','Web URL'].includes(row.label)))
  const loader = info(sample('bind','go_loader'))
  assert.equal(loader.find(row => row.label === 'Web URL').value, '192.168.1.2:8085')
  assert.ok(!loader.some(row => row.label === 'Listener'))
  const bundle = info({...sample('reverse', 'python'), target_os: '', target_arch: ''})
  assert.ok(!bundle.some(row => ['Target OS', 'Target Arch'].includes(row.label)))
  assert.equal(bundle.find(row => row.label === 'Web URL').value, '192.168.1.2:8085')
  const bindBundle = info({...sample('bind', 'python'), target_os: '', target_arch: ''})
  assert.ok(!bindBundle.some(row => ['Target OS', 'Target Arch', 'Web URL'].includes(row.label)))
  assert.equal(info({...sample('reverse'), web_ip: '', web_port: 0}).find(row => row.label === 'Web URL').value, '-')
})
