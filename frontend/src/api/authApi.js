import { apiData, jsonRequestOptions } from './http.js'

const PASSWORD_MASK_KEY = new TextEncoder().encode('RCH-login-transport-mask')

function bytesToBase64(bytes) {
  let text = ''
  for (const byte of bytes) text += String.fromCharCode(byte)
  return btoa(text)
}

function maskPassword(password) {
  const nonce = new Uint8Array(16)
  crypto.getRandomValues(nonce)
  const bytes = new TextEncoder().encode(String(password || ''))
  const masked = bytes.map((value, index) => (
    value ^ PASSWORD_MASK_KEY[index % PASSWORD_MASK_KEY.length] ^ nonce[index % nonce.length]
  ))
  return {
    masked_password: bytesToBase64(masked),
    mask_nonce: bytesToBase64(nonce),
  }
}

export function getAuthSession() {
  return apiData('/api/auth/session', { cache: 'no-store' }, { authenticated: false, username: '' })
}

export function getAuthorizationInfo() {
  return apiData('/api/auth/info', { cache: 'no-store' }, { username: '', api_token: '' })
}

export function changeAdminPassword(currentPassword, newPassword) {
  return apiData(
    '/api/auth/password',
    jsonRequestOptions('POST', {
      current_password: maskPassword(currentPassword),
      new_password: maskPassword(newPassword),
    }),
    {},
  )
}
