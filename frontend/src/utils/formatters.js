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

export function diffDateTimeMs(startValue, endValue = '') {
  const normalize = value => String(value || '').trim().replace(' ', 'T')
  const startText = normalize(startValue)
  if (!startText) return 0

  const startMs = Date.parse(startText)
  if (!Number.isFinite(startMs)) return 0

  const endText = normalize(endValue)
  const endMs = endText ? Date.parse(endText) : Date.now()
  if (!Number.isFinite(endMs)) return 0

  return Math.max(endMs - startMs, 0)
}

export function formatLaunchMode(modeValue, sourceValue = '') {
  const mode = String(modeValue || '').trim().toLowerCase()
  const source = String(sourceValue || '').trim().toLowerCase()
  const modeLabels = {
    terminal: 'Terminal',
    terminal_background: 'Terminal background',
    ide: 'IDE',
    detached: 'Detached',
    user_service: 'User service',
    system_service: 'System service',
    scheduled: 'Scheduled',
    unknown: 'Unknown',
  }
  const sourceLabels = {
    zsh: 'zsh',
    bash: 'bash',
    sh: 'sh',
    dash: 'dash',
    fish: 'fish',
    ksh: 'ksh',
    tcsh: 'tcsh',
    cmd: 'CMD',
    powershell: 'PowerShell',
    pwsh: 'PowerShell',
    pycharm: 'PyCharm',
    pythonista: 'Pythonista',
    launchagent: 'LaunchAgent',
    launchdaemon: 'LaunchDaemon',
    systemd_user: 'systemd --user',
    systemd: 'systemd',
    windows_service: 'Windows Service',
    cron: 'cron',
    schtasks: 'Task Scheduler',
    new_session: 'new session',
    detached_process: 'detached process',
  }

  const modeLabel = modeLabels[mode] || mode || 'Unknown'
  const sourceLabel = sourceLabels[source] || source
  return sourceLabel ? `${modeLabel} (${sourceLabel})` : modeLabel
}
