import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'
import vm from 'node:vm'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../src/components')
const source = fs.readFileSync(path.join(root, 'TerminalOutput.vue'), 'utf8')
const script = source.match(/<script>([\s\S]*?)<\/script>/)?.[1] || ''
const noImports = script.replace(/import\s+[\s\S]*?\s+from\s+['"][^'"]+['"]\s*;?/g, '')
const sandbox = { TerminalLinkedText: {}, setTimeout, clearTimeout }
vm.runInNewContext(noImports.replace('export default {', 'globalThis.component = {'), sandbox)
const component = sandbox.component
const view = { selectedId: 'client-1', currentConnection: { machine_id: 'mac', hostname: 'MacBook' } }
for (const [key, method] of Object.entries(component.methods)) view[key] = method.bind(view)

test('Terminal JSON Viewer save keeps script identity and JSON extension through one request', () => {
  const block = view.normalizeTerminalJsonSaveBlock({
    blockType: 'script', is_script: true, source_command: 'script exec common/recon/list_disks.py',
    script_path: 'common/recon/list_disks.py', source_command_id: 111,
  })
  const body = view.buildTerminalOutputArtifactSaveBody(block, '[{"name":"disk"}]', {
    savedFrom: 'terminal_json_viewer', outputFormat: 'json',
  })
  assert.equal(body.output_kind, 'script')
  assert.equal(body.output_format, 'json')
  assert.equal(body.extra.saved_from, 'terminal_json_viewer')
  assert.equal(body.extra.script_path, 'common/recon/list_disks.py')
  assert.equal(body.extra.source_command, 'script exec common/recon/list_disks.py')
  assert.equal(body.source_command_id, 111)
  assert.ok(!('category' in body) && !('source' in body))
  assert.ok(!('saved_at' in body.extra) && !('origin' in body.extra))
})

test('Command Output and Job Detail use one canonical naming and source protocol', () => {
  const block = view.normalizeTerminalJsonSaveBlock({
    blockType: 'command', source_command: 'whoami', command_id: 105,
  })
  const body = view.buildTerminalOutputArtifactSaveBody(block, 'flc', {
    savedFrom: 'terminal_output',
  })
  assert.equal(body.output_kind, 'command')
  assert.equal(body.output_format, 'text')
  assert.equal(body.extra.source_command, 'whoami')
  assert.deepEqual(Object.keys(body.extra).sort(), ['saved_from', 'source_command'])
  const job = fs.readFileSync(path.join(root, 'BackgroundJobDetailDialog.vue'), 'utf8')
  assert.match(job, /output_kind:\s*'job'/)
  assert.match(job, /saved_from:\s*'background_job_detail'/)
  assert.match(job, /job_key:/)
  assert.doesNotMatch(job, /source:\s*'background_job_detail'/)
})
