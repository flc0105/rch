import { jsonRequestOptions } from './http.js'

// Agent dialogs handle response validation, download navigation and UI feedback.
export function getAgentPlatform() {
  return fetch('/api/agent/platform')
}

export function buildAgent(payload) {
  return fetch('/api/agent/build', jsonRequestOptions('POST', payload))
}

export function agentDownloadUrl(fileName) {
  return `/api/agent/download/${encodeURIComponent(fileName)}`
}

export function listAgentOutputs() {
  return fetch('/api/agent/outputs')
}

export function deleteAgentOutput(fileName) {
  return fetch(`/api/agent/outputs/${encodeURIComponent(fileName)}`, { method: 'DELETE' })
}
