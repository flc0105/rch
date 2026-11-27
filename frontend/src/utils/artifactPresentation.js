import { ARTIFACT_TYPE } from '../data/artifactConstants.js'
import { formatBytes } from './formatters.js'

export function formatArtifactName(row) {
  return row?.original_name || row?.stored_name || 'artifact'
}

export function isSharedFileItem(item) {
  return item?.artifact_type === ARTIFACT_TYPE.SHARED
}

export function useArtifactMoreMenu(item) {
  return item?.artifact_type === ARTIFACT_TYPE.SAVED || item?.artifact_type === ARTIFACT_TYPE.SHARED
}

export function formatArtifactInfoSections(row) {
  if (!row || typeof row !== 'object') return []
  const sections = [
    { key: 'basic', title: 'Basic', fields: [
      ['original_name', 'Original Name'],
      ['saved_path', 'Saved Path'], ['artifact_id', 'Artifact ID'],
      ['artifact_type', 'Artifact Type'], ['size', 'Size'],
      ['saved_at', 'Saved At'], ['category', 'Category'], ['folder_id', 'Folder ID'],
    ] },
    { key: 'source', title: 'Source', fields: [
      ['machine_id', 'Machine ID'], ['client_id', 'Client ID'],
      ['source_command_id', 'Source Command ID'],
      ['linked_jobs', 'Jobs'],
    ] },
  ]
  const result = sections.map(section => ({ ...section, items: section.fields
    .filter(([key]) => Object.prototype.hasOwnProperty.call(row, key))
    .map(([key, label]) => ({ key, label, value: formatArtifactInfoValue(key, row[key]) }))
    .filter(item => item.value !== '-')
  })).filter(section => section.items.length)
  const extras = row.extra && typeof row.extra === 'object' && !Array.isArray(row.extra) ? row.extra : {}
  const extraItems = Object.keys(extras).sort((a, b) => a.localeCompare(b))
    .map(key => ({ key, label: key, value: formatArtifactInfoValue(key, extras[key]) }))
    .filter(item => item.value !== '-')
  if (extraItems.length) result.push({ key: 'extras', title: 'Extras', items: extraItems })
  return result
}

export function formatArtifactInfoValue(key, value) {
  if (value === null || value === undefined || value === '') return '-'

  if (key === 'size') {
    const numericValue = Number(value || 0)
    return `${formatBytes(numericValue)} (${numericValue} bytes)`
  }

  if (typeof value === 'boolean') {
    return value ? 'Yes' : 'No'
  }

  if (Array.isArray(value)) {
    if (!value.length) return '-'
    return value.map(item => formatArtifactInfoNestedValue(item)).join(', ')
  }

  if (typeof value === 'object') {
    const keys = Object.keys(value)
    if (!keys.length) return '-'

    try {
      return JSON.stringify(value, null, 2)
    } catch (_e) {
      return String(value)
    }
  }

  return String(value)
}

export function formatArtifactInfoNestedValue(value) {
  if (value === null || value === undefined || value === '') return '-'

  if (typeof value === 'object') {
    try {
      return JSON.stringify(value)
    } catch (_e) {
      return String(value)
    }
  }

  return String(value)
}
