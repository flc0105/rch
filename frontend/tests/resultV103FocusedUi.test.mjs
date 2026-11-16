import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
const read = name => fs.readFileSync(new URL('../src/components/' + name, import.meta.url), 'utf8')

test('Default full-viewport dialogs are phone-only, including Run and Activity dialogs', () => {
  const files = [
    'QuickActionsDialog.vue',
    'ScriptLibraryDialog.vue',
    'ConnectionInfoDialogs.vue',
    'CommandExecutionDetailDialog.vue',
    'BackgroundJobDetailDialog.vue',
    'BackgroundJobMessageDialog.vue',
    'ScriptRunDialog.vue',
    'TerminalJsonDialog.vue',
  ]

  for (const name of files) {
    const body = read(name)
    const dialogs = body.match(/<el-dialog\b[^>]*>/gs) || []
    const resultDialogs = dialogs.filter(tag => tag.includes('rch-result-detail-fullscreen'))
    assert.ok(resultDialogs.length, `${name} keeps its result/detail dialog marker`)
    for (const tag of resultDialogs) {
      assert.doesNotMatch(tag, /\bfullscreen(?:\s|>|=)/, `${name} must not force Element Plus fullscreen on desktop`)
    }
  }

  const css = fs.readFileSync(new URL('../src/styles/mobileDialogs.css', import.meta.url), 'utf8')
  const mobileRule = css.match(/\/\* Result\/detail dialogs fill phone viewports; desktop keeps each dialog's declared width\. \*\/\s*@media \(max-width: 768px\) \{[\s\S]*?\.script-run-dialog\.el-dialog > \.el-dialog__body \{ max-height: none !important; \}\s*\}/)
  assert.ok(mobileRule, 'shared result/detail fullscreen rule is scoped to phone widths')
  assert.doesNotMatch(css.replace(mobileRule[0], ''), /body \.el-dialog\.rch-result-detail-fullscreen/)

  const runDialog = read('ScriptRunDialog.vue')
  assert.match(runDialog, /width="680px"/)
  assert.match(runDialog, /@media \(max-width: 768px\)/)
  assert.doesNotMatch(runDialog, /max-height: 720px/)
  assert.match(read('CommandExecutionDetailDialog.vue'), /width="1000px"/)
  assert.match(read('CommandHistoryDialog.vue'), /@media \(max-width: 768px\) \{\s*\.command-history-overlay \.el-dialog \{/)

  const componentsUrl = new URL('../src/components/', import.meta.url)
  const componentFiles = fs.readdirSync(componentsUrl).filter(name => name.endsWith('.vue'))
  const fullViewportShortDesktopRules = []
  for (const name of componentFiles) {
    const source = fs.readFileSync(new URL('../src/components/' + name, import.meta.url), 'utf8')
    const activeCss = source.replace(/\/\*[\s\S]*?\*\//g, '')
    const query = /@media\s*\(max-width:\s*768px\)\s*,\s*\(max-height:\s*720px\)\s*\{/g
    let match
    while ((match = query.exec(activeCss))) {
      let index = activeCss.indexOf('{', match.index) + 1
      let depth = 1
      while (index < activeCss.length && depth > 0) {
        if (activeCss[index] === '{') depth += 1
        else if (activeCss[index] === '}') depth -= 1
        index += 1
      }
      const block = activeCss.slice(match.index, index)
      if (/width:\s*100vw|height:\s*100dvh|height:\s*100vh|inset:\s*0/.test(block)) {
        fullViewportShortDesktopRules.push(name)
      }
      query.lastIndex = index
    }
  }
  assert.deepEqual(fullViewportShortDesktopRules, [], 'short desktop height must not trigger default full-viewport dialogs')
})
test('Activity Summary prefers completed event text, not last streamed JSON bracket', () => {
  const source = read('CommandHistoryDialog.vue')
  const begin = source.indexOf('buildCommandExecutionSummary(item) {')
  const end = source.indexOf('formatCommandExecutionRecordText(', begin)
  assert.ok(begin >= 0 && end > begin)
  const method = source.slice(begin, end)
  assert.match(method, /find\(event => event\?\.event_type === 'completed'\)/)
  assert.match(method, /String\(completed\.message \|\| ''\)\.trim\(\)/)
  assert.match(method, /text\.length <= 256/)
})
