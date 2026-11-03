import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'

const component = readFileSync(new URL('../src/components/TerminalOutput.vue', import.meta.url), 'utf8')

test('mobile warning revision actions wrap after message without squeezing the warning text', () => {
  assert.match(component, /'terminal-warning-with-actions': entry\.line\.kind === 'warning'/)
  assert.match(component, /getSuggestedCommandAction\(entry\.line\) \|\| getClientRevisionDetails\(entry\.line\)/)
  const mobile = component.match(/@media \(max-width: 768px\) \{([\s\S]*?)\n\}/)?.[1]
  assert.ok(mobile)
  assert.match(mobile, /\.terminal-warning-with-actions\s*\{\s*display:\s*block;/)
  assert.match(mobile, /\.terminal-warning-with-actions \.terminal-action-link-spaced\s*\{[^}]*white-space:\s*nowrap;/)
  assert.match(component, /class="terminal-line terminal-line-command"/)
})
