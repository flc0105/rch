import { apiData, jsonRequestOptions } from './http.js'

export function getIdentities() { return apiData('/api/identities', {}, { initialized: false, clients: [] }) }
export function initializeIdentities() { return apiData('/api/identities/initialize', { method: 'POST' }, {}) }
export function issueClientIdentity(name, days) {
  return apiData('/api/identities/clients', jsonRequestOptions('POST', { name, days }), {})
}
export function revokeClientIdentity(id) {
  return apiData(`/api/identities/clients/${encodeURIComponent(id)}/revoke`, { method: 'POST' }, {})
}
export function clientIdentityInstallCommand(id) {
  return apiData(`/api/identities/clients/${encodeURIComponent(id)}/install-command`, { cache: 'no-store' }, {})
}
export async function downloadClientIdentity(id) {
  const response = await fetch(`/api/identities/clients/${encodeURIComponent(id)}/download`, { cache: 'no-store' })
  if (!response.ok) {
    const json = await response.json().catch(() => ({}))
    throw new Error(json.message || 'Identity download failed')
  }
  const blob = await response.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `rch-identity-${id}.zip`
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
