import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'
import { formatDateTimeLocal } from '../src/utils/formatters.js'

const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const screenView = fs.readFileSync(path.join(frontend, 'src/components/ScreenViewDialog.vue'), 'utf8')
const api = fs.readFileSync(path.join(frontend, 'src/api/screenViewApi.js'), 'utf8')

test('Screen View saved snapshot uses the shared local timestamp and screenshot filename', () => {
  assert.equal(formatDateTimeLocal(new Date(2026, 10, 10, 18, 32, 18)), '2026-11-10 18:32:18')
  assert.match(screenView, /const stamp = formatDateTimeLocal\(new Date\(\)\)\.replace\(/)
  assert.match(screenView, /filename: `screenshot_\$\{stamp\}\.jpg`/)
  assert.doesNotMatch(screenView, /filename: `screenview_/)
})

test('Screen View screenshot metadata distinguishes its capture origin from folder classification', () => {
  assert.match(api, /form\.append\('category', 'screenshots'\)/)
  assert.match(api, /saved_from: 'screen_view'/)
  assert.match(api, /jpeg_quality:/)
  assert.doesNotMatch(api, /origin: 'screen_view'/)
  assert.doesNotMatch(api, /screen_session_id:/)
})
