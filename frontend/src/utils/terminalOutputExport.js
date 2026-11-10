export function buildTerminalOutputText(lines) {
  const result = []
  for (const line of Array.isArray(lines) ? lines : []) {
    const value = String(line?.text ?? '')
    if (line?.__terminalContinuation && result.length) result[result.length - 1] += value
    else result.push(value)
  }
  return result.join('\n')
}

export function buildTerminalOutputJson(entries) {
  return (Array.isArray(entries) ? entries : [])
    .filter(entry => entry?.hasCommand === true)
    .map(entry => {
      const item = {
        command: String(entry.command ?? ''),
        result: String(entry.result ?? ''),
      }
      if (entry.time !== undefined && entry.time !== null && String(entry.time).trim() !== '') item.time = entry.time
      if (entry.duration_ms !== undefined && entry.duration_ms !== null && String(entry.duration_ms).trim() !== '') {
        item.duration_ms = entry.duration_ms
      }
      return item
    })
}
