export function formatDateTimeStandard(value) {
  const text = String(value || '').trim()
  if (!text) return '-'

  const normalized = text.replace('T', ' ').split('.')[0]
  return normalized || '-'
}

export function formatDateTimeShort(value) {
  const text = String(value || '').trim()
  if (!text) return '-'
  return text.replace('T', ' ').slice(0, 19)
}

export function formatDateTimePreserveFraction(value, empty = '') {
  const text = String(value || '').trim()
  if (!text) return empty
  return text.replace('T', ' ')
}

export function formatDateTimeLocal(value) {
  const date = value instanceof Date ? value : new Date(value)
  if (Number.isNaN(date.getTime())) return '-'

  const pad = number => String(number).padStart(2, '0')
  return [
    date.getFullYear(),
    '-',
    pad(date.getMonth() + 1),
    '-',
    pad(date.getDate()),
    ' ',
    pad(date.getHours()),
    ':',
    pad(date.getMinutes()),
    ':',
    pad(date.getSeconds()),
  ].join('')
}

export function formatBytes(size) {
  const value = Number(size || 0)

  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(2)} KB`
  if (value < 1024 * 1024 * 1024) return `${(value / 1024 / 1024).toFixed(2)} MB`

  return `${(value / 1024 / 1024 / 1024).toFixed(2)} GB`
}

export function formatBytesHuman(size, options = {}) {
  const {
    invalid = '—',
    zero = '0 B',
    maxUnit = 'TB',
    precision = 'adaptive',
    nonPositiveAsZero = false,
  } = options

  const numeric = Number(size)
  if (!Number.isFinite(numeric) || numeric < 0) {
    return nonPositiveAsZero ? zero : invalid
  }
  if (numeric === 0) return zero

  const units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']
  const requestedMaxIndex = units.indexOf(maxUnit)
  const maxIndex = requestedMaxIndex >= 0 ? requestedMaxIndex : units.indexOf('TB')
  const index = Math.min(Math.floor(Math.log(numeric) / Math.log(1024)), maxIndex)
  const scaled = numeric / (1024 ** index)

  let digits = 0
  if (index > 0) {
    if (precision === 'one') digits = 1
    else if (precision === 'compact') digits = scaled >= 10 ? 0 : 1
    else digits = scaled >= 100 ? 0 : (scaled >= 10 ? 1 : 2)
  }

  return `${scaled.toFixed(digits)} ${units[index]}`
}
