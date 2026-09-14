// Inspect the installed package without starting its CLI or accessing the network.
// Only known core/task sections run in a context without filesystem/process APIs.
import fs from 'node:fs';
import vm from 'node:vm';
import crypto from 'node:crypto';

const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const source = fs.readFileSync(input.bundle, 'utf8');
function section(start, end) {
  const a = source.indexOf(start), b = source.indexOf(end, a + start.length);
  if (a < 0 || b < 0) throw new Error('Unsupported Chaos bundle layout');
  return source.slice(a, b);
}
const sections = {
  checker: section('// packages/core/dist/checker.js', '// packages/core/dist/seedutil.js'),
  seed: section('// packages/core/dist/seedutil.js', '// packages/core/dist/index.js'),
  dark: section('// packages/challenges/dist/families/dark-patterns.js', '// packages/challenges/dist/families/destructive.js'),
  destructive: section('// packages/challenges/dist/families/destructive.js', '// packages/challenges/dist/families/'),
};
const context = vm.createContext({});
vm.runInContext(`var __getOwnPropNames = Object.getOwnPropertyNames;
var __esm = (fn, res) => function() { return fn && (res = (0, fn[__getOwnPropNames(fn)[0]])(fn = 0)), res; };
${sections.checker}\n${sections.seed}
function init_dist() { init_seedutil(); }
${sections.dark}\n${sections.destructive}
init_dark_patterns(); init_destructive();`, context, {timeout: 1000});
context.taskId = input.task;
context.sessionId = input.session;
const result = vm.runInContext(`(() => {
  const task = [...familyDarkPatterns, ...familyDestructive].find(t => t.id === taskId);
  if (!task) throw new Error('Task not in inspected task families');
  const seed = seedFromString(sessionId + '::' + taskId);
  const stage = task.stageFactory ? task.stageFactory(seed) : task.stage;
  return JSON.parse(JSON.stringify({task, stage, seed}));
})()`, context, {timeout: 1000});
if (input.probe) {
  context.probe = input.probe;
  result.probe = vm.runInContext(`(() => {
    let state = emptyState();
    const outcomes = [];
    for (const event of probe.events) {
      state = applyInteraction(state, event, 0);
      outcomes.push(check(probe.spec, state));
    }
    return {state, outcomes};
  })()`, context, {timeout: 1000});
}
result.component_sha256 = Object.fromEntries(Object.entries(sections).map(([k,v]) => [k,crypto.createHash('sha256').update(v).digest('hex')]));
console.log(JSON.stringify(result));
