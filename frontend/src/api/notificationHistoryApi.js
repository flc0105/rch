import { apiData } from './http.js'

export function loadNotificationHistory() {
  return apiData('/api/notifications/history', {}, {
    version: 1,
    notifications: [],
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
