import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'

const source = readFileSync(new URL('../src/utils/remoteFileConflicts.js', import.meta.url), 'utf8')
const code = source.replace(/^import\s+.*$/gm, '').replace(/export async function /g, 'async function ')
const fake = (data) => ({ ok: true, json: async () => ({ code: 0, data }) })

function createEnvironment({ enabled = true, action = 'keep_both', conflicts = [] } = {}) {
  const calls = []
  const env = {
    loadRemoteFileConflictPreferences: async () => ({ ask_on_conflict: enabled }),
    pasteRemoteFiles: async (clientId, payload) => { calls.push(['paste', clientId, payload]); return fake({ conflicts }) },
    extractRemoteZip: async (clientId, payload) => { calls.push(['zip', clientId, payload]); return fake({ conflicts }) },
    inspectRemoteUpload: async (clientId, destination, filename) => { calls.push(['upload', clientId, destination, filename]); return fake({ conflicts }) },
    ref: value => ({ value }),
    defineComponent: options => options,
    h: (tag, props, children) => ({tag, props: Array.isArray(props) ? {} : props, children: Array.isArray(props) ? props : children}),
    ElOption: 'option', ElSelect: 'select',
    ElMessageBox: async (options) => {
      const vnode = options.message.tag.setup()()
      const select = vnode.children.find(child => child.tag === 'select')
      assert.ok(select, 'Conflict dialog must have an editable select')
      select.props['onUpdate:modelValue'](action)
    },
  }
  vm.runInNewContext(`${code}\nglobalThis.exports = { preparePasteConflicts, prepareExtractConflict, prepareUploadConflict }`, env)
  return { ...env.exports, calls }
}

test('disabled global setting keeps legacy behavior without inspecting target', async () => {
  const ui = createEnvironment({ enabled: false })
  assert.equal(await ui.preparePasteConflicts('c', { paths: ['/a'], destination_dir: '/b' }), null)
  assert.equal(await ui.prepareExtractConflict('c', { path: '/a.zip', destination_dir: '/b' }), null)
  assert.equal(await ui.prepareUploadConflict('c', '/b', 'name.txt'), null)
  assert.equal(ui.calls.length, 0)
})

test('copy/move inspect once and assign policy by source index, without mutating', async () => {
  const conflicts = [{ source_kind: 'file', target_kind: 'file', target: '/dst/x.txt', index: 1,
    allowed_actions: ['stop', 'replace', 'keep_both'] }]
  const ui = createEnvironment({ conflicts })
  const request = { paths: ['/a', '/x.txt'], destination_dir: '/dst', operation: 'copy' }
  const result = await ui.preparePasteConflicts('c', request)
  assert.equal(JSON.stringify(result), JSON.stringify({ conflict_policies: ['stop', 'keep_both'] }))
  assert.equal(ui.calls.length, 1)
  assert.equal(ui.calls[0][2].inspect, true)
})

test('file-vs-folder stops without replacement; ZIP merge applies to one root', async () => {
  const fileConflict = [{ source_kind: 'file', target_kind: 'directory', target: '/dst/name',
    allowed_actions: ['stop', 'keep_both'] }]
  const stopped = createEnvironment({ conflicts: fileConflict, action: 'stop' })
  assert.equal(await stopped.prepareUploadConflict('c', '/dst', 'name'), false)
  const merged = createEnvironment({ conflicts: [{ source_kind: 'directory', target_kind: 'directory', target: '/dst/root',
    allowed_actions: ['stop','merge','replace','keep_both'] }], action: 'merge' })
  const decision = await merged.prepareExtractConflict('c', { path: '/x.zip', destination_dir: '/dst' })
  assert.equal(JSON.stringify(decision), JSON.stringify({ conflict_policy: 'merge' }))
})

test('when no conflicts, opt-in execution still gets stop policy to guard races', async () => {
  const ui = createEnvironment({ conflicts: [] })
  assert.equal(await ui.prepareUploadConflict('c', '/dir', 'report.bin'), 'stop')
  assert.equal(JSON.stringify(await ui.prepareExtractConflict('c', {path:'/zip',destination_dir:'/dir'})), JSON.stringify({conflict_policy:'stop'}))
})

test('global Settings exposes a persisted default-off conflict toggle', () => {
  const settings = readFileSync(new URL('../src/components/SettingsDialog.vue', import.meta.url), 'utf8')
  assert.match(settings, /name="remote-files"/)
  assert.match(settings, /remoteFileConflictDraft:\s*\{ ask_on_conflict: false \}/)
  assert.match(settings, /saveRemoteFileConflictPreferences\(this\.remoteFileConflictDraft\)/)
  const remoteFiles = readFileSync(new URL('../src/components/RemoteFilesDialog.vue', import.meta.url), 'utf8')
  assert.match(remoteFiles, /preparePasteConflicts\(/)
  assert.match(remoteFiles, /prepareExtractConflict\(/)
  assert.match(remoteFiles, /prepareUploadConflict\(/)
})


test('Remote Files setting uses the shared fixed-height dialog and no nested cards', () => {
  const source = readFileSync(new URL('../src/components/SettingsDialog.vue', import.meta.url), 'utf8')
  const section = source.match(/<el-tab-pane label="Remote Files" name="remote-files">([\s\S]*?)<\/el-tab-pane>/)?.[1]
  assert.ok(section, 'Remote Files settings tab exists')
  assert.match(section, /remote-files-settings-row/)
  assert.match(section, /remote-files-settings-title/)
  assert.doesNotMatch(section, /class="settings-section"|class="settings-section-title"|class="notification-master-row"/)
  assert.match(source, /\.settings-dialog\.el-dialog\s*\{\s*height:\s*680px;/)
  assert.match(source, /\.settings-dialog \.settings-tab-scroll\s*\{[\s\S]*?height:\s*100%;[\s\S]*?overflow-y:\s*auto;/)
  assert.doesNotMatch(source, /settings-dialog--compact/)
  assert.match(section, /v-model="remoteFileConflictDraft\.ask_on_conflict"/)
})
