# Agent-facing documentation

Put new technical handoffs, implementation notes, detailed setup/runbooks,
audits and development-status writeups here. Write for the next coding agent:
state the scope, relevant files, verified evidence and remaining work.

For the human overview, start with the [project README](../../README.md).
The [repository guidance](../../AGENTS.md) describes the documentation policy.

## Existing references

- [Complete hosted sites](full-site-restoration.md): full-source restoration, shared native/client versions, known upstream gaps and validation.

- [Generalization requirements](generalization-requirements.md): interface fidelity, site holdouts, messy observations and eventual real-site transfer.
- [Manual environment hosting](manual-environment-hosting.md): owner-scoped native browser controls, package boundaries and trace semantics.
- [Manual session recovery](manual-session-recovery.md): closed screenshots, status refresh, other-session controls and health route boundaries.
- [Client-rendered inspection feasibility](client-rendered-environment-feasibility.md): ordinary browser probes, per-site effort and hosting options; not a deployed capability.
- [Portable control service](../../deploy/control/README.md): SQLite, private tunnel, Blob migration and single-writer cutover.
- [Completed control-storage cutover](control-storage-cutover.md): exact migration evidence, production checks and current restart limitations.
- [Agent coordination](coordination.md): sparse notifications, delivery semantics, and current steering test status.
- [Observation text limits](observation-text-limit.md): optional larger AX prefixes, metadata, and WorkArena saved-evidence checks.
- [Previous technical README](legacy-readme.md): a historical copy retained when the root README was rewritten for the group. Its older status notes are not current instructions.
- [Team harness](../../TEAM_HARNESS.md) and [hosted worker extension](../../HOSTED_WORKER.md).
- [Vercel setup](../../deploy/VERCEL_SETUP.md) and [worker setup](../../deploy/worker/README.md).
- [Local installation and MiniWoB setup](../../LAPTOP_SETUP.md).
- [Hosted archive/error-boundary acceptance follow-up](hosted-acceptance-followup.md).
- [Daylight action-response format correction](daylight-action-format.md).
- [Dataset curation](../../data/curation/README.md). Training preparation currently lives in the uncommitted local `training/` directory; add a link after it is published.

Existing documents remain at their original paths while other agents are
working. Update them there when needed; do not move them or create parallel
maintained copies as part of this transition.
