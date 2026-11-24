import { ElMessageBox } from 'element-plus'
import { makeRemoteDirectory } from '../api/remoteFilesApi.js'

export async function promptCreateRemoteFolder(clientId, parentPath, isActive) {
  const { value } = await ElMessageBox.prompt('Enter the new folder name', 'Create Directory', {
    confirmButtonText: 'Create', cancelButtonText: 'Cancel',
    inputPattern: /.+/, inputErrorMessage: 'Folder name is required',
  })
  const name = String(value || '').trim()
  if (!name || !isActive()) return false
  const separator = !parentPath.startsWith('/') && (parentPath.includes('\\') || /^[A-Za-z]:/.test(parentPath)) ? '\\' : '/'
  const path = `${parentPath.replace(/[\/\\]+$/, '')}${separator}${name}`
  const response = await makeRemoteDirectory(clientId, path)
  const json = await response.json()
  if (!isActive()) return false
  if (!response.ok || json.code !== 0) throw new Error(json.message || 'Create directory failed')
  return true
}
