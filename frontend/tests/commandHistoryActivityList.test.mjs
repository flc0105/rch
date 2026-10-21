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
  CircleDashed:{}, Ban:{}, Clock3:{}, ChevronRight:{}, AlertTriangle:{}, FolderOpen:{}, ArrowDownToLine:{}, ArrowUpToLine:{}, diffDateTimeMs: () => 0}
vm.runInNewContext(
  script.replace(/^import\s+.*?\s+from\s+.*?\n/gm,'').replace('export default {','globalThis.component = {'),
  context,
)
const component = context.component
const item = {activity_id:'a1', kind:'alias', status:'success', invocation:{input:'now',target:'now'},
  resolved:{command_type:'command',command:'pyexec_collect ...'},result:{output_records:[],truncated:false}}

test('Activity list has identity, state icons, Details navigation and no Use/Delete', () => {
  assert.match(activity, /:key="item\.activity_id"/)
  assert.match(activity, /getActivityKindIcon\(item\.kind, item\.action\)/)
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

test('Remote Files list uses semantic actions and includes the new filter', () => {
  assert.match(activity, /label="Remote Files" value="remote_files"/)
  const entry = {kind:'remote_files', action:'rename_files', status:'success',
    invocation:{arguments:{old_path:'/tmp/a.txt',new_name:'b.txt',count:1}},
    result:{output_records:[{text:'Renamed to: /tmp/b.txt'}]}}
  assert.equal(component.methods.getActivityKindIcon('remote_files'), context.FolderOpen)
  assert.equal(component.methods.buildActivityKindLabel('remote_files'), 'Remote Files')
  assert.equal(component.methods.buildActivityLabel(entry), 'Rename')
  assert.equal(component.methods.buildCommandExecutionSummary.call({},entry), 'Renamed to: /tmp/b.txt')
  assert.equal(component.methods.buildActivityLabel({kind:'remote_files',action:'delete_files',invocation:{arguments:{paths:['a','b'],count:2}}}), 'Delete 2 items')
  assert.equal(component.methods.buildActivityLabel({kind:'remote_files',action:'create_directory',invocation:{arguments:{path:'/tmp/chat_exports'}}}), 'Create directory')
  const detailScript = detail.match(/<script>([\s\S]*?)<\/script>/)?.[1]
  const detailContext = {}
  vm.runInNewContext(detailScript.replace('export default {', 'globalThis.component = {'), detailContext)
  const contents = detailContext.component.methods.getActivityInvocation(entry)
  assert.match(contents, /"old_path": "\/tmp\/a\.txt"/)
  assert.doesNotMatch(contents, /__json__:/)
})


test('Activity summary color reflects operation status, without changing list layout', () => {
  assert.match(activity, /class="activity-summary-preview" :class="\{ 'activity-error-preview': isActivityProblem\(item.status\) \}"/)
  assert.match(source, /\.activity-summary-preview\s*\{[^}]*overflow:\s*hidden;[^}]*text-overflow:\s*ellipsis;/s)
  assert.match(source, /\.activity-error-preview\s*\{\s*color:\s*#dc2626;/s)
  assert.doesNotMatch(source, /\.activity-summary-preview\s*\{[^}]*color:/s)
  assert.equal(component.methods.isActivityProblem('success'), false)
  assert.equal(component.methods.isActivityProblem('error'), true)
  assert.equal(component.methods.isActivityProblem('timed_out'), true)
})


test('Transfer kind preserves filtering and uses compact semantic names', () => {
  assert.match(activity, /label="Transfer" value="transfer"/)
  const transfer = {kind:'transfer', action:'download_files', status:'success', invocation:{arguments:{filename:'archive.zip', count:3}}}
  assert.equal(component.methods.buildActivityLabel(transfer), 'Download 3 items')
  assert.equal(component.methods.buildActivityKindLabel('transfer'), 'Transfer')
  assert.equal(component.methods.getActivityKindIcon('transfer', 'download_files'), context.ArrowDownToLine)
  assert.equal(component.methods.getActivityKindIcon('transfer', 'upload_files'), context.ArrowUpToLine)
  assert.match(activity, /getActivityKindIcon\(item\.kind, item\.action\)/)
  assert.match(activity, /\['remote_files', 'transfer'\]/)
})
