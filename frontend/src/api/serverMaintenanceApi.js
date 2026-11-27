import { apiData, jsonRequestOptions } from './http.js'

export const getServerMaintenance = (adminToken) =>
  apiData('/api/server/maintenance', {
    cache: 'no-store',
    headers: { Authorization: `Bearer ${adminToken}` },
  }, {})

export const performServerMaintenance = (action, adminToken) =>
  apiData(`/api/server/${action}`, jsonRequestOptions('POST', {}, {
    Authorization: `Bearer ${adminToken}`,
  }), {})

const adminOptions = (token) => ({ cache: 'no-store', headers: { Authorization: `Bearer ${token}` } })
const adminRequest = (method, body, token) => jsonRequestOptions(method, body, adminOptions(token).headers)

export const getCleanupSummary = (token) => apiData('/api/server-cleanup/summary', adminOptions(token))
export const previewCleanup = (token) => apiData('/api/server-cleanup/preview', adminRequest('POST', {}, token))
export const executeCleanup = (planId, selectedIds, token) => apiData('/api/server-cleanup/execute',
  adminRequest('POST', { plan_id: planId, selected_ids: selectedIds }, token))
export const getCleanupRun = (id, token) => apiData(`/api/server-cleanup/runs/${encodeURIComponent(id)}`, adminOptions(token))
export const cancelCleanupRun = (id, token) => apiData(`/api/server-cleanup/runs/${encodeURIComponent(id)}/cancel`, adminRequest('POST', {}, token))
export const saveCleanupSettings = (settings, token) => apiData('/api/server-cleanup/settings', adminRequest('PUT', settings, token))
export const getDatabaseSpace = (token) => apiData('/api/server/maintenance/database', adminOptions(token))
export const optimizeDatabase = (token) => apiData('/api/server/maintenance/database/optimize', adminRequest('POST', {}, token))
