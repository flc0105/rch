import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'
import vm from 'node:vm'

const here = dirname(fileURLToPath(import.meta.url))
const source = readFileSync(resolve(here, '../src/composables/useConnections.js'), 'utf8')
const storage = new Map()
const window = {
    sessionStorage: {
        getItem: key => storage.get(key) ?? null,
        setItem: (key, value) => storage.set(key, String(value)),
        removeItem: key => storage.delete(key),
    },
}
const sandbox = {window}
vm.runInNewContext(
    source.replace(/^import\s+.*?from\s+.*?\n/gm, '').replace('export default {', 'globalThis.mixin = {'),
    sandbox,
)
const mixin = sandbox.mixin
const clientA = {machine_id: 'machine-1', client_id: 'client-A', connection_state: 'online'}
const clientB = {machine_id: 'machine-1', client_id: 'client-B', connection_state: 'online'}
const anotherMachine = {machine_id: 'machine-2', client_id: 'client-C', connection_state: 'online'}

function createPage(connections) {
    const state = {
        ...mixin.data(),
        connections,
        statusNowTick: Date.now(),
        ensureOutputBucket() {},
        refreshClientRevisionStatus() {},
        scrollToBottom() {},
    }
    for (const [name, fn] of Object.entries(mixin.methods)) state[name] = fn.bind(state)
    state.refreshClientRevisionStatus = () => {}
    for (const [name, getter] of Object.entries(mixin.computed)) {
        Object.defineProperty(state, name, {get: () => getter.call(state)})
    }
    return state
}

// 两个 Client 属于同一台机器：恢复准确的 client_id，而不是排序靠前的那一个。
let page = createPage([clientA, clientB])
page.selectConnection('client-B')
assert.equal(storage.get('rch:last_selected_machine_id'), 'machine-1')
assert.equal(storage.get('rch:last_selected_client_id'), 'client-B')
page = createPage([clientA, clientB])
page.ensureSelectedConnectionVisible()
assert.equal(page.selectedId, 'client-B', 'refresh must restore the exact selected client')

// 刷新后列表顺序变化也不影响精确恢复。
page = createPage([clientB, clientA])
page.ensureSelectedConnectionVisible()
assert.equal(page.selectedId, 'client-B')

// 原 Client 不存在或被隐藏时，保留同机器的可见 Client 回退行为。
page = createPage([clientA, anotherMachine])
page.ensureSelectedConnectionVisible()
assert.equal(page.selectedId, 'client-A')
assert.equal(storage.get('rch:last_selected_client_id'), 'client-A')
page = createPage([clientA, clientB])
page.selectConnection('client-B')
page = createPage([clientA, clientB])
page.deviceViewPrefs.hiddenClientIds = {'client-B': true}
page.ensureSelectedConnectionVisible()
assert.equal(page.selectedId, 'client-A', 'hidden client must not be selected')

// 若存储的 machine_id 已不存在，不自动选择不相关的机器。
storage.set('rch:last_selected_machine_id', 'machine-missing')
storage.set('rch:last_selected_client_id', 'client-B')
page = createPage([anotherMachine])
page.ensureSelectedConnectionVisible()
assert.equal(page.selectedId, '')

// 没有精确 Client 记录时，按现有机器回退规则选择。
storage.set('rch:last_selected_machine_id', 'machine-1')
storage.delete('rch:last_selected_client_id')
page = createPage([clientA, clientB])
page.ensureSelectedConnectionVisible()
assert.equal(page.selectedId, 'client-A')

console.log('connection selection restore tests passed')
