import { jsonRequestOptions } from './http.js'

const pinnedPathsUrl = clientId =>
  `/api/connections/${encodeURIComponent(clientId)}/pinned_paths`

// Return Response so existing dialogs preserve their context checks and messages.
export function listRemotePinnedPaths(clientId, options = {}) {
  return fetch(pinnedPathsUrl(clientId), options)
}

export function saveRemotePinnedPath(clientId, payload, method = 'POST') {
  return fetch(pinnedPathsUrl(clientId), jsonRequestOptions(method, payload))
}

export function deleteRemotePinnedPath(clientId, displayName) {
  return fetch(pinnedPathsUrl(clientId),
    jsonRequestOptions('DELETE', { display_name: displayName }))
}
