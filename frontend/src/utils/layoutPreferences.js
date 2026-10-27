export const LAYOUT_PREFERENCES_STORAGE_KEY = 'rch:layout-preferences'

const DEFAULT_LAYOUT_PREFERENCES = Object.freeze({
  deviceSidebarCollapsed: false,
  connectionInfoCollapsed: false,
})

function resolveStorage(storage) {
  if (storage) return storage
  try {
    return typeof window !== 'undefined' ? window.localStorage : null
  } catch (error) {
    return null
  }
}

export function loadLayoutPreferences(storage) {
  const resolvedStorage = resolveStorage(storage)
  if (!resolvedStorage) return { ...DEFAULT_LAYOUT_PREFERENCES }

  try {
    const raw = resolvedStorage.getItem(LAYOUT_PREFERENCES_STORAGE_KEY)
    if (!raw) return { ...DEFAULT_LAYOUT_PREFERENCES }

    const saved = JSON.parse(raw)
    return {
      deviceSidebarCollapsed: saved?.deviceSidebarCollapsed === true,
      connectionInfoCollapsed: saved?.connectionInfoCollapsed === true,
    }
  } catch (error) {
    return { ...DEFAULT_LAYOUT_PREFERENCES }
  }
}

export function saveLayoutPreferences(preferences, storage) {
  const resolvedStorage = resolveStorage(storage)
  if (!resolvedStorage) return false

  const saved = {
    deviceSidebarCollapsed: preferences?.deviceSidebarCollapsed === true,
    connectionInfoCollapsed: preferences?.connectionInfoCollapsed === true,
  }

  try {
    resolvedStorage.setItem(LAYOUT_PREFERENCES_STORAGE_KEY, JSON.stringify(saved))
    return true
  } catch (error) {
    return false
  }
}
