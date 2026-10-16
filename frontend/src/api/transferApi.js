function normalizeHeaders(headers = {}) {
  return {...(headers || {})}
}

async function parseApiResponse(res, fallbackMessage) {
  const json = await res.json()
  if (!res.ok || json.code !== 0) {
    throw new Error(json.message || fallbackMessage)
  }
  return json.data || {}
}

export async function loadTransfers(tabId = '') {
  const headers = {}
  const normalizedTabId = String(tabId || '').trim()
  if (normalizedTabId) headers['X-Tab-Id'] = normalizedTabId

  const res = await fetch('/api/transfers', { headers })
  return parseApiResponse(res, 'Failed to load transfers')
}

export async function createBrowserUploadTransfer(payload = {}, headers = {}) {
  const res = await fetch('/api/transfers/browser-upload', {
    method: 'POST',
    headers: normalizeHeaders({
      'Content-Type': 'application/json',
      ...headers,
    }),
    body: JSON.stringify(payload || {}),
  })

  return parseApiResponse(res, 'Failed to initialize upload transfer')
}

export function buildBrowserUploadContentUrl(transfer = {}) {
  const port = String(transfer?.browser_upload_port || '').trim()
  const path = String(transfer?.browser_upload_path || '').trim()
  if (!port || !path) {
    throw new Error('Browser file transfer endpoint is unavailable')
  }

  const url = new URL(window.location.href)
  url.port = port
  url.pathname = path.startsWith('/') ? path : `/${path}`
  url.search = ''
  url.hash = ''
  return url.toString()
}

// Shared browser -> Server -> Client upload path used by both remote file dialogs.
export async function uploadRemoteFileToClient({file, clientId, destinationPath, headers = {}}) {
  const transfer = await createBrowserUploadTransfer({
    client_id: clientId,
    filename: file.name,
    total_bytes: file.size,
    destination_path: destinationPath,
  }, headers)
  const transferId = String(transfer?.transfer_id || '').trim()

  try {
    if (!transferId) throw new Error('Failed to initialize upload transfer')
    const token = String(transfer?.browser_upload_token || '').trim()
    if (!token) throw new Error('Browser file transfer token is unavailable')

    const url = buildBrowserUploadContentUrl(transfer)
    const response = await new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest()
      xhr.open('POST', url, true)
      xhr.setRequestHeader('Content-Type', 'application/octet-stream')
      xhr.setRequestHeader('X-RCH-Transfer-Token', token)
      xhr.addEventListener('load', () => {
        let json = {}
        try {
          json = JSON.parse(xhr.responseText || '{}')
        } catch (error) {
          reject(new Error('Upload returned an invalid response'))
          return
        }
        if (xhr.status < 200 || xhr.status >= 300 || json.code !== 0) {
          reject(new Error(json.message || `Upload failed (${xhr.status || 'network error'})`))
          return
        }
        resolve(json)
      })
      xhr.addEventListener('error', () => reject(new Error('Browser upload connection failed')))
      xhr.addEventListener('abort', () => reject(new Error('Browser upload was cancelled')))
      xhr.send(file)
    })
    return response.data || {}
  } catch (error) {
    if (transferId) {
      updateBrowserUploadTransfer(transferId, {
        state: 'failed',
        error: error.message || 'Browser upload failed',
      }, headers).catch(() => {})
    }
    throw error
  }
}

export async function updateBrowserUploadTransfer(transferId, payload = {}, headers = {}) {
  const normalizedTransferId = String(transferId || '').trim()
  if (!normalizedTransferId) return null

  const res = await fetch(`/api/transfers/${encodeURIComponent(normalizedTransferId)}/browser-upload`, {
    method: 'PATCH',
    headers: normalizeHeaders({
      'Content-Type': 'application/json',
      ...headers,
    }),
    body: JSON.stringify(payload || {}),
  })

  return parseApiResponse(res, 'Failed to update upload transfer')
}


function buildTabHeaders(tabId = '', headers = {}) {
  const result = normalizeHeaders(headers)
  const normalizedTabId = String(tabId || '').trim()
  if (normalizedTabId) result['X-Tab-Id'] = normalizedTabId
  return result
}

export async function cancelTransfer(transferId, tabId = '') {
  const normalizedTransferId = String(transferId || '').trim()
  if (!normalizedTransferId) throw new Error('transfer_id is required')

  const res = await fetch(`/api/transfers/${encodeURIComponent(normalizedTransferId)}/cancel`, {
    method: 'POST',
    headers: buildTabHeaders(tabId),
  })
  return parseApiResponse(res, 'Failed to cancel transfer')
}

export async function deleteRecentTransfer(transferId, tabId = '') {
  const normalizedTransferId = String(transferId || '').trim()
  if (!normalizedTransferId) throw new Error('transfer_id is required')

  const res = await fetch(`/api/transfers/${encodeURIComponent(normalizedTransferId)}`, {
    method: 'DELETE',
    headers: buildTabHeaders(tabId),
  })
  return parseApiResponse(res, 'Failed to delete transfer')
}

export async function clearRecentTransfers(tabId = '') {
  const res = await fetch('/api/transfers/recent', {
    method: 'DELETE',
    headers: buildTabHeaders(tabId),
  })
  return parseApiResponse(res, 'Failed to clear recent transfers')
}
