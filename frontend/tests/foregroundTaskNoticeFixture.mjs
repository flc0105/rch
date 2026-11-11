import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { foregroundTaskNoticeKey, normalizeForegroundTask, shouldShowTaskNotice } from '../src/utils/foregroundTask.js'

export const source = readFileSync(new URL('../src/App.vue', import.meta.url), 'utf8')

function compileMethod(name, injected = {}) {
  const expression = new RegExp(`    (async )?${name}\\(([^)]*)\\) \\{([\\s\\S]*?)\\n    \\},`)
  const match = source.match(expression)
  assert.ok(match, `App.${name} must exist`)
  return new Function(...Object.keys(injected),
    `return ${match[1] || ''}function ${name}(${match[2]}) {${match[3]}\n}`)(...Object.values(injected))
}

const injected = { foregroundTaskNoticeKey, normalizeForegroundTask, shouldShowTaskNotice }
const syncForegroundTaskNotice = compileMethod('syncForegroundTaskNotice', injected)
const applyForegroundTaskUpdate = compileMethod('applyForegroundTaskUpdate', injected)
const closePendingTaskNoticeEntry = compileMethod('closePendingTaskNoticeEntry')
const startTerminalSubmission = compileMethod('startTerminalSubmission')
const selectionWatcher = compileMethod('selectedId')

export const task = { state: 'Running', task_id: 'task-1', command_id: '123', started_at: '2026-10-28T10:00:00Z', command: 'sleep 10', source: 'web', tab_id: 'reused-tab' }

export function fixture(getConnectionTask = async () => ({ state: 'Idle' })) {
  const page = {
    selectedId: 'A', tabId: 'reused-tab', foregroundNoticeEntries: {}, foregroundQuerySequence: 0,
    activeTaskIds: {}, foregroundTasks: {}, outputs: {}, terminalNotices: {}, taskDialogVisible: false,
    get isCurrentConnectionOffline() { return false },
    ensureOutputBucket(id) { this.outputs[id] ??= [] },
    appendOutput(id, text, kind, meta) {
      this.outputs[id].push({ text, kind, meta })
    },
    buildTerminalOutputLine(text, kind, meta) { return { text, kind, meta } },
    getTerminalNotice(id, type) { return this.terminalNotices[id]?.[type] || null },
    setTerminalNotice(id, type, line) {
      this.terminalNotices[id] ??= {}
      if (line) this.terminalNotices[id][type] = line
      else delete this.terminalNotices[id][type]
    },
    scrollToBottom(force) { this.scrollCalls.push(force) }, scrollCalls: [],
    recoverFinishedTask(id, taskId) { delete this.activeTaskIds[id] },
    closePendingTaskNoticeEntry, syncForegroundTaskNotice, applyForegroundTaskUpdate,
    startTerminalSubmission,
  }
  page.refreshForegroundTask = compileMethod('refreshForegroundTask', { getConnectionTask, normalizeForegroundTask })
  page.enter = function (clientId = this.selectedId) {
    this.selectedId = clientId
    return selectionWatcher.call(this)
  }
  return page
}

export function notices(page, id = 'A') {
  return Object.values(page.terminalNotices[id] || {}).filter(line => line.meta?.foregroundTaskNotice)
}
