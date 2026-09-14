const $ = id => document.getElementById(id);
let config, world, area = 'shop', job = null, version = '', polling = false;
const titles = {shop: 'Campus Supply', booking: 'A room to focus', preferences: 'Your preferences'};
const paragraph = text => Object.assign(document.createElement('p'), {textContent: text});
const item = text => Object.assign(document.createElement('li'), {textContent: text});

function notice(text) { $('notice').textContent = text; }
async function api(path, data) {
  const response = await fetch(path, data ? {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data)
  } : {});
  const result = await response.json();
  if (!response.ok) throw Error(result.error || 'Demo unavailable');
  return result;
}
function busy(value) {
  for (const id of ['run', 'reset', 'goal', 'mode']) $(id).disabled = value;
  document.querySelectorAll('.example').forEach(button => button.disabled = value);
}
function modeNote() {
  $('mode-note').textContent = $('mode').value === 'live'
    ? 'Uses the configured model. Each browser action is saved in its activity record.'
    : 'Scripted rehearsal follows this exact example; it is not an LLM run.';
}
async function reset() {
  busy(true);
  try {
    world = (await api('/api/new', {})).world;
    $('site').src = '/world/' + world + '/' + area;
    $('site').hidden = false;
    $('screen').hidden = true;
    $('watching').textContent = 'Explore the page';
    $('outcome').hidden = true;
    $('status').textContent = 'Ready';
    $('steps').replaceChildren(item('Choose a task and I’ll get started.'));
    $('cost').textContent = '';
    $('trace').removeAttribute('href');
    notice('');
    job = null;
    version = '';
  } finally { busy(false); }
}
async function choose(next) {
  area = next;
  $('workspace-title').textContent = titles[area];
  $('address').textContent = 'campus.local / ' + area;
  $('goal').value = config.examples[area].goal;
  document.querySelectorAll('.example').forEach(button =>
    button.classList.toggle('active', button.dataset.area === area));
  await reset();
}
$('run').onclick = async () => {
  try {
    busy(true);
    notice('');
    $('outcome').hidden = true;
    $('status').textContent = 'Starting';
    const result = await api('/api/run', {world, area, goal: $('goal').value, mode: $('mode').value});
    job = result.job;
    $('steps').replaceChildren(item('Opening the page…'));
    $('watching').textContent = 'Watching the agent';
    poll();
  } catch (error) { notice(error.message); busy(false); }
};
$('reset').onclick = () => reset().catch(error => notice(error.message));
$('mode').onchange = modeNote;
document.querySelectorAll('.example').forEach(button =>
  button.onclick = () => choose(button.dataset.area).catch(error => notice(error.message)));

async function poll() {
  if (!job || polling) return;
  polling = true;
  const currentJob = job;
  try {
    const state = await api('/api/jobs/' + currentJob);
    if (job !== currentJob) return;
    $('status').textContent = state.status === 'running' ? 'Working' : state.error ? 'Stopped' : 'Finished';
    if (state.image && version !== state.image) {
      version = state.image;
      $('screen').src = state.image;
      $('screen').hidden = false;
      $('site').hidden = true;
    }
    if (state.activity.length) $('steps').replaceChildren(...state.activity.map(item));
    if (state.trace_url) $('trace').href = state.trace_url;
    if (state.cost !== null) $('cost').textContent = 'Model spend $' + Number(state.cost).toFixed(4);
    if (state.status !== 'running') {
      busy(false);
      $('watching').textContent = (state.mode === 'live' ? 'Live agent' : 'Scripted rehearsal')
        + (state.error ? ' · stopped' : ' · finished');
      if (state.error) notice('The agent stopped before finishing. The page may already have changed; open the activity record for details.');
      if (state.result) {
        $('outcome').hidden = false;
        $('outcome').replaceChildren(paragraph(state.result.title),
          ...state.result.lines.map(text => paragraph('✓ ' + text)));
      }
      job = null;
    }
    if (state.alerts.length) notice(state.alerts.join(' '));
  } catch (error) { notice(error.message); }
  finally { polling = false; }
}
$('screen').onerror = () => { version = ''; };
busy(true);
api('/api/config').then(async result => {
  config = result;
  $('mode').querySelector('[value=live]').disabled = !config.live_available;
  if (config.live_available) $('mode').value = 'live';
  modeNote();
  await choose('shop');
}).catch(error => notice(error.message));
setInterval(poll, 900);
