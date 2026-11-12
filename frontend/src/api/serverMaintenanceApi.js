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
