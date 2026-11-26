import { ElMessageBox } from 'element-plus'
import { makeRemoteDirectory } from '../api/remoteFilesApi.js'
import { joinRemotePath } from './remotePaths.js'

export async function promptCreateRemoteFolder(clientId, parentPath, isActive) {
  const { value } = await ElMessageBox.prompt('Enter the new folder name', 'Create Directory', {
    confirmButtonText: 'Create', cancelButtonText: 'Cancel',
    inputPattern: /.+/, inputErrorMessage: 'Folder name is required',
  })
  const name = String(value || '').trim()
  if (!name || !isActive()) return false
  const path = joinRemotePath(parentPath, name)
  const response = await makeRemoteDirectory(clientId, path)
  const json = await response.json()
  if (!isActive()) return false
  if (!response.ok || json.code !== 0) throw new Error(json.message || 'Create directory failed')
  return true
}
