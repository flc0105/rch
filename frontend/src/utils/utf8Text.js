/** Keep the newest complete UTF-8 characters within a byte budget. */
export function retainRecentUtf8Bytes(value, maxBytes) {
  const text = String(value ?? '')
  if (!text || !Number.isSafeInteger(maxBytes) || maxBytes <= 0) return ''
  const bytes = new TextEncoder().encode(text)
  if (bytes.length <= maxBytes) return text
  let start = bytes.length - maxBytes
  while (start < bytes.length && (bytes[start] & 0xc0) === 0x80) start += 1
  return new TextDecoder('utf-8').decode(bytes.subarray(start))
}
