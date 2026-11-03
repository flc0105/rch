import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import {
  getScriptCatalog, runLibraryScript, createScriptFolder, renameScriptFolder,
  deleteScriptFolder, renameLibraryScript, uploadLibraryScript, deleteLibraryScript,
} from '../src/api/scriptLibraryApi.js'
import {
  getCommandHistory, getCommandExecutionEntry, fetchQuickCommandHistory,
  fetchCommandActivities, pinHistoryCommand, movePinnedHistoryCommand,
  deleteCommandActivity, clearQuickHistory, clearCommandActivities,
} from '../src/api/commandHistoryApi.js'

const mockResponse = { ok: true, json: async () => ({code: 0, data: [{command:'ls'}]}) }
async function capture(fn) {
  const calls = []
  const original = globalThis.fetch
  globalThis.fetch = async (url, options = {}) => {
    calls.push({url, options})
    return mockResponse
  }
  try {
    const result = await fn()
    assert.equal(calls.length, 1, 'API action must produce exactly one request')
    return {...calls[0], result}
  } finally {
    globalThis.fetch = original
  }
}
function bodyOf(call) { return JSON.parse(call.options.body) }

test('script catalog and folder CRUD retain URL, methods and payloads', async () => {
  const catalog = await capture(getScriptCatalog)
  assert.equal(catalog.url, '/api/scripts/catalog')
  assert.equal(catalog.options.method, undefined)
  const paths = [
    [() => createScriptFolder('a/资料'), '/api/scripts/folders', 'POST', {directory:'a/资料'}],
    [() => renameScriptFolder('a', 'b'), '/api/scripts/folders/rename', 'POST', {directory:'a',new_directory:'b'}],
    [() => deleteScriptFolder('a/资料'), '/api/scripts/folders', 'DELETE', {directory:'a/资料'}],
    [() => renameLibraryScript('a.py', 'b.py'), '/api/scripts/rename', 'POST', {name:'a.py',new_name:'b.py'}],
    [() => deleteLibraryScript('script'), '/api/scripts/delete', 'DELETE', {name:'script'}],
  ]
  for (const [run, url, method, payload] of paths) {
    const call = await capture(run)
    assert.equal(call.url,url)
    assert.equal(call.options.method,method)
    assert.equal(call.options.headers['Content-Type'],'application/json')
    assert.deepEqual(bodyOf(call),payload)
  }
})

test('script execution preserves terminal/dialog presentation, run ID and scoped headers', async () => {
  const id = 'client A/B'
  const base = `/api/connections/${encodeURIComponent(id)}/scripts/run`
  const params = {path:'C:\\Some Folder', values:[1,2]}
  const headers = {'Content-Type':'application/json','X-RCH-Tab-ID':'t-123'}
  for (const payload of [
    { script_name:'folder/run', params, presentation:'terminal' },
    { script_name:'folder/run', params, presentation:'dialog', run_id:'run-abc' },
  ]) {
    const call = await capture(() => runLibraryScript(id, payload, headers))
    assert.equal(call.url,base)
    assert.equal(call.options.method,'POST')
    assert.deepEqual(call.options.headers,headers)
    assert.deepEqual(bodyOf(call),payload)
  }
})

test('script multipart upload keeps FormData unchanged, without a JSON content type', async () => {
  const formData = new FormData()
  formData.append('directory','folder name')
  formData.append('file',new Blob(['print(1)']), 'hello.py')
  const call = await capture(() => uploadLibraryScript(formData))
  assert.equal(call.url,'/api/scripts/upload')
  assert.equal(call.options.method,'POST')
  assert.strictEqual(call.options.body,formData)
  assert.equal(call.options.headers,undefined)
})

test('command history queries encode machine and activity IDs and preserve pagination order', async () => {
  const machine='host/台'
  const base=`/api/machines/${encodeURIComponent(machine)}/command-history`
  const quick = await capture(() => fetchQuickCommandHistory(machine))
  assert.equal(quick.url,base)
  const first = await capture(() => fetchCommandActivities(machine, {query:'a + b', kind:'script', errors:true}))
  assert.equal(first.url,`${base}/full?limit=50&query=a+%2B+b&kind=script&errors=true`)
  const next = await capture(() => fetchCommandActivities(machine, {
    cursor:'cursor/1',query:'a + b',kind:'script',errors:true,
  }))
  assert.equal(next.url,`${base}/full?limit=50&cursor=cursor%2F1&query=a+%2B+b&kind=script&errors=true`)
  const detail = await capture(() => getCommandExecutionEntry(machine, 'activity/1'))
  assert.equal(detail.url,`${base}/full/activity%2F1`)
  assert.deepEqual(detail.result,[{command:'ls'}])
  const useInCompletion = await capture(() => getCommandHistory(machine))
  assert.equal(useInCompletion.url,base)
  assert.deepEqual(useInCompletion.result,[{command:'ls'}])
  assert.deepEqual(await getCommandHistory(''),[])
})

test('pin, reorder, delete and scoped clears preserve exact history API contracts', async () => {
  const base='/api/machines/m%2F1/command-history'
  const cases = [
    [() => pinHistoryCommand('m/1','echo ok', true), '/pin', 'POST', {command:'echo ok',is_pinned:true}],
    [() => movePinnedHistoryCommand('m/1','echo ok','down'), '/pin/move', 'POST', {command:'echo ok',direction:'down'}],
  ]
  for (const [run,suffix,method,body] of cases) {
    const call = await capture(run)
    assert.equal(call.url,base+suffix)
    assert.equal(call.options.method,method)
    assert.deepEqual(bodyOf(call),body)
  }
  const del = await capture(() => deleteCommandActivity('m/1','activity#1'))
  assert.equal(del.url,`${base}/full/activity%231`)
  assert.equal(del.options.method,'DELETE')
  const clearQuick = await capture(() => clearQuickHistory('m/1', 'deploy me'))
  assert.equal(clearQuick.url,`${base}?query=deploy+me`)
  assert.equal(clearQuick.options.method,'DELETE')
  const clearQuickAll = await capture(() => clearQuickHistory('m/1'))
  assert.equal(clearQuickAll.url,base)
  const full = await capture(() => clearCommandActivities('m/1',{kind:'external_tool',errors:true,query:'abc'}))
  assert.equal(full.url,`${base}/full?kind=external_tool&errors=true&query=abc`)
  assert.equal(full.options.method,'DELETE')
  const fullAll = await capture(() => clearCommandActivities('m/1'))
  assert.equal(fullAll.url,`${base}/full`)
})

test('dialogs consume feature APIs and the old generic connection module has no history entry points', () => {
  const component = name => readFileSync(new URL(`../src/components/${name}`,import.meta.url),'utf8')
  for (const name of ['ScriptLibraryDialog.vue','CommandHistoryDialog.vue']) {
    const source = component(name)
    assert.match(source, /from ['"]\.\.\/api\/(?:scriptLibrary|commandHistory)Api\.js['"]/)
    assert.doesNotMatch(source.split('    // async clearCommandHistory()')[0], /\bfetch\s*\(/)
  }
  const connections = readFileSync(new URL('../src/api/connectionsApi.js',import.meta.url),'utf8')
  assert.doesNotMatch(connections,/export function getCommandHistory\(|export function getCommandExecutionEntry\(/)
  assert.match(component('CommandInputBar.vue'), /from ['"]\.\.\/api\/commandHistoryApi\.js['"]/) 
})
