import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import {
  executeTerminalAction, getTerminalActionLabel, getTerminalReferenceActions, TERMINAL_RESULT_ACTIONS,
} from '../src/utils/terminalResultActions.js'

const load = file => readFileSync(new URL(file, import.meta.url), 'utf8')
const output = load('../src/components/TerminalOutput.vue')
const sse = load('../src/composables/useSseStream.js')
const projector = load('../../backend/server/application/preferences/notification_event_projector.py')
const commands = []
let confirmResult = true
const script = output.match(/<script>([\s\S]*?)<\/script>/)?.[1]
assert.ok(script, 'TerminalOutput script is present')
const executableScript = script.replace(/import[\s\S]*?from\s+['"][^'"]+['"]\s*/g, '')
  .replace('export default {', 'return {')
const component = new Function('ElMessageBox', 'ElMessage', 'killInstance', 'TerminalLinkedText',
  'executeTerminalAction', 'getTerminalActionLabel', 'getTerminalReferenceActions', executableScript)(
  { confirm: async () => { if (!confirmResult) throw 'cancel' } },
  { success: () => {}, error: error => { throw new Error(error) } },
  async id => { commands.push(id) },
  {}, executeTerminalAction, getTerminalActionLabel, getTerminalReferenceActions,
)
const methods = component.methods
const referenceLine = (clientId='original-client') => ({
  kind: 'success',
  text: 'Verify the new Client before ending this instance.',
  meta: {
    resultClientId: clientId,
    resultReferences: [
      { type: 'log_file', path: '/var/tmp/update-test.log', title: 'Client update' },
      { type: 'session_action', action: 'kill_instance' },
    ],
  },
})
const groupContext = (groupLines, selectedId='other-client') => ({
  ...methods,
  selectedId,
  getTerminalCommandGroupLines: () => groupLines,
  buildTerminalJsonCommandInfo: () => ({ command_name: 'update' }),
})

test('observed Update uses ordinary Result action rows, not a command-specific warning', () => {
  assert.doesNotMatch(output, /getObserveUpdateActions|killObservedClient|viewObservedUpdateLog|terminal-observe-notice/)
  assert.doesNotMatch(output, /getObserveUpdateActions\(entry\.line\) \? 'line-warning'/)
  assert.match(output, /getTerminalTailActionItems\(lines, entry\.index, block\)/)
  assert.match(output, /class="terminal-line terminal-result-actions"/)
  assert.match(output, /v-for="actionItem in getTerminalTailActionItems\(lines, entry\.index, block\)"/)
  assert.match(output, /\.terminal-result-actions\s*\{[^}]*flex-wrap:\s*wrap/s)
  assert.match(output, /\.terminal-result-action\s*>\s*a\s*\{[^}]*white-space:\s*nowrap/s)
  assert.doesNotMatch(output, /v-for="actionItem in \(!isTerminalBlockCollapsed\(block\)/)
  assert.match(output, /getTerminalActionLabel\(actionItem\)/)
  assert.match(output, /@click\.prevent\.stop="handleTerminalActionClick\(actionItem\)"/)
  const line = referenceLine()
  const actions = methods.getTerminalCommandGroupActionItems.call(groupContext([line]), [line], 0)
  assert.deepEqual(actions.map(action => getTerminalActionLabel(action)), ['View Log', 'Kill Instance'])
  assert.deepEqual(actions[0].source, { clientId: 'original-client', path: '/var/tmp/update-test.log', title: 'Client update' })
  assert.equal(actions[1].clientId, 'original-client')
})

test('reference-backed actions are independent, validated and deduplicated within a group', () => {
  const logOnly = {meta: {resultClientId:'client-a', resultReferences:[
    {type:'log_file', path:'/tmp/one.log', title:'Startup'}]}}
  assert.deepEqual(getTerminalReferenceActions(logOnly).map(action => action.type), ['log'])
  const killOnly = {meta: {resultClientId:'client-a', resultReferences:[
    {type:'session_action', action:'kill_instance'}]}}
  assert.deepEqual(getTerminalReferenceActions(killOnly).map(action => action.type), ['kill_instance'])
  assert.deepEqual(getTerminalReferenceActions({meta: {resultReferences:[
    {type:'session_action', action:'kill_instance'}]}}, 'selected-client'), [])
  assert.deepEqual(getTerminalReferenceActions({meta: {resultClientId:'client-a', resultReferences:[
    {type:'session_action', action:'unknown'}, {type:'log_file', path:'  '}]}}, 'selected-client'), [])
  const line = referenceLine()
  const actions = methods.getTerminalCommandGroupActionItems.call(groupContext([line, line]), [line, line], 1)
  assert.deepEqual(actions.map(action => action.type), ['log', 'kill_instance'])
})

test('completed success and failure both expose the shared Result action list', () => {
  const result = referenceLine()
  const command = {kind:'command', text:'> update --observe', meta:{operation_id:'op-1'}}
  result.meta.operation_id = 'op-1'
  for (const state of ['Success', 'Failed']) {
    const finished = {kind: state === 'Success' ? 'success' : 'error',
      text: `[Command finished] update --observe (${state})`,
      meta: {operation_id: 'op-1', event_type: 'completed'}}
    const resultLine = state === 'Success' ? result : {
      ...result,
      kind: 'error',
      meta: {...result.meta, resultReferences: [result.meta.resultReferences[0]]},
    }
    const lines = [command, resultLine, finished]
    const ctx = { ...methods, selectedId: 'other-client',
      getTerminalBlockArtifactActions: () => [],
      buildTerminalJsonCommandInfo: () => ({}), }
    const actions = methods.getTerminalTailActionItems.call(ctx, lines, 2)
    assert.deepEqual(actions.map(item => item.type), state === 'Success' ? ['log', 'kill_instance'] : ['log'])
  }
})

test('log and kill actions target the originating Client after selection changes', async () => {
  commands.length = 0
  confirmResult = true
  const emitted = []
  const ctx = { ...methods, selectedId:'newly-selected-client', $emit: (...args) => emitted.push(args) }
  const actions = getTerminalReferenceActions(referenceLine('original-client'), ctx.selectedId)
  methods.handleTerminalActionClick.call(ctx, actions[0])
  assert.deepEqual(emitted, [['open-log-viewer', {
    clientId:'original-client', path:'/var/tmp/update-test.log', title:'Client update',
  }]])
  await methods.handleTerminalActionClick.call(ctx, actions[1])
  assert.deepEqual(commands, ['original-client'])
  confirmResult = false
  await methods.handleTerminalActionClick.call(ctx, actions[1])
  assert.deepEqual(commands, ['original-client'])
  confirmResult = true
})

test('Preview and View JSON share the same label/handler registry', () => {
  const emitted = []
  const ctx = { ...methods, $emit: (...args) => emitted.push(args) }
  const artifact = {artifact_id:'asset-1'}
  const preview = {type:'preview', line:{artifactInfo: artifact}}
  const json = {type:'json', line:{text:'{}'}, commandInfo:{command_name:'sample'}}
  assert.deepEqual(Object.keys(TERMINAL_RESULT_ACTIONS), ['preview', 'json', 'log', 'kill_instance'])
  assert.equal(getTerminalActionLabel(preview), 'Preview')
  assert.equal(getTerminalActionLabel(json), 'View JSON')
  methods.handleTerminalActionClick.call(ctx, preview)
  methods.handleTerminalActionClick.call(ctx, json)
  assert.deepEqual(emitted, [
    ['preview-artifact', artifact],
    ['open-json', {...json.line, jsonCommandInfo:json.commandInfo}],
  ])
})

test('SSE keeps structured References; all successful log references can notify', () => {
  assert.match(sse, /resultReferences: item\.result\.references, resultClientId: payload\.client_id/)
  assert.doesNotMatch(projector, /reference\.get\('notify'\)/)
  assert.doesNotMatch(projector, /SESSION_ACTION_REFERENCE_TYPE/)
})
