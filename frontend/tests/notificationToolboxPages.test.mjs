import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import { test } from 'node:test'

const read = path => readFileSync(new URL(path, import.meta.url), 'utf8')
function componentOptions(path, globals = {}) {
  const s = read(path).match(/<script>([\s\S]*?)<\/script>/)?.[1]
  assert.ok(s)
  const icons = [...s.matchAll(/import \{([\s\S]*?)\} from ['"](?:@lucide\/vue|@element-plus\/icons-vue)['"]/g)]
    .flatMap(match => match[1].split(',').map(name => name.trim()).filter(Boolean))
  const ctx = { ...Object.fromEntries(icons.map(name => [name, {}])), ...globals }
  vm.runInNewContext(s.replace(/^import\s+[\s\S]*?\s+from\s+['"][^'"]+['"]\s*$/gm, '')
    .replace('export default {', 'const options = {') + '\nglobalThis.options = options', ctx)
  return ctx.options
}
function toolbox(actions, query = '') {
  const options = componentOptions('../src/components/ToolboxDialog.vue', { IconPickerDialog: {}, TOOLBOX_SHORTCUT_ICONS: [], isScriptSupportedOnPlatform: () => true, isQuickActionSupportedOnPlatform: () => true })
  const inst = { ...options.data(), ...options.methods, actions, query, $refs: {} }
  for (const [key, fn] of Object.entries(options.computed)) {
    Object.defineProperty(inst, key, { get() { return fn.call(inst) } })
  }
  return inst
}

test('Toolbox keeps the add tile as the last slot and only shows dots for more than 24 entries', () => {
  const make = n => Array.from({length:n}, (_, i) => ({id:`tool-${i}`, label:`Tool ${i}`}))
  const a = toolbox(make(23))
  assert.equal(a.pageCount, 1)
  assert.equal(a.pageActions.length, 23)
  assert.equal(a.showAddOnPage, true)
  const b = toolbox(make(24))
  assert.equal(b.pageCount, 2)
  assert.equal(b.pageActions.length, 24)
  assert.equal(b.showAddOnPage, false)
  b.setPage(1)
  assert.equal(b.pageActions.length, 0)
  assert.equal(b.showAddOnPage, true)
  const c = toolbox(make(49))
  assert.equal(c.pageCount, 3)
  c.setPage(2)
  assert.deepEqual(Array.from(c.pageActions, item => item.id), ['tool-48'])
  assert.equal(c.showAddOnPage, true)
  c.setPage(99)
  assert.equal(c.currentPage, 2)
})

test('Toolbox switches full pages on wheel or swipe, including vertical direction', () => {
  const list = toolbox(Array.from({length:52}, (_, i) => ({id:`x-${i}`,label:`Tool ${i}`})))
  list.onPageTouchStart({touches:[{clientX:200,clientY:100}]})
  list.onPageTouchEnd({changedTouches:[{clientX:110,clientY:280}]})
  assert.equal(list.currentPage, 0) // Scrolling down when already on the first page is clamped.
  list.onPageTouchStart({touches:[{clientX:200,clientY:280}]})
  list.onPageTouchEnd({changedTouches:[{clientX:198,clientY:100}]})
  assert.equal(list.currentPage, 1)
  list.onPageWheel({deltaX:1,deltaY:48})
  assert.equal(list.currentPage, 2)
  list.onPageWheel({deltaX:1,deltaY:48}) // One gesture cannot skip two pages.
  assert.equal(list.currentPage, 2)
  list.onPageWheel({deltaX:0,deltaY:-48}) // Reverse works without waiting for a cooldown.
  assert.equal(list.currentPage, 1)
  list.onPageWheel({deltaX:-48,deltaY:0}) // The same gesture stays on one page.
  assert.equal(list.currentPage, 1)
  list.lastPageWheelAt = 0 // A later gesture can flip back to page one.
  list.onPageWheel({deltaX:-48,deltaY:0})
  assert.equal(list.currentPage, 0)
})


test('Toolbox accumulates trackpad wheel steps and respects gesture direction and delta mode', () => {
  const list = toolbox(Array.from({length:60}, (_, i) => ({id:`x-${i}`,label:`Tool ${i}`})))
  for (let i=0;i<3;i++) list.onPageWheel({deltaX:0,deltaY:4})
  assert.equal(list.currentPage,0)
  list.onPageWheel({deltaX:0,deltaY:4})
  assert.equal(list.currentPage,1)
  list.onPageWheel({deltaX:0,deltaY:80})
  assert.equal(list.currentPage,1) // Long wheel stream stays on the same page.
  list.onPageWheel({deltaX:0,deltaY:-2})
  list.onPageWheel({deltaX:0,deltaY:-12})
  assert.equal(list.currentPage,0) // Reverse direction is immediately usable.
  list.lastPageWheelAt = 0
  list.onPageWheel({deltaX:0,deltaY:1,deltaMode:1})
  assert.equal(list.currentPage,1) // A line-based mouse wheel switches immediately.
  assert.match(read('../src/components/ToolboxDialog.vue'),/gap: 9px; padding: 8px 0 5px/)
})

test('Toolbox stays on the page that opened Add when shortcuts update', () => {
  const options = componentOptions('../src/components/ToolboxDialog.vue', { IconPickerDialog: {}, TOOLBOX_SHORTCUT_ICONS: [], isScriptSupportedOnPlatform: () => true, isQuickActionSupportedOnPlatform: () => true })
  const list = toolbox(Array.from({length:24}, (_, i) => ({id:`tool-${i}`,label:`Tool ${i}`})))
  list.setPage(1)
  list.actions = [...list.actions, {id:'new-shortcut',label:'New shortcut'}]
  options.watch.actions.call(list)
  assert.equal(list.currentPage, 1)
  assert.equal(list.pageActions.length, 1)
  assert.equal(list.showAddOnPage, true)
  list.actions = Array.from({length:10}, (_, i) => ({id:`tool-${i}`,label:`Tool ${i}`}))
  options.watch.actions.call(list)
  assert.equal(list.currentPage, 0)
  assert.match(read('../src/components/ToolboxDialog.vue'), /@wheel\.prevent="onPageWheel"/)
})
test('Toolbox search paginates matched entries without the Add tile, and can clamp stale page', () => {
  const actions = Array.from({length:30}, (_, i) => ({id:`x-${i}`, label:`Tool ${i}`}))
  const list = toolbox(actions)
  list.setPage(1)
  list.query = 'Tool 2'
  assert.equal(list.pageCount, 1)
  assert.equal(list.currentPage, 0)
  assert.equal(list.showAddOnPage, false)
  assert.equal(list.pageActions.length, 11)
})

test('Notification Center labels and clearing targets follow selected type; All is unchanged', async () => {
  const requested = []
  const messages = []
  const events = []
  const options = componentOptions('../src/components/NotificationCenterDrawer.vue', {
    Bell: {}, CircleCheckFilled: {}, CircleCloseFilled: {}, Close: {}, Delete: {}, InfoFilled: {}, WarningFilled: {},
    ElMessage: {error: e => { throw new Error(e) }},
    ElMessageBox: {confirm: async (...args) => { messages.push(args) }},
    clearNotificationHistory: async type => { requested.push(type) },
    deleteNotificationHistory: async () => {}, formatDateTimeLocal: v => v,
  })
  const instance = { ...options.data(), ...options.methods, notifications: [{id:'s',type:'success'}, {id:'e',type:'error'}], $emit: e => events.push(e) }
  for (const [key, fn] of Object.entries(options.computed)) {
    Object.defineProperty(instance, key, {get() {return fn.call(instance)}})
  }
  assert.equal(instance.clearLabel, 'Clear All')
  await instance.clearAll()
  assert.equal(messages[0][0], 'Clear all notifications? This cannot be undone.')
  assert.equal(messages[0][2].confirmButtonText, 'Clear All')
  instance.typeFilter = 'error'
  assert.equal(instance.clearLabel, 'Clear Error')
  assert.equal(instance.filteredNotifications.length, 1)
  await instance.clearAll()
  assert.equal(messages[1][0], 'Clear error notifications? This cannot be undone.')
  assert.equal(messages[1][2].confirmButtonText, 'Clear Error')
  instance.typeFilter = 'warning'
  await instance.clearAll() // Empty filtered category cannot call the API.
  assert.deepEqual(requested, ['all', 'error'])
  assert.equal(events.length, 2)
})

test('Notification Center uses Element Plus select with unchanged dimensions', () => {
  const s = read('../src/components/NotificationCenterDrawer.vue')
  assert.match(s, /<el-select[\s\S]*?class="notification-center-filter"/)
  assert.match(s, /\.notification-center-filter\s*\{\s*width: 82px;\s*height: 24px;/)
  assert.doesNotMatch(s, /<select\s+v-model="typeFilter"/)
})

test('Notification API retains original clear-all URL and scopes filtered URL', async () => {
  const source = read('../src/api/notificationHistoryApi.js')
  const urls = []
  const ctx = { apiData: async url => { urls.push(url); return { removed_count: 1 } } }
  vm.runInNewContext(source.replace(/^import.*$/gm, '').replaceAll('export function', 'function')
    + '\nglobalThis.clearNotificationHistory = clearNotificationHistory', ctx)
  await ctx.clearNotificationHistory()
  await ctx.clearNotificationHistory('warning')
  assert.deepEqual(urls, ['/api/notifications/history', '/api/notifications/history?type=warning'])
})
