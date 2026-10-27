import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

import { formatLaunchMode } from '../src/utils/formatters.js'

const read = path => readFileSync(new URL(path, import.meta.url), 'utf8')

test('launch mode formatter presents mode and concrete source', () => {
  assert.equal(formatLaunchMode('terminal', 'zsh'), 'Terminal (zsh)')
  assert.equal(formatLaunchMode('ide', 'pycharm'), 'IDE (PyCharm)')
  assert.equal(formatLaunchMode('user_service', 'launchagent'), 'User service (LaunchAgent)')
  assert.equal(formatLaunchMode('system_service', 'launchdaemon'), 'System service (LaunchDaemon)')
  assert.equal(formatLaunchMode('scheduled', 'schtasks'), 'Scheduled (Task Scheduler)')
  assert.equal(formatLaunchMode('detached', 'new_session'), 'Detached (new session)')
  assert.equal(formatLaunchMode('unknown', ''), 'Unknown')
})

test('Basic Info and Connection History display launch mode snapshots', () => {
  const basicInfo = read('../src/components/ConnectionInfoDialogs.vue')
  const history = read('../src/components/MachineConnectionHistoryDialog.vue')

  assert.match(basicInfo, /label: 'Launch Mode'/)
  assert.match(basicInfo, /formatLaunchMode\(conn\.launch_mode, conn\.launch_source\)/)
  assert.match(history, /<span class="label">Launch mode<\/span>/)
  assert.match(history, /formatLaunchMode\(row\?\.launch_mode, row\?\.launch_source\)/)
})
