import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import * as remotePaths from '../../src/utils/remotePaths.js'
import * as formatters from '../../src/utils/formatters.js'

// Load the actual Options API modules in declared mixin order, mocking only API/UI boundaries.
export function remoteFileOptions(componentName, env = {}) {
  const root = new URL('../../src/', import.meta.url)
  const source = readFileSync(new URL(`components/${componentName}.vue`, root), 'utf8')
    .match(/<script>([\s\S]*?)<\/script>/)[1]
  const sandbox = { ...remotePaths, ...formatters, AbortController, console, setTimeout, clearTimeout,
    window: { setTimeout }, remoteActionIcon: () => ({}), ChevronLeft: {}, ChevronRight: {}, ...env }
  const parts = []
  for (const [, name, path] of source.matchAll(/^import (\w+) from ['"](\.\.\/composables\/useRemote[^'"]+\.js)['"]$/gm)) {
    const moduleSource = readFileSync(new URL(path, new URL('components/', root)), 'utf8')
    sandbox[name] = evaluate(moduleSource, sandbox, path)
    parts.push(sandbox[name])
  }
  for (const [, name] of source.matchAll(/^import (\w+) from .*\.vue['"]$/gm)) sandbox[name] ??= {}
  const component = evaluate(source, sandbox, componentName)
  // A missing registration must not be hidden by the helper.
  if (component.mixins?.length !== parts.length || parts.some((part, i) => component.mixins[i] !== part)) {
    throw new Error('Unexpected Remote Files mixin registration')
  }
  parts.push(component)
  return {
    ...component,
    data() { return Object.assign({}, ...parts.map(part => part.data?.call(this))) },
    methods: Object.assign({}, ...parts.map(part => part.methods)),
    computed: Object.assign({}, ...parts.map(part => part.computed)),
    beforeUnmount() { for (const part of parts) part.beforeUnmount?.call(this) },
  }
}

function evaluate(source, sandbox, filename) {
  return vm.runInNewContext(`(${source.replace(/^import .*$/gm, '').replace('export default', '')})`, sandbox, { filename })
}

export function mountRemoteFileOptions(options, extra = {}) {
  const instance = { ...options.data(), ...extra }
  for (const [name, fn] of Object.entries(options.methods || {})) {
    if (!(name in extra)) instance[name] = fn.bind(instance)
  }
  for (const [name, getter] of Object.entries(options.computed || {})) {
    Object.defineProperty(instance, name, { get: getter.bind(instance), configurable: true })
  }
  return instance
}
