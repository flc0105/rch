import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = readFileSync(new URL('../src/components/ExternalToolManagerDialog.vue', import.meta.url), 'utf8')

function getMethod(name, params) {
  const marker = `${name}(${params}) {`
  const start = source.indexOf(marker)
  assert.ok(start >= 0, `missing ${name}`)
  const bodyStart = start + marker.length
  let depth = 1
  let end = bodyStart
  for (; end < source.length && depth; end++) {
    if (source[end] === '{') depth += 1
    if (source[end] === '}') depth -= 1
  }
  assert.equal(depth, 0, `unbalanced ${name}`)
  return new Function(...params.replace(' = \'\'', '').split(', ').map(s => s.trim()), source.slice(bodyStart, end - 1))
}

test('Web still groups lightweight instance items without redundant by_tool', () => {
  const group = getMethod('groupInstancesByTool', 'items = []')
  const normalize = getMethod('normalizeInstanceByToolPayload', 'data = {}, modules = []')
  const context = { groupInstancesByTool: group }
  const items = [{ tool_id: 'gost.socks5', instance_id: 'rch-result-117', running: false }]
  const result = normalize.call(context, { items }, [{ id: 'gost.socks5' }, { id: 'frp.frpc' }])
  assert.deepEqual(result['gost.socks5'], items)
  assert.deepEqual(result['frp.frpc'], [])
})

test('instance Info retains executable and runtime paths from flat result fields', () => {
  const normalize = getMethod('normalizeInstanceRow', "item, instance, deviceId = ''")
  const context = {
    normalizeDeviceId: value => value,
    getMachineIdForConnectionId: () => 'machine',
    getHostnameForConnectionId: () => 'host',
    getMachineLabel: () => 'machine',
  }
  const instance = {
    tool_id: 'gost.socks5', instance_id: 'rch-result-117', status: 'stopped', running: false,
    argv: ['/installed/gost', '-L'], cwd: '/installed', stdout: '/runtime/stdout.log',
    pid_file: '/runtime/tool.pid', state_file: '/runtime/state.json',
    params: { listen_port: 49181 },
  }
  const row = normalize.call(context, { id: 'gost.socks5' }, instance, 'client')
  assert.equal(row.exec_path, '/installed/gost')
  assert.deepEqual(row.argv, ['/installed/gost', '-L'])
  assert.equal(row.stdout, '/runtime/stdout.log')
  assert.equal(row.pid_file, '/runtime/tool.pid')
  assert.deepEqual(row.params, { listen_port: 49181 })
})
