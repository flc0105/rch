import assert from 'node:assert/strict'
import { test } from 'node:test'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import { createTerminalOperation } from '../src/utils/terminalOperation.js'
import { isJsonContainerText, isJsonStartLine, parseJsonLines, jsonBracketDelta } from '../src/utils/terminalJson.js'
import { formatTerminalCommandFinishedLine } from '../src/composables/terminalMarkers.js'

const source = name => readFileSync(new URL(name, import.meta.url), 'utf8')
function load(sourceText, imports = {}) {
  const script = sourceText.includes('<script>')
    ? sourceText.split('<script>')[1].split('</script>')[0] : sourceText
  const sandbox = { ...imports, console }
  vm.runInNewContext(script.replace(/^import\s+[\s\S]*?\s+from\s+['"][^'"]+['"]\s*;?\s*$/gm, '')
    .replace('export default {', 'globalThis.component = {'), sandbox)
  return sandbox.component
}

function fixture() {
  const handlers = new Map(), notifications = []
  const es = { addEventListener(name, cb) { handlers.set(name, cb) }, close() {} }
  const imports = {
    createTerminalOperation, isJsonContainerText, isJsonStartLine, parseJsonLines, jsonBracketDelta,
    formatTerminalCommandFinishedLine,
    TERMINAL_BACKGROUND_PREFIX: '[Background]', TERMINAL_FILE_READY_PREFIX: '[File Ready]',
    isTerminalCancelRequestedText: () => false,
    isTerminalCommandFailedText: () => false,
    isTerminalCommandFinishedText: line => String(line || '').startsWith('[Command finished]'),
    openWebEventStream: () => es, h: () => {}, ElNotification: () => {},
    DEFAULT_SSE_NOTIFICATION_PREFERENCES: {}, cloneSseNotificationPreferences: () => ({}),
  }
  const output = load(source('../src/composables/useTerminalOutput.js'), imports)
  const sse = load(source('../src/composables/useSseStream.js'), imports)
  const render = load(source('../src/components/TerminalOutput.vue'), {
    ...imports, canRerunTerminalSource: () => false,
    getTerminalReplayAction: () => null, TerminalLinkedText: {},
  })
  const ctx = {
    ...output.data(), ...sse.data(), selectedId: 'client-a', connections: [],
    $nextTick: cb => cb(), $refs: {},
    ensureTabId: () => 'tab-1', loadConnections: async () => {},
    refreshArtifactsIfOpen: async () => {},
    showSseNotification: (...args) => notifications.push(args),
    scrollToBottom() {}, markTaskCompleted() {}, noteTaskOutput() {},
    routeTerminalTaskCapture: () => false,
  }
  for (const [name, method] of Object.entries(output.methods)) ctx[name] = method.bind(ctx)
  for (const [name, method] of Object.entries(sse.methods)) ctx[name] = method.bind(ctx)
  ctx.showSseNotification = (...args) => notifications.push(args)
  ctx.ensureTabId = () => 'tab-1'
  ctx.initSSE()
  const view = { lines: [], artifacts: [], ...render.data(), $emit: (...args) => events.push(args) }
  const events = []
  for (const [name, method] of Object.entries(render.methods)) view[name] = method.bind(view)
  const blocks = () => {
    view.lines = ctx.outputs['client-a'] || []
    view.artifacts = ctx.terminalArtifactLinks['client-a'] || []
    return render.computed.terminalBlocks.call(view)
  }
  const emit = (name, payload) => handlers.get(name)({ data: JSON.stringify(payload), lastEventId: 'event' })
  const op = (kind, cmd = 'produce') => {
    const operation = createTerminalOperation({kind, action: 'run', clientId: 'client-a'})
    ctx.appendOutput('client-a', `> ${cmd}`, 'command', {operation})
    return operation
  }
  const complete = (operation, id) => ctx.appendOutput('client-a', '[Command finished] produce (Success)', 'success', {
    operation_id: operation.operation_id, command_id: id, event_type: 'completed', execution_success: true,
  })
  const artifact = (artifact_id, source_command_id, overrides = {}) => ({
    artifact_id, source_command_id, client_id: 'client-a', artifact_type: 'files',
    original_name: `${artifact_id}.png`, ...overrides,
  })
  return {ctx, blocks, emit, op, complete, artifact, view, notifications, events}
}

function previewActions({view, blocks}, index = 0) {
  const block = blocks()[index]
  const completed = block?.bodyLines?.find(x => view.isCommandFinishedLine(x.line))
  return completed ? view.getTerminalTailActionItems(view.lines, completed.index, block)
    .filter(x => x.type === 'preview') : []
}

test('artifact SSE does not write File Ready, keeps existing notification and Artifacts refresh', async () => {
  const h = fixture()
  await h.emit('artifact_created', h.artifact('file-1', 77, {original_name: 'chart.png'}))
  assert.equal(h.ctx.outputs['client-a'], undefined)
  assert.equal(h.ctx.terminalArtifactLinks['client-a'][0].original_name, 'chart.png')
  assert.equal(h.notifications.length, 0, 'raw artifact event updates terminal links without a Toast')
  await h.emit('notification_center_updated', {
    action: 'added', notification: {
      id: 'notice-1', event_id: 'event-artifact-1', notification_key: 'artifact_created',
      title: 'File Ready', message: 'chart.png has been saved', type: 'success',
      context: {client_id: 'client-a', artifact_id: 'file-1'},
      actions: [
        {id: 'download', label: 'Download', type: 'artifact_download', url: '/download'},
        {id: 'preview', label: 'Preview', type: 'artifact_preview'},
        {id: 'open-artifacts', label: 'Open Artifacts', type: 'open_artifacts'},
      ],
    },
  })
  assert.equal(h.notifications.length, 1)
  assert.equal(h.notifications[0][0], 'artifact_created')
  assert.deepEqual(Array.from(h.notifications[0][2].actions, a => a.id), ['download', 'preview', 'open-artifacts'])
})

test('single command output renders [Preview] filename before completion; late artifact is attached', async () => {
  const h = fixture()
  const operation = h.op('command')
  h.complete(operation, 77)
  assert.equal(previewActions(h).length, 0)
  await h.emit('artifact_created', h.artifact('a1', 77, {original_name:'chart.png'}))
  const actions = previewActions(h)
  assert.equal(actions.length, 1)
  assert.equal(actions[0].fileName, 'chart.png')
  assert.equal(actions[0].line.artifactInfo.artifact_id, 'a1')
  h.view.handleTerminalActionClick(actions[0])
  assert.equal(h.events[0][0], 'preview-artifact')
  assert.equal(h.events[0][1].artifact_id, 'a1')
  assert.match(source('../src/components/TerminalOutput.vue'), /\[Preview\]/)
  assert.match(source('../src/components/TerminalOutput.vue'), /\{\{ actionItem\.fileName \}\}/)
})

test('multiple artifacts create independent [Preview] filename rows and dedupe replay', async () => {
  const h = fixture()
  const operation = h.op('script', '[Run Script] export')
  await h.emit('artifact_created', h.artifact('a1', '18', {original_name:'report.csv'}))
  await h.emit('artifact_created', h.artifact('a2', 18, {original_name:'chart.png'}))
  await h.emit('artifact_created', h.artifact('a1', 18, {original_name:'report.csv'}))
  h.complete(operation, 18)
  const actions = previewActions(h)
  assert.deepEqual(Array.from(actions, item => item.fileName), ['report.csv', 'chart.png'])
  assert.notEqual(actions[0].key, actions[1].key)
  assert.match(source('../src/components/TerminalOutput.vue'), /v-for="actionItem in \(!isTerminalBlockCollapsed\(block\)/)
})

test('alias shares command behavior; transfer, different command, incomplete and unrelated client are excluded', async () => {
  const h = fixture()
  const alias = h.op('alias', 'download')
  await h.emit('artifact_created', h.artifact('own', 21))
  await h.emit('artifact_created', h.artifact('wrong-command', 22))
  await h.emit('artifact_created', h.artifact('other-client', 21, {client_id:'client-b'}))
  assert.equal(previewActions(h).length, 0)
  h.complete(alias, 21)
  assert.deepEqual(Array.from(previewActions(h), item => item.key), ['preview:own'])
  const upload = h.op('transfer','[Remote Upload] file')
  h.complete(upload, 22)
  assert.equal(previewActions(h, 1).length, 0)
  assert.deepEqual(Array.from(previewActions(h, 0), item => item.key), ['preview:own'])
})

test('missing source identity and remote-only artifacts stay outside Terminal; Clear clears link state', async () => {
  const h = fixture()
  const op = h.op('command')
  h.complete(op, 88)
  await h.emit('artifact_created', h.artifact('remote-no-id', null))
  await h.emit('artifact_created', h.artifact('remote-no-client', 88, {client_id:''}))
  assert.equal(previewActions(h).length, 0)
  h.ctx.clearOutput()
  assert.equal(h.ctx.outputs['client-a'].length, 0)
  assert.equal(h.ctx.terminalArtifactLinks['client-a'], undefined)
})

test('missing > operation marker does not render Preview even with a matching completed ID', async () => {
  const h = fixture()
  const operation = createTerminalOperation({kind:'command', action:'invoke', clientId:'client-a'})
  h.ctx.appendOutput('client-a', 'orphaned command title', 'command', {operation})
  h.complete(operation, 32)
  await h.emit('artifact_created', h.artifact('orphan', 32))
  assert.equal(previewActions(h).length, 0)
})

test('real command SSE result and completion use the artifact command ID for Quick Action', async () => {
  const h = fixture()
  const operation = h.op('alias', 'report')
  const task = {
    task_id: 'task-33', client_id: 'client-a', command: 'report', command_id: 33,
    metadata: {operation_id: operation.operation_id, quick_action: true,
      quick_action_presentation: 'terminal', quick_action_display_command: 'report'},
  }
  await h.emit('command_result', {...task, text: 'report created'})
  await h.emit('artifact_created', h.artifact('generated', 33, {original_name:'report.pdf'}))
  await h.emit('command_complete', {...task, success:true, status:'success'})
  const [block] = h.blocks()
  assert.equal(block.commandId, 33)
  assert.equal(block.blockType, 'quick_action')
  assert.deepEqual(Array.from(previewActions(h), item => item.fileName), ['report.pdf'])
  assert.deepEqual(Array.from(h.view.lines, item => item.text), [
    '> report', 'report created', '[Command finished] report (Success)',
  ])
})
