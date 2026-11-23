import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const read = name => readFileSync(new URL(name, import.meta.url), 'utf8')
const transfer = read('../src/components/TransferCenterDrawer.vue')
const notifications = read('../src/components/NotificationCenterDrawer.vue')

test('Machine filter sits beside Clear Recent, not in the title header or a large full-width toolbar', () => {
  const header = transfer.split('<div class="transfer-center-header">')[1].split('<section')[0]
  const recentHeading = transfer.split('<div class="transfer-center-section-heading">')[1].split('</div>\n\n        <article')[0]
  assert.doesNotMatch(header, /class="transfer-machine-filter"/)
  assert.match(recentHeading, /class="transfer-center-recent-tools"/)
  assert.match(recentHeading, /class="transfer-machine-filter"/)
  assert.match(recentHeading, /Clear Recent/)
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
