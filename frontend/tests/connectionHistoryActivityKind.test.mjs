import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import vm from 'node:vm'

const read = path => readFileSync(new URL(path, import.meta.url), 'utf8')

function loadComponent(path) {
  const source = read(path)
  const script = source.match(/<script>([\s\S]*?)<\/script>/)?.[1]
  assert.ok(script, `Missing script in ${path}`)
  const sandbox = Object.fromEntries([
    'EditPen', 'CommandExecutionDetailDialog', 'TextCursorInput', 'Star', 'StarFilled',
    'ArrowUp', 'ArrowDown', 'Terminal', 'Zap', 'FileCode2', 'CheckCircle2', 'XCircle',
    'CircleDashed', 'Ban', 'Clock3', 'ChevronRight', 'AlertTriangle', 'FolderOpen',
    'ArrowDownToLine', 'ArrowUpToLine', 'Wrench', 'BriefcaseBusiness',
    'Monitor', 'Clipboard', 'Activity',
  ].map(name => [name, {}]))
  vm.runInNewContext(
    script.replace(/^import\s+[\s\S]*?\s+from\s+['"][^'"]+['"]\s*;?\s*$/gm, '')
      .replace('export default {', 'globalThis.component = {'),
    sandbox,
  )
  return { source, component: sandbox.component }
}

const history = loadComponent('../src/components/MachineConnectionHistoryDialog.vue')
const center = loadComponent('../src/components/CommandHistoryDialog.vue')

test('Connection History and Activity Center label every persisted activity kind identically', () => {
  for (const kind of [
    'command', 'alias', 'script', 'remote_files', 'transfer', 'external_tool', 'background_job',
    'pty', 'screen_view', 'clipboard', 'process',
  ]) {
    assert.equal(history.component.methods.activityKindLabel(kind),
      center.component.methods.buildActivityKindLabel(kind), `Unexpected label for ${kind}`)
  }
  assert.equal(history.component.methods.activityKindLabel('background_job'), 'Background Job')
  assert.equal(history.component.methods.activityKindLabel('unrecognized_kind'), 'Activity')
})

test('Connection History renders the activity kind label in desktop and mobile views', () => {
  assert.match(history.source, /activityKindLabel\(activity\.kind\)/)
  assert.match(history.source, /activityKindLabel\(commandScope\.row\.kind\)/)
})
