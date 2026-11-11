import { apiData, jsonRequestOptions } from './http.js'

export function openScreenView(clientId, payload = {}) {
  return apiData(
    `/api/connections/${encodeURIComponent(clientId)}/screen-view/open`,
    jsonRequestOptions('POST', payload),
    {},
  )
}

export function updateScreenView(screenSessionId, payload = {}) {
  return apiData(
    `/api/screen-view/${encodeURIComponent(screenSessionId)}/config`,
    jsonRequestOptions('POST', payload),
    {},
  )
}

export function closeScreenView(screenSessionId) {
  return apiData(
    `/api/screen-view/${encodeURIComponent(screenSessionId)}/close`,
    { method: 'POST' },
    {},
  )
}

export function pollScreenView(screenSessionId, afterSeq = 0) {
  return apiData(
    `/api/screen-view/${encodeURIComponent(screenSessionId)}/poll?after_seq=${encodeURIComponent(afterSeq)}`,
    {},
    {},
  )
}


export function uploadScreenViewScreenshot(blob, metadata = {}) {
  const filename = String(metadata.filename || '').trim()
  if (!filename) throw new Error('Screenshot filename is required')
  const form = new FormData()

  if (typeof File === 'function') {
    form.append('file', new File([blob], filename, { type: 'image/jpeg' }))
  } else {
    form.append('file', blob, filename)
  }

  form.append('artifact_type', 'files')
  form.append('category', 'screenshots')
  form.append('client_id', String(metadata.clientId || ''))
  form.append('hostname', String(metadata.hostname || ''))
  form.append('machine_id', String(metadata.machineId || ''))
  form.append('extra', JSON.stringify({
    source: 'screen_view',
    origin: 'screen_view',
    screen_session_id: String(metadata.screenSessionId || ''),
    frame_strategy: String(metadata.frameStrategy || ''),
    quality: Number(metadata.quality || 0),
    width: Number(metadata.width || 0),
    height: Number(metadata.height || 0),
    captured_at: new Date().toISOString(),
  }))

  return apiData('/api/files/upload', {
    method: 'POST',
    body: form,
  }, {})
}