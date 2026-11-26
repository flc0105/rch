import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'

const source = ['fileConflictDecisions','remoteFileConflicts'].map(name => readFileSync(new URL(`../src/utils/${name}.js`, import.meta.url), 'utf8')).join('\n')
const fileActions = ['stop', 'skip', 'replace', 'keep_both']
const directoryActions = [...fileActions, 'merge']
const mixedActions = ['stop', 'skip', 'keep_both']
const conflict = (index, actions = fileActions) => ({ index, target: `/target/${index}`, allowed_actions: actions })
const response = conflicts => ({ ok: true, json: async () => ({ code: 0, data: { conflicts } }) })
const plain = value => JSON.parse(JSON.stringify(value))

function resolver({ decisions, paste = [], upload = {}, extract = [], enabled = true }) {
  const prompts = []
  const select = Symbol('select')
  const checkbox = Symbol('checkbox')
  const env = {
    defineComponent: component => component,
    h: (type, props, children) => Array.isArray(props) ? ({ type, children: props }) : ({ type, props, children }),
    ref: value => ({ value }), ElCheckbox: checkbox, ElSelect: select, ElOption: Symbol('option'),
    async ElMessageBox({ message }) {
      const controls = message.type.setup()().children
      const picker = controls.find(item => item.type === select)
      const apply = controls.find(item => item.type === checkbox)
      assert.equal(apply.children(), 'Apply to all')
      assert.equal(apply.props.modelValue, false)
      prompts.push(picker.children().map(item => item.props.value))
      const decision = decisions.shift()
      assert.ok(decision, 'unexpected conflict dialog')
      if (decision.cancel) throw Error('cancel')
      assert.ok(prompts.at(-1).includes(decision.action))
      picker.props['onUpdate:modelValue'](decision.action)
      apply.props['onUpdate:modelValue'](Boolean(decision.all))
    },
    loadServerPreferences: async () => ({ ask_on_conflict: enabled }),
    pasteRemoteFiles: async () => response(paste),
    inspectRemoteUpload: async (_, __, filename) => response(upload[filename] || []),
    extractRemoteZip: async () => response(extract),
  }
  const functions = vm.runInNewContext(`${source.replace(/^import .*$/gm, '').replaceAll('export async function', 'async function')}\n;({ preparePasteConflicts, prepareUploadConflict, prepareExtractConflict })`, env)
  return { ...functions, prompts }
}

test('paste applies a checked action to later compatible conflicts and leaves nonconflicting targets alone', async () => {
  const { preparePasteConflicts, prompts } = resolver({
    decisions: [{ action: 'replace', all: true }], paste: [conflict(0), conflict(2)],
  })
  assert.deepEqual(plain(await preparePasteConflicts('client', { paths: ['a', 'b', 'c'] })), { conflict_policies: ['replace', 'stop', 'replace'] })
  assert.equal(prompts.length, 1)
})

test('mixed target types re-prompt for unsupported action; a checked new decision supersedes it', async () => {
  const { preparePasteConflicts, prompts } = resolver({
    decisions: [{ action: 'merge', all: true }, { action: 'keep_both', all: true }],
    paste: [conflict(0, directoryActions), conflict(1, mixedActions), conflict(2)],
  })
  assert.deepEqual(plain(await preparePasteConflicts('client', { paths: ['a', 'b', 'c'] })), { conflict_policies: ['merge', 'keep_both', 'keep_both'] })
  assert.equal(prompts.length, 2)
})

test('unchecked decisions do not carry forward and a new paste never inherits a prior decision', async () => {
  const { preparePasteConflicts, prompts } = resolver({
    decisions: [{ action: 'skip' }, { action: 'keep_both', all: true }, { action: 'stop', all: true }],
    paste: [conflict(0), conflict(1)],
  })
  assert.deepEqual(plain(await preparePasteConflicts('client', { paths: ['a', 'b'] })), { conflict_policies: ['skip', 'keep_both'] })
  assert.equal(await preparePasteConflicts('client', { paths: ['a', 'b'] }), false)
  assert.equal(prompts.length, 3)
})

test('drag upload remembers Skip across actual conflicts, never skips new files, and resets for new batches', async () => {
  const { prepareUploadConflict, prompts } = resolver({
    decisions: [{ action: 'skip', all: true }, { action: 'keep_both', all: true }],
    upload: { a: [conflict(0)], b: [conflict(0)], d: [conflict(0, mixedActions)] },
  })
  const conflictScope = {}
  const options = { allowSkip: true, conflictScope }
  assert.equal(await prepareUploadConflict('client', '/target', 'a', options), 'skip')
  assert.equal(await prepareUploadConflict('client', '/target', 'c', options), 'stop')
  assert.equal(await prepareUploadConflict('client', '/target', 'b', options), 'skip')
  assert.equal(await prepareUploadConflict('client', '/target', 'd', options), 'skip')
  assert.equal(await prepareUploadConflict('client', '/target', 'a', { allowSkip: true, conflictScope: {} }), 'keep_both')
  assert.equal(prompts.length, 2)
})

test('cancel and disabled preference remain non-destructive; extraction uses the same dialog', async () => {
  const enabled = resolver({ decisions: [{ cancel: true }, { action: 'replace', all: true }], paste: [conflict(0)], extract: [conflict(0)] })
  assert.equal(await enabled.preparePasteConflicts('client', { paths: ['a'] }), false)
  assert.deepEqual(plain(await enabled.prepareExtractConflict('client', {})), { conflict_policy: 'replace' })
  const disabled = resolver({ decisions: [], enabled: false, paste: [conflict(0)] })
  assert.deepEqual(plain(await disabled.preparePasteConflicts('client', { paths: ['a'] })), { conflict_policies: ['stop'] })
  assert.equal(await disabled.prepareUploadConflict('client', '/target', 'a'), 'stop')
  assert.deepEqual(plain(await disabled.prepareExtractConflict('client', {})), { conflict_policy: 'stop' })
  assert.equal(disabled.prompts.length, 0)
})
