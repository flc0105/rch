function jsonHeaders(headers = {}) {
  return {
    'Content-Type': 'application/json',
    ...headers,
  }
}

async function externalToolRequest(url, options = {}, defaultMessage = 'External tool request failed') {
  const response = await fetch(url, options)
  let payload = null

  try {
    payload = await response.json()
  } catch (_) {
    payload = null
  }

  if (!response.ok || (payload && payload.code !== undefined && payload.code !== 0)) {
    const message = payload && payload.message ? payload.message : defaultMessage
    throw new Error(message)
  }

  return payload && Object.prototype.hasOwnProperty.call(payload, 'data') ? payload.data : {}
}

function postJson(url, body = {}, headers = {}, defaultMessage = 'External tool request failed') {
  return externalToolRequest(
    url,
    {
      method: 'POST',
      headers: jsonHeaders(headers),
      body: JSON.stringify(body || {}),
    },
    defaultMessage,
  )
}

// External Tool catalog/instance reads share a single foreground slot per Client.
// Serialize this tab's reads and tolerate a short busy window caused by SSE
// refreshes from other tabs or by an in-flight lifecycle command. Writes are
// intentionally excluded: starting/stopping a process must never be retried.
const clientReadTails = new Map()
const CLIENT_BUSY_RETRY_DELAYS_MS = [150, 300, 600, 900, 1250, 1750]

function queueClientRead(clientId, request) {
  const key = String(clientId || '').trim()
  const previous = clientReadTails.get(key) || Promise.resolve()
  const current = previous.catch(() => {}).then(async () => {
    for (let attempt = 0; ; attempt += 1) {
      try {
        return await request()
      } catch (error) {
        const busy = /^Client is busy(?::|$)/i.test(String(error?.message || ''))
        if (!busy || attempt >= CLIENT_BUSY_RETRY_DELAYS_MS.length) throw error
        await new Promise(resolve => setTimeout(resolve, CLIENT_BUSY_RETRY_DELAYS_MS[attempt]))
      }
    }
  })
  clientReadTails.set(key, current)
  current.then(
    () => { if (clientReadTails.get(key) === current) clientReadTails.delete(key) },
    () => { if (clientReadTails.get(key) === current) clientReadTails.delete(key) },
  )
  return current
}

export function loadExternalToolCatalog() {
  return externalToolRequest('/api/external-tools/catalog', {}, 'Failed to load external tools')
}

export function loadExternalToolParamPresets(toolId) {
  return externalToolRequest(
    `/api/external-tools/${encodeURIComponent(toolId)}/param-presets`,
    {},
    'Failed to load parameter presets',
  )
}

export function createExternalToolParamPreset(toolId, payload = {}) {
  return postJson(
    `/api/external-tools/${encodeURIComponent(toolId)}/param-presets`,
    payload,
    {},
    'Failed to create parameter preset',
  )
}

export function updateExternalToolParamPreset(toolId, presetId, payload = {}) {
  return externalToolRequest(
    `/api/external-tools/${encodeURIComponent(toolId)}/param-presets/${encodeURIComponent(presetId)}`,
    {
      method: 'PUT',
      headers: jsonHeaders(),
      body: JSON.stringify(payload || {}),
    },
    'Failed to update parameter preset',
  )
}

export function deleteExternalToolParamPreset(toolId, presetId) {
  return externalToolRequest(
    `/api/external-tools/${encodeURIComponent(toolId)}/param-presets/${encodeURIComponent(presetId)}`,
    { method: 'DELETE' },
    'Failed to delete parameter preset',
  )
}

export function loadClientExternalToolCatalog(clientId, payload = {}, headers = {}) {
  return queueClientRead(clientId, () => postJson(
    `/api/connections/${encodeURIComponent(clientId)}/external-tools/catalog`,
    payload,
    headers,
    'Failed to load client install statuses',
  ))
}

export function loadAllClientInstances(clientId, headers = {}) {
  return queueClientRead(clientId, () => postJson(
    `/api/connections/${encodeURIComponent(clientId)}/external-tools/instances`,
    {},
    headers,
    'Failed to load client instances',
  ))
}

export function loadClientInstances(clientId, toolId, headers = {}) {
  return queueClientRead(clientId, () => postJson(
    `/api/connections/${encodeURIComponent(clientId)}/external-tools/${encodeURIComponent(toolId)}/instances`,
    {},
    headers,
    'Failed to load client instances',
  ))
}

export function uninstallClientTool(clientId, toolId, payload = {}, headers = {}) {
  return postJson(
    `/api/connections/${encodeURIComponent(clientId)}/external-tools/${encodeURIComponent(toolId)}/uninstall`,
    payload,
    { ...headers, 'X-RCH-Origin': 'web_ui' },
    'Failed to uninstall client package',
  )
}

export function clearClientPackageCache(clientId, toolId, payload = {}, headers = {}) {
  return postJson(
    `/api/connections/${encodeURIComponent(clientId)}/external-tools/${encodeURIComponent(toolId)}/clear-cache`,
    payload,
    { ...headers, 'X-RCH-Origin': 'web_ui' },
    'Failed to clear client package cache',
  )
}

export function installClientTool(clientId, toolId, payload = {}, headers = {}) {
  return postJson(
    `/api/connections/${encodeURIComponent(clientId)}/external-tools/${encodeURIComponent(toolId)}/install`,
    payload,
    { ...headers, 'X-RCH-Origin': 'web_ui' },
    'Failed to install package',
  )
}

export function resolveClientLauncher(clientId, toolId, payload = {}, headers = {}) {
  return postJson(
    `/api/connections/${encodeURIComponent(clientId)}/external-tools/${encodeURIComponent(toolId)}/launcher`,
    payload,
    headers,
    'Failed to resolve client launcher',
  )
}

export function startClientInstance(clientId, toolId, payload = {}, headers = {}) {
  return postJson(
    `/api/connections/${encodeURIComponent(clientId)}/external-tools/${encodeURIComponent(toolId)}/instances/start`,
    payload,
    { ...headers, 'X-RCH-Origin': 'web_ui' },
    'Failed to start client tool',
  )
}

export function previewClientInstanceCommand(clientId, toolId, payload = {}, headers = {}) {
  return postJson(
    `/api/connections/${encodeURIComponent(clientId)}/external-tools/${encodeURIComponent(toolId)}/instances/preview-command`,
    payload,
    headers,
    'Failed to preview client command',
  )
}

export function runClientOneshot(clientId, toolId, payload = {}, headers = {}) {
  return postJson(
    `/api/connections/${encodeURIComponent(clientId)}/external-tools/${encodeURIComponent(toolId)}/oneshot`,
    payload,
    { ...headers, 'X-RCH-Origin': 'web_ui' },
    'Failed to run client oneshot',
  )
}

export function stopClientInstance(clientId, toolId, instanceId, payload = {}, headers = {}) {
  return postJson(
    `/api/connections/${encodeURIComponent(clientId)}/external-tools/${encodeURIComponent(toolId)}/instances/${encodeURIComponent(instanceId)}/stop`,
    payload,
    { ...headers, 'X-RCH-Origin': 'web_ui' },
    'Failed to stop client instance',
  )
}

export function removeClientInstance(clientId, toolId, instanceId, payload = {}, headers = {}) {
  return postJson(
    `/api/connections/${encodeURIComponent(clientId)}/external-tools/${encodeURIComponent(toolId)}/instances/${encodeURIComponent(instanceId)}/remove`,
    payload,
    { ...headers, 'X-RCH-Origin': 'web_ui' },
    'Failed to remove client instance',
  )
}

export function clearClientInstanceLogs(clientId, toolId, instanceId, payload = {}, headers = {}) {
  return postJson(
    `/api/connections/${encodeURIComponent(clientId)}/external-tools/${encodeURIComponent(toolId)}/instances/${encodeURIComponent(instanceId)}/clear-logs`,
    payload,
    { ...headers, 'X-RCH-Origin': 'web_ui' },
    'Failed to clear client logs',
  )
}

export function loadExternalToolMetaContent(toolId) {
  return externalToolRequest(
    `/api/external-tools/${encodeURIComponent(toolId)}/meta/content`,
    {},
    'Failed to load external tool meta',
  )
}

export function saveExternalToolMetaContent(toolId, content) {
  return postJson(
    `/api/external-tools/${encodeURIComponent(toolId)}/meta/content`,
    { content },
    {},
    'Failed to save external tool meta',
  )
}

export function buildExternalToolDownloadUrl(toolId, { platform = '', arch = '' } = {}) {
  const params = new URLSearchParams()
  if (platform) params.set('platform', platform)
  if (arch) params.set('arch', arch)
  return `/api/external-tools/${encodeURIComponent(toolId)}/download?${params.toString()}`
}
