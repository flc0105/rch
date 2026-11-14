import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'
import vm from 'node:vm'

const here = dirname(fileURLToPath(import.meta.url))
const source = readFileSync(resolve(here, '../src/components/CommandHistoryDialog.vue'), 'utf8')
const detail = readFileSync(resolve(here, '../src/components/CommandExecutionDetailDialog.vue'), 'utf8')
const historyApi = readFileSync(resolve(here, '../src/api/commandHistoryApi.js'), 'utf8')
const quick = source.match(/<el-tab-pane label="Quick History"[\s\S]*?<\/el-tab-pane>/)?.[0]
const activity = source.match(/<el-tab-pane label="Activity Center"[\s\S]*?<\/el-tab-pane>/)?.[0]
assert.ok(quick && activity, 'Quick History and Activity Center must remain')

const script = source.match(/<script>([\s\S]*?)<\/script>/)?.[1]
assert.ok(script)
const context = {console, EditPen:{}, CommandExecutionDetailDialog:{}, TextCursorInput:{}, Star:{}, StarFilled:{},
  ArrowUp:{}, ArrowDown:{}, Terminal:{}, Zap:{}, FileCode2:{}, CheckCircle2:{}, XCircle:{},
  CircleDashed:{}, Ban:{}, Clock3:{}, ChevronRight:{}, AlertTriangle:{}, FolderOpen:{}, ArrowDownToLine:{}, ArrowUpToLine:{}, Wrench:{}, BriefcaseBusiness:{}, Monitor:{}, Clipboard:{}, Activity:{}, diffDateTimeMs: () => 0}
vm.runInNewContext(
  script.replace(/^import\s+[\s\S]*?\s+from\s+['"][^'"]+['"]\s*;?\s*$/gm, '').replace('export default {','globalThis.component = {'),
  context,
)
const component = context.component
const item = {activity_id:'a1', kind:'alias', status:'success', summary:'now', invocation:{command:'now'},
  resolved:{type:'command',id:1,text:'pyexec_collect ...'},result:{output_records:[]}}

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

test('Activity Output Records show structured JSON inline instead of replacing it with a button', () => {
  assert.match(detail, /\{\{ formatCommandExecutionRecordText\(record\.text \|\| ''\) \}\}/)
  assert.doesNotMatch(detail, /record\.envelope\?\.display === 'data' \? ''/)
  assert.doesNotMatch(detail, /View JSON|openFullValue\('Structured Output'|openFullValue\('Result Data'/)
})

test('Only necessary Quick columns are hidden, Use/Pin/ordering remain', () => {
  assert.doesNotMatch(quick, /prop="last_used_at"|prop="status"/)
  assert.match(quick, /@row-dblclick="applyHistoryCommand"/)
  assert.match(quick, /toggleCommandHistoryPinned/)
  assert.match(quick, /moveCommandHistoryPinned/)
  assert.match(quick, /Use/)
})

test('Kind and Errors filters are sent for both pages and scoped bulk clear', () => {
  assert.match(activity, /v-model="activityKindFilter"/)
  assert.match(activity, /v-model="activityErrorsOnly"/)
  assert.equal((source.match(/fetchCommandActivities\(machineId,/g) || []).length, 2)
  assert.match(historyApi, /if \(kind\) params\.set\('kind', kind\)/)
  assert.match(historyApi, /if \(errors\) params\.set\('errors', 'true'\)/)
  assert.match(source, /clearCommandActivities\(machineId, \{ kind, errors, query \}\)/)
})

test('Activity labels use semantic invocation, Details use new Activity ID', () => {
  assert.equal(component.methods.buildActivityLabel(item), 'now')
  assert.equal(component.methods.getActivityKindIcon('script'), context.FileCode2)
  const state = {...component.data(), commandExecutionItems:[item]}
  component.methods.openCommandExecutionDetail.call(state,item)
  assert.equal(state.selectedCommandExecutionEntryId,'a1')
  assert.equal(state.commandExecutionDetailDialogVisible,true)
  assert.match(detail,/entry\.result\?\.output_records/)
  assert.match(detail,/getActivityResolved\(entry\)/)
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
  assert.equal(build('a'.repeat(256)), 'a'.repeat(256))
  assert.equal(build('a'.repeat(257)), 'Completed')
  assert.equal(build('line1\nline2'), 'Completed')
  const failed = text => component.methods.buildCommandExecutionSummary.call({isActivityProblem: () => true}, {status:'error', files:[], result:{output_records:[{text}]}})
  assert.equal(failed('Traceback\nNameError'), 'Failed')
  assert.equal(failed('a'.repeat(257)), 'Failed')
  assert.equal(component.methods.buildCommandExecutionSummary.call({isActivityProblem: () => false}, {
    status:'success', result:{output_records:[{text:'first'}, {text:'second'}]}, files:[],
  }), 'Completed')
})


test('Activity summary uses only the completed event output, with a 256-char limit', () => {
  const build = entry => component.methods.buildCommandExecutionSummary.call({isActivityProblem: () => false}, entry)
  const result = (terminalText, eof = 1) => ({
    result_events: [
      {event_type: 'progress', message: 'Downloading...'},
      {event_type: 'chunk', message: 'Interim line'},
      {event_type: 'completed', status: 'success', message: terminalText},
    ],
    output_records: [
      {text: 'Downloading...', eof: 0}, {text: 'Interim line', eof: 0},
      ...(terminalText ? [{text: terminalText, eof}] : []),
    ],
  })
  assert.equal(build({kind: 'job', status: 'success', files: [], result: result('Job started.')}), 'Job started.')
  assert.equal(build({kind: 'script', status: 'success', files: [], result: result('x'.repeat(256))}), 'x'.repeat(256))
  assert.equal(build({kind: 'script', status: 'success', files: [], result: result('x'.repeat(257))}), 'Completed')
  assert.equal(build({kind: 'script', status: 'success', files: [], result: result('one\ntwo')}), 'Completed')
  assert.equal(build({kind: 'command', status: 'success', files: [], result: result('')}), 'Completed')
  assert.equal(build({kind: 'command', status: 'interrupted', files: [], result: {
    output_records: [{text: 'partial', eof: 0}],
    result_events: [{event_type: 'chunk', message: 'partial'}],
  }}), 'Interrupted')
  assert.equal(build({kind: 'remote_files', status: 'success', files: [{id: 'file-1'}], result: {
    result_events: [{event_type: 'completed', status: 'success', message: ''}], output_records: [],
  }}), 'Produced 1 file(s)')
  assert.equal(build({kind: 'command', status: 'success', files: [], result: {output_records: []}}), 'Completed')
  assert.equal(build({kind: 'command', status: 'success', files: [], result: {output_records: [], result_events: [{event_type: 'completed', status: 'success'}]}}), 'Completed')
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
  const entry = {kind:'remote_files', action:'rename_path', status:'success',
    summary:'Rename', invocation:{}, resolved:{type:'control',id:2,domain:'remote_files',action:'rename_path',payload:{old_path:'/tmp/a.txt',new_name:'b.txt',count:1}},
    result:{output_records:[{text:'Renamed to: /tmp/b.txt'}]}}
  assert.equal(component.methods.getActivityKindIcon('remote_files'), context.FolderOpen)
  assert.equal(component.methods.buildActivityKindLabel('remote_files'), 'Remote Files')
  assert.equal(component.methods.buildActivityLabel(entry), 'Rename')
  assert.equal(component.methods.buildCommandExecutionSummary.call({},entry), 'Renamed to: /tmp/b.txt')
  assert.equal(component.methods.buildActivityLabel({kind:'remote_files',action:'delete_paths',summary:'Delete 2 items',invocation:{}}), 'Delete 2 items')
  assert.equal(component.methods.buildActivityLabel({kind:'remote_files',action:'create_directory',summary:'Create directory',invocation:{}}), 'Create directory')
  const detailScript = detail.match(/<script>([\s\S]*?)<\/script>/)?.[1]
  const detailContext = {}
  vm.runInNewContext(detailScript.replace('export default {', 'globalThis.component = {'), detailContext)
  assert.equal(detailContext.component.methods.getActivityInvocation(entry), '-')
  const contents = detailContext.component.methods.getActivityResolved(entry)
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
  const transfer = {kind:'transfer', action:'download_files', status:'success', summary:'Download 3 items',invocation:{}}
  assert.equal(component.methods.buildActivityLabel(transfer), 'Download 3 items')
  assert.equal(component.methods.buildActivityKindLabel('transfer'), 'Transfer')
  assert.equal(component.methods.getActivityKindIcon('transfer', 'download_files'), context.ArrowDownToLine)
  assert.equal(component.methods.getActivityKindIcon('transfer', 'upload_files'), context.ArrowUpToLine)
  assert.match(activity, /getActivityKindIcon\(item\.kind, item\.action\)/)
  assert.match(source, /\['command', 'script', 'remote_files', 'transfer', 'external_tool', 'job', 'pty', 'screen_view', 'clipboard', 'process', 'configuration', 'watchdog'\]/)
})

test('External Tool Manager Activity is semantic, searchable and uses a distinct icon', () => {
  assert.match(activity, /label="External Tool" value="external_tool"/)
  assert.match(source, /external_tool: Wrench/)
  assert.equal(component.methods.getActivityKindIcon('external_tool'), context.Wrench)
  assert.equal(component.methods.buildActivityKindLabel('external_tool'), 'External Tool')
  const example = {kind: 'external_tool', action: 'start_instance',
    summary:'Start heartbeat.worker (alpha)',invocation:{}}
  assert.equal(component.methods.buildActivityLabel(example), 'Start heartbeat.worker (alpha)')
  assert.equal(component.methods.buildActivityLabel({kind:'external_tool', action:'install_package',
    summary:'Install heartbeat',invocation:{}}), 'Install heartbeat')
  assert.match(source, /\['command', 'script', 'remote_files', 'transfer', 'external_tool', 'job', 'pty', 'screen_view', 'clipboard', 'process', 'configuration', 'watchdog'\]\.includes\(item\?\.kind\)/)
})


test('xt Exec uses semantic External Tool label and human invocation', () => {
  const entry = {kind:'external_tool', action:'run_exec',
    summary:'Run ffmpeg',invocation:{command:'xt run ffmpeg -- -version'},
    resolved:{type:'command',id:3,text:'external_tool_exec __json__:encoded'}}
  assert.equal(component.methods.buildActivityLabel(entry), 'Run ffmpeg')
  assert.equal(component.methods.getActivityKindIcon('external_tool'), context.Wrench)
  const detailContext = {}
  const detailScript = detail.match(/<script>([\s\S]*?)<\/script>/)?.[1]
  vm.runInNewContext(detailScript.replace('export default {', 'globalThis.component = {'), detailContext)
  assert.equal(detailContext.component.methods.getActivityInvocation(entry), 'xt run ffmpeg -- -version')
  assert.equal(JSON.parse(detailContext.component.methods.getActivityResolved(entry)).text, entry.resolved.text)
})

test('Background Job actions use one semantic Activity and a distinct icon', () => {
  assert.match(activity, /label="Background Job" value="job"/)
  assert.equal(component.methods.getActivityKindIcon('job'), context.BriefcaseBusiness)
  assert.equal(component.methods.buildActivityKindLabel('job'), 'Background Job')
  assert.equal(component.methods.buildActivityLabel({kind:'job', action:'start',
    summary:'Start cleanup',invocation:{}}), 'Start cleanup')
  assert.equal(component.methods.buildActivityLabel({kind:'job', action:'stop',
    summary:'Stop cleanup',invocation:{}}), 'Stop cleanup')
  assert.equal(component.methods.buildActivityLabel({kind:'job', action:'stop_all',summary:'Stop all jobs',
    invocation:{}}), 'Stop all jobs')
})


test('Job detail preserves exact request and output counts without projecting results into Resolved', () => {
  const detailContext = {}
  const detailScript = detail.match(/<script>([\s\S]*?)<\/script>/)?.[1]
  vm.runInNewContext(detailScript.replace('export default {', 'globalThis.component = {'), detailContext)
  const request = {type:'control', id:4, domain:'job', action:'stop_all',payload:{}}
  const counts = {total:2,succeeded:1,failed:1,job_ids:['a']}
  const entry = {kind:'job',action:'stop_all',invocation:{},resolved:request,result:{output_records:[{text:JSON.stringify(counts)}]}}
  assert.deepEqual(JSON.parse(detailContext.component.methods.getActivityResolved(entry)),request)
  assert.deepEqual(JSON.parse(entry.result.output_records[0].text),counts)
  assert.match(detail,/entry\.result\?\.output_records/)
})


test('PTY, Screen View, Clipboard Set and Process Kill have semantic Activity filters and labels', () => {
  for (const [kind, title] of [['pty', 'PTY'], ['screen_view', 'Screen View'], ['clipboard', 'Clipboard'], ['process', 'Process']]) {
    assert.match(activity, new RegExp(`label="${title}" value="${kind}"`))
    assert.equal(component.methods.buildActivityKindLabel(kind), title)
  }
  assert.equal(component.methods.buildActivityLabel({kind:'pty',action:'session',summary:'PTY'}), 'PTY')
  assert.equal(component.methods.buildActivityLabel({kind:'screen_view',action:'session',summary:'Screen View'}), 'Screen View')
  assert.equal(component.methods.buildActivityLabel({kind:'clipboard',action:'set',summary:'Send Artifact file',invocation:{}}), 'Send Artifact file')
  assert.equal(component.methods.buildActivityLabel({kind:'process',action:'kill',summary:'Kill app Safari (PID 42)',invocation:{}}), 'Kill app Safari (PID 42)')
  assert.equal(component.methods.getActivityKindIcon('screen_view'), context.Monitor)
  assert.equal(component.methods.getActivityKindIcon('clipboard'), context.Clipboard)
  assert.equal(component.methods.getActivityKindIcon('process'), context.Activity)
})


test('Session, clipboard metadata and named process activity labels remain compact', () => {
  const label = component.methods.buildActivityLabel
  assert.equal(label({kind:'pty', action:'session', summary:'PTY · /bin/zsh',invocation:{}}), 'PTY · /bin/zsh')
  assert.equal(label({kind:'screen_view', action:'session',summary:'Screen View'}), 'Screen View')
  assert.equal(label({kind:'clipboard', action:'set', summary:'Set text · hello world',invocation:{}}), 'Set text · hello world')
  assert.equal(label({kind:'clipboard', action:'set', summary:'Set image · shot.png',invocation:{}}), 'Set image · shot.png')
  assert.equal(label({kind:'clipboard', action:'set', summary:'Set files · report.pdf, pics',invocation:{}}), 'Set files · report.pdf, pics')
  assert.equal(label({kind:'clipboard', action:'set', summary:'Send Artifact file · notes.txt',invocation:{}}), 'Send Artifact file · notes.txt')
  assert.equal(label({kind:'process', action:'kill', summary:'Kill process chrome.exe (PID 123)',invocation:{}}), 'Kill process chrome.exe (PID 123)')
})
