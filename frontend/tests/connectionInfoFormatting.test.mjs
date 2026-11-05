import assert from 'node:assert/strict'
import { test } from 'node:test'
import { formatDateTimeLocal } from '../src/utils/formatters.js'
import {
  formatConnectionDateTime,
  getConnectionDisplayState,
} from '../src/utils/connectionInfoFormatting.js'

test('connection timestamps are rendered in the browser local timezone', () => {
  const value = '2026-11-04T12:00:00+08:00'
  assert.equal(formatConnectionDateTime(value), formatDateTimeLocal(value))
  assert.notEqual(formatConnectionDateTime(value), value)
})

test('connection staleness parses an explicit UTC offset independent of browser timezone', () => {
  const lastSeenAt = '2026-11-04T04:00:00+00:00'
  assert.equal(getConnectionDisplayState({
    connection_state: 'online',
    last_seen_at: lastSeenAt,
    stale_after_seconds: 45,
  }, Date.parse(lastSeenAt) + 46_000), 'stale')
})
