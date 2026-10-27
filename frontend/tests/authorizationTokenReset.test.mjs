import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { test } from 'node:test'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const app = readFileSync(resolve(root, 'src/App.vue'), 'utf8')
const api = readFileSync(resolve(root, 'src/api/authApi.js'), 'utf8')
const backend = readFileSync(resolve(root, '../backend/server/web/routes/auth.py'), 'utf8')

test('Authorization Info exposes a confirmed reset and updates the displayed token immediately', () => {
  assert.match(app, /@click="resetAuthorizationToken"/)
  assert.match(app, /Reset API Token/)
  assert.match(app, /const result = await resetAdminApiToken\(\)/)
  assert.match(app, /api_token: token/)
  assert.match(app, /authorizationTokenResetting/)
  assert.match(api, /apiData\('\/api\/auth\/token\/reset', jsonRequestOptions\('POST', \{\}\), \{\}\)/)
  assert.match(backend, /@blueprint\.post\('\/api\/auth\/token\/reset'\)/)
  assert.match(backend, /server_config\.reload_admin_auth\(\)/)
  assert.match(backend, /response\.headers\['Cache-Control'\] = 'no-store'/)
})
