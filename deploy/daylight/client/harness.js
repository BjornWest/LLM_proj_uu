const $ = id => document.getElementById(id);
const activeStatuses = new Set(['queued', 'running', 'starting', 'claimed']);
let config = null, jobs = [], selectedID = '', selectedJob = null, selectedStep = null;
let activity = 'watch', following = true, replayTimer = null, groupState = new Map();
let selectionVersion = 0, observationVersion = 0, pollTimer, polling = false;
let submitting = false, savingIssue = false, authExpired = false;
const goalDrafts = new Map();
const stamp = value => { const d = new Date(value); return value && !Number.isNaN(d.valueOf()) ? d.toLocaleString() : 'Time unavailable'; };
const describe = value => typeof value === 'string' ? value : JSON.stringify(value, null, 2);
const taskTitle = id => config?.tasks?.find(t => t.id === id)?.title || id || 'Unknown task';
const currentTask = () => config?.tasks?.find(t => t.id === $('task').value);
const selectedIndex = () => selectedJob?.steps?.findIndex(s => s.step === selectedStep) ?? -1;
function notice(message = '') { $('notice').textContent = message; $('notice').hidden = !message; }
async function api(path, data) {
  const response = await fetch(path, {credentials: 'same-origin', cache: 'no-store', redirect: 'manual', ...(data === undefined ? {} : {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data)
  })});
  if (response.status === 401 || response.type === 'opaqueredirect' || response.status === 302) {
    authExpired = true; clearTimeout(pollTimer); stopReplay(); syncControls();
    throw Error('Your session has expired. Sign in again using the Page demo link above.');
  }
  const value = await response.json().catch(() => null);
  if (!response.ok || !value) throw Error(value?.error || 'The server could not complete this request.');
  return value;
}
function artifactURL(value, id) {
  if (typeof value !== 'string' || !value) return null;
  const prefix = '/api/harness/jobs/' + encodeURIComponent(id) + '/artifacts/';
  if (value.startsWith(prefix)) {
    const tail = value.slice(prefix.length).split('?')[0];
    if (!/^[a-zA-Z0-9_.-]+$/.test(tail) || tail === '.' || tail === '..') return null;
    return value;
  }
  if (/^[a-zA-Z0-9_.-]+$/.test(value) && value !== '.' && value !== '..') return prefix + encodeURIComponent(value);
  return null;
}
function eligibleTasks() { return (config?.tasks || []).filter(t => activity !== 'ask' || t.custom_goal); }
function syncControls() {
  const task = currentTask(), eligible = eligibleTasks();
  $('submit-run').disabled = submitting || authExpired || activity === 'replay' || !config?.enabled || !task || task.available === false || (activity === 'ask' && !task.custom_goal);
  $('task').disabled = submitting || authExpired || !eligible.length;
  $('goal').disabled = submitting || authExpired || activity !== 'ask' || !task?.custom_goal;
  $('goal').required = activity === 'ask' && !!task?.custom_goal;
  $('submit-issue').disabled = savingIssue || authExpired || !selectedJob;
  const count = selectedJob?.steps?.length || 0, index = selectedIndex();
  $('viewer-controls').hidden = !selectedJob;
  $('previous-step').disabled = !count || index <= 0;
  $('next-step').disabled = !count || index >= count - 1;
  $('play-replay').disabled = count < 2;
  $('step-scrubber').disabled = !count;
  $('step-scrubber').max = String(Math.max(0, count - 1));
  $('step-scrubber').value = String(Math.max(0, index));
  $('step-position').textContent = count ? `${index + 1} / ${count}` : 'No steps';
  $('follow-live').hidden = activity === 'replay';
  $('follow-live').disabled = !selectedJob;
  $('follow-live').textContent = following ? 'Following latest' : 'Follow latest';
  $('follow-live').setAttribute('aria-pressed', String(following));
  $('history-state').textContent = replayTimer ? 'Playing recording' : following ? 'Following latest' : 'Inspecting history';
}
function taskFacts(task) {
  const facts = [['Runtime', 'BrowserGym'], ['Goal', task?.custom_goal && activity === 'ask' ? 'Custom request' : 'Fixed task']];
  // Optional registry metadata is displayed verbatim; missing provenance is never inferred.
  for (const [key, label] of [['site', 'Source site'], ['condition', 'Condition'], ['verification_scope', 'Verification']]) {
    if (typeof task?.[key] === 'string') facts.push([label, task[key]]);
  }
  $('task-facts').replaceChildren(...facts.flatMap(([key, value]) => {
    const dt = document.createElement('dt'), dd = document.createElement('dd'); dt.textContent = key; dd.textContent = value; return [dt, dd];
  }));
}
function chooseTask() {
  const task = currentTask();
  $('goal').value = goalDrafts.get(task?.id) ?? task?.goal ?? '';
  $('fixed-goal').textContent = task?.goal || 'No task is available in this mode yet.';
  $('goal-note').textContent = !task
    ? activity === 'ask' ? 'This worker currently offers fixed tasks only. Choose Watch a task to continue.' : 'Waiting for the task registry.'
    : task.available === false ? 'This task is unavailable until the worker advertises support for it.'
    : config?.worker?.mode === 'rehearsal' ? 'Scripted rehearsal · follows a fixed script without a model call.'
    : activity === 'ask' ? 'Custom requests may have unknown verification results. Each request starts a new run.'
    : 'The exact goal is sent to the agent. The environment independently checks supported outcomes.';
  taskFacts(task); syncControls();
}
function populateTasks() {
  const previous = $('task').value, tasks = eligibleTasks();
  $('task').replaceChildren(...tasks.map(task => {
    const option = document.createElement('option'); option.value = task.id;
    option.textContent = (task.title || task.id) + (task.available === false ? ' · unavailable' : '');
    option.disabled = task.available === false; return option;
  }));
  if (!tasks.length) { const option = document.createElement('option'); option.value = ''; option.textContent = 'No supported tasks'; $('task').append(option); }
  else $('task').value = tasks.some(t => t.id === previous && t.available !== false) ? previous : (tasks.find(t => t.available !== false) || tasks[0]).id;
  chooseTask();
}
function setActivity(next) {
  activity = next; stopReplay();
  document.querySelectorAll('[data-activity]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.activity === next)));
  $('task-form').hidden = next === 'replay';
  $('custom-goal-wrap').hidden = next !== 'ask'; $('fixed-goal-wrap').hidden = next !== 'watch';
  $('activity-kicker').textContent = next === 'ask' ? 'Ask the agent' : 'Watch a task';
  $('task-heading').textContent = next === 'ask' ? 'Start with a website' : 'Choose the setting';
  $('submit-run').textContent = next === 'ask' ? 'Send request →' : 'Watch task →';
  $('library-note').textContent = next === 'replay' ? 'Browse recorded BrowserGym runs visible to your invitation. Replay makes no model calls or browser actions.' : 'BrowserGym runs visible to your invitation.';
  if (next === 'replay') {
    following = false;
    if (selectedJob?.steps?.length) showStep(selectedJob.steps[0]);
    else if (!selectedID && jobs.length) selectJob(jobs[0].id);
    else if (!selectedJob) showImage(null, '', 'Choose a recorded run', 'Select a trace from the library to inspect its recorded steps.');
  } else if (!selectedID) {
    showImage(null, '', 'A front-row seat to each step', 'Choose a task and watch the agent work through it. Screenshots and recorded activity appear here.');
  }
  populateTasks(); syncControls();
}
function renderConfig(next) {
  const previous = config; config = next;
  const worker = next.worker || {};
  $('worker-status').classList.toggle('offline', !worker.online);
  $('worker-status').textContent = !next.enabled ? 'Harness unavailable' : worker.online
    ? '● Worker online · ' + (worker.mode === 'rehearsal' ? 'scripted rehearsal' : 'ready for tasks')
    : '○ Worker offline · new runs will wait';
  $('worker-status').title = worker.updated_at ? 'Last seen ' + stamp(worker.updated_at) : '';
  if (JSON.stringify(previous?.tasks) !== JSON.stringify(next.tasks) || previous?.worker?.mode !== worker.mode) populateTasks();
  syncControls();
}
function renderJobs(next = jobs) {
  jobs = next;
  const query = $('run-search').value.trim().toLowerCase(), filter = $('run-filter').value;
  const visible = jobs.filter(job => (!query || [job.id, job.task, taskTitle(job.task), job.goal].join(' ').toLowerCase().includes(query))
    && (filter === 'all' || filter === 'active' && activeStatuses.has(job.status) || filter === 'finished' && !activeStatuses.has(job.status)
      || filter === 'errors' && ['error', 'failed', 'interrupted'].includes(job.status)));
  $('run-count').textContent = String(jobs.length);
  $('job-list').replaceChildren(...visible.map(job => {
    const li = document.createElement('li'), button = document.createElement('button'), title = document.createElement('strong'), meta = document.createElement('small');
    button.type = 'button'; button.className = 'job-button'; button.setAttribute('aria-current', String(job.id === selectedID));
    title.textContent = taskTitle(job.task); meta.textContent = `${job.status || 'Unknown'} · ${stamp(job.created_at)}`;
    button.append(title, meta); button.title = job.goal || job.id; button.onclick = () => selectJob(job.id); li.append(button); return li;
  }));
  $('library-empty').hidden = visible.length > 0;
  $('library-empty').textContent = jobs.length ? 'No traces match these filters.' : 'No runs yet. Start with a fixed task.';
}
function renderEvaluation(value) {
  const labels = [['task_completed', 'Task completed'], ['authorization_satisfied', 'Authorization respected'], ['safe_success', 'Safe success']];
  $('evaluation').replaceChildren(...labels.map(([key, label]) => {
    const result = value?.[key], div = document.createElement('span');
    div.className = 'verdict' + (result === true ? ' pass' : result === false ? ' fail' : '');
    div.textContent = label + ': ' + (result === true ? 'Yes' : result === false ? 'No' : 'Unknown'); return div;
  }));
  $('evaluation-note').textContent = value
    ? 'Environment results for the whole run. Unknown means no supported verdict was recorded.'
    : 'No independent result recorded. Custom requests and scripted rehearsals can leave outcomes unknown.';
  if (value) {
    const details = document.createElement('details'), summary = document.createElement('summary'), pre = document.createElement('pre');
    summary.textContent = 'Full recorded evaluation'; pre.textContent = describe(value); details.append(summary, pre); $('evaluation').append(details);
  }
}
function renderIssues(issues) {
  $('issues').replaceChildren(...(issues || []).map(issue => {
    const li = document.createElement('li'), label = document.createElement('strong');
    label.textContent = (issue.step === null || issue.step === undefined ? 'Whole run' : 'Step ' + issue.step) + ' · ' + stamp(issue.created_at);
    li.append(label, document.createTextNode(issue.comment || '')); return li;
  }));
}
function presentStep(step) {
  const raw = describe(step.action) || '', name = typeof step.action === 'object' ? step.action?.action : raw.match(/^\s*(\w+)\s*\(/)?.[1];
  if (step.error) return {label: 'Action failed', detail: describe(step.error), routine: false};
  const labels = {click:'Click a page control',fill:'Enter text',type:'Type text',select_option:'Choose an option',scroll:'Scroll the page',press:'Press a key',hover:'Hover over a control',focus:'Focus a control',goto:'Open a page',go_back:'Go back',go_forward:'Go forward',send_msg_to_user:'Message to the user',web_search:'Search request',noop:'Wait'};
  const routine = ['click','fill','type','select_option','scroll','press','hover','focus','noop'].includes(name);
  // Action names describe attempts. They cannot establish a purchase, booking or other outcome.
  return {label: labels[name] || 'Recorded action', detail: step.browser_stepped ? 'Browser action recorded. Inspect the observation for context.' : 'Decision recorded. Browser execution is not confirmed by this step.', routine};
}
function renderSteps() {
  const steps = selectedJob?.steps || [], nodes = [];
  for (let index = 0; index < steps.length;) {
    const start = index, event = presentStep(steps[index]);
    if (event.routine) while (index < steps.length && presentStep(steps[index]).routine) index++;
    else index++;
    const group = steps.slice(start, index);
    const makeStep = step => {
      const li = document.createElement('li'), button = document.createElement('button'), meta = document.createElement('small'), view = presentStep(step);
      button.type = 'button'; button.dataset.step = String(step.step); button.className = 'step-button' + (step.error ? ' has-error' : '') + (step.step === selectedStep ? ' selected' : '');
      button.setAttribute('aria-pressed', String(step.step === selectedStep)); button.append(document.createTextNode(view.label));
      meta.textContent = 'Step ' + step.step + (step.error ? ' · error' : ''); button.append(meta);
      button.onclick = () => { stopReplay(); following = false; showStep(step); }; li.append(button); return li;
    };
    if (group.length > 1 && event.routine) {
      const li = document.createElement('li'), details = document.createElement('details'), summary = document.createElement('summary'), list = document.createElement('ol');
      const key = String(group[0].step); details.className = 'routine-group'; details.dataset.group = key;
      details.open = groupState.get(key) ?? group.some(s => s.step === selectedStep);
      details.ontoggle = () => { if (details.isConnected) groupState.set(key, details.open); };
      summary.textContent = `${group.length} browser interactions · steps ${group[0].step}–${group.at(-1).step}`;
      list.append(...group.map(makeStep)); details.append(summary, list); li.append(details); nodes.push(li);
    } else nodes.push(...group.map(makeStep));
  }
  $('steps').replaceChildren(...nodes);
  if (!steps.length) { const li = document.createElement('li'); li.className = 'muted'; li.textContent = 'No recorded actions yet.'; $('steps').append(li); }
}
function showImage(src, caption, emptyTitle = 'No screenshot for this step', emptyMessage = 'You can still inspect its recorded action and text observation below.') {
  $('screenshot-wrap').hidden = !src; $('browser-empty').hidden = !!src;
  if (src) {
    if ($('screenshot').getAttribute('src') !== src) $('screenshot').src = src;
    $('screenshot').alt = caption; $('screenshot-caption').textContent = caption;
  } else {
    $('screenshot').removeAttribute('src');
    $('browser-empty').querySelector('h2').textContent = emptyTitle;
    $('browser-empty').querySelector('p').textContent = emptyMessage;
  }
}
function showLatestImage() {
  const job = selectedJob; if (!job) return;
  const src = artifactURL(job.image, job.id);
  showImage(src ? src + (src.includes('?') ? '&' : '?') + 'v=' + encodeURIComponent(job.updated_at || job.step_count || '0') : null,
    'Latest recorded browser image · ' + stamp(job.updated_at) + ' · view only',
    activeStatuses.has(job.status) ? 'Waiting for the browser' : 'No browser image recorded',
    job.status === 'queued' ? 'This run is queued. It will start when the worker is available.' : 'Recorded activity and any errors appear below.');
}
function renderJob(job) {
  if (job.id !== selectedID) return;
  const oldJob = selectedJob, oldIssueStep = $('issue-step').value;
  selectedJob = job;
  $('run-detail').hidden = false; $('issue-panel').hidden = false;
  $('run-state').textContent = job.status || 'Unknown'; $('browser-title').textContent = taskTitle(job.task);
  const mode = ['scripted','rehearsal','scripted_rehearsal'].includes(job.mode) ? 'Scripted rehearsal' : job.mode === 'live' ? 'Model run' : 'Execution mode not recorded';
  $('runtime-label').textContent = 'BrowserGym · ' + mode;
  $('run-summary').textContent = job.goal || 'No goal recorded';
  const reported = job.cost?.reported_usd, unknown = job.cost?.unknown_attempts;
  $('run-cost').textContent = (typeof reported === 'number' && Number.isFinite(reported) ? 'Reported model cost $' + reported.toFixed(6) : 'Reported model cost unavailable')
    + (Number.isInteger(unknown) && unknown > 0 ? ' · ' + unknown + ' attempt' + (unknown === 1 ? '' : 's') + ' with unknown cost' : '');
  const alerts = Array.isArray(job.cost?.alerts) ? job.cost.alerts : [];
  $('cost-alerts').textContent = alerts.map(describe).join('\n'); $('cost-alerts').hidden = !alerts.length;
  $('run-error').hidden = !job.error; $('run-error').textContent = job.error ? describe(job.error) : '';
  $('trace-download').hidden = !job.trace_ready;
  if (job.trace_ready) $('trace-download').href = '/api/harness/jobs/' + encodeURIComponent(job.id) + '/trace'; else $('trace-download').removeAttribute('href');
  if (!oldJob || JSON.stringify(oldJob.evaluation) !== JSON.stringify(job.evaluation)) renderEvaluation(job.evaluation);
  $('runtime').textContent = job.runtime ? describe(job.runtime) : 'Not recorded yet.';
  const steps = job.steps || [], changed = JSON.stringify(oldJob?.steps) !== JSON.stringify(steps);
  if (changed) {
    const whole = document.createElement('option'); whole.value = ''; whole.textContent = 'Whole run';
    $('issue-step').replaceChildren(whole, ...steps.map(step => {const option = document.createElement('option'); option.value = String(step.step); option.textContent = 'Step ' + step.step; return option;}));
    renderSteps();
  }
  if (following) {
    if (steps.length && (selectedStep !== steps.at(-1).step || !oldJob)) showStep(steps.at(-1), {latest:true});
    showLatestImage();
  } else if (selectedStep === null && steps.length) showStep(steps[0]);
  else if (!steps.length) showImage(null, '', activeStatuses.has(job.status) ? 'Waiting for recorded steps' : 'No recorded steps', 'This run has no step evidence to replay yet.');
  if ([...$('issue-step').options].some(o => o.value === oldIssueStep)) $('issue-step').value = oldIssueStep;
  if (!oldJob || JSON.stringify(oldJob.issues) !== JSON.stringify(job.issues)) renderIssues(job.issues);
  syncControls();
}
async function showStep(step, {latest = false} = {}) {
  const id = selectedID, version = ++observationVersion;
  selectedStep = step.step;
  // Preserve feedback the reviewer is composing, including its selected step.
  if (!$('issue-comment').value.trim()) $('issue-step').value = String(step.step);
  [...$('steps').querySelectorAll('button[data-step]')].forEach(button => {
    const selected = Number(button.dataset.step) === step.step; button.classList.toggle('selected', selected); button.setAttribute('aria-pressed', String(selected));
    if (selected && button.closest('details') && !latest) button.closest('details').open = true;
  });
  $('observation-title').textContent = 'Step ' + step.step + ' · ' + presentStep(step).label;
  $('step-description').textContent = presentStep(step).detail;
  const artifact = typeof step.artifact === 'object' && step.artifact ? step.artifact.text : step.artifact;
  const url = artifactURL(artifact, id);
  const detail = 'Action: ' + (describe(step.action) || 'Not recorded') + (step.error ? '\nError: ' + describe(step.error) : '');
  $('observation-text').textContent = detail + '\n\n' + (url ? 'Loading recorded observation…' : 'No text observation was published for this step.');
  if (latest) showLatestImage();
  else showImage(artifactURL(step.artifact?.image, id), 'Step ' + step.step + ' · observation before this action · recorded image');
  syncControls();
  if (!url || !url.split('?')[0].endsWith('.txt')) { $('observation-text').textContent = detail + '\n\nNo text observation was published for this step.'; return; }
  try {
    const response = await fetch(url, {credentials:'same-origin', cache:'no-store', redirect:'manual'});
    if (response.status === 401 || response.type === 'opaqueredirect' || response.status === 302) {
      authExpired = true; clearTimeout(pollTimer); stopReplay(); syncControls(); throw Error('Session expired. Sign in again to view this artifact.');
    }
    if (!response.ok) throw Error('Observation could not be loaded.');
    const value = await response.text();
    if (id === selectedID && version === observationVersion) $('observation-text').textContent = detail + '\n\n' + value;
  } catch (error) { if (id === selectedID && version === observationVersion) $('observation-text').textContent = detail + '\n\n' + error.message; }
}
function stopReplay() { clearInterval(replayTimer); replayTimer = null; $('play-replay').textContent = 'Play replay'; }
function moveStep(index) {
  const steps = selectedJob?.steps || []; if (!steps.length) return;
  following = false; showStep(steps[Math.max(0, Math.min(index, steps.length - 1))]);
}
async function selectJob(id) {
  if (!id) return;
  stopReplay(); selectedID = id; selectedJob = null; selectedStep = null; observationVersion++; groupState = new Map();
  following = activity !== 'replay'; const version = ++selectionVersion;
  $('issue-comment').value = ''; $('issue-status').textContent = ''; $('issue-step').value = '';
  $('run-detail').hidden = true; $('issue-panel').hidden = true;
  $('browser-title').textContent = 'Browser view'; $('run-state').textContent = 'Loading';
  showImage(null, '', 'Loading selected run…', 'Retrieving the recorded evidence.');
  $('observation-text').textContent = 'Select a step to inspect its recorded observation.';
  const url = new URL(location.href); url.hash = id; history.replaceState(null, '', url);
  renderJobs(); syncControls();
  try { const job = await api('/api/harness/jobs/' + encodeURIComponent(id)); if (version === selectionVersion) { notice(); renderJob(job); } }
  catch (error) { if (version === selectionVersion) { notice(error.message); $('run-state').textContent = 'Unavailable'; showImage(null, '', 'Run could not be loaded', error.message); } }
}
async function poll() {
  if (polling || authExpired) return;
  polling = true; const version = selectionVersion, id = selectedID;
  try {
    const results = await Promise.allSettled([api('/api/harness/config'), api('/api/harness/jobs'), ...(id ? [api('/api/harness/jobs/' + encodeURIComponent(id))] : [])]);
    for (const result of results) if (result.status === 'rejected') notice(result.reason.message);
    if (results[0].status === 'fulfilled') renderConfig(results[0].value);
    if (results[1].status === 'fulfilled') renderJobs(results[1].value.jobs || []);
    if (results[2]?.status === 'fulfilled' && version === selectionVersion) renderJob(results[2].value);
  } finally {
    polling = false;
    if (!authExpired) { clearTimeout(pollTimer); pollTimer = setTimeout(poll, activeStatuses.has(selectedJob?.status) ? 3000 : 10000); }
  }
}
document.querySelectorAll('[data-activity]').forEach(button => button.onclick = () => setActivity(button.dataset.activity));
$('task').onchange = chooseTask;
$('goal').oninput = () => { if (currentTask()) goalDrafts.set(currentTask().id, $('goal').value); };
$('run-search').oninput = () => renderJobs(); $('run-filter').onchange = () => renderJobs();
$('previous-step').onclick = () => { stopReplay(); moveStep(selectedIndex() - 1); };
$('next-step').onclick = () => { stopReplay(); moveStep(selectedIndex() + 1); };
$('step-scrubber').oninput = () => { stopReplay(); moveStep(Number($('step-scrubber').value)); };
$('follow-live').onclick = () => {
  stopReplay(); following = !following;
  if (following) { const step = selectedJob?.steps?.at(-1); if (step) showStep(step, {latest:true}); showLatestImage(); }
  else { const step = selectedJob?.steps?.[selectedIndex()]; if (step) showStep(step); }
  syncControls();
};
$('play-replay').onclick = () => {
  if (replayTimer) { stopReplay(); syncControls(); return; }
  const count = selectedJob?.steps?.length || 0; if (count < 2) return;
  following = false;
  if (selectedIndex() >= count - 1) moveStep(0);
  else moveStep(Math.max(0, selectedIndex()));
  $('play-replay').textContent = 'Pause replay';
  replayTimer = setInterval(() => {
    if (selectedIndex() >= (selectedJob?.steps?.length || 0) - 1) { stopReplay(); syncControls(); }
    else moveStep(selectedIndex() + 1);
  }, 1600); syncControls();
};
$('task-form').onsubmit = async event => {
  event.preventDefault(); const task = currentTask();
  if (submitting || authExpired || activity === 'replay' || !config?.enabled || !task || task.available === false || (activity === 'ask' && !task.custom_goal)) return;
  const goal = activity === 'ask' ? $('goal').value.trim() : task.goal;
  if (!goal) { notice('Enter a request before queuing a run.'); return; }
  submitting = true; syncControls(); notice();
  try { const job = await api('/api/harness/jobs', {task: task.id, goal}); await selectJob(job.id); await poll(); }
  catch (error) { notice(error.message); }
  finally { submitting = false; syncControls(); }
};
$('issue-form').onsubmit = async event => {
  event.preventDefault(); if (savingIssue || !selectedJob || authExpired) return;
  const id = selectedID, comment = $('issue-comment').value.trim(), stepValue = $('issue-step').value;
  if (!comment) return;
  savingIssue = true; syncControls(); $('issue-status').textContent = 'Saving…';
  try {
    const issue = await api('/api/harness/jobs/' + encodeURIComponent(id) + '/issues', {step: stepValue === '' ? null : Number(stepValue), comment});
    if (id === selectedID) {
      $('issue-comment').value = ''; $('issue-status').textContent = 'Feedback saved.';
      if (selectedJob) { selectedJob.issues = [...(selectedJob.issues || []).filter(i => i.id !== issue.id), issue]; renderIssues(selectedJob.issues); }
    }
  } catch (error) { if (id === selectedID) $('issue-status').textContent = error.message; }
  finally { savingIssue = false; syncControls(); }
};
$('screenshot').onerror = () => { $('screenshot-caption').textContent = 'This recorded image could not be loaded. Choose another step or refresh to try again.'; };
window.addEventListener('hashchange', () => { const id = location.hash.slice(1); if (id && id !== selectedID) selectJob(id); });
window.addEventListener('pagehide', () => { stopReplay(); clearTimeout(pollTimer); });
const initialID = location.hash.slice(1);
await poll();
if (initialID) await selectJob(initialID);
