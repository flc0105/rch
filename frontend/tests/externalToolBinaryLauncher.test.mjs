import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'

const source = readFileSync(new URL('../src/components/ExternalToolManagerDialog.vue', import.meta.url), 'utf8')

// Test the component's real methods without booting Vue or a browser.
function method(name, arg) {
  const match = source.match(new RegExp(`\\n    ${name}\\(${arg}\\) \\{([\\s\\S]*?)\\n    \\},`))
  assert.ok(match, `missing ${name} method`)
  return new Function(arg, match[1])
}

const normalize = method('normalizeModuleFromPackage', 'pkg, module')
const execution = method('getModuleExecution', 'module')
const launcher = method('getModuleLauncher', 'module')

test('manager resolves daemon launcher from binaries rather than public execs', () => {
  const pkg = {
    id: 'java-bundle-demo',
    binaries: { 'java-bundle-demo': { launcher: { type: 'system', command: 'java', prefix_args: ['-jar'] } } },
    modules: [{ id: 'web', binary: 'java-bundle-demo', execution: 'daemon' }],
  }
  const ctx = { getModuleExecution: execution }
  const module = normalize.call(ctx, pkg, pkg.modules[0])
  assert.equal(module.package_binaries['java-bundle-demo'].launcher.command, 'java')
  assert.deepEqual(launcher.call(ctx, module).command, 'java')
  assert.equal(launcher.call(ctx, { binary: 'missing', package_binaries: pkg.binaries }), null)
})
