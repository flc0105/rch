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
  password: 'password',
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

const KEYCHAIN_SOURCE_FIELDS = new Set(['username', 'secret_value'])

export function normalizeKeychainPicker(param) {
  const source = param?.keychain_picker
  if (!source || typeof source !== 'object' || Array.isArray(source)) return null
  if (normalizeParamType(param?.type) !== 'password') return null

  const kind = String(source.kind || '').trim().toLowerCase()
  if (!['login', 'secret'].includes(kind)) return null
  if (!source.bindings || typeof source.bindings !== 'object' || Array.isArray(source.bindings)) return null

  const bindings = {}
  const destinations = new Set()
  for (const [field, rawName] of Object.entries(source.bindings)) {
    const name = String(rawName || '').trim()
    if (!KEYCHAIN_SOURCE_FIELDS.has(field) || !name || destinations.has(name)) return null
    if (field === 'username' && kind !== 'login') return null
    bindings[field] = name
    destinations.add(name)
  }
  if (!Object.prototype.hasOwnProperty.call(bindings, 'secret_value')) return null

  return { kind, bindings }
}

export function mapKeychainPickerValues(param, item, paramSpecs = []) {
  const picker = normalizeKeychainPicker(param)
  if (!picker || !item || typeof item !== 'object' || Array.isArray(item)) return null
  if (String(item.kind || '').trim().toLowerCase() !== picker.kind) return null

  const availableNames = new Set((Array.isArray(paramSpecs) ? paramSpecs : [])
    .map(spec => String(spec?.name || '').trim()).filter(Boolean))
  const values = {}
  for (const [source, target] of Object.entries(picker.bindings)) {
    if (availableNames.size && !availableNames.has(target)) return null
    if (!Object.prototype.hasOwnProperty.call(item, source) || item[source] === null || item[source] === undefined) {
      return null
    }
    values[target] = String(item[source])
  }
  return values
}

export function normalizeParamType(value) {
  const text = String(value || 'string').trim().toLowerCase()
  return PARAM_TYPE_ALIASES[text] || text || 'string'
}

export function normalizeParamControl(value) {
  return String(value || '').trim().toLowerCase()
}

function isParamConditionObject(condition) {
  return !!condition && typeof condition === 'object' && !Array.isArray(condition)
}

export function matchesParamCondition(condition, values = {}) {
  if (!isParamConditionObject(condition)) return false
  const entries = Object.entries(condition)
  if (!entries.length) return false
  const source = values && typeof values === 'object' && !Array.isArray(values) ? values : {}

  return entries.every(([name, expected]) => {
    const actual = source[name]
    return Array.isArray(expected)
      ? expected.some(value => Object.is(actual, value))
      : Object.is(actual, expected)
  })
}

export function isParamVisible(param, values = {}) {
  const condition = param?.visible_when
  return !isParamConditionObject(condition) || !Object.keys(condition).length
    ? true
    : matchesParamCondition(condition, values)
}

export function isParamDisabled(param, values = {}) {
  const condition = param?.disabled_when
  return isParamConditionObject(condition) && Object.keys(condition).length
    ? matchesParamCondition(condition, values)
    : false
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

  if (Object.prototype.hasOwnProperty.call(item, 'keychain_picker')) {
    normalized.keychain_picker = normalizeKeychainPicker(normalized)
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
