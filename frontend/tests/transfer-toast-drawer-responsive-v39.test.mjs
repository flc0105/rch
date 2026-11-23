import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'

const read = path => readFileSync(new URL(path, import.meta.url), 'utf8')
const app = read('../src/App.vue')
const drawer = read('../src/components/TransferCenterDrawer.vue')
const toast = read('../src/utils/transferStartedToast.js')

function optionMethod(source, name) {
  const pattern = new RegExp(`    ${name}\\(\\) \\{([\\s\\S]*?)\\n    \\},`)
  const found = source.match(pattern)
  assert.ok(found, `Missing ${name}() method`)
  return vm.runInNewContext(`(() => { const RECENT_RENDER_BATCH_SIZE = 100; return ({ ${name}() { ${found[1]} } }).${name} })()`)
}

function computedMethod(source, name) {
  return optionMethod(source, name)
}

test('opening Transfer Center does not wait for an unresolved network request', () => {
  const calls = []
  const pending = new Promise(() => {})
  const ctx = {
    $refs: { transferCenterDrawerRef: { open() { calls.push('open') } } },
    loadTransferItems() { calls.push('fetch'); return pending },
  }
  const open = optionMethod(app, 'openTransferCenter')
  open.call(ctx)
  assert.deepEqual(calls, ['open', 'fetch'])
  assert.doesNotMatch(app, /openTransferCenter\(\)\s*\{\s*await/)
})

test('Transfer Center renders recent rows in bounded batches, never deletes or truncates stored data', () => {
  assert.match(drawer, /RECENT_RENDER_BATCH_SIZE = 100/)
  assert.match(drawer, /Show more \(\{\{ remainingRecentCount \}\} remaining\)/)
  const records = Array.from({length: 301}, (_, i) => ({ transfer_id: `${i}`, state: 'completed' }))
  const ctx = { transfers: records, recentRenderLimit: 100 }
  const recent = computedMethod(drawer, 'recentTransfers')
  const remaining = computedMethod(drawer, 'remainingRecentCount')
  const count = computedMethod(drawer, 'recentTransferCount')
  const more = optionMethod(drawer, 'showMoreRecent')
  ctx.recentTransferCount = count.call(ctx)
  ctx.recentTransfers = recent.call(ctx)
  assert.equal(ctx.recentTransfers.length, 100)
  assert.equal(remaining.call(ctx), 201)
  more.call(ctx)
  ctx.recentTransfers = recent.call(ctx)
  assert.equal(ctx.recentTransfers.length, 200)
  more.call(ctx)
  more.call(ctx)
  assert.equal(recent.call(ctx).length, 301)
  assert.equal(records.length, 301)
  assert.equal(records[300].transfer_id, '300')
})

test('mobile transfer Toast uses native 14px typography and wraps the entire filename', () => {
  assert.match(toast, /class: 'el-message__content rch-transfer-started-content'/)
  assert.match(toast, /h\('a', \{[\s\S]*?href: '#'/)
  assert.doesNotMatch(toast, /h\('button'/)
  assert.doesNotMatch(toast, /rch-transfer-started-open-short/)
  const nativeStyles = app.match(/<style>([\s\S]*?)<\/style>/g) || []
  const css = nativeStyles.join('')
  assert.ok(css.includes('.el-message.rch-transfer-started-toast'), 'Teleported Message must use unscoped CSS')
  assert.match(css, /\.el-message\.rch-transfer-started-toast \.el-message__content \{[\s\S]*?font-size: 14px;[\s\S]*?white-space: normal;[\s\S]*?overflow-wrap: anywhere;/)
  assert.doesNotMatch(css, /text-overflow:\s*ellipsis/)
  assert.doesNotMatch(css, /rch-transfer-started-open-short|@media \(max-width: 350px\)/)
  assert.doesNotMatch(css, /rch-transfer-started-inline|rch-transfer-started-label[\s\S]*?white-space: nowrap/)
  assert.match(css, /\.rch-transfer-started-toast \.rch-transfer-started-open \{[\s\S]*?text-decoration: underline;/)
})
