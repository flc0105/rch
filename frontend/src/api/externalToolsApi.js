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
  return postJson(
    `/api/connections/${encodeURIComponent(clientId)}/external-tools/catalog`,
    payload,
    headers,
    'Failed to load client install statuses',
  )
}

export function loadAllClientInstances(clientId, headers = {}) {
  return postJson(
    `/api/connections/${encodeURIComponent(clientId)}/external-tools/instances`,
    {},
    headers,
    'Failed to load client instances',
  )
}

export function loadClientInstances(clientId, toolId, headers = {}) {
  return postJson(
    `/api/connections/${encodeURIComponent(clientId)}/external-tools/${encodeURIComponent(toolId)}/instances`,
    {},
    headers,
    'Failed to load client instances',
  )
}

export function uninstallClientTool(clientId, toolId, payload = {}, headers = {}) {
  return postJson(
    `/api/connections/${encodeURIComponent(clientId)}/external-tools/${encodeURIComponent(toolId)}/uninstall`,
    payload,
    headers,
    'Failed to uninstall client package',
  )
}

export function clearClientPackageCache(clientId, toolId, payload = {}, headers = {}) {
  return postJson(
    `/api/connections/${encodeURIComponent(clientId)}/external-tools/${encodeURIComponent(toolId)}/clear-cache`,
    payload,
    headers,
    'Failed to clear client package cache',
  )
}

export function installClientTool(clientId, toolId, payload = {}, headers = {}) {
  return postJson(
    `/api/connections/${encodeURIComponent(clientId)}/external-tools/${encodeURIComponent(toolId)}/install`,
    payload,
    headers,
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
    headers,
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
    headers,
    'Failed to run client oneshot',
  )
}

export function stopClientInstance(clientId, toolId, instanceId, payload = {}, headers = {}) {
  return postJson(
    `/api/connections/${encodeURIComponent(clientId)}/external-tools/${encodeURIComponent(toolId)}/instances/${encodeURIComponent(instanceId)}/stop`,
    payload,
    headers,
    'Failed to stop client instance',
  )
}

export function readClientInstanceLogs(clientId, toolId, instanceId, payload = {}, headers = {}) {
  return postJson(
    `/api/connections/${encodeURIComponent(clientId)}/external-tools/${encodeURIComponent(toolId)}/instances/${encodeURIComponent(instanceId)}/logs`,
    payload,
    headers,
    'Failed to read client logs',
  )
}

export function removeClientInstance(clientId, toolId, instanceId, payload = {}, headers = {}) {
  return postJson(
    `/api/connections/${encodeURIComponent(clientId)}/external-tools/${encodeURIComponent(toolId)}/instances/${encodeURIComponent(instanceId)}/remove`,
    payload,
    headers,
    'Failed to remove client instance',
  )
}

export function clearClientInstanceLogs(clientId, toolId, instanceId, payload = {}, headers = {}) {
  return postJson(
    `/api/connections/${encodeURIComponent(clientId)}/external-tools/${encodeURIComponent(toolId)}/instances/${encodeURIComponent(instanceId)}/clear-logs`,
    payload,
    headers,
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
