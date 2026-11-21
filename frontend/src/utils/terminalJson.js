// Shared JSON recognition and render model for Terminal and execution result dialogs.
// Only standalone JSON objects/arrays are actionable; ordinary log text is not JSON.
export const JSON_ROW_SOURCE = Symbol('terminalJsonRowSource')

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

// Script and command output may contain several structured records. Select the
// latest view-bearing record; never attach its actions to another record's data.
export function selectJsonViewResult(previous, result) {
  if (!result || result.data === undefined) return previous
  const candidate = { jsonText: JSON.stringify(result.data), view: result.view ?? null }
  if (previous?.view && !candidate.view) return previous
  return candidate
}

export function normalizeJsonViewActions(actions) {
  if (!Array.isArray(actions)) return []
  return actions.flatMap(action => {
    if (!isPlainObject(action)) return []
    const label = typeof action.label === 'string' ? action.label.trim() : ''
    const command = typeof action.command === 'string' ? action.command.trim() : ''
    return label && command ? [{ label, command, confirm: action.confirm !== false, refresh: action.refresh === true }] : []
  })
}

export function formatJsonFlatValue(value) {
  if (value === null || value === undefined) return ''
  return typeof value === 'object' ? JSON.stringify(value) : String(value)
}

export function buildJsonTableModel(parsed) {
  if (!Array.isArray(parsed) || !parsed.length || !parsed.every(isPlainObject)) return null
  const firstKeys = Object.keys(parsed[0])
  if (!firstKeys.length) return null
  const sortedKeys = [...firstKeys].sort()
  if (!parsed.every(item => {
    const keys = Object.keys(item).sort()
    return keys.length === sortedKeys.length && keys.every((key, i) => key === sortedKeys[i])
  })) return null

  return {
    columns: firstKeys.map(key => ({ prop: key, label: key })),
    rows: parsed.map(item => {
      const row = {}
      for (const key of firstKeys) row[key] = formatJsonFlatValue(item[key])
      Object.defineProperty(row, JSON_ROW_SOURCE, { value: item, configurable: true })
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

export function getJsonRenderModel(jsonText, view = null) {
  let parsed
  try { parsed = JSON.parse(String(jsonText ?? '').trim()) } catch (_) { return { mode: 'raw', columns: [], rows: [], groups: [], flatRows: [] } }
  // An empty typed result can still show its declared columns after the final row is deleted.
  if (Array.isArray(parsed) && parsed.length === 0 && Array.isArray(view?.columns) && view.columns.length) {
    return { mode: 'table', columns: view.columns.filter(col => typeof col?.field === 'string').map(col => ({ prop: col.field, label: col.field })),
      rows: [], groups: [], flatRows: [] }
  }
  const table = buildJsonTableModel(parsed)
  const groups = table ? null : buildJsonGroupedModel(parsed)
  const flat = table || groups ? null : buildJsonFlatModel(parsed)
  return {
    mode: table ? 'table' : groups ? 'grouped' : flat ? 'flat' : 'raw',
    columns: table?.columns || [], rows: table?.rows || [],
    groups: groups || [], flatRows: flat || [],
  }
}


// The view is optional, result-level metadata. Raw JSON fields never get rewritten.
export function normalizeJsonView(view, availableColumns = []) {
  const source = isPlainObject(view) ? view : {}
  const known = new Set(availableColumns.map(item => item.prop))
  const columns = Array.isArray(source.columns) ? source.columns.flatMap(item => {
    if (!isPlainObject(item) || typeof item.field !== 'string' || !known.has(item.field)) return []
    const entry = { prop: item.field, label: item.field }
    if (Number.isInteger(item.width) && item.width >= 40 && item.width <= 1600) entry.width = item.width
    if (Number.isInteger(item.minWidth) && item.minWidth >= 40 && item.minWidth <= 1600) entry.minWidth = item.minWidth
    return [entry]
  }) : []
  const details = Array.isArray(source.details)
    ? [...new Set(source.details.filter(field => typeof field === 'string' && known.has(field)))]: []
  const actions = Array.isArray(source.actions) ? normalizeJsonViewActions(source.actions) : []
  return {
    titleField: known.has(source.titleField) ? source.titleField : '',
    columns: columns.length ? columns : availableColumns.filter(col => !details.includes(col.prop)),
    details,
    actions,
  }
}

// Quote substitutions as a single token according to the Server ACMD shlex parser.
// A missing/complex field suppresses the action rather than sending a guessed command.
function quoteJsonActionValue(value) {
  if (value === null || value === undefined || typeof value === 'object') return null
  const text = String(value)
  if (/[\u0000-\u001f]/.test(text)) return null
  return /^[a-zA-Z0-9_@%+=:,./-]+$/.test(text) ? text : "'" + text.replaceAll("'", "'\\''") + "'"
}

export function resolveJsonViewRowActions(view, rawRow) {
  if (!isPlainObject(rawRow)) return []
  const templates = Array.isArray(view?.actions) ? view.actions : []
  return templates.flatMap(action => {
    let missing = false
    const placeholder = /\{([a-zA-Z_][a-zA-Z0-9_]*)\}/g
    if (/\{[^{}]*\}/.test(action.command.replace(placeholder, ''))) return []
    const command = action.command.replace(placeholder, (_, field) => {
      if (!Object.prototype.hasOwnProperty.call(rawRow, field)) { missing = true; return '' }
      const value = quoteJsonActionValue(rawRow[field])
      if (value === null) { missing = true; return '' }
      return value
    })
    if (missing) return []
    return [{ ...action, command }]
  })
}
