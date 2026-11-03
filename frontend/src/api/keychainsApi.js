import { jsonRequestOptions } from './http.js'

const credentialUrl = credId => `/api/keychains/${encodeURIComponent(credId)}`

// Return the native Response; the manager and picker own scope checks and UI feedback.
export function listKeychains(machineId = '') {
  const query = new URLSearchParams()
  if (machineId) query.set('machine_id', machineId)
  const suffix = query.toString()
  return fetch(`/api/keychains${suffix ? `?${suffix}` : ''}`)
}

export function getKeychainCredential(credId) {
  return fetch(credentialUrl(credId))
}

export function saveKeychainCredential(payload, credId = '') {
  return fetch(credId ? credentialUrl(credId) : '/api/keychains',
    jsonRequestOptions(credId ? 'PUT' : 'POST', payload))
}

export function deleteKeychainCredential(credId) {
  return fetch(credentialUrl(credId), { method: 'DELETE' })
}
