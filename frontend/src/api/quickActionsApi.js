import { apiData, jsonRequestOptions } from './http.js'

function baseUrl(clientId) {
  return `/api/connections/${encodeURIComponent(clientId)}/quick-actions`
}

export function listQuickActions(clientId) {
  return apiData(baseUrl(clientId), {}, {
    supported_platforms: [],
    current_platform: 'common',
    default_platforms: ['common'],
    items: [],
  })
}

export function createQuickAction(clientId, payload = {}) {
  return apiData(baseUrl(clientId), jsonRequestOptions('POST', payload), {})
}

export function updateQuickAction(clientId, payload = {}) {
  return apiData(baseUrl(clientId), jsonRequestOptions('PUT', payload), {})
}

export function deleteQuickAction(clientId, payload = {}) {
  return apiData(baseUrl(clientId), jsonRequestOptions('DELETE', payload), {})
}

export function executeQuickAction(clientId, payload = {}, headers = {}) {
  return apiData(
    `${baseUrl(clientId)}/execute`,
    jsonRequestOptions('POST', payload, headers),
    {},
  )
}
