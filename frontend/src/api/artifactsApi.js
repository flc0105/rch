import { jsonRequestOptions } from './http.js'

const artifactUrl = (artifactId, suffix = '') =>
  `/api/artifacts/${encodeURIComponent(artifactId)}${suffix}`

// Return Response to retain the callers' existing validation and UI feedback.
export function listArtifacts() {
  return fetch('/api/artifacts')
}

export function uploadArtifact(formData, headers) {
  return fetch('/api/files/upload', {
    method: 'POST',
    ...(headers === undefined ? {} : { headers }),
    body: formData,
  })
}

export function renameArtifact(artifactId, name, headers = {}) {
  return fetch(artifactUrl(artifactId, '/rename'),
    jsonRequestOptions('POST', { name, original_name: name }, headers))
}

export function sendArtifactToClient(artifactId, clientId, targetPath, headers = {}) {
  return fetch(artifactUrl(artifactId, '/send-to-client'),
    jsonRequestOptions('POST', { client_id: clientId, target_path: targetPath }, headers))
}

export function deleteArtifact(artifactId) {
  return fetch(artifactUrl(artifactId), { method: 'DELETE' })
}

export function clearArtifacts(type, machineId = '') {
  return fetch('/api/artifacts/clear',
    jsonRequestOptions('POST', { type, machine_id: machineId }))
}

export function previewArtifact(artifactId) {
  return fetch(artifactUrl(artifactId, '/preview'))
}

export function saveArtifactContent(artifactId, content, encoding) {
  return fetch(artifactUrl(artifactId, '/content'),
    jsonRequestOptions('PUT', { content, encoding }))
}

export function saveCommandOutputArtifact(payload) {
  return fetch('/api/artifacts/command-output/save', jsonRequestOptions('POST', payload))
}
