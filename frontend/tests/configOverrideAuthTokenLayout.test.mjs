import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'

const config = readFileSync(new URL('../src/components/ConnectionInfoDialogs.vue', import.meta.url), 'utf8')
const app = readFileSync(new URL('../src/App.vue', import.meta.url), 'utf8')

test('Configuration override badge retains the original right-aligned placement', () => {
  const configuration = config.match(/label="Configuration"[\s\S]*?label="Variables"/)?.[0] || ''
  assert.match(configuration, /<\/div>\s*<span\s+v-if="item\.source === 'override'"/)
  assert.doesNotMatch(configuration, /{{ item\.key }}\s*<span\s+v-if="item\.source === 'override'"/)
  assert.match(config, /\.connection-config-override-badge\s*\{\s*flex:\s*0 0 auto;/)
})

test('Authorization Info Copy and Reset are standalone buttons outside token input', () => {
  const token = app.match(/<div class="authorization-token-control">([\s\S]*?)\n        <\/div>/)?.[1] || ''
  assert.match(token, /<el-input[\s\S]*?\s*\/>\s*<el-button[^>]*@click="copyAuthorizationToken"/)
  assert.match(token, /<el-button[\s\S]*?@click="resetAuthorizationToken"/)
  assert.doesNotMatch(token, /<template #append>/)
})
