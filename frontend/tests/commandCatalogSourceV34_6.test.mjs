import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import {dirname,resolve} from 'node:path'
import {fileURLToPath} from 'node:url'
import test from 'node:test'
import vm from 'node:vm'
const here=dirname(fileURLToPath(import.meta.url))
const read=n=>readFileSync(resolve(here,'../src/components',n),'utf8')
const input=read('CommandInputBar.vue')
const info=read('ConnectionInfoDialogs.vue')
test('Server main command script stays in top-level manifest candidates, not script-path OS filter',()=>{
  const sc=input.match(/<script[^>]*>([\s\S]*?)<\/script>/)?.[1]
  assert.ok(sc)
  // Component may mix imported setup helpers; test the source logic directly.
  assert.match(input,/source === 'script'\s*\|\|\s*\/\^script/)
  assert.doesNotMatch(input,/group === 'script' \|\|/)
  assert.match(input,/const serverCandidates = visibleSystemCandidates\.filter\(item => item\.source === 'server'\)/)
  assert.match(input,/serverCandidates\.forEach\(pushUniqueCandidate\)/)
})
test('Info Commands reuses old card list with a single title-level source selector',()=>{
  assert.match(info,/<span>Command List<\/span>/)
  assert.match(info,/v-model="connectionCommandSource"/)
  assert.match(info,/<el-option label="Client" value="client"/)
  assert.match(info,/<el-option label="Server" value="server"/)
  assert.match(info,/visibleConnectionCommands/)
  assert.doesNotMatch(info,/class="connection-command-panel-title">Server Commands/)
})
