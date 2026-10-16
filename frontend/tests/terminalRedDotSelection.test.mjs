import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import {fileURLToPath} from 'node:url'
import {dirname, resolve} from 'node:path'
import vm from 'node:vm'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const toolbar = readFileSync(resolve(root, 'src/components/TerminalToolbar.vue'), 'utf8')
const app = readFileSync(resolve(root, 'src/App.vue'), 'utf8')
const source = readFileSync(resolve(root, 'src/composables/useConnections.js'), 'utf8')

assert.match(toolbar, /class="dot dot-red dot-action"/)
assert.match(toolbar, /@click="\$emit\('clear-selection'\)"/)
assert.match(toolbar, /'clear-selection'/)
assert.match(toolbar, /class="dot dot-green dot-action"/)
assert.match(toolbar, /\.dot-red\.dot-action:hover/)
assert.match(app, /@clear-selection="clearSelectedConnection"/)

const storage = new Map()
const sandbox = {
  window: {sessionStorage: {
    getItem: key => storage.get(key) ?? null,
    setItem: (key, value) => storage.set(key, String(value)),
    removeItem: key => storage.delete(key),
  }},
}
vm.runInNewContext(
  source.replace(/^import\s+.*?from\s+.*?\n/gm, '').replace('export default {', 'globalThis.mixin = {'),
  sandbox,
)
const mixin = sandbox.mixin
const a = {machine_id: 'machine-one', client_id: 'client-A', connection_state: 'online'}
const b = {machine_id: 'machine-one', client_id: 'client-B', connection_state: 'online'}
const c = {machine_id: 'machine-two', client_id: 'client-C', connection_state: 'online'}
let candidateRefresh = 0
function page(connections) {
  const state = {
    ...mixin.data(), connections,
    statusNowTick: Date.now(),
    commandHistoryItems: ['old history'], commandExecutionItems: ['old executions'],
    ensureOutputBucket() {}, refreshClientRevisionStatus() {}, scrollToBottom() {},
    reloadCommandCandidatesFromRuntime() {candidateRefresh += 1},
  }
  for (const [name, fn] of Object.entries(mixin.methods)) state[name] = fn.bind(state)
  state.refreshClientRevisionStatus = () => {}
  for (const [name, getter] of Object.entries(mixin.computed)) {
    Object.defineProperty(state, name, {get: () => getter.call(state)})
  }
  return state
}

let state = page([a,b,c])
state.selectConnection('client-B')
assert.equal(storage.get('rch:last_selected_machine_id'), 'machine-one')
assert.equal(storage.get('rch:last_selected_client_id'), 'client-B')
const oldCount = candidateRefresh
state.clearSelectedConnection()
assert.equal(state.selectedId, '')
assert.equal(storage.has('rch:last_selected_machine_id'), false)
assert.equal(storage.has('rch:last_selected_client_id'), false)
assert.equal(state.commandHistoryItems.length, 0)
assert.equal(state.commandExecutionItems.length, 0)
assert.equal(candidateRefresh, oldCount+1)
// Refresh and subsequent connection-list notifications must not reselect a Client.
state.ensureSelectedConnectionVisible()
assert.equal(state.selectedId, '')
state = page([b,a,c])
state.ensureSelectedConnectionVisible()
assert.equal(state.selectedId, '')
// Only an explicit left-sidebar selection restores the chosen Client.
state.selectConnection('client-A')
assert.equal(state.selectedId, 'client-A')
state.ensureSelectedConnectionVisible()
assert.equal(state.selectedId, 'client-A')
console.log('terminal red-dot selection behavior passed')
