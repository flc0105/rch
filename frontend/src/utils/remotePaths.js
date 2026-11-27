// Remote path style belongs to the target path, not the browser OS.
export function joinRemotePath(root, relativePath) {
  const windows = !root.startsWith('/') && (root.includes('\\') || /^[A-Za-z]:/.test(root))
  const separator = windows ? '\\' : '/'
  const base = windows ? root.replace(/[\\/]+$/, '') : root.replace(/\/+$/, '')
  return `${base}${separator}${relativePath.split('/').join(separator)}`
}

export function buildRemoteBreadcrumbItems(path) {
  const currentPath = String(path || '').trim()
  if (!currentPath) return []

  const windowsMatch = currentPath.match(/^([A-Za-z]:)([\\/].*)?$/)

  if (windowsMatch) {
    const drive = windowsMatch[1]
    const rest = String(windowsMatch[2] || '').replace(/^[\\/]+/, '')
    const parts = rest ? rest.split(/[\\/]+/).filter(Boolean) : []
    const items = [{label: drive, path: `${drive}\\`}]
    let accumulated = `${drive}\\`

    parts.forEach(part => {
      accumulated = accumulated.replace(/[\\/]+$/, '') + '\\' + part
      items.push({label: part, path: accumulated})
    })

    return items
  }

  const isAbsolute = currentPath.startsWith('/')
  const parts = currentPath.split('/').filter(Boolean)
  const items = []

  if (isAbsolute) {
    items.push({label: 'Root', path: '/'})
  }

  let accumulated = ''

  parts.forEach(part => {
    if (isAbsolute) {
      accumulated += `/${part}`
    } else {
      accumulated = accumulated ? `${accumulated}/${part}` : part
    }

    items.push({label: part, path: accumulated})
  })

  if (!items.length && isAbsolute) {
    items.push({label: 'Root', path: '/'})
  }

  return items
}

export function isZipEntry(row) {
  if (!row || row.is_dir || row.is_parent_entry) return false
  const name = String(row.name || row.path || '').trim().toLowerCase()
  return name.endsWith('.zip')
}
