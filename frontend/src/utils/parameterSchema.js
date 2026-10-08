const PARAM_TYPE_ALIASES = {
  int: 'integer',
  integer: 'integer',
  float: 'number',
  number: 'number',
  str: 'string',
  string: 'string',
  bool: 'boolean',
  boolean: 'boolean',
  select: 'select',
  text: 'textarea',
  multiline: 'textarea',
  textarea: 'textarea',
  remote_file: 'remote_file',
  remote_files: 'remote_files',
  remote_folder: 'remote_folder',
  remote_folders: 'remote_folders',
}

const REMOTE_PARAM_TYPES = new Set([
  'remote_file',
  'remote_files',
  'remote_folder',
  'remote_folders',
])

const REMOTE_MULTI_PARAM_TYPES = new Set([
  'remote_files',
  'remote_folders',
])

export function normalizeParamType(value) {
  const text = String(value || 'string').trim().toLowerCase()
  return PARAM_TYPE_ALIASES[text] || text || 'string'
}

export function normalizeParamSpec(item = {}) {
  if (!item || typeof item !== 'object' || Array.isArray(item)) return null
  const name = String(item.name || '').trim()
  if (!name) return null

  const type = normalizeParamType(item.type)
  const normalized = {
    ...item,
    name,
    label: String(item.label || name).trim() || name,
    type,
    required: !!item.required,
    description: String(item.description || '').trim(),
  }

  if (Object.prototype.hasOwnProperty.call(item, 'options')) {
    normalized.options = Array.isArray(item.options) ? [...item.options] : []
  } else if (type === 'select') {
    normalized.options = []
  }

  if (REMOTE_MULTI_PARAM_TYPES.has(type) && !Object.prototype.hasOwnProperty.call(item, 'multiple')) {
    normalized.multiple = true
  }

  return normalized
}

export function normalizeParamSpecs(items) {
  return (Array.isArray(items) ? items : [])
    .map(item => normalizeParamSpec(item))
    .filter(Boolean)
}

export function isRemoteParam(param) {
  return REMOTE_PARAM_TYPES.has(normalizeParamType(param?.type))
}

export function isRemoteMultiParam(param) {
  return REMOTE_MULTI_PARAM_TYPES.has(normalizeParamType(param?.type)) || !!param?.multiple
}

export function remoteParamSelectionMode(param) {
  const explicit = String(param?.selection_mode || '').trim().toLowerCase()
  if (explicit === 'folder' || explicit === 'file') return explicit
  const type = normalizeParamType(param?.type)
  return ['remote_folder', 'remote_folders'].includes(type) ? 'folder' : 'file'
}

export function remoteParamInitialPath(param, currentValue = '') {
  const type = normalizeParamType(param?.type)
  if (type === 'remote_folder') {
    const currentPath = String(currentValue || '').trim()
    if (currentPath) return currentPath
  }

  return String(param?.initial_path || '').trim()
}

export function cloneParamValue(value) {
  if (Array.isArray(value)) return value.map(item => cloneParamValue(item))
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, cloneParamValue(item)]))
  }
  return value
}
