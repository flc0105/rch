import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import { remoteFileOptions, mountRemoteFileOptions } from './helpers/remote-file-options.mjs'
import { buildRemoteBreadcrumbItems } from '../src/utils/remotePaths.js'

const source = name => readFileSync(new URL(`../src/components/${name}.vue`, import.meta.url), 'utf8')
const messages = { warning() {}, error() {}, success() {} }
const plain = value => JSON.parse(JSON.stringify(value))
const deferred = () => { let resolve, reject; const promise = new Promise((a,b)=>{resolve=a;reject=b}); return {promise,resolve,reject} }
const reply = (path, entries = []) => ({ok:true,json:async()=>({code:0,data:{current_path:path,parent_path:'/',entries,pagination:{page:1,total_visible:entries.length}}})})
function mount(name, extra = {}, env = {}) {
  return mountRemoteFileOptions(remoteFileOptions(name, {OPEN_TRANSFER_CENTER_KEY:'transfer',ElMessage:messages,...env}), {
    visible:true, selectedId:'device-a', remoteFilesClientId:'device-a', selectionMode:'file', $emit(){}, ...extra,
  })
}

test('Browser and Picker use the same four behavior modules, with scoped management and common view components', () => {
  const browser = source('RemoteFilesDialog'), picker = source('RemoteFilePicker')
  for (const name of ['useRemoteDirectory','useRemoteFileSelection','useRemoteUpload','useRemoteFolderCreation']) {
    for (const content of [browser,picker]) assert.match(content,new RegExp(`import ${name} from`))
  }
  for (const name of ['useRemoteBatchUpload','useRemoteFileOperations','useRemotePinnedPaths']) assert.ok(!picker.includes(name))
  for (const content of [source('RemoteFileList'),picker]) assert.match(content,/<RemoteDirectoryTable\b/)
  for (const content of [source('RemoteFilesToolbar'),picker]) {
    assert.match(content,/<RemoteFileNavigation\b/)
    assert.match(content,/<RemoteSystemJumpItems\b/)
  }
  for (const content of [source('RemoteFileList'),picker]) assert.doesNotMatch(content,/<el-table-column label="Name"/)
  assert.match(source('RemoteDirectoryTable'),/<el-table-column label="Name"/)
})

test('directory requests cancel only within their own window; late replies cannot replace current data', async()=>{
  const pending=[], errors=[]
  const env={ElMessage:{...messages,error:e=>errors.push(e)},listRemoteDirectory:(id,params,opts)=>{
    const d=deferred();pending.push({...d,id,params,signal:opts.signal});return d.promise
  }}
  const browser=mount('RemoteFilesDialog',{},env), picker=mount('RemoteFilePicker',{},env)
  const first=browser.loadRemoteDirectory('/old'), other=picker.loadRemoteDirectory('/picker'), latest=browser.loadRemoteDirectory('/new')
  assert.equal(pending[0].signal.aborted,true);assert.equal(pending[1].signal.aborted,false)
  pending[0].reject(new Error('late failure'));await first
  assert.equal(browser.remoteFilesLoading,true);assert.deepEqual(errors,[])
  pending[2].resolve(reply('/new'));await latest
  pending[1].resolve(reply('/picker'));await other
  assert.equal(browser.remoteFilesCurrentPath,'/new');assert.equal(picker.remoteFilesCurrentPath,'/picker')
  const close=picker.loadRemoteDirectory('/late');picker.resetPicker();pending[3].resolve(reply('/late'));await close
  assert.equal(pending[3].signal.aborted,true);assert.equal(picker.remoteFilesCurrentPath,'');assert.equal(picker.remoteFilesLoading,false)
  assert.equal(browser.remoteFilesCurrentPath,'/new')
})

test('folder picker filters files, file picker cannot select folders, and Browser selection is independent',()=>{
  const rows=[{name:'a',path:'/a',is_dir:false},{name:'b',path:'/b',is_dir:true}]
  const browser=mount('RemoteFilesDialog',{remoteFilesEntries:rows,remoteFilesParentPath:'/'})
  const picker=mount('RemoteFilePicker',{remoteFilesEntries:rows,remoteFilesParentPath:'/',selectionMode:'folder',multiple:true})
  assert.deepEqual(plain(picker.displayRemoteFilesEntries.map(r=>r.path)),['/','/b'])
  picker.handleRemoteSelectionChange(rows);browser.handleRemoteSelectionChange(rows)
  assert.deepEqual(plain(picker.remoteSelectedPaths),['/b']);assert.deepEqual(plain(browser.remoteSelectedPaths),['/a','/b'])
  picker.selectionMode='file';picker.handleRemoteSelectionChange(rows);assert.deepEqual(plain(picker.remoteSelectedPaths),['/a'])
  browser.remoteSearchKeyword='a';assert.equal(browser.displayRemoteFilesEntries.some(r=>r.is_parent_entry),false)
  browser.clearRemoteSelection();assert.deepEqual(plain(picker.remoteSelectedPaths),['/a'])
})

test('shared breadcrumb builder handles POSIX and Windows paths',()=>{
  assert.deepEqual(buildRemoteBreadcrumbItems('/a/b').map(x=>x.path),['/','/a','/a/b'])
  assert.deepEqual(buildRemoteBreadcrumbItems('C:\\Users\\me').map(x=>x.path),['C:\\','C:\\Users','C:\\Users\\me'])
})

test('Browser switching target clears clipboard and pin state; pins cannot rebind an open Browser',async()=>{
  const pinned=[]
  const browser=mount('RemoteFilesDialog',{selectedId:'device-b',remoteClipboardPaths:['/old'],remoteClipboardMode:'copy',remotePinnedJumpItems:[{path:'/old'}],remoteZipCreating:true,
    loadQuickJumpPaths(){},loadPinnedQuickJumps(){pinned.push(this.remoteFilesClientId)},loadRemoteDirectory:async()=>{}})
  await browser.open('/new')
  assert.equal(browser.remoteFilesClientId,'device-b');assert.equal(browser.remoteClipboardPaths.length,0)
  assert.equal(browser.remotePinnedJumpItems.length,0);assert.equal(browser.remoteZipCreating,false)
  browser.selectedId='device-c';browser.openPinnedQuickJumpManager()
  assert.equal(browser.remoteFilesClientId,'device-b');assert.deepEqual(pinned,['device-b','device-b'])
})

test('late path prompt cannot navigate a newly opened picker',async()=>{
  const prompt=deferred(), nav=[]
  const picker=mount('RemoteFilePicker',{navigateRemoteDirectory:async path=>nav.push(path)},{ElMessageBox:{prompt:()=>prompt.promise}})
  const pending=picker.promptRemotePathNavigate();picker.resetPicker();picker.selectedId='device-b';prompt.resolve({value:'/old'});await pending
  assert.deepEqual(nav,[]);assert.equal(picker.remoteFilesPathInput,'')
})

test('shared upload preflight cannot submit into a stale target',async()=>{
  const conflict=deferred();let submissions=0
  const picker=mount('RemoteFilePicker',{remoteFilesCurrentPath:'/old'},{prepareUploadConflict:()=>conflict.promise,uploadRemoteFileToClient:async()=>{submissions++}})
  const pending=picker.submitRemoteFile({name:'a.txt'},'remote_file_picker');picker.resetPicker();picker.selectedId='device-b';picker.remoteFilesCurrentPath='/new'
  conflict.resolve('replace');assert.equal(await pending,false);assert.equal(submissions,0);assert.equal(picker.remoteUploadLoading,false)
})

test('file-list event and selection methods forward arguments without interpreting operations',()=>{
  const script=source('RemoteFileList').match(/<script>([\s\S]*?)<\/script>/)[1].replace(/^import .*$/gm,'').replace('export default','')
  const options=vm.runInNewContext(`(${script})`,{RemoteDirectoryTable:{},RemoteFileEntryIcon:{},EllipsisVertical:{},remoteActionIcon(){},isZipEntry(){},formatBytesValue(){}})
  const calls=[], row={path:'/test'}
  const ctx={$emit:(...args)=>calls.push(args),$refs:{remoteFilesTableRef:{clearSelection:()=>calls.push(['clear']),toggleRowSelection:(...args)=>calls.push(['toggle',...args])}}}
  options.methods.handleRemoteMoreAction.call(ctx,'copy_to',row)
  options.methods.handleRemoteSelectionChange.call(ctx,[row]);options.methods.clearSelection.call(ctx);options.methods.toggleRowSelection.call(ctx,row,true)
  assert.deepEqual(calls,[['row-command','copy_to',row],['selection-change',[row]],['clear'],['toggle',row,true]])
})


test('Browser table, mobile card/list and Picker share Lucide file icons and action icons', () => {
  const table = source('RemoteDirectoryTable'), list = source('RemoteFileList')
  assert.match(table, /<RemoteFileEntryIcon :entry="row"/)
  assert.equal((list.match(/<RemoteFileEntryIcon :entry="row"/g) || []).length, 2)
  assert.match(source('RemoteFileEntryIcon'), /from '@lucide\/vue'/)
  assert.match(source('RemoteFileEntryIcon'), /<FolderUp v-if="entry.is_parent_entry"/)
  assert.match(source('RemoteFilesToolbar'), /<Ellipsis :size="19"/)
  assert.match(list, /<EllipsisVertical/)
  assert.match(source('RemoteFilePagination'), /<ChevronLeft/)
  assert.match(source('RemoteFilePagination'), /<ChevronRight/)
  assert.match(source('RemoteFileNavigation'), /<ChevronRight/)
  for (const component of ['RemoteFilesToolbar', 'RemoteFileList', 'RemoteFilePicker', 'RemoteSystemJumpItems']) {
    const content = source(component)
    assert.match(content, /:icon="remoteActionIcon\(/)
    assert.doesNotMatch(content, /@element-plus\/icons-vue|📁|📄|⋮/)
  }
})
