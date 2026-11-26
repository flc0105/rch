// Remote path style belongs to the target path, not the browser OS.
export function joinRemotePath(root, relativePath) {
  const windows = !root.startsWith('/') && (root.includes('\\') || /^[A-Za-z]:/.test(root))
  const separator = windows ? '\\' : '/'
  const base = windows ? root.replace(/[\\/]+$/, '') : root.replace(/\/+$/, '')
  return `${base}${separator}${relativePath.split('/').join(separator)}`
}
