import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import taskState from '../src/composables/useTaskState.js';
import { normalizeForegroundTask } from '../src/utils/foregroundTask.js';

const app = readFileSync(new URL('../src/App.vue', import.meta.url), 'utf8');
const start = app.indexOf('    applyForegroundTaskUpdate(');
const end = app.indexOf('\n    async refreshForegroundTask()', start);
assert.ok(start >= 0 && end > start);
const body = app.slice(start, end).match(/\{([\s\S]*)\},\s*$/)?.[1];
assert.ok(body);
const apply = new Function('normalizeForegroundTask', `return function applyForegroundTaskUpdate(clientId, payload) {${body}}`)(normalizeForegroundTask);

function fixture() {
  const state = {
    ...taskState.data(),
    selectedId: 'c1', connections: [], foregroundTasks: {}, foregroundQuerySequence: 0,
    outputs: [],
    syncForegroundTaskNotice() {}, appendOutput(...args) { this.outputs.push(args) },
    applyForegroundTaskUpdate: apply,
  };
  for (const [key, method] of Object.entries(taskState.methods)) state[key] = method;
  return state;
}

test('missing command_complete followed by authoritative Idle recovers Run/Cancel and blocks late POST', async () => {
  const page = fixture();
  page.setActiveTask('c1', 'task-fast');
  assert.equal(page.activeTaskIds.c1, 'task-fast');
  page.applyForegroundTaskUpdate('c1', { state: 'Idle' });
  await Promise.resolve();
  assert.equal(page.activeTaskIds.c1, undefined);
  assert.ok(page.completedTaskIds['task-fast']);
  page.setActiveTask('c1', 'task-fast');
  assert.equal(page.activeTaskIds.c1, undefined);
});

test('a previous task Idle must not release a newer live task', async () => {
  const page = fixture();
  page.setActiveTask('c1', 'task-new');
  page.applyForegroundTaskUpdate('c1', { state: 'Running', task_id: 'task-new' });
  assert.equal(page.activeTaskIds.c1, 'task-new');
});
