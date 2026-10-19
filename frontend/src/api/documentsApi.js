import { apiData, jsonRequestOptions } from './http.js'

const url = (route, params = {}) => {
  const search = new URLSearchParams(params)
  return `/api/documents/${route}${search.size ? `?${search}` : ''}`
}

export const listDocumentRoots = () => apiData(url('roots'), {}, { items: [] })
export const listDocumentTree = (rootId, path = '') => apiData(url('tree', { root_id: rootId, path }), {}, { items: [] })
export const readDocument = (rootId, path) => apiData(url('content', { root_id: rootId, path }))
export const saveDocument = (payload) => apiData(url('content'), jsonRequestOptions('PUT', payload))
export const createDocument = (payload) => apiData(url('files'), jsonRequestOptions('POST', payload))
export const createDocumentDirectory = (payload) => apiData(url('directories'), jsonRequestOptions('POST', payload))
