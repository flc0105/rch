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

test('Preferences uses the same section/row styles as Maintenance and stores byte limits', () => {
  assert.match(settings, /label="Preferences" name="server-preferences"/)
  assert.match(settings, /label="Maintenance" name="server"/)
  assert.doesNotMatch(settings, /label="Remote Files" name="remote-files"/)
  assert.match(settings, /serverPreferencesDraft\.ask_on_conflict/)
  assert.match(settings, /serverPreferencesDraft\.preview_text_max_kib/)
  assert.match(settings, /serverPreferencesDraft\.log_viewer_max_kib/)
  assert.match(clientPrefs, /'\/api\/server\/preferences'/)
  assert.match(clientPrefs, /log_viewer_max_bytes/)
  assert.match(settings, /saveServerPreferences\(/)
  const tab = settings.split('<el-tab-pane label="Preferences" name="server-preferences">')[1]
    .split('<el-tab-pane label="Notifications" name="notifications">')[0]
  assert.equal((tab.match(/class="settings-section"/g) || []).length, 2)
  assert.equal((tab.match(/class="settings-section-title"/g) || []).length, 2)
  assert.equal((tab.match(/class="server-maintenance-row"/g) || []).length, 3)
  const files = tab.split('<div class="settings-section-title">Files</div>')[1]
    .split('</section>')[0]
  assert.match(files, /serverPreferencesDraft\.ask_on_conflict/)
  assert.match(files, /serverPreferencesDraft\.preview_text_max_kib/)
  assert.match(tab, /<div class="settings-section-title">Logs<\/div>/)
  assert.match(tab, /Text preview limit/)
  assert.match(tab, /Log display limit/)
  assert.equal((tab.match(/<span>KiB<\/span>/g) || []).length, 2)
  assert.doesNotMatch(tab, /preference-group|Ki chars|Streaming and Follow still work normally/)
  assert.doesNotMatch(settings, /\.preference-group\s*\{/)
})

test('Log Viewer toggles Streaming and Wrap in More with checked defaults', () => {
  assert.match(logViewer, /command="toggle-streaming"/)
  assert.match(logViewer, /command="toggle-wrap"/)
  assert.match(logViewer, /streaming: true/)
  assert.match(logViewer, /wrap: true/)
  assert.doesNotMatch(logViewer, /<el-switch v-model="wrap"/)
  assert.match(logViewer, /retainRecentUtf8Bytes\(this\.content, this\.displayMaxBytes\)/)
})
