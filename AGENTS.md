# Repository guidance

## Test-suite execution

- Run independent suite cases in parallel by default, with separate browser sessions,
  traces and concurrency-safe budget accounting. Use bounded concurrency appropriate
  to local resources. Run sequentially only for an explicit isolation experiment or
  a demonstrated shared-state/resource dependency; explain that exception.

## Model-run authorization and costs

- An explicitly agreed finite episode list is sufficient spending authorization
  for those runs. Do not ask for a separate dollar cap or impose an arbitrary
  per-episode monetary ceiling. Enforce the agreed episode, turn and context
  limits, track actual provider charges, and flag unexpected cost increases.
- Request an explicit spending limit for open-ended or iterative unsupervised
  experimentation. Historical dollar-capped cohorts retain their original rules;
  do not silently rerun cases or expand an approved episode list.

## Context-size reporting

- Report model context sizes and formatting/compression comparisons in tokens,
  naming the tokenizer/model and distinguishing message text from complete requests.
- If only characters or bytes are known, label that measurement explicitly; do not
  present it as token usage or infer token savings from it. API limits and conservative
  byte-based budget bounds may still use their actual units.

## Imported website fidelity

- Import complete upstream sites, including their original navigation, surrounding pages, styling and distractions. Do not remove content because it is unrelated to the selected task, inconvenient to grade, or absent from a partial source cache.
- Prefer packaging dependencies locally and repairing demonstrated incompatibilities while preserving behavior. Omission is only a last resort for an actual application-breaking incompatibility; document it explicitly and consider not using the affected page/site instead of presenting a reduced version as the original.
- Keep task selection, setup and verification separate from the available website. Grade outcomes and relevant side effects; missing verifier coverage is a limitation to report, not a reason to hide controls or pages. Do not claim authorization/safety for effects the verifier cannot establish.
- Existing reduced fixtures remain explicitly labeled historical/development adaptations until replaced and revalidated. See [generalization requirements](docs/agents/generalization-requirements.md).

## Agent coordination

- Use agent-to-agent messages **sparingly and strictly for coordination**: an active ownership conflict, a blocker, a decision needed to proceed, or a handoff that changes the recipient's next action. Faster delivery is not permission to send more messages.
- Do not ping agents with routine progress, test counts, completion announcements, "moving on to X," general findings, or acknowledgments of acknowledgments. Put those in the appropriate document. A completion message is warranted only when it releases an explicit hold or unblocks dependent work.
- Keep notifications to 1–3 short sentences (normally at most 80 words): what you are doing, affected files or resource, and the requested action. Put longer context in a temporary document under `.local/coordination/` and link its exact path. Include enough in the notification to identify the consequence; the recipient decides whether to read the details.
- For necessary coordination with an **active, reachable** agent, prefer `turn/steer`, targeting its current `expectedTurnId`. Steering adds input to active work; do not use `turn/interrupt` to deliver ordinary coordination.
- Use `codex queue` sparingly for idle agents needing action, or a necessary nonurgent message that will remain relevant when consumed. Do not queue time-sensitive holds behind active work and assume they were read. If steering is unavailable, report that delivery limitation instead of pretending queue delivery was immediate.
- Check status before sending. A server's `notLoaded` status does **not** mean an independently running CLI session is idle. Do not resume, duplicate, or restart another agent's session to make it reachable without coordinating the transition.
- Distinguish accepted delivery from read acknowledgment and completed action. Do not resend on an uncertain outcome; inspect delivery evidence first. Recheck relevance and status after a rejected stale-turn request. Never blindly fall back to queuing the same message.
- Give each coordination request a stable ID; record owner, scope, relevant commit, and open/resolved/superseded status in its handoff document. Remove obsolete pending messages when possible. A delayed message is not a fresh instruction: check whether its request is still open.
- Work on independent tasks while awaiting an answer. Pause only dependent work. If another agent's hold blocks you, contact its owner; this is standard procedure and need not be appended to every ping. Explicitly release holds when they end.
- Prefer stable agent names mapped to exact thread IDs. Use a single coordinated publisher for overlapping releases. Never claim another agent's acknowledgment or steering capability without evidence.
- Use `python3 scripts/agent_coordination.py status` and its `steer` command as described in the [coordination runbook](docs/agents/coordination.md). Active-turn delivery was verified on a shared-server UX session; independently running CLI sessions are not thereby made reachable. Check each recipient.

## Documentation audiences

- Keep the root `README.md` concise and approachable for human group members. Explain the project's purpose, agent loop, integration roles and code layout in plain language.
- Put new documents intended mainly for coding agents in `docs/agents/`: technical handoffs, implementation notes, detailed setup/runbooks, audits and development-status writeups. Use descriptive filenames and link from `docs/agents/README.md` when useful.
- Do not move or rename existing documentation during the current concurrent work. Continue updating existing documents at their current paths when that is the task; do not create competing copies. A later migration needs explicit coordination and link updates.
- Human-oriented explanations may live in `docs/` and be linked from the root README. Keep command-heavy operational detail out of the introductory README; link to the relevant guide instead.
- Distinguish implemented local capabilities from deployed capabilities, scripted validation from model results, and adapted fixtures from full upstream benchmarks. Describe training preparation as preparation until supported by actual training evidence.
- `docs/agents/legacy-readme.md` preserves the previous root README as a historical reference. Do not treat its older status notes as current instructions or keep it synchronized with the new introduction.

## Human-readable report presentation

- When sharing a report over HTTP, render Markdown into proper HTML, including tables, headings, lists, links and code blocks. Do not wrap the whole Markdown document in `<pre>` or serve raw Markdown as the human-facing report. Keep the source Markdown or raw JSON available separately when useful.
- Use a Markdown renderer with table support and readable styling; wide tables should scroll on narrow screens. Preserve literal formatting inside actual code blocks. Treat raw HTML in report inputs as untrusted rather than executing it by default.
- Verify presentation as well as HTTP availability before sharing: a 200 response alone is insufficient. Check that tables become real table elements and Markdown syntax is rendered; inspect the browser when layout is uncertain.
- Apply this to new reports and existing reports when actively updating or sharing them. Fix presentation without rewriting historical trace/evaluation evidence; a display fix does not require rerunning experiments.
