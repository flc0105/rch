import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import vm from 'node:vm'
import {test} from 'node:test'

const read = path => readFileSync(new URL(path, import.meta.url), 'utf8')
const source = read('../src/components/CommandHistoryDialog.vue')
const script = source.match(/<script>([\s\S]*?)<\/script>/)[1]
const mockIcons = Object.fromEntries([...script.matchAll(/import\s*\{([^}]*)\}\s*from\s*['"][^'"]+['"];?/g)]
  .flatMap(m => m[1].split(',').map(v => v.trim()).filter(Boolean)).map(k => [k, {}]))

function historyInstance({tab='quick', kind='', errors=false, query=''} = {}) {
  const requests = [], prompts = [], notices = []
  const fetch = async (url, config = {}) => {
    requests.push({url, method:config.method || 'GET'})
    return {ok:true, json:async()=>({code:0,data:{items:[],total_count:0,has_more:false}})}
  }
  const ElMessage = {success:msg => notices.push(msg), error:msg=>{throw Error(msg)}, warning:msg=>{throw Error(msg)}}
  const ElMessageBox = {confirm:async(...args)=>{prompts.push(args)}}
  const ctx = {...mockIcons, ElMessage, ElMessageBox, CommandExecutionDetailDialog:{}, diffDateTimeMs(){}, fetch, URLSearchParams, window: { clearTimeout() {} }}
  vm.runInNewContext(script.replace(/^import\s+[\s\S]*?\s+from\s+['"][^'"]+['"];?\s*$/gm,'')
    .replace('export default {','const options = {') + '\nglobalThis.options = options', ctx)
  const options = ctx.options
  const inst = {...options.data(), ...options.methods,
    commandHistoryActiveTab:tab, activityKindFilter:kind, activityErrorsOnly:errors,
    commandHistorySearchText:query, selectedId:'c-1', currentConnection:{machine_id:'m-1'},
  }
  return {inst, requests, prompts, notices, options}
}

test('History Refresh requests only the selected tab', async () => {
  const a=historyInstance()
  await a.inst.refreshActiveHistory()
  assert.deepEqual(a.requests.map(req=>req.url), ['/api/machines/m-1/command-history'])
  const b=historyInstance({tab:'full',kind:'transfer',errors:true})
  await b.inst.refreshActiveHistory()
  assert.equal(b.requests.length,1)
  assert.match(b.requests[0].url,/\/command-history\/full\?/) 
  assert.match(b.requests[0].url,/kind=transfer/)
  assert.match(b.requests[0].url,/errors=true/)
})

test('Quick Clear affects only Quick Recent; Activity Clear follows type, errors and search scope', async () => {
  const a=historyInstance()
  await a.inst.clearCommandHistory()
  assert.deepEqual(a.requests.filter(req=>req.method==='DELETE'), [{url:'/api/machines/m-1/command-history',method:'DELETE'}])
  assert.equal(a.prompts[0][1],'Clear Quick History')
  assert.match(a.prompts[0][0],/Pinned commands will be kept/)
  const b=historyInstance({tab:'full',kind:'external_tool',errors:true,query:'deploy'})
  await b.inst.clearCommandHistory()
  assert.equal(b.prompts[0][1], 'Clear Activities')
  assert.match(b.prompts[0][0],/external tool activities with errors matching “deploy”/)
  const del=b.requests.filter(req=>req.method==='DELETE')
  assert.equal(del.length,1)
  assert.equal(del[0].url, '/api/machines/m-1/command-history/full?kind=external_tool&errors=true&query=deploy')
  assert.ok(b.requests.every(req=>!req.url.endsWith('/command-history')))
  const all=historyInstance({tab:'full'})
  await all.inst.clearCommandHistory()
  assert.match(all.prompts[0][0],/all activities for the current device/)
  assert.equal(all.requests[0].url,'/api/machines/m-1/command-history/full')
})

test('Quick Clear with search only sends matching query, preserves search text and explains pinned retention', async () => {
  const a=historyInstance({tab:'quick', query:'DEPLOY'})
  await a.inst.clearCommandHistory()
  const del=a.requests.filter(req=>req.method==='DELETE')
  assert.equal(del.length,1)
  assert.equal(del[0].url,'/api/machines/m-1/command-history?query=DEPLOY')
  assert.match(a.prompts[0][0],/matching “DEPLOY”/)
  assert.match(a.prompts[0][0],/Pinned commands will be kept/)
  assert.equal(a.inst.commandHistorySearchText, 'DEPLOY')
  const b=historyInstance({tab:'full',errors:true,query:'timeout'})
  await b.inst.clearCommandHistory()
  assert.match(b.prompts[0][0],/activities with errors matching “timeout”/)
  assert.equal(b.requests[0].url,'/api/machines/m-1/command-history/full?errors=true&query=timeout')
})

test('Activity clearing refreshes a pending search before offering its scoped confirmation', async () => {
  const a=historyInstance({tab:'full',kind:'script',errors:true,query:'deploy'})
  a.inst.commandHistorySearchTimer = 123
  await a.inst.clearCommandHistory()
  assert.equal(a.requests[0].method, 'GET')
  assert.match(a.requests[0].url, /query=deploy&kind=script&errors=true/)
  assert.equal(a.requests[1].method, 'DELETE')
  assert.match(a.prompts[0][0], /script activities with errors matching “deploy”/)
})

test('Activity list already filtered by server remains visible with search term', () => {
  const a=historyInstance({tab:'full',query:'foo'})
  a.inst.commandExecutionItems = [{activity_id:'one',action:'run',invocation:{input:'foo'}}]
  assert.equal(a.options.computed.filteredCommandExecutionItems.call(a.inst).length,1)
  assert.match(source, /Clear Quick History.*Clear Activities/)
})
