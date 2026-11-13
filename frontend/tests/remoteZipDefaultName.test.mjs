import {test} from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import vm from 'node:vm'

const source = readFileSync(new URL('../src/components/RemoteFilesDialog.vue', import.meta.url), 'utf8')
const script = source.match(/<script>([\s\S]*?)<\/script>/)?.[1]
assert.ok(script)
const MockDate = class extends Date {
  constructor(...args) { super(...(args.length ? args : [2026, 10, 12, 18, 24, 28])) }
}
const env = {Date: MockDate, RemotePinsDialog: {}, RemoteZipPeekDialog: {}, MoreFilled: {}}
vm.runInNewContext(script.replace(/^import\s+.*$/gm, '').replace('export default {', 'globalThis.component = {'), env)
const methods = env.component.methods

const nameFor = paths => {
  const state = {remoteSelectedPaths: paths}
  state.remotePathBaseName = methods.remotePathBaseName.bind(state)
  return methods.buildRemoteZipDefaultName.call(state)
}

test('multi-path Create ZIP uses the shared Artifact bundle timestamp contract', () => {
  assert.equal(nameFor(['/tmp/a.txt', '/tmp/b.txt']), 'bundle_20261112_182428.zip')
  assert.doesNotMatch(nameFor(['/tmp/a.txt', '/tmp/b.txt']), /^archive_/)
})

test('single path Create ZIP keeps its descriptive file or directory name', () => {
  assert.equal(nameFor(['/tmp/reports']), 'reports.zip')
  assert.equal(nameFor(['/tmp/report.zip']), 'report_archive.zip')
})
