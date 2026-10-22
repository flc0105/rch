// Shared JSON recognition and render model for Terminal and execution result dialogs.
// Only standalone JSON objects/arrays are actionable; ordinary log text is not JSON.
export const JSON_ROW_ACTIONS = Symbol('terminalJsonRowActions')

export function isJsonContainerText(text) {
  const raw = String(text ?? '').trim()
  if (!raw || !((raw[0] === '{' && raw.at(-1) === '}') || (raw[0] === '[' && raw.at(-1) === ']'))) return false
  try {
    const value = JSON.parse(raw)
    return value !== null && typeof value === 'object'
  } catch (_) {
    return false
  }
}

export function isJsonStartLine(text) {
  const raw = String(text ?? '').trim()
  return raw === '{' || raw === '['
}

export function jsonBracketDelta(text) {
  const raw = String(text ?? '')
  let depth = 0
  let inString = false
  let escaped = false
  for (const ch of raw) {
    if (escaped) { escaped = false; continue }
    if (ch === '\\' && inString) { escaped = true; continue }
    if (ch === '"') { inString = !inString; continue }
    if (inString) continue
    if (ch === '{' || ch === '[') depth++
    else if (ch === '}' || ch === ']') depth--
  }
  return depth
}

export function parseJsonLines(lines) {
  if (!Array.isArray(lines) || !lines.length) return null
  const raw = lines.join('\n').trim()
  return isJsonContainerText(raw) ? raw : null
}

// Result dialogs receive accumulated output rather than Terminal's line events.
// Prefer a complete JSON result; otherwise find a complete standalone JSON block.
export function findJsonOutput(text) {
  const normalized = String(text ?? '').replace(/\r\n?/g, '\n').trim()
  if (isJsonContainerText(normalized)) return normalized
  const lines = normalized.split('\n')
  for (let i = 0; i < lines.length; i++) {
    const candidate = lines[i].trim()
    if (isJsonContainerText(candidate)) return candidate
    if (!isJsonStartLine(candidate)) continue
    const buffer = []
    let depth = 0
    for (let j = i; j < lines.length; j++) {
      buffer.push(lines[j])
      depth += jsonBracketDelta(lines[j])
      if (depth <= 0) {
        const block = parseJsonLines(buffer)
        if (block) return block
        break
      }
    }
  }
  return null
}

const isPlainObject = value => !!value && typeof value === 'object' && !Array.isArray(value)

export function normalizeJsonRowActions(actions) {
  if (!Array.isArray(actions)) return []
  return actions.flatMap(action => {
    if (!isPlainObject(action)) return []
    const label = typeof action.label === 'string' ? action.label.trim() : ''
    const command = typeof action.command === 'string' ? action.command.trim() : ''
    return label && command ? [{ label, command }] : []
  })
}

export function formatJsonFlatValue(value) {
  if (value === null || value === undefined) return ''
  return typeof value === 'object' ? JSON.stringify(value) : String(value)
}

export function buildJsonTableModel(parsed) {
  if (!Array.isArray(parsed) || !parsed.length || !parsed.every(isPlainObject)) return null
  const firstKeys = Object.keys(parsed[0]).filter(key => key !== '_actions')
  if (!firstKeys.length) return null
  const sortedKeys = [...firstKeys].sort()
  if (!parsed.every(item => {
    const keys = Object.keys(item).filter(key => key !== '_actions').sort()
    return keys.length === sortedKeys.length && keys.every((key, i) => key === sortedKeys[i])
  })) return null

  return {
    columns: firstKeys.map(key => ({ prop: key, label: key })),
    rows: parsed.map(item => {
      const row = {}
      for (const key of firstKeys) row[key] = formatJsonFlatValue(item[key])
      Object.defineProperty(row, JSON_ROW_ACTIONS, { value: normalizeJsonRowActions(item._actions), configurable: true })
      return row
    }),
  }
}

export function buildJsonGroupedModel(parsed) {
  if (!isPlainObject(parsed)) return null
  const keys = Object.keys(parsed)
  if (keys.length < 2 || !keys.every(key => isPlainObject(parsed[key]) && Object.keys(parsed[key]).length > 0)) return null
  return keys.map(key => ({
    key,
    items: Object.keys(parsed[key]).map(itemKey => ({ key: itemKey, label: itemKey, value: formatJsonFlatValue(parsed[key][itemKey]) })),
  }))
}

export function buildJsonFlatModel(parsed) {
  if (!isPlainObject(parsed)) return null
  return Object.keys(parsed).map(key => ({ key, label: key, value: formatJsonFlatValue(parsed[key]) }))
}

export function getJsonRenderModel(jsonText) {
  let parsed
  try { parsed = JSON.parse(String(jsonText ?? '').trim()) } catch (_) { return { mode: 'raw', columns: [], rows: [], groups: [], flatRows: [] } }
  const table = buildJsonTableModel(parsed)
  const groups = table ? null : buildJsonGroupedModel(parsed)
  const flat = table || groups ? null : buildJsonFlatModel(parsed)
  return {
    mode: table ? 'table' : groups ? 'grouped' : flat ? 'flat' : 'raw',
    columns: table?.columns || [], rows: table?.rows || [],
    groups: groups || [], flatRows: flat || [],
  }
}
