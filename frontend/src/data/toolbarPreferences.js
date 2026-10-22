export const TOOLBAR_ACTION_CATALOG = [
  { id: 'remote-files', label: 'Remote Files', icon: 'folder-open', accent: true },
  { id: 'artifacts', label: 'Artifacts', icon: 'archive', accent: true },
  { id: 'info', label: 'Info', icon: 'monitor' },
  { id: 'scripts', label: 'Scripts', icon: 'file-code' },
  { id: 'history', label: 'History', icon: 'history' },
  { id: 'pty', label: 'PTY', icon: 'terminal' },
  { id: 'screen-view', label: 'Screen View', icon: 'monitor-play' },
  { id: 'clipboard', label: 'Clipboard', icon: 'clipboard' },
  { id: 'external-tools', label: 'External Tools', icon: 'wrench' },
  { id: 'log-viewer', label: 'Log Viewer', icon: 'scroll-text' },
  { id: 'jobs', label: 'Jobs', icon: 'calendar-clock' },
  { id: 'agents', label: 'Agents', icon: 'bot' },
  { id: 'processes', label: 'Processes', icon: 'activity' },
  { id: 'keychains', label: 'Keychains', icon: 'key-round' },
  { id: 'documents', label: 'Documents', icon: 'book-open' },
  { id: 'one-liners', label: 'One-liners', icon: 'code-2' },
  { id: 'quick-actions', label: 'Quick Actions', icon: 'zap' },
]

// Shared sub-actions used by the Toolbar hover menus and Toolbox right-click menu.
export const TOOLBAR_ACTION_OPTIONS = Object.freeze({
  clipboard: Object.freeze([
    { id: 'get', label: 'Get' },
    { id: 'send', label: 'Send' },
  ]),
  'screen-view': Object.freeze([
    { id: 'new-tab', label: 'Open in New Tab' },
  ]),
})

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
    'log-viewer',
    'jobs',
    'agents',
    'processes',
    'keychains',
    'documents',
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
