import { formatConnectionDateTime, formatConnectionLastSeen, formatConnectionRtt, formatConnectionStatus } from '../utils/connectionInfoFormatting.js'
import { formatLaunchMode } from '../utils/formatters.js'

export const CONNECTION_CONTEXT_FIELD_CATALOG = Object.freeze([
  { id: 'status', label: 'Status', icon: 'Activity', description: 'Current connection state' },
  { id: 'task', label: 'Task', icon: 'Activity', description: 'Current foreground task state' },
  { id: 'hostname', label: 'Hostname', icon: 'Monitor', description: 'Device hostname' },
  { id: 'address', label: 'Address', icon: 'Network', description: 'Client network address' },
  { id: 'client_id', label: 'Client ID', icon: 'Fingerprint', description: 'Current client instance' },
  { id: 'os_type', label: 'OS Type', icon: 'Monitor', description: 'Operating system type' },
  { id: 'platform', label: 'Platform', icon: 'Globe2', description: 'Platform description' },
  { id: 'os_name', label: 'OS Name', icon: 'Globe2', description: 'Operating system name' },
  { id: 'os_version', label: 'OS Version', icon: 'GitBranch', description: 'Operating system version' },
  { id: 'os_alias', label: 'OS Alias', icon: 'Code2', description: 'Normalized operating system alias' },
  { id: 'arch', label: 'Arch', icon: 'Cpu', description: 'CPU architecture' },
  { id: 'manufacturer', label: 'Manufacturer', icon: 'Box', description: 'Device manufacturer' },
  { id: 'model', label: 'Model', icon: 'Boxes', description: 'Device model' },
  { id: 'integrity', label: 'Integrity', icon: 'ShieldCheck', description: 'Client integrity level' },
  { id: 'build_version', label: 'Build Version', icon: 'Archive', description: 'Client build version' },
  { id: 'client_revision', label: 'Client Revision', icon: 'GitCommit', description: 'Client source revision' },
  { id: 'machine_id', label: 'Machine ID', icon: 'KeyRound', description: 'Stable machine identity' },
  { id: 'fingerprint_basis', label: 'Fingerprint Basis', icon: 'DatabaseBackup', description: 'Machine fingerprint basis' },
  { id: 'last_seen', label: 'Last Seen', icon: 'Clock', description: 'Most recent connection heartbeat' },
  { id: 'connected_at', label: 'Connected At', icon: 'CalendarClock', description: 'Session start time' },
  { id: 'disconnected_at', label: 'Disconnected At', icon: 'CalendarClock', description: 'Session end time' },
  { id: 'rtt', label: 'RTT', icon: 'Activity', description: 'Heartbeat round-trip time' },
  { id: 'working_directory', label: 'Working Directory', icon: 'FolderOpen', description: 'Client working directory' },
  { id: 'pid', label: 'PID', icon: 'Hash', description: 'Client process ID' },
  { id: 'process_name', label: 'Process Name', icon: 'Terminal', description: 'Client process name' },
  { id: 'launch_command', label: 'Launch Command', icon: 'Terminal', description: 'Client launch command' },
  { id: 'launch_mode', label: 'Launch Mode', icon: 'Rocket', description: 'Client launch mode and source' },
  { id: 'client_log', label: 'Client Log', icon: 'FileText', description: 'Client log path' },
  { id: 'username', label: 'Username', icon: 'UserRound', description: 'Client user name' },
  { id: 'python_version', label: 'Python Version', icon: 'Code2', description: 'Client Python version' },
])

const FIELD_IDS = new Set(CONNECTION_CONTEXT_FIELD_CATALOG.map(field => field.id))

export const DEFAULT_CONNECTION_CONTEXT_PREFERENCES = Object.freeze({ field_ids: [] })

export function normalizeConnectionContextPreferences(value) {
  const source = value && typeof value === 'object' && !Array.isArray(value) ? value : {}
  const rawFieldIds = Array.isArray(source.field_ids) ? source.field_ids : []
  const fieldIds = []
  const seen = new Set()
  for (const rawId of rawFieldIds) {
    const id = String(rawId || '').trim()
    if (!FIELD_IDS.has(id) || seen.has(id)) continue
    seen.add(id)
    fieldIds.push(id)
  }
  return { field_ids: fieldIds }
}

export function cloneConnectionContextPreferences(value = DEFAULT_CONNECTION_CONTEXT_PREFERENCES) {
  return normalizeConnectionContextPreferences(value)
}

function normalizeDisplayValue(value) {
  if (value === null || value === undefined || value === '') return '-'
  if (typeof value === 'boolean') return value ? 'true' : 'false'
  if (Array.isArray(value)) return value.length ? value.join(', ') : '-'
  if (typeof value === 'object') {
    try {
      return JSON.stringify(value)
    } catch (_error) {
      return String(value)
    }
  }
  return String(value)
}

export function resolveConnectionContextValue(fieldId, connection, nowTick = Date.now()) {
  const conn = connection && typeof connection === 'object' ? connection : {}
  const rawValues = {
    hostname: conn.hostname,
    address: conn.addr,
    client_id: conn.client_id,
    os_type: conn.os_type,
    platform: conn.os_full,
    os_name: conn.os_name,
    os_version: conn.os_ver,
    os_alias: conn.os_alias,
    arch: conn.arch,
    manufacturer: conn.manufacturer,
    model: conn.model,
    integrity: conn.integrity,
    build_version: conn.build_version,
    client_revision: conn.client_revision,
    machine_id: conn.machine_id,
    fingerprint_basis: conn.machine_fingerprint_basis,
    connected_at: formatConnectionDateTime(conn.connected_at),
    disconnected_at: formatConnectionDateTime(conn.disconnected_at),
    working_directory: conn.cwd,
    pid: conn.process_id,
    process_name: conn.process_name,
    launch_command: conn.launch_command,
    launch_mode: formatLaunchMode(conn.launch_mode, conn.launch_source),
    client_log: conn.client_log_path,
    username: conn.username,
    python_version: conn.python_ver,
  }

  if (fieldId === 'status') return formatConnectionStatus(conn, nowTick)
  if (fieldId === 'task') return conn.foreground_task?.state || 'Idle'
  if (fieldId === 'last_seen') return formatConnectionLastSeen(conn, nowTick)
  if (fieldId === 'rtt') return formatConnectionRtt(conn)
  return normalizeDisplayValue(rawValues[fieldId])
}
