import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'
import vm from 'node:vm'

const here = dirname(fileURLToPath(import.meta.url))
const source = readFileSync(resolve(here, '../src/components/CommandHistoryDialog.vue'), 'utf8')
const detail = readFileSync(resolve(here, '../src/components/CommandExecutionDetailDialog.vue'), 'utf8')
const quick = source.match(/<el-tab-pane label="Quick History"[\s\S]*?<\/el-tab-pane>/)?.[0]
const activity = source.match(/<el-tab-pane label="Activity Center"[\s\S]*?<\/el-tab-pane>/)?.[0]
assert.ok(quick && activity, 'Quick History and Activity Center must remain')

const script = source.match(/<script>([\s\S]*?)<\/script>/)?.[1]
assert.ok(script)
const context = {console, EditPen:{}, CommandExecutionDetailDialog:{}, TextCursorInput:{}, Star:{}, StarFilled:{},
  ArrowUp:{}, ArrowDown:{}, Terminal:{}, Zap:{}, FileCode2:{}, CheckCircle2:{}, XCircle:{},
  CircleDashed:{}, Ban:{}, Clock3:{}, ChevronRight:{}, AlertTriangle:{}, diffDateTimeMs: () => 0}
vm.runInNewContext(
  script.replace(/^import\s+.*?\s+from\s+.*?\n/gm,'').replace('export default {','globalThis.component = {'),
  context,
)
const component = context.component
const item = {activity_id:'a1', kind:'alias', status:'success', invocation:{input:'now',target:'now'},
  resolved:{command_type:'command',command:'pyexec_collect ...'},result:{output_records:[],truncated:false}}

test('Activity list has identity, state icons, Details navigation and no Use/Delete', () => {
  assert.match(activity, /:key="item\.activity_id"/)
  assert.match(activity, /getActivityKindIcon\(item\.kind\)/)
  assert.match(activity, /getActivityStatusIcon\(item\.status\)/)
  assert.match(activity, /buildActivityLabel\(item\)/)
  assert.match(activity, /ChevronRight/)
  assert.match(activity, /@click="openCommandExecutionDetail\(item\)"/)
  assert.doesNotMatch(activity, /applyHistoryCommand\(item\)|deleteCommandExecutionItem\(item\)/)
  assert.match(detail, /@click="\$emit\('delete-activity', entry\)"/)
  assert.match(source, /@delete-activity="deleteCommandExecutionItem"/)
})

test('Only necessary Quick columns are hidden, Use/Pin/ordering remain', () => {
  assert.doesNotMatch(quick, /prop="last_used_at"|prop="status"/)
  assert.match(quick, /@row-dblclick="applyHistoryCommand"/)
  assert.match(quick, /toggleCommandHistoryPinned/)
  assert.match(quick, /moveCommandHistoryPinned/)
  assert.match(quick, /Use/)
})

test('Kind and Errors filters are sent to server for both first and next pages', () => {
  assert.match(activity, /v-model="activityKindFilter"/)
  assert.match(activity, /v-model="activityErrorsOnly"/)
  assert.equal((source.match(/params\.set\('kind', this\.activityKindFilter\)/g) || []).length,2)
  assert.equal((source.match(/params\.set\('errors', 'true'\)/g) || []).length,2)
})

test('Activity labels use semantic invocation, Details use new Activity ID', () => {
  assert.equal(component.methods.buildActivityLabel(item), 'now')
  assert.equal(component.methods.getActivityKindIcon('script'), context.FileCode2)
  const state = {...component.data(), commandExecutionItems:[item]}
  component.methods.openCommandExecutionDetail.call(state,item)
  assert.equal(state.selectedCommandExecutionEntryId,'a1')
  assert.equal(state.commandExecutionDetailDialogVisible,true)
  assert.match(detail,/entry\.result\?\.output_records/)
  assert.match(detail,/entry\.resolved\?\.command/)
})


test('Activity scrolling keeps filters fixed and list independently scrollable', () => {
  assert.match(source, /\.command-execution-list-shell\s*\{[^}]*display:\s*flex;[^}]*flex-direction:\s*column;/s)
  assert.match(source, /\.command-execution-list\s*\{[^}]*flex:\s*1 1 auto;[^}]*overflow-y:\s*auto;/s)
})

test('Long Activity titles and detail values truncate, full text opens on click', () => {
  assert.match(source, /\.activity-operation\s*\{[^}]*max-width:[^}]*text-overflow:\s*ellipsis;/s)
  assert.match(detail, /class="background-job-stat-value activity-single-line-value"/)
  assert.match(detail, /@click="openFullValue\('Invocation'/)
  assert.match(detail, /@click="openFullValue\('Resolved'/)
  assert.match(detail, /class="activity-full-value-text"/)
  const detailScript = detail.match(/<script>([\s\S]*?)<\/script>/)?.[1]
  const detailContext = {}
  vm.runInNewContext(detailScript.replace('export default {', 'globalThis.component = {'), detailContext)
  const state = {...detailContext.component.data()}
  detailContext.component.methods.openFullValue.call(state, 'Invocation', 'x'.repeat(500))
  assert.equal(state.fullValueText.length, 500)
  assert.equal(state.fullValueTitle, 'Invocation')
  assert.equal(state.fullValueVisible, true)
  assert.doesNotMatch(detail, /class="background-job-stat-label">Kind<\/div>/)
  assert.match(detail, /class="background-job-stat-label">Action<\/div>/)
  assert.match(detail, /entry.kind \|\| '-' }} · {{ entry.action/)
  assert.match(detail, /return 'Activity Detail'/)
  assert.match(source, /title="History"/)

})

test('Summary distinguishes success and failure for long output', () => {
  const build = text => component.methods.buildCommandExecutionSummary.call({
    isActivityProblem: () => false,
  }, {status:'success', files:[], result:{output_records:[{text}]}})
  assert.equal(build('test'), 'test')
  assert.equal(build('a'.repeat(128)), 'a'.repeat(128))
  assert.equal(build('a'.repeat(129)), 'Completed')
  assert.equal(build('line1\nline2'), 'Completed')
  const failed = text => component.methods.buildCommandExecutionSummary.call({isActivityProblem: () => true}, {status:'error', files:[], result:{output_records:[{text}]}})
  assert.equal(failed('Traceback\nNameError'), 'Failed')
  assert.equal(failed('a'.repeat(129)), 'Failed')
  assert.equal(component.methods.buildCommandExecutionSummary.call({isActivityProblem: () => false}, {
    status:'success', result:{output_records:[{text:'first'}, {text:'second'}]}, files:[],
  }), 'Completed')
})


test('Quick command cells show latest status via Lucide icon on desktop and mobile', () => {
  assert.match(quick, /getActivityStatusIcon\(row\.status\)/)
  assert.equal((quick.match(/getActivityStatusIcon\(row\.status\)/g) || []).length, 2)
  assert.match(quick, /activity-status-\$\{row\.status\}/)
  assert.match(quick, /class="quick-command-label mono"/)
  assert.match(source, /\.quick-command-label\s*\{[^}]*display:\s*flex;/s)
  assert.doesNotMatch(quick, /<el-table-column[^>]+prop="status"/)
})
