const $ = id => document.getElementById(id);
const activeStatuses = new Set(['queued', 'running', 'starting', 'claimed']);
let config = null, selectedID = '', selectedJob = null, selectedStep = null;
let selectionVersion = 0, observationVersion = 0, pollTimer, polling = false;
let submitting = false, savingIssue = false, authExpired = false;
const stamp = value => { const d = new Date(value); return value && !Number.isNaN(d.valueOf()) ? d.toLocaleString() : 'Time unavailable'; };
const describe = value => typeof value === 'string' ? value : JSON.stringify(value, null, 2);
function notice(message = '') { $('notice').textContent = message; $('notice').hidden = !message; }
async function api(path, data) {
  const response = await fetch(path, {credentials: 'same-origin', cache: 'no-store', redirect: 'manual', ...(data === undefined ? {} : {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data)
  })});
  if (response.status === 401 || response.type === 'opaqueredirect' || response.status === 302) {
    authExpired = true; clearTimeout(pollTimer); syncControls();
    throw Error('Your session has expired. Sign in again using the page demo link above.');
  }
  const value = await response.json().catch(() => null);
  if (!response.ok || !value) throw Error(value?.error || 'The server could not complete this request.');
  return value;
}
function artifactURL(value, id) {
  if (typeof value !== 'string' || !value) return null;
  const prefix = '/api/harness/jobs/' + encodeURIComponent(id) + '/artifacts/';
  if (value.startsWith(prefix)) {
    // Only this job's selected artifacts, never arbitrary URLs from stored output.
    const tail = value.slice(prefix.length).split('?')[0];
    if (!/^[a-zA-Z0-9_.-]+$/.test(tail) || tail === '.' || tail === '..') return null;
    return value;
  }
  if (/^[a-zA-Z0-9_.-]+$/.test(value) && value !== '.' && value !== '..') return prefix + encodeURIComponent(value);
  return null;
}
function syncControls() {
  const selectedTask = config?.tasks?.find(t => t.id === $('task').value);
  $('submit-run').disabled = submitting || authExpired || !config?.enabled || !selectedTask || selectedTask.available === false;
  $('task').disabled = submitting || authExpired || !config?.tasks?.length;
  $('goal').disabled = submitting || authExpired || !config?.tasks?.length;
  $('submit-issue').disabled = savingIssue || authExpired || !selectedID;
}
function chooseTask() {
  const task = config?.tasks?.find(t => t.id === $('task').value);
  $('goal').value = task?.goal || '';
  $('goal').readOnly = !task?.custom_goal || config?.worker?.mode === 'rehearsal';
  $('goal-note').textContent = task?.available === false
    ? 'This task is unavailable until the worker advertises support for it.'
    : config?.worker?.mode === 'rehearsal'
    ? 'Scripted rehearsal: this fixed request exercises the browser harness without a model call.'
    : task?.custom_goal
    ? 'Use this fictional environment to try your own request. Automatic verification may be unavailable for custom goals.'
    : 'This task uses a fixed request so its independent verifier can check the result.';
  syncControls();
}
function renderConfig(next) {
  const previous = config;
  config = next;
  const worker = next.worker || {};
  $('worker-status').classList.toggle('offline', !worker.online);
  $('worker-status').textContent = !next.enabled ? 'Harness access is not enabled for this deployment yet.' : worker.online
    ? 'Worker online · ' + (worker.updated_at ? 'last seen ' + stamp(worker.updated_at) : 'ready for queued runs')
    : 'Worker offline. Queued requests will wait until the PC worker reconnects.';
  // Preserve a request the reviewer is currently composing.
  if (JSON.stringify(previous?.tasks) !== JSON.stringify(next.tasks) || previous?.worker?.mode !== next.worker?.mode) {
    const currentTask = $('task').value, currentGoal = $('goal').value;
    $('task').replaceChildren(...(next.tasks || []).map(task => {
      const option = document.createElement('option'); option.value = task.id; option.textContent = (task.title || task.id) + (task.available === false ? ' · unavailable' : ''); option.disabled = task.available === false; return option;
    }));
    if ((next.tasks || []).some(task => task.id === currentTask && task.available !== false)) {
      $('task').value = currentTask; chooseTask();
      if (previous && !$('goal').readOnly) $('goal').value = currentGoal;
    } else { const available = (next.tasks || []).find(task => task.available !== false); if (available) $('task').value = available.id; chooseTask(); }
  }
  syncControls();
}
function renderJobs(jobs) {
  const options = jobs.map(job => {
    const option = document.createElement('option'); option.value = job.id;
    option.textContent = `${stamp(job.created_at)} · ${job.task} · ${job.status}`;
    return option;
  });
  if (!options.length) { const option = document.createElement('option'); option.value = ''; option.textContent = 'No runs yet'; options.push(option); }
  if (selectedID && !jobs.some(j => j.id === selectedID)) {
    const option = document.createElement('option'); option.value = selectedID; option.textContent = 'Selected run · ' + selectedID; options.unshift(option);
  }
  $('job-select').replaceChildren(...options);
  if (selectedID) $('job-select').value = selectedID;
  else if (jobs.length) selectJob(jobs[0].id);
}
function renderEvaluation(value) {
  const labels = [['task_completed', 'Task completed'], ['authorization_satisfied', 'Authorization respected'], ['safe_success', 'Safe success']];
  const nodes = labels.map(([key, label]) => {
    const result = value?.[key];
    const div = document.createElement('span');
    div.className = 'verdict' + (result === true ? ' pass' : result === false ? ' fail' : '');
    div.textContent = label + ': ' + (result === true ? 'Yes' : result === false ? 'No' : 'Unknown');
    return div;
  });
  $('evaluation').replaceChildren(...nodes);
  $('evaluation-note').textContent = value
    ? 'Independent environment results. Unknown means no supported verdict was recorded; it is not a pass or a failure.'
    : 'No independent evaluation is available yet. Custom requests and scripted rehearsals may leave results unknown.';
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
function renderJob(job) {
  if (job.id !== selectedID) return;
  selectedJob = job;
  $('run-detail').hidden = false; $('issue-panel').hidden = false;
  $('run-state').textContent = job.status || 'Unknown'; $('browser-title').textContent = job.task || 'Remote browser';
  const mode = job.mode === 'scripted' || job.mode === 'rehearsal' || job.mode === 'scripted_rehearsal' ? 'Scripted rehearsal' : job.mode === 'live' ? 'Live model run' : job.mode ? 'Mode: ' + job.mode : 'Execution mode not recorded';
  $('run-summary').textContent = `${mode} · ${job.step_count ?? job.steps?.length ?? 0} recorded steps · ${job.goal || 'No goal recorded'}`;
  const reported = job.cost?.reported_usd, unknown = job.cost?.unknown_attempts;
  $('run-cost').textContent = (typeof reported === 'number' && Number.isFinite(reported)
    ? 'Reported model cost $' + reported.toFixed(6) : 'Reported model cost unavailable')
    + (Number.isInteger(unknown) && unknown > 0 ? ' · ' + unknown + ' attempt' + (unknown === 1 ? '' : 's') + ' with unknown cost' : '');
  const costAlerts = Array.isArray(job.cost?.alerts) ? job.cost.alerts : [];
  $('cost-alerts').textContent = costAlerts.map(describe).join('\n'); $('cost-alerts').hidden = !costAlerts.length;
  $('run-error').hidden = !job.error; $('run-error').textContent = job.error ? describe(job.error) : '';
  const src = artifactURL(job.image, job.id);
  $('screenshot-wrap').hidden = !src; $('browser-empty').hidden = !!src;
  if (src) {
    // Use the revision as a cache key only if the API has not already provided one.
    const versioned = src + (src.includes('?') ? '&' : '?') + 'v=' + encodeURIComponent(job.updated_at || job.step_count || '0');
    if ($('screenshot').getAttribute('src') !== versioned) $('screenshot').src = versioned;
    $('screenshot-caption').textContent = 'Latest recorded browser image · ' + stamp(job.updated_at) + ' · view only';
  } else {
    const title = $('browser-empty').querySelector('h1'), message = $('browser-empty').querySelector('p');
    title.textContent = activeStatuses.has(job.status) ? 'Waiting for the browser image' : 'No browser image was recorded';
    message.textContent = job.status === 'queued' ? 'This request is queued. The worker will run it when available.' : 'Activity and errors appear below as the worker publishes them.';
  }
  $('trace-download').hidden = !job.trace_ready;
  if (job.trace_ready) $('trace-download').href = '/api/harness/jobs/' + encodeURIComponent(job.id) + '/trace';
  else $('trace-download').removeAttribute('href');
  renderEvaluation(job.evaluation);
  $('runtime').textContent = job.runtime ? describe(job.runtime) : 'Not recorded yet.';
  const steps = job.steps || [], oldIssueStep = $('issue-step').value;
  const whole = document.createElement('option'); whole.value = ''; whole.textContent = 'Whole run';
  $('issue-step').replaceChildren(whole, ...steps.map(step => {const option = document.createElement('option'); option.value = String(step.step); option.textContent = 'Step ' + step.step; return option;}));
  if ([...$('issue-step').options].some(o => o.value === oldIssueStep)) $('issue-step').value = oldIssueStep;
  $('steps').replaceChildren(...steps.map(step => {
    const li = document.createElement('li'), button = document.createElement('button'); button.type = 'button';
    button.className = 'step-button' + (step.error ? ' has-error' : '') + (step.step === selectedStep ? ' selected' : '');
    button.textContent = 'Step ' + step.step + ' · ' + (describe(step.action) || 'No action recorded') + (step.error ? '\nError: ' + describe(step.error) : '');
    button.setAttribute('aria-pressed', String(step.step === selectedStep)); button.onclick = () => showStep(step);
    li.append(button); return li;
  }));
  if (selectedStep === null && steps.length) showStep(steps[steps.length - 1]);
  renderIssues(job.issues); syncControls();
}
async function showStep(step) {
  const id = selectedID, version = ++observationVersion;
  selectedStep = step.step; $('issue-step').value = String(step.step);
  [...$('steps').querySelectorAll('button')].forEach((button, index) => {
    const selected = selectedJob.steps[index].step === step.step; button.classList.toggle('selected', selected); button.setAttribute('aria-pressed', String(selected));
  });
  $('observation-title').textContent = 'Step ' + step.step + ' · recorded observation';
  const artifact = typeof step.artifact === 'object' && step.artifact ? step.artifact.text : step.artifact;
  const url = artifactURL(artifact, id);
  const detail = 'Action: ' + (describe(step.action) || 'Not recorded') + (step.error ? '\nError: ' + describe(step.error) : '');
  $('observation-text').textContent = detail + '\n\n' + (url ? 'Loading recorded observation…' : 'No text observation was published for this step.');
  if (!url || !url.split('?')[0].endsWith('.txt')) { $('observation-text').textContent = detail + '\n\nNo text observation was published for this step.'; return; }
  try {
    const response = await fetch(url, {credentials:'same-origin', cache:'no-store', redirect:'manual'});
    if (response.status === 401 || response.type === 'opaqueredirect') throw Error('Session expired. Sign in again to view this artifact.');
    if (!response.ok) throw Error('Observation could not be loaded.');
    const value = await response.text();
    if (id === selectedID && version === observationVersion) $('observation-text').textContent = detail + '\n\n' + value;
  } catch (error) { if (id === selectedID && version === observationVersion) $('observation-text').textContent = detail + '\n\n' + error.message; }
}
async function selectJob(id) {
  if (!id) return;
  selectedID = id; selectedJob = null; selectedStep = null; observationVersion++;
  const version = ++selectionVersion;
  $('issue-comment').value = ''; $('issue-status').textContent = ''; $('issue-step').value = '';
  $('run-detail').hidden = true; $('issue-panel').hidden = true; $('screenshot-wrap').hidden = true;
  $('browser-empty').hidden = false; $('browser-empty').querySelector('h1').textContent = 'Loading selected run…';
  $('observation-text').textContent = 'Select a step to inspect its recorded observation.';
  $('job-select').value = id;
  const url = new URL(location.href); url.hash = id; history.replaceState(null, '', url);
  try { const job = await api('/api/harness/jobs/' + encodeURIComponent(id)); if (version === selectionVersion) renderJob(job); }
  catch (error) { if (version === selectionVersion) notice(error.message); }
}
async function poll() {
  if (polling || authExpired) return;
  polling = true;
  const version = selectionVersion, id = selectedID;
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
$('task').onchange = chooseTask;
$('job-select').onchange = () => selectJob($('job-select').value);
$('task-form').onsubmit = async event => {
  event.preventDefault(); if (submitting || authExpired || !config?.enabled || config.tasks?.find(t => t.id === $('task').value)?.available === false) return;
  const goal = $('goal').value.trim(); if (!goal) { notice('Enter a request before queuing a run.'); return; }
  submitting = true; syncControls(); notice();
  try { const job = await api('/api/harness/jobs', {task: $('task').value, goal}); await selectJob(job.id); await poll(); }
  catch (error) { notice(error.message); }
  finally { submitting = false; syncControls(); }
};
$('issue-form').onsubmit = async event => {
  event.preventDefault(); if (savingIssue || !selectedID || authExpired) return;
  const id = selectedID, comment = $('issue-comment').value.trim(), stepValue = $('issue-step').value;
  if (!comment) return;
  savingIssue = true; syncControls(); $('issue-status').textContent = 'Saving…';
  try {
    const issue = await api('/api/harness/jobs/' + encodeURIComponent(id) + '/issues', {step: stepValue === '' ? null : Number(stepValue), comment});
    if (id === selectedID) {
      $('issue-comment').value = ''; $('issue-status').textContent = 'Issue saved.';
      if (selectedJob) { selectedJob.issues = [...(selectedJob.issues || []).filter(i => i.id !== issue.id), issue]; renderIssues(selectedJob.issues); }
    }
  } catch (error) { if (id === selectedID) $('issue-status').textContent = error.message; }
  finally { savingIssue = false; syncControls(); }
};
$('screenshot').onerror = () => { $('screenshot-caption').textContent = 'The browser image could not be loaded. It will refresh with the next worker update.'; };
window.addEventListener('hashchange', () => { const id = location.hash.slice(1); if (id && id !== selectedID) selectJob(id); });
selectedID = location.hash.slice(1);
await poll();
