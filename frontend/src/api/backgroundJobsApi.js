import { jsonRequestOptions } from './http.js'

const backgroundJobsUrl = (clientId, suffix = '') =>
  `/api/connections/${encodeURIComponent(clientId)}/background-jobs${suffix}`

// Keep the native Response: dialogs handle their own feedback and task refresh timing.
export function getBackgroundJobCatalog(clientId) {
  return fetch(backgroundJobsUrl(clientId, '/catalog'))
}

export function getBackgroundJobs(clientId) {
  return fetch(backgroundJobsUrl(clientId))
}

export function getBackgroundJobDetail(clientId, jobId) {
  return fetch(backgroundJobsUrl(clientId, `/${encodeURIComponent(jobId)}`))
}

export function startBackgroundJob(clientId, jobName, params = {}, executionMode = 'inproc', headers = {}) {
  return fetch(backgroundJobsUrl(clientId, '/start'),
    jsonRequestOptions('POST', {
      job_name: jobName,
      params,
      execution_mode: executionMode,
    }, { ...headers, 'X-RCH-Origin': 'web_ui' }))
}

export function stopBackgroundJob(clientId, jobKey) {
  return fetch(backgroundJobsUrl(clientId, '/stop'),
    jsonRequestOptions('POST', { job_key: jobKey }, { 'X-RCH-Origin': 'web_ui' }))
}

export function deleteBackgroundJobRecord(clientId, jobId) {
  return fetch(backgroundJobsUrl(clientId, `/${encodeURIComponent(jobId)}`), { method: 'DELETE' })
}

export function uploadServerJob(formData) {
  return fetch('/api/jobs/upload', { method: 'POST', body: formData })
}

export function deleteServerJob(name) {
  return fetch('/api/jobs/delete', jsonRequestOptions('DELETE', { name }))
}

export function saveServerJob(name, content) {
  return fetch('/api/jobs/save', jsonRequestOptions('POST', { name, content }))
}

export function downloadServerJob(name) {
  return fetch(`/api/jobs/download?name=${encodeURIComponent(name)}`)
}

// Job file previews can use a URL supplied by the Server.
export function previewBackgroundJobFile(url) {
  return fetch(url)
}
