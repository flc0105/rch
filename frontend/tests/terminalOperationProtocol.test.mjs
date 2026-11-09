import assert from 'node:assert/strict'
import { test } from 'node:test'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import { createTerminalOperation, getTerminalReplayAction, operationHeaders } from '../src/utils/terminalOperation.js'
import { canRerunTerminalSource } from '../src/utils/terminalRerun.js'
import { isJsonContainerText, isJsonStartLine, parseJsonLines, jsonBracketDelta } from '../src/utils/terminalJson.js'

const read = path => readFileSync(new URL(path, import.meta.url), 'utf8')
const factory = (source, imports) => {
  const js = source.replace(/<script>([\s\S]*?)<\/script>/, '<<<script>>>$1<<<end>>>')
  const body = js.includes('<<<script>>>') ? js.split('<<<script>>>')[1].split('<<<end>>>')[0] : source
  const sandbox = { ...imports }
  vm.runInNewContext(body.replace(/^import\s+[\s\S]*?\s+from\s+['"][^'"]+['"]\s*;?\s*$/gm, '')
    .replace('export default {','globalThis.component = {'), sandbox)
  return sandbox.component
}

function makeModel() {
  const output = factory(read('../src/composables/useTerminalOutput.js'), {
    isJsonContainerText, isJsonStartLine, parseJsonLines, jsonBracketDelta,
    TERMINAL_BACKGROUND_PREFIX: '[Background]',
    isTerminalCancelRequestedText:()=>false, isTerminalCommandFailedText:()=>false,
    isTerminalCommandFinishedText:()=>false,
  })
  const state = { ...output.data(), scrollToBottom() {}, selectedId:'client-a' }
  for (const [name, value] of Object.entries(output.methods)) state[name] = value.bind(state)
  state.scrollToBottom = () => {}
  const render = factory(read('../src/components/TerminalOutput.vue'), {
    canRerunTerminalSource, getTerminalReplayAction, TerminalLinkedText: {},
    isTerminalRemoteUploadText:()=>false,
    isTerminalCommandFinishedText:text=>String(text).startsWith('[Command finished]'),
    TERMINAL_FILE_READY_PREFIX:'[File Ready]', TERMINAL_RUN_SCRIPT_PREFIX:'[Run Script]',
  })
  const view = { lines:[], ...render.data() }
  for (const [name, value] of Object.entries(render.methods)) view[name] = value.bind(view)
  const blocks = () => { view.lines=state.outputs['client-a']||[]; return render.computed.terminalBlocks.call(view) }
  return { state, view, blocks }
}

test('typed operations have independent identity and explicit replay payload', () => {
  const a=createTerminalOperation({kind:'command',action:'invoke',clientId:'client-a',
    invocation:{input:'echo hello'},replay:{type:'command',command:'echo hello'}})
  const b=createTerminalOperation({kind:'transfer',action:'upload_files',clientId:'client-a',
    invocation:{source:'artifact_send',artifact_id:'id'},replay:null})
  assert.notEqual(a.operation_id,b.operation_id)
  assert.match(a.operation_id,/^[0-9a-f-]{36}$/)
  assert.deepEqual(getTerminalReplayAction(a),{type:'command',command:'echo hello'})
  assert.equal(getTerminalReplayAction(b),null)
  assert.equal(canRerunTerminalSource({operation:b}),false)
  assert.equal(operationHeaders(a,{'X-Tab-Id':'tab-1'})['X-RCH-Operation-ID'],a.operation_id)
  assert.equal(getTerminalReplayAction({replay:{type:'command',command:''}}),null)
  assert.equal(getTerminalReplayAction({replay:{type:'script',script_name:''}}),null)
})

test('interleaved same-text operations group by UUID, never by visible command', () => {
  const {state,view,blocks}=makeModel()
  const mk = () => createTerminalOperation({kind:'command',action:'invoke',clientId:'client-a',
    invocation:{input:'echo identical'},replay:{type:'command',command:'echo identical'}})
  const a=mk(), b=mk()
  state.appendOutput('client-a','> echo identical','command',{operation:a})
  state.appendOutput('client-a','> echo identical','command',{operation:b})
  state.appendOutput('client-a','out A','normal',{operation_id:a.operation_id,task_id:'task-a',event_type:'output'})
  state.appendOutput('client-a','out B','normal',{operation_id:b.operation_id,task_id:'task-b',event_type:'output'})
  state.appendOutput('client-a','[Command finished] echo identical (Success)','success',
    {operation_id:b.operation_id,event_type:'completed',execution_success:true,execution_status:'success'})
  state.appendOutput('client-a','[Command finished] echo identical (Failed)','error',
    {operation_id:a.operation_id,event_type:'completed',execution_success:false,execution_status:'failed'})
  const groups=blocks()
  assert.equal(groups.length,2)
  assert.notEqual(groups[0].key,groups[1].key)
  assert.deepEqual(Array.from(groups,g=>g.lines.length),[3,3])
  assert.equal(groups[0].lines[1].line.text,'out A')
  assert.equal(groups[1].lines[1].line.text,'out B')
  assert.equal(state.terminalOperationRegistry[a.operation_id].status,'error')
  assert.equal(state.terminalOperationRegistry[b.operation_id].status,'success')
  assert.equal(groups[0].taskId,'task-a')
  assert.equal(groups[1].taskId,'task-b')
  assert.equal(view.canRerunTerminalBlock(groups[0]),true)
  assert.equal(view.getTerminalBlockReplayCommand(groups[0]),'echo identical')
  assert.deepEqual(Array.from(view.getTerminalCommandGroupLines(view.lines,3),line=>line.text),
    ['> echo identical','out B'])
})

test('script replay stays typed, upload is never interpreted as shell, output JSON is scoped', () => {
  const {state,view,blocks}=makeModel()
  const script=createTerminalOperation({kind:'script',action:'run',clientId:'client-a',
    replay:{type:'script',script_name:'diagnostics/check',params:{n:2}}})
  const upload=createTerminalOperation({kind:'transfer',action:'upload_files',clientId:'client-a',replay:null})
  state.appendOutput('client-a','> [Run Script] check','command',{operation:script})
  state.appendOutput('client-a','{','normal',{operation_id:script.operation_id})
  state.appendOutput('client-a','> [Remote Upload] data.zip -> /tmp','command',{operation:upload})
  state.appendOutput('client-a','"success": true','normal',{operation_id:script.operation_id})
  state.appendOutput('client-a','}','normal',{operation_id:script.operation_id})
  state.appendOutput('client-a','[+] Uploaded','success',{operation_id:upload.operation_id})
  const groups=blocks()
  assert.equal(groups.length,2)
  assert.equal(groups[0].blockType,'script')
  assert.equal(groups[1].blockType,'remote_upload')
  assert.equal(view.canRerunTerminalBlock(groups[0]),true)
  assert.equal(view.canRerunTerminalBlock(groups[1]),false)
  assert.equal(view.getTerminalBlockReplayCommand(groups[1]),'')
  const jsonLines=groups[0].lines.map(x=>x.line).filter(x=>x.isJsonMessage)
  assert.equal(jsonLines.length,1)
  assert.equal(JSON.parse(jsonLines[0].jsonText).success,true)
  state.clearOutput()
  assert.equal(Object.keys(state.terminalOperationRegistry).length,0)
})

test('typed completion is determined by event type, not a command-looking output string', () => {
  const { state, view, blocks } = makeModel()
  const op = createTerminalOperation({ kind:'command', action:'invoke', clientId:'client-a',
    invocation:{input:'printf'}, replay:{type:'command',command:'printf'} })
  state.appendOutput('client-a','> printf','command',{operation:op})
  state.appendOutput('client-a','[Command finished] this is stdout, not completion','normal',
    {operation_id:op.operation_id,event_type:'output'})
  state.appendOutput('client-a','[Command finished] printf (Success)','success',
    {operation_id:op.operation_id,event_type:'completed',execution_status:'success',execution_success:true})
  const [block] = blocks()
  assert.equal(view.isCommandFinishedLine(block.lines[1].line),false)
  assert.equal(view.isCommandFinishedLine(block.lines[2].line),true)
  assert.match(view.getTerminalBlockOutputText(block), /this is stdout/)
  assert.doesNotMatch(view.getTerminalBlockOutputText(block), /printf \(Success\)/)
})

test('non-command operation starts keep >, without adding a shell $ prompt', () => {
  const {state, view, blocks}=makeModel()
  for (const [kind, title] of [
    ['transfer','[Remote Upload] sample.zip -> /tmp'],
    ['script','[Run Script] diagnostics'],
    ['alias','cwd'],
    ['transfer','[Artifact Send] report -> MacBook'],
  ]) {
    const op=createTerminalOperation({kind,action:'invoke',clientId:'client-a',replay:null})
    state.appendOutput('client-a',`> ${title}`,'command',{operation:op})
    assert.equal(view.getTerminalBlockDisplayTitle(blocks().at(-1)), `> ${title}`)
  }
  assert.equal(view.canRerunTerminalBlock(blocks()[0]), false)
  assert.match(read('../src/components/TerminalOutput.vue'), /v-if="!block.operation \|\| block.operation.kind === 'command'" class="terminal-prefix">\$/)
})


test('output-free Quick Action still offers Run again while upload does not', () => {
  const {state, view, blocks} = makeModel()
  const alias = createTerminalOperation({kind:'alias',action:'invoke',clientId:'client-a',
    replay:{type:'alias',alias:'silent',platform:'mac',arguments:[]}})
  state.appendOutput('client-a','> silent','command',{operation:alias})
  state.appendOutput('client-a','[Command finished] silent (Success)','success',{
    operation_id:alias.operation_id,event_type:'completed',execution_success:true,execution_status:'success',
  })
  const block = blocks()[0]
  assert.equal(view.hasTerminalBlockOutput(block), false)
  assert.equal(view.canRerunTerminalBlock(block), true)
  assert.equal(view.canUseTerminalBlockActions(block), true)
})
