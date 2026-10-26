import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import vm from 'node:vm'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const app = readFileSync(resolve(root, 'src/App.vue'), 'utf8')
const banner = app.split('<header class="banner">')[1].split('</header>')[0]
const styles = app.split('<style scoped>')[1]

// One shared icon family, 3 icon buttons, and two tall separators.
assert.match(app, /import \{[^}]*Bell[^}]*Grid[^}]*Sort[^}]*\} from '@element-plus\/icons-vue'/)
assert.match(banner, /<el-icon><Sort \/><\/el-icon>/)
assert.match(banner, /<el-icon><Bell \/><\/el-icon>/)
assert.match(banner, /<el-icon><Grid \/><\/el-icon>/)
assert.equal((banner.match(/class="banner-icon-action/g) || []).length, 3)
assert.equal((banner.match(/tool-separator banner-major-separator/g) || []).length, 2)
assert.match(styles, /\.banner-major-separator\s*\{[^}]*height:\s*24px/s)
assert.match(styles, /\.banner-icon-action\s*\{[^}]*width:\s*24px;[^}]*height:\s*32px;/s)
assert.doesNotMatch(banner, /banner-transfer-symbol|class="banner-inline-action"[^>]*@click="openAgentBuilderDialog"/)

// Both menu entries dispatch directly to independent existing dialogs (no Client guard).
assert.match(banner, /<el-dropdown trigger="click" @command="handleBannerUtilityCommand">/)
assert.match(banner, /<el-dropdown-item command="one-liners">One-liners<\/el-dropdown-item>/)
assert.match(banner, /<el-dropdown-item command="build-agent">Build Agent<\/el-dropdown-item>/)
const method = app.match(/handleBannerUtilityCommand\(command\) \{([\s\S]*?)\n    \},/)
assert.ok(method, 'utilities handler missing')
const handler = vm.runInNewContext(`(function(command){ ${method[1]} })`)
const opened = []
const ctx = {
  selectedId: null,
  currentConnection: null,
  openOneLinersDialog() { opened.push('one-liners') },
  openAgentBuilderDialog() { opened.push('build-agent') },
}
handler.call(ctx, 'one-liners')
handler.call(ctx, 'build-agent')
handler.call(ctx, 'unrecognized')
assert.deepEqual(opened, ['one-liners', 'build-agent'])

// Sign out remains the exact existing button (not a dropdown item).
assert.match(banner, /<button\s+class="banner-inline-action"\s+type="button"\s+onclick="window\.RatAuth && window\.RatAuth\.logout\(\)"\s*>\s*Sign out\s*<\/button>/)
assert.equal((banner.match(/>\s*Sign out\s*</g) || []).length, 1)
console.log('Banner utilities and icon grouping tests passed')
