import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'

const read = file => readFileSync(new URL(file, import.meta.url), 'utf8')
const sidebar = read('../src/components/DeviceSidebar.vue')
const source = read('../src/composables/useConnections.js')
const connections = vm.runInNewContext(`(() => {
  ${source.replace(/^import .*$/gm, '').replace('export default', 'const component =')}
  return component
})()`, {})
const sidebarScript = sidebar.split('<script>')[1].split('</script>')[0]
const sidebarComponent = vm.runInNewContext(`(() => {
  const Icon = {}, CirclePlus = {}, ClockAlert = {}, LockKeyhole = {}, ShieldPlus = {}
  ${sidebarScript.replace(/^import[\s\S]*?from ['"][^'"]+['"]\s*\n/gm, '').replace('export default', 'const component =')}
  return component
})()`, {})

function sidebarVm(items, overrides = {}) {
  return { ...sidebarComponent.data(), connections: items, ...overrides }
}

const sample = [
  { client_id: 'reverse-tcp', connection_direction: 'reverse', listener_id: 'tcp-main', listener_name: 'TCP Main' },
  { client_id: 'reverse-tls', connection_direction: 'reverse', listener_id: 'tls-local', listener_name: 'TLS Local', connection_state: 'offline' },
  { sidebar_key: 'bind:a', connection_direction: 'bind', listener_id: '', saved_bind_target: { target_id: 'a' } },
  { sidebar_key: 'bind:b', connection_direction: 'bind', saved_bind_target: { target_id: 'b' } },
]

function visible(vmInstance) {
  return Array.from(sidebarComponent.computed.filteredConnections.call(vmInstance),
    item => item.client_id || item.sidebar_key)
}

test('existing group menu is extended with independent direction and listener sections', () => {
  assert.match(sidebar, /:hide-on-click="false"/)
  assert.match(sidebar, /Group<\/el-dropdown-item>/)
  assert.match(sidebar, /Direction<\/el-dropdown-item>/)
  assert.match(sidebar, /Listener<\/el-dropdown-item>/)
  assert.match(sidebar, /Ungrouped/)
  assert.match(sidebar, /No Listener/)
  assert.match(sidebar, /Clear filters/)
  assert.match(sidebar, /v-for="item in filteredConnections"/)
  assert.match(sidebar, /:command="\{ category: 'listener', value: listener\.id \}"/)
})

test('direction and listener filters are combined, including offline Bind targets', () => {
  const state = sidebarVm(sample)
  assert.deepEqual(visible(state), ['reverse-tcp', 'reverse-tls', 'bind:a', 'bind:b'])
  state.selectedDirection = 'bind'
  assert.deepEqual(visible(state), ['bind:a', 'bind:b'])
  state.selectedListenerId = null
  assert.deepEqual(visible(state), ['bind:a', 'bind:b'])
  state.selectedDirection = 'reverse'
  assert.deepEqual(visible(state), [])
  state.selectedListenerId = 'tls-local'
  assert.deepEqual(visible(state), ['reverse-tls'])
  state.selectedDirection = ''
  assert.deepEqual(visible(state), ['reverse-tls'])
  assert.equal(sidebarComponent.computed.activeFacetFilterCount.call(state), 1)
})

test('listener choices use stable listener IDs, with readable names and no Bind pseudo-listener', () => {
  const state = sidebarVm([...sample, {
    client_id: 'another-reverse', connection_direction: 'reverse',
    listener_id: 'tcp-main', listener_name: 'Same listener',
  }])
  const items = Array.from(sidebarComponent.computed.availableListeners.call(state), x => ({ ...x }))
  assert.deepEqual(items, [
    { id: 'tcp-main', name: 'TCP Main' },
    { id: 'tls-local', name: 'TLS Local' },
  ])
})

test('commands update each filter without erasing the others, and clear resets all', () => {
  const emitted = []
  const state = sidebarVm(sample, {
    closeDeviceContextMenu() {},
    $emit(...event) { emitted.push(event) },
  })
  const act = command => sidebarComponent.methods.handleDeviceFilterCommand.call(state, command)
  act({ category: 'group', value: 'office' })
  act({ category: 'direction', value: 'bind' })
  act({ category: 'listener', value: null })
  assert.equal(state.selectedDirection, 'bind')
  assert.equal(state.selectedListenerId, null)
  assert.deepEqual(emitted, [['group-filter-change', 'office']])
  assert.equal(sidebarComponent.computed.activeFacetFilterCount.call(state), 2)
  act({ category: 'clear' })
  assert.equal(state.selectedDirection, '')
  assert.equal(state.selectedListenerId, '')
  assert.deepEqual(emitted[1], ['group-filter-change', ''])
})

test('ungrouped filter uses machine group assignments; counts distinct machines and unsaved targets', () => {
  const state = {
    ...connections.data(),
    deviceGroups: [{ group_id: 'office', name: 'Office' }],
    machineGroupAssignments: { 'm1': 'office' },
    getMachineDeviceGroupId: id => connections.methods.getMachineDeviceGroupId.call(state, id),
    normalizeMachineGroupKey: id => connections.methods.normalizeMachineGroupKey.call(state, id),
    normalizeMachineId: id => connections.methods.normalizeMachineId.call(state, id),
    normalizeClientId: id => connections.methods.normalizeClientId.call(state, id),
    normalizeDeviceGroupId: id => connections.methods.normalizeDeviceGroupId.call(state, id),
    ensureSelectedConnectionVisible() {},
    connections: [
      { client_id: 'reverse-a', machine_id: 'm1' },
      { client_id: 'reverse-b', machine_id: 'm1' },
      { client_id: 'reverse-c', machine_id: 'm2' },
    ],
    savedBindTargets: [
      { target_id: 'a', machine_id: 'm2' },
      { target_id: 'b', machine_id: '' },
    ],
  }
  const set = groupId => connections.methods.setSelectedDeviceGroup.call(state, groupId)
  const includes = item => connections.methods.isConnectionInSelectedDeviceGroup.call(state, item)
  set(null)
  assert.equal(includes({ machine_id: 'm1' }), false)
  assert.equal(includes({ machine_id: 'm2' }), true)
  assert.equal(includes({ machine_id: '' }), true)
  set('office')
  assert.equal(includes({ machine_id: 'm1' }), true)
  assert.equal(includes({ machine_id: 'm2' }), false)
  set('')
  assert.equal(includes({ machine_id: 'm1' }), true)
  assert.equal(includes({ machine_id: 'm2' }), true)
  const counts = connections.computed.deviceGroupMachineCounts.call(state)
  assert.equal(counts.__all__, 3)
  assert.equal(counts.office, 1)
  assert.equal(counts.ungrouped, 2)
})

test('rollback removes v62 fake short capsule and restores v61 native thin scrollbar', () => {
  assert.match(sidebar, /\.sidebar-body\s*\{[^}]*scrollbar-width:\s*thin/)
  assert.match(sidebar, /\.sidebar-body::-webkit-scrollbar\s*\{[^}]*width:\s*8px/)
  assert.doesNotMatch(sidebar, /52px no-repeat|short handle|:is\(:hover, :focus-within\)::-webkit-scrollbar-thumb/)
})

test('group filter and local direction/listener filters compose on the same sidebar items', () => {
  const vmInstance = {
    ...connections.data(),
    connections: [
      { client_id: 'office-tcp', machine_id: 'office-machine', connection_direction: 'reverse', listener_id: 'tcp-main', connection_state: 'online' },
      { client_id: 'office-tls', machine_id: 'office-machine', connection_direction: 'reverse', listener_id: 'tls-main', connection_state: 'offline' },
      { client_id: 'home-tls', machine_id: 'home-machine', connection_direction: 'reverse', listener_id: 'tls-main', connection_state: 'online' },
    ],
    savedBindTargets: [
      { target_id: 'office-bind', machine_id: 'office-machine', host: '192.168.0.2', port: 9443 },
      { target_id: 'home-bind', machine_id: 'home-machine', host: '192.168.0.3', port: 9443 },
    ],
    deviceGroups: [{ group_id: 'office', name: 'Office' }],
    machineGroupAssignments: { 'office-machine': 'office' },
    decorateConnectionForDeviceView: x => x,
    getConnectionDisplayState: x => x.connection_state,
    normalizeMachineGroupKey: id => connections.methods.normalizeMachineGroupKey.call(vmInstance, id),
    normalizeMachineId: id => connections.methods.normalizeMachineId.call(vmInstance, id),
    normalizeDeviceGroupId: id => connections.methods.normalizeDeviceGroupId.call(vmInstance, id),
    getMachineDeviceGroupId: id => connections.methods.getMachineDeviceGroupId.call(vmInstance, id),
    isConnectionInSelectedDeviceGroup: item => connections.methods.isConnectionInSelectedDeviceGroup.call(vmInstance, item),
    compareSidebarConnectionOrder: (a, b) => String(a.sidebar_key || a.client_id).localeCompare(String(b.sidebar_key || b.client_id)),
  }
  const items = () => Array.from(connections.computed.deviceSidebarConnections.call(vmInstance))
  vmInstance.selectedDeviceGroupId = 'office'
  assert.deepEqual(items().map(item => item.client_id || item.sidebar_key), ['bind:office-bind', 'office-tcp', 'office-tls'])
  let sidebarState = sidebarVm(items(), { selectedDirection: 'reverse', selectedListenerId: 'tls-main' })
  assert.deepEqual(visible(sidebarState), ['office-tls'])
  sidebarState = sidebarVm(items(), { selectedDirection: 'bind', selectedListenerId: null })
  assert.deepEqual(visible(sidebarState), ['bind:office-bind'])
  vmInstance.selectedDeviceGroupId = null
  sidebarState.connections = items()
  assert.deepEqual(visible(sidebarState), ['bind:home-bind'])
})


test('approved Lucide direction icons have matching monitor geometry, 13px size and 1.7 stroke', () => {
  assert.match(sidebar, /import \{ Icon, CirclePlus,/)
  assert.match(sidebar, /<Icon :icon-node="getDirectionIconNode\(item\)" :size="13" :stroke-width="1\.7"/)
  const reverse = sidebarComponent.methods.getDirectionIconNode({ connection_direction: 'reverse' })
  const bind = sidebarComponent.methods.getDirectionIconNode({ connection_direction: 'bind' })
  assert.equal(reverse.length, 4)
  assert.equal(bind.length, 4)
  assert.deepEqual(Array.from(reverse.slice(0, 2), node => node[1].d),
    Array.from(bind.slice(0, 2), node => node[1].d))
  assert.equal(reverse[2][1].d, 'M11.82 11H22.6')
  assert.equal(reverse[3][1].d, 'M19.8 8.2 22.6 11 19.8 13.8')
  assert.equal(bind[2][1].d, 'M22.6 11H11.82')
  assert.equal(bind[3][1].d, 'M14.62 8.2 11.82 11 14.62 13.8')
  assert.match(sidebar, /item\.connection_direction !== 'bind' && item\.listener_name/)
})

test('All Devices popper scroll is low contrast, scoped and reset to top on each open', () => {
  assert.match(sidebar, /popper-class="device-filter-popper"/)
  assert.match(sidebar, /@visible-change="handleDeviceFilterVisibility"/)
  assert.match(sidebar, /\.device-filter-popper \.device-filter-dropdown::-webkit-scrollbar-thumb/)
  assert.match(sidebar, /\.device-filter-popper \.el-scrollbar__wrap::-webkit-scrollbar-thumb/)
  assert.match(sidebar, /\.device-filter-popper \.el-scrollbar__thumb/)
  const nodes = [{ scrollTop: 98 }, { scrollTop: 211 }]
  const popper = { querySelectorAll: selector => {
    assert.equal(selector, '.device-filter-dropdown, .el-scrollbar__wrap')
    return nodes
  } }
  const instance = {
    $nextTick: callback => callback(),
  }
  const context = { document: { querySelector: selector => {
    assert.equal(selector, '.device-filter-popper')
    return popper
  } } }
  // The imported DOM global is used by the method's VM context, not this test's global.
  sidebarComponent.methods.handleDeviceFilterVisibility.call({ ...instance, $nextTick: () => {} }, false)
  const sandboxScript = sidebarScript.replace(/^import[\s\S]*?from ['"][^'"]+['"]\s*\n/gm, '')
    .replace('export default', 'const component =')
  const isolated = vm.runInNewContext(`(() => {
    const Icon = {}, CirclePlus = {}, ClockAlert = {}, LockKeyhole = {}, ShieldPlus = {}
    ${sandboxScript}
    return component
  })()`, context)
  isolated.methods.handleDeviceFilterVisibility.call(instance, true)
  assert.deepEqual(nodes.map(node => node.scrollTop), [0, 0])
  nodes[0].scrollTop = 54
  nodes[1].scrollTop = 67
  isolated.methods.handleDeviceFilterVisibility.call(instance, false)
  assert.deepEqual(nodes.map(node => node.scrollTop), [54, 67])
  isolated.methods.handleDeviceFilterVisibility.call(instance, true)
  assert.deepEqual(nodes.map(node => node.scrollTop), [0, 0])
})
