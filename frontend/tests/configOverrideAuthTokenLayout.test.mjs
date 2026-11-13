import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'

const config = readFileSync(new URL('../src/components/ConnectionInfoDialogs.vue', import.meta.url), 'utf8')
const app = readFileSync(new URL('../src/App.vue', import.meta.url), 'utf8')

test('Configuration cards use status backgrounds and keep the editor badges', () => {
  const configuration = config.match(/label="Configuration"[\s\S]*?label="Variables"/)?.[0] || ''
  assert.match(configuration, /'connection-config-stat-override': item\.editable !== false && item\.source === 'override'/)
  assert.match(configuration, /'connection-config-stat-unavailable': item\.editable === false/)
  assert.match(configuration, /:aria-disabled="item\.editable === false"/)
  assert.doesNotMatch(configuration, /connection-config-override-badge/)
  assert.match(config, /\.connection-config-stat-override\s*\{\s*background: var\(--el-color-warning-light-9\)/)
  assert.match(config, /\.connection-config-stat-unavailable\s*\{\s*background: var\(--el-color-danger-light-9\)/)
  const editor = config.match(/title="Edit Configuration"[\s\S]*?<\/template>\s*<\/el-dialog>/)?.[0] || ''
  assert.match(editor, /v-if="runtimeConfigEditorItem\.source === 'override'"[\s\S]*?>\s*override\s*<\/span>/)
  assert.match(editor, /v-if="runtimeConfigEditorItem\.editable === false"[\s\S]*?>\s*Unavailable\s*<\/span>/)
  assert.match(config, /openRuntimeConfigEditor\(item\) \{\s*if \(!item \|\| item\.editable === false\) return/)
})

test('Authorization Info Copy and Reset are standalone buttons outside token input', () => {
  const token = app.match(/<div class="authorization-token-control">([\s\S]*?)\n        <\/div>/)?.[1] || ''
  assert.match(token, /<el-input[\s\S]*?\s*\/>\s*<el-button[^>]*@click="copyAuthorizationToken"/)
  assert.match(token, /<el-button[\s\S]*?@click="resetAuthorizationToken"/)
  assert.doesNotMatch(token, /<template #append>/)
})
