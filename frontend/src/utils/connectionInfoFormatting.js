import { formatDateTimeStandard } from './formatters.js'

export function getConnectionDisplayState(conn, nowTick = Date.now()) {
  const connection = conn || {}
  const state = String(connection.connection_state || '').trim()
  if (state === 'offline') return 'offline'

  if (connection.is_transfer_active) return 'online'

  const disconnectedAt = String(connection.disconnected_at || '').trim()
  if (disconnectedAt) return 'offline'

  const lastSeenAt = String(connection.last_seen_at || '').trim()
  if (!lastSeenAt) return state || 'online'

  const staleAfterSeconds = Number(connection.stale_after_seconds || 45)
  const seenMs = Date.parse(lastSeenAt)
  if (!Number.isFinite(seenMs)) return state || 'online'

  const ageMs = Math.max(nowTick - seenMs, 0)
  if (ageMs > staleAfterSeconds * 1000) return 'stale'

  return 'online'
}

export function formatConnectionStatus(conn, nowTick = Date.now()) {
  const state = getConnectionDisplayState(conn, nowTick)
  if (state === 'online') return 'online'
  if (state === 'stale') return 'stale'
  return 'offline'
}

export function formatConnectionDateTime(value) {
  return formatDateTimeStandard(value)
}

export function formatConnectionLastSeen(conn, nowTick = Date.now()) {
  if (!conn) return '-'
  const state = getConnectionDisplayState(conn, nowTick)
  if (state === 'offline') return formatConnectionDateTime(conn.disconnected_at) || '-'
  return formatConnectionDateTime(conn.last_seen_at) || '-'
}

export function formatConnectionRtt(conn) {
  const value = conn && conn.last_rtt_ms
  if (value === null || value === undefined || value === '') return '-'
  return `${value} ms`
}
