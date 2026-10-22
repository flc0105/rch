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
  toolbox_shortcuts: [],
}

export function cloneToolbarPreferences(preferences = DEFAULT_TOOLBAR_PREFERENCES) {
  return {
    toolbar: [...(preferences?.toolbar || [])],
    more: [...(preferences?.more || [])],
    toolbox_shortcuts: normalizeToolboxShortcuts(preferences?.toolbox_shortcuts),
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

export const TOOLBOX_SHORTCUT_ICONS = Object.freeze([
  'file-code', 'terminal', 'zap', 'rocket', 'play', 'activity', 'shield-check',
  'folder-open', 'monitor', 'wrench', 'calendar-clock', 'book-open', 'code-2',
  'archive', 'clipboard', 'scroll-text',
  'star', 'heart', 'check-circle', 'circle-alert', 'bell', 'bookmark', 'flag',
  'folder', 'folder-code', 'file-text', 'file-json', 'files', 'braces', 'bug',
  'git-branch', 'git-merge', 'git-pull-request', 'git-commit', 'box', 'boxes',
  'cpu', 'hard-drive', 'cloud', 'cloud-upload', 'cloud-download', 'download', 'upload',
  'settings', 'sliders-horizontal', 'database-backup', 'shield', 'lock', 'key-round',
  'refresh-ccw', 'repeat', 'timer', 'clock', 'calendar', 'list-checks', 'list-todo',
  'chart-no-axes-column', 'chart-line', 'eye', 'search', 'filter', 'link', 'globe-2',
  'network', 'wifi', 'send', 'mail', 'message-square', 'image', 'camera',
  'video', 'music', 'headphones', 'pencil', 'pen-line', 'trash-2', 'copy',
  'scissors', 'save', 'printer', 'power', 'plug', 'lightbulb', 'sun', 'moon',
])

// Match the platform names used by Script metadata and Quick Action scope.
export function normalizeToolboxPlatform(value) {
  const text = String(value || '').trim().toLowerCase()
  if (!text) return ''
  if (['*', 'all', 'any', 'common'].includes(text)) return '*'
  if (text.includes('ios') || text.includes('iphone') || text.includes('ipad')) return 'ios'
  if (text.includes('darwin') || text.includes('mac') || text.includes('osx')) return 'mac'
  if (text.includes('windows') || text.startsWith('win') || text === 'nt') return 'win'
  if (text.includes('linux') || /(ubuntu|debian|centos|fedora|redhat|rhel|alpine|arch)/.test(text)) return 'linux'
  return text
}

export function isScriptSupportedOnPlatform(item, platform) {
  const raw = item?.metadata?.platforms
  const platforms = (Array.isArray(raw) ? raw : (typeof raw === 'string' && raw.trim() ? [raw] : []))
    .map(normalizeToolboxPlatform).filter(Boolean)
  return !platforms.length || platforms.includes('*') || (!!platform && platforms.includes(platform))
}

export function isQuickActionSupportedOnPlatform(platformKey, platform) {
  const normalized = normalizeToolboxPlatform(platformKey)
  return normalized === '*' || (!!platform && normalized === platform)
}

export function toolboxShortcutKey(item) {
  return item?.kind === 'script'
    ? `script\u0000${item.script_name}`
    : `quick_action\u0000${item?.platform}\u0000${item?.alias}`
}

export function normalizeToolboxShortcuts(value) {
  if (!Array.isArray(value)) return []
  const seen = new Set()
  const result = []
  for (const raw of value) {
    if (!raw || typeof raw !== 'object') continue
    const kind = String(raw.kind || '').trim()
    const icon = String(raw.icon || '').trim()
    const label = String(raw.label || '').trim().slice(0, 64)
    if (!TOOLBOX_SHORTCUT_ICONS.includes(icon)) continue
    let item
    if (kind === 'script') {
      const script_name = String(raw.script_name || '').trim()
      if (!script_name) continue
      item = { kind, script_name, icon }
    } else if (kind === 'quick_action') {
      const platform = String(raw.platform || '').trim().toLowerCase()
      const alias = String(raw.alias || '').trim()
      if (!platform || !alias) continue
      item = { kind, platform, alias, icon }
    } else continue
    if (label) item.label = label
    const key = toolboxShortcutKey(item)
    if (seen.has(key)) continue
    seen.add(key)
    result.push(item)
  }
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
    toolbox_shortcuts: normalizeToolboxShortcuts(preferences?.toolbox_shortcuts),
  }

  TOOLBAR_ACTION_CATALOG.forEach((action) => {
    if (used.has(action.id)) return
    const section = DEFAULT_TOOLBAR_PREFERENCES.toolbar.includes(action.id) ? 'toolbar' : 'more'
    normalized[section].push(action.id)
    used.add(action.id)
  })

  return normalized
}
