// Presentation only: these entries never become model conversation messages.
const labels = {running:'Running',saving:'Saving record',applied:'Applied',failed:'Failed',unrecorded:'Record not saved'};
const element = (tag, className, text) => {
  const el = document.createElement(tag); el.className = className;
  if (text !== undefined) el.textContent = text;
  return el;
};
export function createToolActivity(action, captured, step) {
  // Resolve the target against this exact pre-action snapshot, never the latest DOM.
  const control = captured.observation.controls.find(item => item.id === action.id);
  const target = control?.label || (action.id ? 'Control ' + action.id : 'Page');
  const verb = {click:'Click',select:'Select',check:action.value ? 'Check' : 'Uncheck',fill:'Fill'}[action.action] || action.action;
  const value = action.action === 'select' || action.action === 'fill' ? String(action.value ?? '') : null;
  const title = verb + ' · ' + target + (value === null ? '' : ' → ' + value);
  const root = element('details', 'tool-activity'); root.dataset.step = String(step);
  const summary = element('summary', 'tool-activity-summary');
  const icon = element('span', 'tool-activity-icon', '↗'); icon.setAttribute('aria-hidden', 'true');
  const heading = element('span', 'tool-activity-heading');
  heading.append(element('span', 'tool-activity-label', 'Browser tool · Step ' + step), element('span', 'tool-activity-title', title));
  const status = element('span', 'tool-activity-status');
  summary.append(icon, heading, status);
  const body = element('div', 'tool-activity-details');
  body.append(element('p', 'tool-activity-context', 'Page before action: ' + (captured.observation.title || 'Title not recorded')),
    element('pre', 'tool-activity-action', JSON.stringify(action, null, 2)));
  const note = element('p', 'tool-activity-note'); body.append(note); root.append(summary, body);
  function update(state, error = '') {
    root.dataset.state = state; status.textContent = labels[state];
    note.textContent = error || (state === 'applied' ? 'The browser applied this action and saved its record. Task grading is separate.'
      : state === 'saving' ? 'The browser returned from the action. Saving its record…' : 'Using the target from this step’s recorded observation.');
    summary.title = title + ' · ' + labels[state];
  }
  update('running');
  return {element:root, update};
}
export function keepChatPosition(log, change) {
  const follow = log.scrollHeight - log.scrollTop - log.clientHeight < 64;
  const top = log.scrollTop; change();
  log.scrollTop = follow ? log.scrollHeight : top;
}
export function showChatWorking(log, text) {
  keepChatPosition(log, () => {
    let status = log.querySelector('.chat-working');
    if (!text) { status?.remove(); return; }
    if (!status) { status = element('div', 'chat-working'); log.append(status); }
    status.textContent = text;
  });
}
