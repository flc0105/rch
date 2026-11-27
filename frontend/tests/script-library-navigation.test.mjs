import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = readFileSync(new URL('../src/components/ScriptLibraryDialog.vue', import.meta.url), 'utf8')
const script = source.split('<script>')[1].split('</script>')[0]
  .replace(/^import\s+[\s\S]*?\s+from\s+['"][^'"]+['"][^\n]*\n/gm, '')
const componentNames = script.match(/components:\s*\{([^}]+)\}/)[1].split(',').map(s => s.trim()).filter(Boolean)
const component = new Function(...componentNames, script.replace('export default {', 'return {'))(...componentNames.map(() => ({})))

function createLibrary() {
  const pane = { scrollTop: 100 }
  const tree = { selectedKey: null, expandParent: false, setCurrentKey(key, expandParent) { this.selectedKey = key; this.expandParent = expandParent } }
  const state = {
    ...component.data(),
    $refs: { scriptDirectoryPane: pane, scriptDirectoryTreeRef: tree },
    $nextTick(fn) { fn() },
    scriptCatalogDirectories: [
      { path: '' }, { path: 'mac/ops' }, { path: 'mac/empty' },
      { path: 'mac/ops/sub' }, { path: 'linux/ops' }, { path: 'mac/ops' },
    ],
    scriptCatalogItems: [
      { script_name: 'mac/ops/backup', path: 'mac/ops/backup.py', display_name: 'Backup' },
      { script_name: 'mac/ops/sub/backup', path: 'mac/ops/sub/backup.py', display_name: 'Backup child' },
      { script_name: 'linux/ops/backup', path: 'linux/ops/backup.py', display_name: 'Backup Linux' },
    ],
  }
  for (const [name, method] of Object.entries(component.methods)) state[name] = method.bind(state)
  for (const [name, getter] of Object.entries(component.computed)) Object.defineProperty(state, name, { get: getter.bind(state) })
  return state
}

test('right pane uses immediate, sorted, unique folders from the same catalog tree, including empty folders', () => {
  const state = createLibrary()
  assert.deepEqual(state.currentScriptDirectoryFolders.map(folder => folder.path), ['linux', 'mac'])
  state.selectedDirectory = 'mac'
  assert.deepEqual(state.currentScriptDirectoryFolders.map(folder => folder.path), ['mac/empty', 'mac/ops'])
  state.selectedDirectory = 'mac/ops'
  assert.deepEqual(state.currentScriptDirectoryFolders.map(folder => folder.path), ['mac/ops/sub'])
  state.selectedDirectory = 'mac/empty'
  assert.deepEqual(state.currentScriptDirectoryFolders, [])
  assert.deepEqual(state.filteredCurrentScriptDirectoryItems, [])
})

test('navigation updates the single selected directory, reveals its ancestors and returns to root', () => {
  const state = createLibrary()
  state.navigateScriptDirectory('mac/ops/sub')
  assert.equal(state.selectedScriptDirectoryTreeKey, 'dir:mac/ops/sub')
  assert.equal(state.$refs.scriptDirectoryTreeRef.selectedKey, 'dir:mac/ops/sub')
  assert.equal(state.$refs.scriptDirectoryTreeRef.expandParent, true)
  for (const key of ['dir:.', 'dir:mac', 'dir:mac/ops', 'dir:mac/ops/sub']) assert.ok(state.scriptTreeExpandedKeys.includes(key))
  assert.equal(state.$refs.scriptDirectoryPane.scrollTop, 0)
  state.handleScriptTreeNodeCollapse({ key: 'dir:mac/ops' })
  assert.equal(state.selectedScriptDirectoryTreeKey, 'dir:mac/ops/sub')
  state.navigateScriptDirectory(state.getParentScriptDirectory(state.selectedDirectory))
  assert.equal(state.selectedScriptDirectoryTreeKey, 'dir:mac/ops')
  state.handleScriptTreeNodeClick({ path: 'linux/ops' })
  assert.equal(state.selectedScriptDirectoryTreeKey, 'dir:linux/ops')
  state.navigateScriptDirectory('')
  assert.equal(state.selectedScriptDirectoryTreeKey, 'dir:.')
  assert.match(source, /<FolderOpen v-if="data\.key === selectedScriptDirectoryTreeKey"/)
  assert.match(source, /v-if="selectedDirectory"[\s\S]*?@click="navigateScriptDirectory\(getParentScriptDirectory\(selectedDirectory\)\)"/)
})

test('search always recurses within the current directory without including sibling directories', () => {
  const state = createLibrary()
  state.navigateScriptDirectory('mac/ops')
  assert.deepEqual(state.filteredCurrentScriptDirectoryItems.map(item => item.script_name), ['mac/ops/backup'])
  state.scriptSearchText = 'backup'
  assert.deepEqual(state.filteredCurrentScriptDirectoryItems.map(item => item.script_name), ['mac/ops/backup', 'mac/ops/sub/backup'])
  state.scriptCatalogItems.push({ script_name: 'mac/ops-extra/backup', path: 'mac/ops-extra/backup.py' })
  assert.deepEqual(state.filteredCurrentScriptDirectoryItems.map(item => item.script_name), ['mac/ops/backup', 'mac/ops/sub/backup'])
  state.scriptSearchText = '   '
  assert.equal(state.hasScriptSearch, false)
  assert.deepEqual(state.filteredCurrentScriptDirectoryItems.map(item => item.script_name), ['mac/ops/backup'])
  state.scriptSearchText = 'backup'
  state.navigateScriptDirectory('mac/ops/sub')
  assert.deepEqual(state.filteredCurrentScriptDirectoryItems.map(item => item.script_name), ['mac/ops/sub/backup'])
  state.navigateScriptDirectory('linux/ops')
  assert.deepEqual(state.filteredCurrentScriptDirectoryItems.map(item => item.script_name), ['linux/ops/backup'])
})

test('folder counts include nested scripts, exclude sibling prefixes and ignore search', () => {
  const state = createLibrary()
  state.scriptCatalogDirectories.push({ path: 'mac/ops-extra' })
  state.scriptCatalogItems.push({ script_name: 'mac/ops-extra/test', path: 'mac/ops-extra/test.py' })
  assert.deepEqual(state.currentScriptDirectoryFolders.map(({ path, scriptCount }) => [path, scriptCount]), [['linux', 1], ['mac', 3]])
  state.navigateScriptDirectory('mac')
  assert.deepEqual(state.currentScriptDirectoryFolders.map(({ path, scriptCount }) => [path, scriptCount]), [['mac/empty', 0], ['mac/ops', 2], ['mac/ops-extra', 1]])
  state.scriptSearchText = 'missing'
  assert.equal(state.currentScriptDirectoryFolders.find(folder => folder.path === 'mac/ops').scriptCount, 2)
  state.scriptCatalogItems = state.scriptCatalogItems.filter(item => item.script_name !== 'mac/ops/sub/backup')
  assert.equal(state.currentScriptDirectoryFolders.find(folder => folder.path === 'mac/ops').scriptCount, 1)
})

test('compact cards keep full path and description in tooltips and tree toggle is always accessible', () => {
  const state = createLibrary()
  assert.equal(state.scriptTreeVisible, true)
  assert.match(source, /v-show="scriptTreeVisible" class="script-library-tree panel-lite"/)
  assert.match(source, /class="script-library-tree-toggle"[\s\S]*?@click="scriptTreeVisible = !scriptTreeVisible"/)
  assert.doesNotMatch(source, /class="script-library-card-path/)
  assert.match(source, /:title="\[item\.display_name, item\.path \|\| item\.script_name\]/)
  assert.match(source, /\.script-library-card-description\s*\{[^}]*white-space:\s*nowrap;[^}]*text-overflow:\s*ellipsis;/)
  assert.match(source, /\.script-library-card,\s*\.script-library-folder-row:not\(\.script-library-parent-row\)\s*\{/)
})


test('breadcrumb contains root and exact ancestor paths, and stale tree sync cannot replace a newer selection', () => {
  const state = createLibrary()
  const callbacks = []
  state.$nextTick = fn => callbacks.push(fn)
  state.navigateScriptDirectory('mac/ops/sub')
  assert.deepEqual(state.scriptDirectoryBreadcrumb, [
    { label: 'root', path: '' }, { label: 'mac', path: 'mac' },
    { label: 'ops', path: 'mac/ops' }, { label: 'sub', path: 'mac/ops/sub' },
  ])
  state.navigateScriptDirectory('linux/ops')
  callbacks.reverse().forEach(fn => fn())
  assert.equal(state.$refs.scriptDirectoryTreeRef.selectedKey, 'dir:linux/ops')
  state.navigateScriptDirectory('')
  assert.deepEqual(state.scriptDirectoryBreadcrumb, [{ label: 'root', path: '' }])
  assert.match(source, /aria-label="Script directory"[\s\S]*?@click="navigateScriptDirectory\(crumb.path\)"/)
})


test('search hides folder rows and header counts, and the sidebar toggle has explicit state and labels', () => {
  assert.match(source, /v-if="!hasScriptSearch && \(selectedDirectory \|\| currentScriptDirectoryFolders.length\)" class="script-library-folder-list"/)
  assert.doesNotMatch(source, /scriptSearchRecursive|scriptDirectoryItemCountText|Include subfolders/)
  assert.match(source, /<PanelLeftClose v-if="scriptTreeVisible"/)
  assert.match(source, /<PanelLeftOpen v-else/)
  assert.match(source, /:aria-expanded="scriptTreeVisible"/)
  assert.match(source, /scriptTreeVisible \? 'Hide folder tree' : 'Show folder tree'/)
})
