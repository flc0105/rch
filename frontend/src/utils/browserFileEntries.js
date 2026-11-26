// Browser FileSystemEntry traversal is shared by Clipboard Send and drag uploads.
export async function readFileSystemEntries(directory) {
  const reader = directory.createReader()
  const entries = []
  while (true) {
    const batch = await new Promise((resolve, reject) => reader.readEntries(resolve, reject))
    if (!batch.length) break
    entries.push(...batch)
  }
  return entries
}

export async function collectFileSystemEntry(entry) {
  if (entry?.isFile) {
    const file = await new Promise((resolve, reject) => entry.file(resolve, reject))
    return file ? { kind: 'file', name: file.name, file } : null
  }
  if (!entry?.isDirectory) return null
  const directories = []
  const files = []
  async function visit(directory, path) {
    directories.push(path)
    for (const child of await readFileSystemEntries(directory)) {
      const relativePath = `${path}/${child.name}`
      if (child.isDirectory) await visit(child, relativePath)
      else if (child.isFile) {
        const file = await new Promise((resolve, reject) => child.file(resolve, reject))
        if (!file) throw new Error(`Cannot read ${relativePath}`)
        files.push({ file, relativePath })
      } else throw new Error(`Cannot read ${relativePath}`)
    }
  }
  await visit(entry, entry.name)
  return { kind: 'directory', name: entry.name, directories, files }
}

export async function collectTransferAttachments(transfer) {
  const items = Array.from(transfer?.items || []).filter(item => item?.kind === 'file')
  if (!items.length) return Array.from(transfer?.files || []).map(file => ({ kind: 'file', name: file.name, file }))
  // Capture every item synchronously while the browser still exposes the drop data.
  const sources = items.map(item => ({ entry: item.webkitGetAsEntry?.(), file: item.getAsFile?.() }))
  const fallback = Array.from(transfer?.files || [])
  const attachments = []
  for (const [index, source] of sources.entries()) {
    const attachment = source.entry ? await collectFileSystemEntry(source.entry) : null
    const file = source.file || (fallback.length === sources.length ? fallback[index] : null)
    if (attachment) attachments.push(attachment)
    else if (file) attachments.push({ kind: 'file', name: file.name, file })
    else throw new Error('Cannot read all dropped files')
  }
  return attachments
}

// A native directory picker returns file paths, not empty directory entries.
export function collectDirectoryPickerAttachments(files) {
  const roots = new Map()
  for (const file of files || []) {
    const path = file.webkitRelativePath || ''
    const parts = path.split('/')
    if (parts.length < 2 || parts.at(-1) !== file.name) throw new Error('Cannot read selected folder paths')
    const name = parts[0]
    if (!roots.has(name)) roots.set(name, { kind: 'directory', name, directories: [name], files: [] })
    roots.get(name).files.push({ file, relativePath: path })
  }
  return [...roots.values()]
}

export function flattenUploadAttachments(attachments) {
  const directories = new Set()
  const files = []
  const check = value => {
    const path = String(value || '')
    const parts = path.split('/')
    if (!path || parts.some(part => !part || part === '.' || part === '..' || /[\\\x00-\x1f]/.test(part))) {
      throw new Error('Invalid upload path')
    }
    return parts
  }
  const roots = new Set()
  for (const item of attachments || []) {
    if (roots.has(item?.name)) throw new Error(`Duplicate selected item: ${item.name}`)
    roots.add(item?.name)
    if (item?.kind === 'directory') {
      const rootParts = check(item.name)
      if (rootParts.length !== 1) throw new Error('Invalid upload path')
      directories.add(item.name)
      for (const path of item.directories || []) {
        const parts = check(path)
        if (parts[0] !== item.name) throw new Error('Invalid upload path')
        for (let i = 1; i <= parts.length; i++) directories.add(parts.slice(0, i).join('/'))
      }
      for (const entry of item.files || []) {
        if (!entry.file) throw new Error(`Cannot read ${entry.relativePath}`)
        const parts = check(entry.relativePath)
        if (parts[0] !== item.name) throw new Error('Invalid upload path')
        for (let i = 1; i < parts.length; i++) directories.add(parts.slice(0, i).join('/'))
        files.push({ file: entry.file, relativePath: parts.join('/') })
      }
    } else if (item?.kind === 'file' && item.file) {
      const parts = check(item.name)
      if (parts.length !== 1) throw new Error('Invalid upload path')
      files.push({ file: item.file, relativePath: parts[0] })
    }
  }
  const filePaths = new Set()
  for (const { file, relativePath } of files) {
    if (file.name !== relativePath.split('/').at(-1) || filePaths.has(relativePath) || directories.has(relativePath)) {
      throw new Error('Invalid or duplicate upload path')
    }
    filePaths.add(relativePath)
  }
  const totalBytes = files.reduce((total, entry) => total + (Number(entry.file.size) || 0), 0)
  return { totalBytes, directories: [...directories].sort((a, b) => a.split('/').length - b.split('/').length || a.localeCompare(b)), files }
}
