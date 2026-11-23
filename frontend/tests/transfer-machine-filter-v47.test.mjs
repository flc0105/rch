import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const read = name => readFileSync(new URL(name, import.meta.url), 'utf8')
const transfer = read('../src/components/TransferCenterDrawer.vue')
const notifications = read('../src/components/NotificationCenterDrawer.vue')

test('Machine filter sits in the Transfer header, not a large full-width toolbar', () => {
  const header = transfer.match(/<div class="transfer-center-header">([\s\S]*?)<\/div>\s*<\/div>\s*<section/)?.[1]
  assert.ok(header, 'header encloses controls before first section')
  assert.match(header, /class="transfer-center-header-actions"/)
  assert.match(header, /class="transfer-machine-filter"/)
  assert.match(header, /class="transfer-center-close"/)
  assert.doesNotMatch(transfer, /<div class="transfer-machine-filter">/)
  assert.doesNotMatch(transfer, /\.transfer-machine-filter \.el-select\s*\{\s*width:\s*100%/)
})

test('Machine selector uses Notification Center compact Element Plus dimensions', () => {
  assert.match(transfer, /class="transfer-machine-filter"\s+size="small"/)
  assert.match(notifications, /class="notification-center-filter"\s+size="small"/)
  for (const css of ['min-height: 24px', 'height: 24px', 'padding: 0 6px', 'border-radius: 6px', 'font-size: 11px']) {
    const declaration = css.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    assert.match(transfer.match(/\.transfer-machine-filter :deep\(\.el-select__wrapper\)\s*\{([^}]+)\}/)?.[1] || '', new RegExp(declaration))
    assert.match(notifications.match(/\.notification-center-filter :deep\(\.el-select__wrapper\)\s*\{([^}]+)\}/)?.[1] || '', new RegExp(declaration))
  }
  assert.match(transfer, /\.transfer-machine-filter \{[\s\S]*?width: 148px;/)
  assert.match(transfer, /@media \(max-width: 380px\) \{[\s\S]*?\.transfer-machine-filter \{ width: 124px; \}/)
})

test('Machine ID remains filter value, but only alias or hostname is displayed', () => {
  assert.match(transfer, /:model-value="machineId"/)
  assert.match(transfer, /filterable\s+clearable/)
  assert.match(transfer, /@change="\$emit\('filter-machine', \$event \|\| ''\)"/)
  assert.match(transfer, /:value="machine\.machine_id"/)
  assert.match(transfer, /:label="machine\.label"/)
  assert.match(transfer, /const label = alias \|\| hostname \|\| existing\?\.label \|\| 'Unknown device'/)
})
