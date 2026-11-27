export function getModuleLauncher(module) {
  if (!module) return null
  const binaryName = String(module.binary || '').trim()
  const binaries = module.package_binaries && typeof module.package_binaries === 'object' ? module.package_binaries : {}
  const binaryItem = binaryName && binaries[binaryName] && typeof binaries[binaryName] === 'object' ? binaries[binaryName] : {}
  const launcher = binaryItem.launcher && typeof binaryItem.launcher === 'object' ? binaryItem.launcher : null
  const launcherType = String(launcher?.type || 'direct').trim().toLowerCase()
  return launcher && launcherType !== 'direct' ? launcher : null
}

export function getModuleExecution(module) {
  if (!module) return ''
  const value = String(module.execution || '').trim().toLowerCase()
  return value
}

export function isOneshotModule(module) {
  return getModuleExecution(module) === 'oneshot'
}

export function formatExecutionLabel(module) {
  const execution = getModuleExecution(module)
  return execution || 'unknown'
}

export function getExecutionTagType(module) {
  return isOneshotModule(module) ? 'success' : 'info'
}

export function getRunButtonLabel(module = null) {
  const action = isOneshotModule(module) ? 'Run Once' : 'Run'
  return `${action} on This Client`
}

export function stringifyDetailValue(value) {
  if (value === undefined || value === null || value === '') return '-'
  if (typeof value === 'string') return value
  try {
    return JSON.stringify(value, null, 2)
  } catch (_) {
    return String(value)
  }
}
