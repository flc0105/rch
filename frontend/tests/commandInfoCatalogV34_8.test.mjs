import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import {resolve,dirname} from 'node:path'
import {fileURLToPath} from 'node:url'
import test from 'node:test'
import vm from 'node:vm'
const dir=dirname(fileURLToPath(import.meta.url))
const info=readFileSync(resolve(dir,'../src/components/ConnectionInfoDialogs.vue'),'utf8')
const terminal=readFileSync(resolve(dir,'../src/components/CommandInputBar.vue'),'utf8')
const match=info.match(/visibleConnectionCommands\(\) \{([\s\S]*?)\n    \},\n\n    connectionInfoCards\(/)
assert.ok(match,'Computed catalog must exist')
const filter=vm.runInNewContext('(function(){'+match[1]+'\n})')
test('client commands sort by group then name, case-insensitively and without changing source',()=>{
 const items=[{group:'shell',name:'Zebra'},{group:'file',name:'zulu'},{group:'File',name:'Alpha'},{group:'runtime',name:'A'}]
 const ctx={connectionCommandSource:'client',connectionInfoClientCommands:items,connectionInfoServerCommands:[],connectionCommandSearch:''}
 assert.deepEqual(Array.from(filter.call(ctx),x=>x.name),['Alpha','zulu','A','Zebra'])
 assert.equal(items[0].name,'Zebra')
})
test('search is scoped to selected command source and case insensitive',()=>{
 const ctx={connectionCommandSource:'server',connectionInfoClientCommands:[{name:'help',help:'client'}],connectionInfoServerCommands:[{name:'script',help:'Server script'},{name:'job',help:'Manage jobs'}],connectionCommandSearch:'SCRIPT'}
 assert.deepEqual(Array.from(filter.call(ctx),x=>x.name),['script'])
 ctx.connectionCommandSource='client'
 assert.equal(filter.call(ctx).length,0)
 ctx.connectionCommandSearch=''
 assert.equal(filter.call(ctx).length,1)
})
test('server hides group only; search and source remain in compact title, terminal has no pathname fallback',()=>{
 assert.match(info,/v-if="connectionCommandSource === 'client' && item.group"/)
 assert.match(info,/v-model="connectionCommandSearch"/)
 assert.match(info,/class="connection-command-heading-controls"/)
 assert.doesNotMatch(terminal,/filterExecScriptCandidatesByCurrentOs/)
 assert.doesNotMatch(terminal,/getExecScriptRoot/)
 assert.match(terminal,/Server\./)
})
