/** Normalize the relative Python filename used by Server Job editors and uploads. */
export function normalizeServerJobFilename(scriptName, fallbackName = 'new_job.py') {
  let normalized = String(scriptName || '').trim().replace(/\\/g, '/').replace(/^\/+/, '')
  if (!normalized) normalized = fallbackName
  if (!/\.py$/i.test(normalized)) normalized = `${normalized}.py`
  return normalized
}
