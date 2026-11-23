import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const app = readFileSync(new URL('../src/App.vue', import.meta.url), 'utf8')
const toolbox = readFileSync(new URL('../src/data/toolbarPreferences.js', import.meta.url), 'utf8')
const banner = app.slice(app.indexOf('<header class="banner">'), app.indexOf('</header>'))

test('Banner exposes six requested tools with exact Lucide icons and full hover labels', () => {
  const tools = [
    ['Settings', 'Settings2', 'openSettingsDialog'],
    ['Transfer Center', 'ArrowDownUp', 'openTransferCenter'],
    ['Notification Center', 'Bell', 'openNotificationCenter'],
    ['Listeners', 'RadioTower', '$refs.listenerManagerDialogRef?.open()'],
    ['Build Agents', 'Bot', 'openAgentBuilderDialog'],
    ['One-liners', 'Rocket', 'openOneLinersDialog'],
  ]
  for (const [label, icon, handler] of tools) {
    const button = banner.match(new RegExp(`<button\\b[^>]*title="${label}"[\\s\\S]*?<\\/button>`))?.[0]
    assert.ok(button, `${label} banner button exists`)
    assert.ok(button.includes(`aria-label="${label}"`), `${label} accessible label`)
    assert.ok(button.includes(`<${icon} `), `${label} icon`)
    assert.ok(button.includes(`@click="${handler}"`), `${label} unchanged action`)
  }
  assert.match(app, /import \{ ArrowDownUp, Bell, Blocks, Bot, RadioTower, Rocket, Settings2 \} from '@lucide\/vue'/)
  assert.match(toolbox, /id: 'agents', label: 'Agents', icon: 'bot'/)
  assert.match(banner, /<Bot :size="15" :stroke-width="1\.4"/)
  assert.match(banner, /v-if="activeTransferCount" class="banner-transfer-count"/)
})

test('Utilities retains only unspecified tools and unchanged dispatch actions', () => {
  const menu = banner.match(/<el-dropdown trigger="click" @command="handleBannerUtilityCommand">([\s\S]*?)<\/el-dropdown>/)?.[1]
  assert.ok(menu)
  assert.match(menu, /title="Utilities"/)
  assert.match(menu, /<Blocks :size="15" :stroke-width="1\.4"/)
  assert.deepEqual([...menu.matchAll(/<el-dropdown-item command="([^"]+)"/g)].map(match => match[1]), [
    'agent-outputs', 'artifacts',
  ])
  for (const action of ['one-liners', 'build-agent', 'listeners', 'settings']) {
    assert.doesNotMatch(menu, new RegExp(`<el-dropdown-item command="${action}"`))
  }
  assert.match(app, /if \(command === 'agent-outputs'\) return this\.openAgentOutputsDialog\(\)/)
  assert.match(app, /if \(command === 'artifacts'\) return this\.openServerArtifactsDialog\(\)/)
})

test('Banner retains account menu and mobile layout makes room for tools', () => {
  assert.match(banner, /@command="handleAccountCommand"/)
  for (const command of ['change-password', 'authorization-info', 'sign-out']) {
    assert.match(banner, new RegExp(`command="${command}"`))
  }
  assert.match(app, /@media \(max-width: 640px\) \{\s*\.banner-right \{\s*width: 100%;\s*flex-wrap: wrap;/)
  assert.match(app, /\.banner-icon-action \{[\s\S]*?width: 22px;[\s\S]*?height: 28px;/)
  assert.match(app, /\.banner-icon-action :deep\(svg\) \{[\s\S]*?stroke-linecap: round;/)
})

test('Banner tools follow requested order and all use 15px/1.4 Lucide styling', () => {
  const expected = [
    'Notification Center', 'Transfer Center', 'Listeners',
    'Build Agents', 'One-liners', 'Settings', 'Utilities',
  ]
  const actual = [...banner.matchAll(/title="(Notification Center|Transfer Center|Listeners|Build Agents|One-liners|Settings|Utilities)"/g)]
    .map(match => match[1])
  assert.deepEqual(actual, expected)
  for (const icon of ['Bell', 'ArrowDownUp', 'RadioTower', 'Bot', 'Rocket', 'Settings2', 'Blocks']) {
    assert.ok(banner.includes(`<${icon} :size="15" :stroke-width="1.4"`), `${icon} must be small and light`)
  }
  assert.doesNotMatch(banner, /:size="16" :stroke-width="1\.6"/)
})
