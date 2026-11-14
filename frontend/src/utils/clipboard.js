/** Copy via a temporary textarea when the Clipboard API is unavailable. */
export function copyTextFallback(text) {
  const textarea = document.createElement('textarea')
  textarea.value = String(text || '')
  textarea.setAttribute('readonly', '')
  textarea.style.position = 'fixed'
  textarea.style.left = '0'
  textarea.style.top = '0'
  textarea.style.opacity = '0'
  textarea.style.fontSize = '16px'
  textarea.style.width = '1px'
  textarea.style.height = '1px'
  document.body.appendChild(textarea)
  try {
    textarea.focus()
    textarea.select()
    textarea.setSelectionRange(0, textarea.value.length)
    if (!document.execCommand('copy')) throw new Error('Fallback copy failed')
  } finally {
    document.body.removeChild(textarea)
  }
}
