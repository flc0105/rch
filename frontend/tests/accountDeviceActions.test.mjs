import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const app = readFileSync(resolve(root, 'src/App.vue'), 'utf8')
const sidebar = readFileSync(resolve(root, 'src/components/DeviceSidebar.vue'), 'utf8')
const authApi = readFileSync(resolve(root, 'src/api/authApi.js'), 'utf8')

// Device List actions stay on the existing generic command endpoint and target the clicked client_id.
assert.match(sidebar, /Duplicate connection/)
assert.match(sidebar, /Restart connection/)
assert.match(sidebar, /runConnectionSessionCommand\(item, 'spawn_instance',/)
assert.match(sidebar, /runConnectionSessionCommand\(item, 'relaunch_instance',/)
assert.match(sidebar, /const clientId = String\(item\?\.client_id \|\| ''\)\.trim\(\)/)
assert.match(sidebar, /await sendCommandApi\(clientId, command, headers\)/)
assert.match(sidebar, /getTabScopedHeaders/)
assert.match(app, /:get-tab-scoped-headers="getTabScopedHeaders"/)
assert.match(sidebar, /:disabled="!canRunContextConnectionCommand"/)

// Account button is driven by the authenticated username, not a hard-coded Sign out label.
assert.match(app, /currentAuthUsername: ''/)
assert.match(app, /authUsernameLabel\(\) \{[\s\S]*return String\(this\.currentAuthUsername/)
assert.match(app, /const sessionInfo = await getAuthSession\(\)/)
assert.match(app, /command="change-password"/)
assert.match(app, /command="authorization-info"/)
assert.match(app, /command="sign-out" divided/)

// Password policy is exactly the requested minimum: at least 8 chars plus English + digit.
assert.match(app, /\[\.\.\.value\]\.length < 8/)
assert.match(app, /\/\[A-Za-z\]\//)
assert.match(app, /\/\[0-9\]\//)
assert.doesNotMatch(app, /Chinese character|\\u3400-\\u4DBF/)
assert.match(app, /newPassword !== confirmPassword/)
assert.match(app, /window\.location\.replace\('\/login\.html'\)/)

// Auth API reuses masked password transport and does not send plaintext password fields.
assert.match(authApi, /current_password: maskPassword\(currentPassword\)/)
assert.match(authApi, /new_password: maskPassword\(newPassword\)/)
assert.doesNotMatch(authApi, /current_password:\s*currentPassword/)
assert.doesNotMatch(authApi, /new_password:\s*newPassword/)
assert.match(authApi, /\/api\/auth\/info/)
assert.match(authApi, /\/api\/auth\/password/)

// Authorization dialog exposes only the useful admin token and username.
assert.match(app, /authorizationInfo\.username/)
assert.match(app, /authorizationInfo\.api_token/)
assert.match(app, /copyAuthorizationToken/)
assert.doesNotMatch(app, /session_secret|password_hash/)

console.log('Account menu and Device List connection action tests passed')
