// Extract text from the active xterm buffer, including its retained scrollback.
// A wrapped display line belongs to the previous logical line.
export function getPtyBufferText(term) {
  const buffer = term?.buffer?.active
  if (!buffer) return ''
  const lines = []
  for (let i = 0; i < buffer.length; i++) {
    const line = buffer.getLine(i)
    if (!line) continue
    const text = line.translateToString(true)
    if (line.isWrapped && lines.length) lines[lines.length - 1] += text
    else lines.push(text)
  }
  while (lines.length && !lines[lines.length - 1]) lines.pop()
  return lines.join('\n')
}
