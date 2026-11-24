import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import { answerInteraction } from '../src/api/interactionApi.js'

const read = file => readFileSync(new URL(file, import.meta.url), 'utf8')
const plain = value => JSON.parse(JSON.stringify(value))
const component = (file, env = {}) => vm.runInNewContext(`(${read(file).match(/<script>([\s\S]*?)<\/script>/)[1].replace(/^import .*$/gm, '').replace('export default', '')})`, env)
function instance(c, extra = {}) {
  const o = { ...c.data(), ...extra }
  for (const [k, v] of Object.entries(c.methods || {})) if (!(k in extra)) o[k] = v.bind(o)
  for (const [k, v] of Object.entries(c.computed || {})) Object.defineProperty(o, k, { get: () => v.call(o) })
  return o
}
const messages = { success() {}, info() {}, warning() {}, error(e) { throw Error(e) } }

test('manual input and Save keep the typed endpoint', async () => {
  const calls = [], events = []
  const c = component('../src/components/ConnectToClientDialog.vue', {
    saveBindTarget: async (...args) => calls.push(args),
    ElMessage:messages,
  })
  const o = instance(c, {$emit: (...args) => events.push(args)})
  o.visible = true
  o.form = {host:' example.test ',port:'9555',name:' Test ',serverWebBaseUrl:'http://localhost:8085'}
  o.targetId = 'saved-target'
  await o.save()
  assert.deepEqual(calls,[['example.test',9555,'http://localhost:8085','Test','saved-target']])
  assert.deepEqual(events,[['saved']]); assert.equal(o.visible,false)
  o.form.port = '65536'
  await o.save()
  assert.equal(calls.length,1)
})

test('stale HTTP answer preserves HTTP conflict status', async t => {
  t.mock.method(globalThis, 'fetch', async () => ({ok:false,status:409,json:async()=>({code:1,message:'Interaction not pending or already answered'})}))
  await assert.rejects(answerInteraction('id',{approved:false}), e=>e.status===409)
})

for (const approved of [false,true]) test(`expired preview closes on ${approved?'Approve':'Reject'} without dropping other queued requests`, async () => {
  const warnings=[]
  const c=component('../src/components/ExecutionInteractionDialog.vue',{
    answerInteraction:async()=>{throw Object.assign(Error('Interaction not pending or already answered'),{status:409})},
    ElMessage:{warning:msg=>warnings.push(msg)},
  })
  const o=instance(c)
  o.enqueue({interaction_id:'stale',kind:'preview',preview:{}})
  o.enqueue({interaction_id:'next',kind:'input'})
  await o.submit(approved)
  assert.equal(o.current.interaction_id,'next'); assert.equal(o.submitting,false); assert.equal(o.errorText,''); assert.equal(warnings.length,1)
})

test('normal validation/network errors remain retryable; unrelated resolved event keeps current draft',async()=>{
  let fail=true
  const c=component('../src/components/ExecutionInteractionDialog.vue',{
    answerInteraction:async()=>{if(fail)throw Object.assign(Error('network error'),{status:500})},ElMessage:messages,
  })
  const o=instance(c); o.enqueue({interaction_id:'current',kind:'input'}); o.enqueue({interaction_id:'other',kind:'confirm'})
  o.inputValue='draft'; o.resolved({interaction_id:'other'}); assert.equal(o.inputValue,'draft')
  await o.submit(true); assert.equal(o.current.interaction_id,'current'); assert.equal(o.errorText,'network error')
  fail=false; await o.submit(true); assert.equal(o.current,null)
})

test('reconnect pending snapshot removes stale entries but retains newly arrived SSE requests',async()=>{
  let resolve
  const c=component('../src/components/ExecutionInteractionDialog.vue',{listPendingInteractions:()=>new Promise(r=>{resolve=r}),ElMessage:messages})
  const o=instance(c); o.enqueue({interaction_id:'stale',tab_id:'tab',kind:'confirm'}); o.enqueue({interaction_id:'resolved-during-load',tab_id:'tab',kind:'confirm'})
  const reload=o.reloadPending('tab'); o.resolved({interaction_id:'resolved-during-load'}); o.enqueue({interaction_id:'new',tab_id:'tab',kind:'confirm'})
  resolve([{interaction_id:'resolved-during-load',tab_id:'tab',kind:'confirm'}]); await reload
  assert.deepEqual(plain(o.queue.map(x=>x.interaction_id)),['new'])
})

function folderHelper(env) {
  const s=read('../src/utils/remoteFolderCreation.js').replace(/^import .*$/gm,'').replace('export async function','async function')
  return vm.runInNewContext(`${s}\npromptCreateRemoteFolder`,env)
}

test('shared mkdir handles POSIX and Windows roots and Unicode, cancellation, context changes and errors',async()=>{
  const calls=[]; let cancel=false,fail=false
  const promptCreateRemoteFolder=folderHelper({ElMessageBox:{prompt:async()=>{if(cancel)throw 'cancel';return {value:'资料 folder'}}},makeRemoteDirectory:async(...args)=>{calls.push(args);return {ok:!fail,json:async()=>({code:fail?1:0,message:'already exists'})}}})
  assert.equal(await promptCreateRemoteFolder('c','/',()=>true),true)
  assert.equal(await promptCreateRemoteFolder('c','C:\\',()=>true),true)
  assert.equal(await promptCreateRemoteFolder('c','/tmp',()=>false),false)
  assert.deepEqual(calls,[['c','/资料 folder'],['c','C:\\资料 folder']])
  cancel=true; await assert.rejects(promptCreateRemoteFolder('c','/tmp',()=>true),e=>e==='cancel'); assert.equal(calls.length,2)
  cancel=false;fail=true;await assert.rejects(promptCreateRemoteFolder('c','/tmp',()=>true),/already exists/)
})

test('Picker new folder refreshes on success and does not operate without an active directory',async()=>{
  let refresh=0,created=[]
  const c=component('../src/components/RemoteFilePicker.vue',{OPEN_TRANSFER_CENTER_KEY:'transfer',ElMessage:messages,promptCreateRemoteFolder:async(id,path,active)=>{if(active())created.push([id,path]);return active()}})
  const o=instance(c,{visible:true,selectedId:'c',remoteFilesCurrentPath:'/tmp',refreshRemoteDirectory:async()=>{refresh++}})
  await o.createRemoteFolder(); assert.deepEqual(created,[['c','/tmp']]);assert.equal(refresh,1)
  o.remoteFilesCurrentPath='';await o.createRemoteFolder();assert.equal(created.length,1)
})

test('Picker discards directory responses from an old device',async()=>{
  const pending=[]
  const c=component('../src/components/RemoteFilePicker.vue',{OPEN_TRANSFER_CENTER_KEY:'transfer',ElMessage:messages,listRemoteDirectory:()=>new Promise(r=>pending.push(r))})
  const o=instance(c,{visible:true,selectedId:'old',clearTableSelection(){}})
  const a=o.loadRemoteDirectory('/old');o.selectedId='new';o.pickerContextSeq++;const b=o.loadRemoteDirectory('/new')
  const reply=path=>({ok:true,json:async()=>({code:0,data:{current_path:path,entries:[]}})})
  pending[0](reply('/old'));await a;assert.equal(o.remoteFilesCurrentPath,'');assert.equal(o.remoteFilesLoading,true)
  pending[1](reply('/new'));await b;assert.equal(o.remoteFilesCurrentPath,'/new');assert.equal(o.remoteFilesLoading,false)
})

test('Copy To and Move To share paste preflight and mutation, preserve clipboard and browser path',async()=>{
  const calls=[]; let stop=false, refresh=0
  const c=component('../src/components/RemoteFilesDialog.vue',{OPEN_TRANSFER_CENTER_KEY:'transfer',RemotePinsDialog:{},RemoteFilePicker:{},MoreFilled:{},ElMessage:messages,
    preparePasteConflicts:async(id,req)=>{calls.push(['inspect',id,plain(req)]);return stop?false:{conflict_policies:['keep_both']}},
    pasteRemoteFiles:async(id,req)=>{calls.push(['paste',id,plain(req)]);return {ok:true,json:async()=>({code:0,data:{succeeded:1,failed:0}})}},
  })
  const o=instance(c,{visible:true,remoteFilesClientId:'c',remoteFilesCurrentPath:'/src',remoteClipboardPaths:['/other'],remoteClipboardMode:'copy',refreshRemoteDirectory:async()=>{refresh++}})
  for(const cmd of ['copy_to','move_to']){o.handleRemoteMoreAction(cmd,{path:'/src/file'});assert.equal(o.destinationPickerVisible,true);await o.handleDestinationSelected('/dest')}
  assert.equal(calls.length,4);assert.equal(calls[1][2].operation,'copy');assert.equal(calls[3][2].operation,'move');assert.equal(calls[3][2].destination_dir,'/dest');assert.deepEqual(calls[3][2].conflict_policies,['keep_both'])
  assert.deepEqual(o.remoteClipboardPaths,['/other']);assert.equal(o.remoteFilesCurrentPath,'/src');assert.equal(refresh,2)
  stop=true;o.openDestinationPicker({path:'/src/file'},'copy');await o.handleDestinationSelected('/dest');assert.equal(calls.length,5)
  stop=false;o.openDestinationPicker({path:'/src/file'},'move');o.remoteFilesContextSeq++;await o.handleDestinationSelected('/dest');assert.equal(calls.length,5)
  o.remoteClipboardMode='move';o.remoteClipboardPaths=['/other'];await o.pasteRemoteClipboard();assert.equal(o.remoteClipboardPaths.length,0);assert.equal(calls[6][2].operation,'move')
  const source=read('../src/components/RemoteFilesDialog.vue');assert.equal((source.match(/command="copy_to"/g)||[]).length,3);assert.equal((source.match(/command="move_to"/g)||[]).length,3)
})
