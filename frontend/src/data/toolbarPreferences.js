export const TOOLBAR_ACTION_CATALOG = [
  { id: 'remote-files', label: 'Remote Files', accent: true },
  { id: 'artifacts', label: 'Artifacts', accent: true },
  { id: 'info', label: 'Info' },
  { id: 'scripts', label: 'Scripts' },
  { id: 'history', label: 'History' },
  { id: 'pty', label: 'PTY' },
  { id: 'screen-view', label: 'Screen View' },
  { id: 'clipboard', label: 'Clipboard' },
  { id: 'external-tools', label: 'External Tools' },
  { id: 'jobs', label: 'Jobs' },
  { id: 'agents', label: 'Agents' },
  { id: 'processes', label: 'Processes' },
  { id: 'keychains', label: 'Keychains' },
  { id: 'one-liners', label: 'One-liners' },
  { id: 'quick-actions', label: 'Quick Actions' },
]

export const DEFAULT_TOOLBAR_PREFERENCES = {
  toolbar: [
    'remote-files',
    'artifacts',
    'info',
    'scripts',
    'history',
    'pty',
    'screen-view',
    'clipboard',
  ],
  more: [
    'external-tools',
    'jobs',
    'agents',
    'processes',
    'keychains',
    'one-liners',
    'quick-actions',
  ],
  quick_actions_pinned: [],
}

export function cloneToolbarPreferences(preferences = DEFAULT_TOOLBAR_PREFERENCES) {
  return {
    toolbar: [...(preferences?.toolbar || [])],
    more: [...(preferences?.more || [])],
    quick_actions_pinned: (preferences?.quick_actions_pinned || []).map((item) => ({
      platform: String(item?.platform || '').trim(),
      alias: String(item?.alias || '').trim(),
    })).filter((item) => item.platform && item.alias),
  }
}

export function quickActionPinKey(platform, alias) {
  return `${String(platform || '').trim()}\u0000${String(alias || '').trim()}`
}

export function normalizeQuickActionPins(value) {
  if (!Array.isArray(value)) return []
  const result = []
  const seen = new Set()
  value.forEach((item) => {
    const platform = String(item?.platform || '').trim().toLowerCase()
    const alias = String(item?.alias || '').trim()
    if (!platform || !alias) return
    const key = quickActionPinKey(platform, alias)
    if (seen.has(key)) return
    seen.add(key)
    result.push({ platform, alias })
  })
  return result
}

export function normalizeToolbarPreferences(preferences = {}) {
  const allowed = new Set(TOOLBAR_ACTION_CATALOG.map((item) => item.id))
  const used = new Set()
  const normalizeList = (value) => {
    if (!Array.isArray(value)) return []
    const result = []
    value.forEach((item) => {
      const id = String(item || '').trim()
      if (!allowed.has(id) || used.has(id)) return
      used.add(id)
      result.push(id)
    })
    return result
  }

  const normalized = {
    toolbar: normalizeList(preferences?.toolbar),
    more: normalizeList(preferences?.more),
    quick_actions_pinned: normalizeQuickActionPins(preferences?.quick_actions_pinned),
  }

  TOOLBAR_ACTION_CATALOG.forEach((action) => {
    if (used.has(action.id)) return
    const section = DEFAULT_TOOLBAR_PREFERENCES.toolbar.includes(action.id) ? 'toolbar' : 'more'
    normalized[section].push(action.id)
    used.add(action.id)
  })

  return normalized
}
