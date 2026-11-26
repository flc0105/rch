import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const read = (file) => readFileSync(new URL(file, import.meta.url), 'utf8')
const app = read('../src/App.vue')
const settings = read('../src/components/SettingsDialog.vue')
const toolbox = read('../src/components/TerminalToolbar.vue')
const logViewer = read('../src/components/LogViewerDialog.vue')
const clientPrefs = read('../src/api/serverPreferencesApi.js')

test('Banner owns Settings outside Utilities, and Toolbox launches Server Listeners', () => {
  assert.match(app, /class="banner-icon-action banner-settings-action"[\s\S]*?@click="openSettingsDialog"/)
  assert.doesNotMatch(app, /<el-dropdown-item command="settings">/)
  assert.match(app, /@open-listeners="\$refs\.listenerManagerDialogRef\?\.open\(\)"/)
  assert.match(toolbox, /id: 'listeners', label: 'Listeners'/)
  assert.match(toolbox, /this\.\$emit\('open-listeners'\)/)
})

test('Server Preferences contain conflict, preview and Log Viewer limits', () => {
  assert.match(settings, /label="Server Preferences" name="server-preferences"/)
  assert.doesNotMatch(settings, /label="Remote Files" name="remote-files"/)
  assert.match(settings, /serverPreferencesDraft\.ask_on_conflict/)
  assert.match(settings, /serverPreferencesDraft\.preview_text_max_kib/)
  assert.match(settings, /serverPreferencesDraft\.log_viewer_max_kichars/)
  assert.match(clientPrefs, /'\/api\/server\/preferences'/)
  assert.match(settings, /saveServerPreferences\(/)
})

test('Log Viewer toggles Streaming and Wrap in More with checked defaults', () => {
  assert.match(logViewer, /command="toggle-streaming"/)
  assert.match(logViewer, /command="toggle-wrap"/)
  assert.match(logViewer, /streaming: true/)
  assert.match(logViewer, /wrap: true/)
  assert.doesNotMatch(logViewer, /<el-switch v-model="wrap"/)
  assert.match(logViewer, /this\.content\.slice\(-this\.displayMaxChars\)/)
})
