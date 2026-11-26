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
        if (file) files.push({ file, relativePath })
      }
    }
  }
  await visit(entry, entry.name)
  return { kind: 'directory', name: entry.name, directories, files }
}

export async function collectTransferAttachments(transfer) {
  const items = Array.from(transfer?.items || []).filter(item => item?.kind === 'file')
  const entries = items.map(item => item.webkitGetAsEntry?.()).filter(Boolean)
  if (entries.length) {
    const attachments = []
    for (const entry of entries) {
      const attachment = await collectFileSystemEntry(entry)
      if (attachment) attachments.push(attachment)
    }
    if (attachments.length) return attachments
  }
  return Array.from(transfer?.files || []).map(file => ({ kind: 'file', name: file.name, file }))
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
  for (const item of attachments || []) {
    if (item?.kind === 'directory') {
      const rootParts = check(item.name)
      if (rootParts.length !== 1) throw new Error('Invalid upload path')
      for (const path of item.directories || []) {
        const parts = check(path)
        if (parts[0] !== item.name) throw new Error('Invalid upload path')
        directories.add(parts.join('/'))
      }
      for (const entry of item.files || []) {
        if (!entry.file) continue
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
  return { directories: [...directories].sort((a, b) => a.split('/').length - b.split('/').length || a.localeCompare(b)), files }
}
