# Sparse agent coordination

The communication rules in [AGENTS.md](../../AGENTS.md) apply to both queue and steering. This mechanism is for ownership, blockers, decisions, and dependent handoffs, not status reporting.

Example:

> Curation → backend [WA-W01-HOLD]: Running WA-W01; hold edits to `intent_browser/` until this probe finishes. Details: `.local/coordination/workarena.md`.

The owner records resolution in that document and sends one release if someone is waiting on the hold. Do not attach a long evidence report to the notification. Do not send a reply merely to acknowledge a reply.

## Transport status — 2026-09-15

Installed Codex is 0.154.0. Its generated protocol exposes `turn/steer` with an `expectedTurnId`, along with queue and thread-status methods. Official semantics: <https://learn.chatgpt.com/docs/app-server#steer-an-active-turn>.

The existing five CLI conversations were launched independently. Initially no shared daemon was running (the old socket refused connections). Starting the local daemon made saved conversations listable, but all five appeared as `notLoaded` with `canAcceptDirectInput: null`, including the actively executing backend/root conversation. A steering probe to that root conversation was rejected with `thread not found`. No thread was resumed or duplicated, and no model call was started by this probe.

This initial result is a **negative reachability test**. Evidence: `.local/coordination/steering-check/report.json`. It remains valid for the independently running sessions, not for the subsequently connected UX session described below.

The local daemon uses WebSocket JSON-RPC over its Unix socket, not newline JSON-RPC. The tested client handshake uses `ws://localhost/rpc` over `/home/bjorn/.codex/app-server-control/app-server-control.sock`, with WebSocket compression disabled. `codex app-server proxy` forwards raw socket bytes; it does not translate newline JSON into WebSocket frames.

### Positive result and permissions

After Bjorn closed the old UX CLI, the existing UX thread was loaded into the shared server. A bounded test started turn `01a0a5f6-5da0-7260-acd2-6e4c6007d2a5`; the server accepted a unique steering marker against that active turn; the agent wrote the exact marker acknowledgment and completed the same turn normally. No `turn/interrupt` was sent. Evidence: `.local/coordination/steering-check/live-58edefa3/report.json` and its `ack.json`. This used Codex inference for the explicitly requested test, not project OpenRouter/Parallel funding or a browser task.

Codex 0.154.0 rejects **explicit permission overrides** such as `--yolo` on the remote-resume command. Removing that flag alone did not initially preserve full access: the first resume returned `approvalPolicy: never` with a workspace sandbox. Per Bjorn's request to retain YOLO, the supported `thread/settings/update` API selected `approvalPolicy: never` and `sandboxPolicy: {type: dangerFullAccess}` for this idle UX thread before its test began. A fresh resume after the completed test returned the same full-access settings. Evidence: `ux-resume-permissions.json`, `ux-yolo-permissions.json`, and `ux-post-test-resume-permissions.json` under the same steering-check directory. This changed one session, not global defaults or other agents.

When reconnecting other threads, inspect effective permissions rather than assuming their CLI flags or old settings carry across. Configure only permissions already authorized by the user. Do not automatically apply YOLO to other sessions.

## Connecting an existing session for a controlled test

Coordinate closing only an idle agent's existing CLI before reopening the same thread against the shared server. Do not do this during browser actions, inference, or cleanup. Do not create a second writer for a running conversation.

```bash
codex app-server daemon start
codex resume --remote unix:///home/bjorn/.codex/app-server-control/app-server-control.sock THREAD_ID
```

The daemon is local and uses the existing Codex installation. These commands do not configure an OpenRouter key or use the project model budgets. Starting agent work still uses its configured Codex model/account.

Do not append `--yolo` to the remote-resume command in this CLI version. The UX thread now has the requested permissions stored server-side. Other threads need their effective permissions checked after a coordinated transition.

### Everyday session commands

Ensure the local daemon is running (starting an already running daemon is harmless):

```bash
codex app-server daemon start
```

For a **new** session, permission flags are supported at creation. To use the user's requested YOLO settings in this repository:

```bash
codex --remote unix:///home/bjorn/.codex/app-server-control/app-server-control.sock --yolo --cd /home/bjorn/code/LLM_proj_uu
```

For an **existing** session, finish active work and close its independent CLI first, then run the `codex resume --remote ... THREAD_ID` command above without permission override flags. This retains its conversation; it is not a new task. Check `/permissions` after connecting because legacy session migration did not reliably restore the original sandbox during the first UX test. Use the server-side permission setting only as authorized by the user. The new-session versus resume flag distinction was checked against Codex 0.154.0's TUI startup and thread-parameter source.

Keep the CLI connected while expecting active-turn steering. No PC reboot is needed. After a daemon stop or workstation restart, start the daemon again and reconnect the relevant sessions. Recheck status; `notLoaded` is not evidence that an independent agent has stopped working.

## Sending a necessary coordination message

Use workstation `python3`, which already has `websockets`; this helper is separate from the project inference runtime.

```bash
python3 scripts/agent_coordination.py status
python3 scripts/agent_coordination.py status --thread THREAD_ID
python3 scripts/agent_coordination.py steer --thread THREAD_ID --message 'Sender → recipient [REQUEST-ID]: concise coordination request; details at .local/coordination/request.md.'
```

The helper requires a reachable active thread, reads its current turn, and sends one request with `expectedTurnId` and a unique message ID. It refuses idle/not-loaded targets, unavailable active-turn metadata, empty/long messages, or a changed explicitly supplied `--expected-turn`. It does not start a daemon, resume threads, retry, or queue on failure. A transport timeout is an unknown delivery outcome: inspect evidence before resending.

For a necessary durable message to an idle agent, existing `codex queue --thread THREAD_ID --message '…'` remains available. An unreachable independent agent may receive the one-time nonurgent policy-read request through that queue; this does not establish live steering reception.

## Positive-test acceptance

1. Read the connected thread's status and verify it accepts direct input.
2. Have that agent undertake a bounded coordination-only test. No project edits, paid project inference, purchases, or deployments.
3. While its turn is active, submit a uniquely identified short message using `turn/steer` with the observed active turn ID.
4. Retain the acceptance response and recipient evidence that the marker was consumed in that same turn before it completed. Acceptance alone is insufficient.
5. Test a stale turn ID rejection without automatic queue fallback. Distinguish active, idle, and not loaded.
6. Once working, ask the four recent agents to read the new rules and provide one short capability acknowledgment. An agent unable to steer must say so; a policy acknowledgment is not a capability test.

The test must not cancel the recipient's work via `turn/interrupt`. Tools already executing are not guaranteed to stop merely because steering input was accepted.

## Recent agent directory

| Role | Thread |
| --- | --- |
| Backend/root | `01a0a0db-781f-7c90-8575-a5fbabe133dd` |
| Curation/WorkArena | `01a0a12d-4cf0-7380-8135-c5a9936025af` |
| UX | `01a0a4f9-b9e9-77f0-9aec-23a448aac843` |
| Training | `01a0a180-8830-7b01-a062-7c2739fee73d` |
| Documentation | `01a0a51d-e8c8-72f1-92f5-05e265ffc533` |

These identities were checked through the local server's repository-filtered thread list. They are not a live status board. Recheck reachability before acting.
