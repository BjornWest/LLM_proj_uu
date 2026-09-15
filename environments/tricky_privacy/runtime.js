// DERIVED contract: committed state is external-journal-backed, drafts are local.
const clone = value => JSON.parse(JSON.stringify(value));
window.__privacyState = await window.__privacyReady;
await window.__intentEmit('hydrate', {state: window.__privacyState});
window.__privacySave = async draft => {
  const before = clone(window.__privacyState);
  const after = {...before, privacy: clone(draft)};
  await window.__intentEmit('privacy_commit', {before, after, draft});
  window.__privacyState = after;
};
window.__privacyCancel = async appointmentId => {
  const before = clone(window.__privacyState);
  const after = {...before, appointments: before.appointments.filter(a => a.id !== appointmentId)};
  await window.__intentEmit('cancel', {before, after, appointmentId});
  window.__privacyState = after;
};
