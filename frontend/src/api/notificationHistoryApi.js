import { apiData } from './http.js'

export function loadNotificationHistory({ limit = 20, offset = 0, type = 'all' } = {}) {
  const query = new URLSearchParams({ limit: String(limit), offset: String(offset) })
  if (type !== 'all') query.set('type', type)
  return apiData(`/api/notifications/history?${query}`, {}, {
    version: 1, notifications: [], total_count: 0, filtered_count: 0,
  })
}

export function deleteNotificationHistory(notificationId) {
  return apiData(
    `/api/notifications/history/${encodeURIComponent(notificationId)}`,
    { method: 'DELETE' },
    { deleted: false },
  )
}

export function clearNotificationHistory(type = 'all') {
  const url = type === 'all'
    ? '/api/notifications/history'
    : `/api/notifications/history?type=${encodeURIComponent(type)}`
  return apiData(
    url,
    { method: 'DELETE' },
    { removed_count: 0 },
  )
}
