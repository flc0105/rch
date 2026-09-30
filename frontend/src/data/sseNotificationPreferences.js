export const DEFAULT_SSE_NOTIFICATION_PREFERENCES = {
  version: 1,
  enabled: true,
  events: {
    connection_online: true,
    connection_offline: true,
    device_event: true,
    artifact_created: true,
    file_transfer_started: false,
    file_transfer_stopped: false,
    file_transfer_error: true,
    pty_opened: true,
    pty_closed: true,
    pty_error: true,
    screen_view_started: true,
    screen_view_closed: true,
    screen_view_error: true,
    background_job_running: true,
    background_job_stopped: true,
    background_job_error: true,
    external_tool_daemon_started: true,
    external_tool_daemon_stopped: true,
    external_tool_daemon_error: true,
    external_tool_install_completed: true,
    external_tool_install_failed: true,
    external_tool_uninstall_completed: false,
    external_tool_uninstall_failed: false,
    agent_build_completed: true,
    agent_build_error: true,
    server_cleanup_completed: true,
  },
}

export const SSE_NOTIFICATION_GROUPS = [
  {
    title: 'Devices',
    items: [
      { key: 'connection_online', label: 'Device online' },
      { key: 'connection_offline', label: 'Device offline' },
      { key: 'device_event', label: 'Device events' },
    ],
  },
  {
    title: 'Files',
    items: [
      { key: 'artifact_created', label: 'File ready' },
      { key: 'file_transfer_started', label: 'Transfer started' },
      { key: 'file_transfer_stopped', label: 'Transfer stopped' },
      { key: 'file_transfer_error', label: 'Transfer error' },
    ],
  },
  {
    title: 'PTY',
    items: [
      { key: 'pty_opened', label: 'PTY started' },
      { key: 'pty_closed', label: 'PTY stopped' },
      { key: 'pty_error', label: 'PTY error' },
    ],
  },
  {
    title: 'Screen View',
    items: [
      { key: 'screen_view_started', label: 'Screen View started' },
      { key: 'screen_view_closed', label: 'Screen View stopped' },
      { key: 'screen_view_error', label: 'Screen View error' },
    ],
  },
  {
    title: 'Background Jobs',
    items: [
      { key: 'background_job_running', label: 'Job started' },
      { key: 'background_job_stopped', label: 'Job finished' },
      { key: 'background_job_error', label: 'Job error' },
    ],
  },
  {
    title: 'External Tools',
    items: [
      { key: 'external_tool_daemon_started', label: 'Daemon started' },
      { key: 'external_tool_daemon_stopped', label: 'Daemon stopped' },
      { key: 'external_tool_daemon_error', label: 'Daemon error' },
      { key: 'external_tool_install_completed', label: 'Install completed' },
      { key: 'external_tool_install_failed', label: 'Install failed' },
      { key: 'external_tool_uninstall_completed', label: 'Uninstall completed' },
      { key: 'external_tool_uninstall_failed', label: 'Uninstall failed' },
    ],
  },
  {
    title: 'Agent Build',
    items: [
      { key: 'agent_build_completed', label: 'Build completed' },
      { key: 'agent_build_error', label: 'Build error' },
    ],
  },
  {
    title: 'Maintenance',
    items: [
      { key: 'server_cleanup_completed', label: 'Server cleanup completed' },
    ],
  },
]

export function cloneSseNotificationPreferences(preferences = DEFAULT_SSE_NOTIFICATION_PREFERENCES) {
  return {
    version: DEFAULT_SSE_NOTIFICATION_PREFERENCES.version,
    enabled: preferences?.enabled !== false,
    events: {
      ...DEFAULT_SSE_NOTIFICATION_PREFERENCES.events,
      ...(preferences?.events || {}),
    },
  }
}

export function normalizeSseNotificationPreferences(preferences = {}) {
  const source = preferences && typeof preferences === 'object' ? preferences : {}
  const sourceEvents = source.events && typeof source.events === 'object' ? source.events : {}
  const normalized = cloneSseNotificationPreferences(DEFAULT_SSE_NOTIFICATION_PREFERENCES)

  if (typeof source.enabled === 'boolean') {
    normalized.enabled = source.enabled
  }

  Object.keys(normalized.events).forEach((eventKey) => {
    if (typeof sourceEvents[eventKey] === 'boolean') {
      normalized.events[eventKey] = sourceEvents[eventKey]
    }
  })

  return normalized
}
