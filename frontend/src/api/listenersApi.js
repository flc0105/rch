import { jsonRequestOptions } from './http.js'

export function listListenerProtocols() { return fetch('/api/listener-protocols') }
export function listListeners() { return fetch('/api/listeners') }
export function createListener(payload) { return fetch('/api/listeners', jsonRequestOptions('POST', payload)) }
export function setListenerEnabled(id, enabled) { return fetch(`/api/listeners/${encodeURIComponent(id)}`, jsonRequestOptions('PATCH', { enabled })) }
export function removeListener(id) { return fetch(`/api/listeners/${encodeURIComponent(id)}`, { method: 'DELETE' }) }
