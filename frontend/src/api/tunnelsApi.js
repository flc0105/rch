import { apiData, jsonRequestOptions } from './http.js'

const root = (clientId) => `/api/connections/${encodeURIComponent(clientId)}/tunnels`
const entry = (clientId, name) => `${root(clientId)}/${encodeURIComponent(name)}`

export const listTunnelInstances = (clientId) => apiData(root(clientId), {}, { instances: [] })
export const createTunnelInstance = (clientId, data) => apiData(root(clientId), jsonRequestOptions('POST', data))
export const editTunnelInstance = (clientId, name, data) => apiData(entry(clientId, name), jsonRequestOptions('PUT', data))
export const removeTunnelInstance = (clientId, name) => apiData(entry(clientId, name), { method: 'DELETE' })
export const runTunnelInstance = (clientId, name, action) => apiData(`${entry(clientId, name)}/${action}`, jsonRequestOptions('POST'))
