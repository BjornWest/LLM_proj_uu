# Korp laptop demo: issues found on 2026-10-22

Handoff from the laptop (WSL2 Ubuntu 22.04, native Windows Chrome for Testing 156 via
`--windows-browser`, `--demo-mode`) after the presentation. Code state: branch
`claude/korp-flock-20261022` at `907c648`. Nothing in this document has been fixed; it
records causes, evidence and suggested fixes for the PC to pick up.

Run IDs refer to laptop-only trace directories `.local/raven-runs/<run>/attempt-N/`
(git-ignored, not transferred). Models used: Claude Sonnet 5.5 (`claude-sonnet` preset),
GPT-6.1 Sol (`sol`), Qwen 27B + SFT on Modal (`qwen-sft-modal`).

## Summary

| # | Symptom | Cause | Status |
|---|---|---|---|
| 1 | Question in a second window answered only "Sorry — I couldn't finish that" | One `user_window` task at a time; demo mode replaces the 400 reason | Confirmed, reproduced |
| 2 | Claude replies in German/Spanish/Arabic/Vietnamese to English questions | Language sentence appended to every user goal | Confirmed by replay ablation |
| 3 | Closing the Korp Chrome window "crashes the app" | Backend survives but never relaunches the browser | Confirmed, reproduced |
| 4 | Restart right after closing the window sometimes fails once | Startup races the previous Chrome shutdown (likely) | Observed once |
| 5 | Flock: helpers restart from scratch, findings lost on cancel | Demo retry applies to helpers; helper reports live only in the main run | Confirmed from traces |
| 6 | Episodes die with `ObservationChanged: Document/custody changed during preview` | Exception from the dynamic preview is not handled | Location confirmed; trigger likely a post-navigation reload in one case, unknown in the other |
| 7 | Page reads take 5-70 s on frame-heavy pages; flock is slow | Every CDP round trip crosses the PowerShell stdin/stdout relay (inferred) | Latency measured; relay cause inferred |
| 8 | Smaller laptop/setup issues | See section 8 | Confirmed |

## 1. A second window's task is refused, and demo mode hides why

User report: in a new window, "what is the cheapest price to fly to mars tomorrow?" was
answered only with "Sorry — I couldn't finish that. Could you try again or rephrase?".

- No run directory exists for it: the task was refused at submission. The service log
  has `HTTP 400 /api/tasks: The shared window already has an active task` at 14:00:50.
  At that time the flock run `e6d6eb0d` (mode `flock`, mapped to `user_window`) was
  active. The same 400 happened at 13:39:49 while a test run of mine held the shared window.
- Source: `apps/raven/backend.py:494-498` (`_submit`) allows one non-helper
  `user_window` run across the whole service, regardless of which Chrome window or panel
  sent it. A new window's side panel is a second client of the same service.
- Demo mode then masks the reason twice: `Handler.json` replaces every `error` with
  `FRIENDLY_ERROR` (`apps/raven/backend.py:874-878`), and the transport does the same
  client-side (`design/raven/outputs/raven/raven-transport.js:9`). The user cannot tell a
  busy window from a model failure.
- Reproduced (no model tokens; both runs cancelled before any model call): POST one
  `user_window` task, then a second → HTTP 400 with the friendly text in the body.

Suggested fixes: map "already has an active task" to a specific friendly message (for
example "Korp is busy in another window; stop that task or wait"), or let each window
or panel own its run instead of the single global slot. Keep `FRIENDLY_ERROR` for real
failures only.

## 2. Non-English replies to English questions (Claude Sonnet 5.5)

Seen live: "can you find the cheapest plane tickets to paris" (run `b291b876`, only an
example.com tab open) got a German clarifying question; a Mexico time question got a
Spanish reply (`9eb5229b` attempt 2). Sol never did this in today's runs.

Cause: `apps/raven/episode.py:562` appends, in the user's voice, "Write the final answer
in the same language as my message above, even if the websites use another language."
The system prompt already says to answer "in the language of the user's latest message
(not the website's language)".

Replay of the recorded first request of `b291b876` (55 calls; provider-reported
`prompt_tokens`/`completion_tokens` of complete requests: 710,565 in, 8,042 out, about
$1.50 at $2/$10 per MTok). All calls used Anthropic's OpenAI-compatible endpoint (the path
Korp uses; the recorded request is the wire request) except the native-API row.
"No-observation base" is the recorded request with the example.com `BROWSER UPDATE` /
`CURRENT BROWSER OBSERVATION` part of the user message removed.

| Variant | Non-English replies |
|---|---|
| Exact recorded request | 1 of 5 (Spanish) |
| Exact recorded request, native Messages API with summarized adaptive thinking | 2 of 5 (Spanish) |
| No-observation base | 8 of 15 (German, Spanish, Arabic, Vietnamese); 6 of 10 within the batch used for the rows below |
| No-observation base minus the system sentence "never infer it from your own name, the language of the message or website content" | 7 of 10 (German) |
| **No-observation base minus only the appended language sentence** | **0 of 10** |
| No-observation base minus every language instruction | 0 of 10 |

The thinking summaries (native API) never mention language or the user's nationality.
They only say the origin city and dates are missing. Every replay reply was a follow-up
question, but the problem is not limited to those: live runs also gave full answers in
the wrong language (`9eb5229b` attempt 2 in Spanish, `de69e569` final in Spanish,
`81ff5e34` in German after the German first turn).

Suggested fix: delete only that sentence from the appended goal suffix and keep the rest,
including the `\n\n` separator before "For research answers…" (the sentence has no
trailing space, so the current text reads "…another language.For research answers").
That is the tested "minus only the appended language sentence" variant. Tested on this one
request (without the page observation) and only with Claude Sonnet 5.5; re-check other
presets after the change.

## 3. Closing the Korp Chrome window leaves the service without a browser

Reproduced: closing the Chrome for Testing window (`CloseMainWindow`) ended every
Korp Chrome process. `backend.py` kept serving `/api/health` (HTTP 200), but the next
`user_window` task (`ba4955eb`) failed with
`TimeoutError: BrowserType.connect_over_cdp: Timeout 30000ms exceeded`. Demo mode started
attempt 2; I cancelled it after 24 s, so the final friendly error was not observed, but
`backend.py:618-630` would show it after a second timeout. Nothing relaunches Chrome; only rerunning
`start_demo.sh` recovers. The side panel lives in that window, so the user also loses the UI.

Suggested fixes: detect browser disconnect in `UserWindow` and relaunch Chrome (with the
extension), or make `/api/health` report the missing browser and exit so a supervisor
can restart. Either way, tasks should fail fast with "the Korp window was closed" instead
of up to two 30 s CDP timeouts.

## 4. Restart right after a close sometimes fails once

Once (13:25), `start_demo.sh` failed with
`RuntimeError: Page.goto: Target page, context or browser has been closed` in
`UserWindow.__init__` (`backend.py:64`). Before that it logged `Could not clear the demo
browser cache` (`backend.py:131`, `TargetClosedError`). Quoted from the launcher's terminal
output; the log itself was overwritten by the next start (section 8). A second run a few seconds later
worked. Likely cause, not verified: `start_demo.sh` stops the old Chrome with
`Stop-Process` and waits 2 s; a new Chrome with the same profile can start while the old
one is still exiting and then close. A wait until no `raven-demo` Chrome remains
(bounded) before launching would avoid it.

## 5. Flock mode problems (run `e6d6eb0d`, Claude Sonnet 5.5)

The request was flagship phones from four brands. The main agent spawned helpers iPhone
`52c11f83`, Samsung `7119a78d`, OnePlus `bdaacc96` and Google Pixel `40f0d3f1` at 13:57.

1. **Helpers restart from scratch, unseen by the main agent.** The demo retry
   (`backend.py:612-629`) also applies to helper runs (`_helper_of`). Pixel attempt 1
   died at 14:01:35 (`Page.screenshot: Timeout 2000ms exceeded`); iPhone attempt 1 died
   at 14:07:34 after 24 steps (`ObservationChanged`, section 6). Each restarted with an
   empty history while `wait_for_helpers` kept reporting `working`. The iPhone helper never
   reported anything in 16 minutes. Suggested fix: do not retry helpers silently. Report
   the failure to the main agent as a helper message/state, or retry with the conversation
   so far.
2. **Cancelling the main run loses all helper findings.** The user's follow-up
   ("what info did you get so far? dont make more searches") cancelled `e6d6eb0d` at
   14:13:30 and started `b8262859`. That new episode only receives the visible chat
   (`episode.py:561`, `Previous conversation (context)`), so it answered "I haven't looked
   up any specs or prices yet" although OnePlus and Samsung had reported prices.
   Suggested fix: on cancel/steer, carry helper reports (or a main-agent summary) into the
   next turn's context, or deliver the follow-up as a steer instead of a new run.
3. **Bot checks dominate.** GSMArena and PhoneArena showed Cloudflare checks and Google
   Store looped on consent.google.com (buttons rejected with `target_or_ancestry_changed`).
   The helper policy says to stop and report on bot checks, so there was much
   main↔helper back-and-forth. Not a bug, but it makes phone comparisons a poor flock demo.
4. **`close_helper` was once refused** with `tab_content_changed_since_decision` because the
   main agent's own Kayak tab kept changing (`change_count` 5057), so it needed a
   `proceed_action`. Host-only flock tools probably should not be gated on tab changes.

## 6. `ObservationChanged: Document/custody changed during preview` ends the episode

Seen twice. Raised by `intent_browser/dynamic_preview.py:89-90` when `identity()` (tab,
handover id, main document backend node id, loader id and URL) differs before and after
the shallow AX read. The call site `intent_browser/observation_pipeline.py:428` does not
handle it, so it propagates and the episode fails instead of recapturing.
`ObservationChanged` is handled only on the overlapped/pending path
(`observation_pipeline.py:353`, 372-393); the other path re-raises (397-398).

- `52c11f83` attempt 1 (iPhone helper): the failing preview (12:07:25-28 UTC) was the
  first one after step 22 `goto('https://www.gsmarena.com/results.php3?…iphone+18+pro')`,
  whose load wait took only 0.03 s. GSMArena was serving a Cloudflare Turnstile check to
  the helpers, which reloads/redirects the page. A post-navigation reload changing the
  loader id is the likely trigger. (The apple.com URL in the final `human_tab_transition`
  record is stale metadata.)
- `3ac2f263` attempt 1 (Qwen + SFT on Modal, example.com, single agent): trigger unknown;
  I did not determine which identity field changed. The preview took 1.9 s (item 7); the
  user's panel request was refused (section 1) about 30 s earlier.

Suggested fix: do not blanket-catch. `preview()` also raises
`ObservationChanged('Preview custody unavailable')` from `identity()`
(`dynamic_preview.py:56-57`) when the user holds the tab, and a full capture there would
read a user-controlled tab. Limit the fallback to the "changed during preview" case:
re-check custody, count it in `invalidation_streak`, then return a full capture. Log
the identity diff.

## 7. Slow page reads with `--windows-browser`

CDP traffic goes through `powershell.exe` copying stdin/stdout to a TCP client
(`intent_browser/windows_browser.py:83-85`). The per-frame phase `frame_owner_lookup`
has a median of 0.11-0.22 s across today's traces (0.20-0.22 s in the flock runs); that
is a phase time, which may include more than one CDP round trip. Capture time grows with
frame count:

| Pages | Frames per capture | Capture time |
|---|---|---|
| example.com, apple.com/se, prisjakt | 1-3 | 0.4-2.9 s |
| time.is (ads/trackers) | 20-49 | 5-14 s |
| time.is, one capture | about 280 | 70 s |
| Flock run, 5 agents sharing one Chrome | — | median 6-12 s per agent |

Frame count does not explain everything: Kayak (8 frames) took 5-8 s with one agent, and
samsung.com (7-11 frames) took 35-44 s in the flock run. The live clock on time.is is not
the cause; almost no time goes to stability waits. The 2000 ms screenshot timeout
(`intent_browser/visual_readiness.py:108,113`) is also easier to hit under this load
(Pixel helper). There is no direct-CDP baseline and I did not measure the PC, so blaming
the relay is an inference. A direct CDP connection (for example WSL mirrored networking to
the Windows debugging port) would test it and remove the per-call relay cost.

## 8. Laptop setup and smaller issues

- `scripts/raven_laptop_setup.sh` requires `python3.12` or `python3.11` on PATH; Ubuntu
  22.04 has 3.10 and this laptop's `.venv` uses a uv-managed CPython 3.12. Workaround:
  prepend `~/.local/share/uv/python/cpython-3.12.12-linux-x86_64-gnu/bin` to PATH.
- Sol needs **Node ≥22.19** on the service's PATH (Pi 0.80.6), **Pi's own login**
  (`~/.pi/agent/auth.json`; the Codex CLI login is separate) and a running **Codex
  app-server daemon**. Without the daemon, `SubscriptionQuotaGuard` cannot read quota
  (`held_unverifiable`, `FileNotFoundError` on the stale socket), the bridge returns HTTP 502
  and the user sees only the friendly error. `codex app-server daemon start` fixed it.
  `LAPTOP_SETUP.md` does not mention the daemon, and `LAPTOP_SETUP.md:408-409` still says
  Sol "is not set up on the laptop".
- `start_demo.sh:27` truncates `.local/raven-logs/raven-$PORT.log` on every start, so
  each restart deletes the evidence of the previous failure. Appending or rotating would
  have preserved the 13:42-13:49 window lost today.
- `ModelRegistry.available()` (`backend.py:331`) marks OpenRouter presets available when
  `OPENROUTER_API_KEY` merely exists (the laptop has a 15-character placeholder). For
  self-hosted presets it GETs `/v1/models` with a 2 s timeout whenever the 10 s probe
  cache has expired (`backend.py:333-334,351`); the panel called `/api/models` 14 times in
  3 minutes, so each Modal preset is probed up to every 10 s. Inferred, not verified: such
  probes can wake a scaled-to-zero GPU, and a cold start never answers in 2 s, so Korp
  falls back instead. Modal's function stats (read via the `modal` client, not checkable
  from local files) showed a backlog of 229 and one starting runner shortly before the
  talk.
- The `apps.raven.smoke` mock service has no `models` attribute, so the panel's
  `/api/models` call logs `AttributeError: 'MockService' object has no attribute 'models'`
  tracebacks during an otherwise passing smoke.
- Xvfb was not installed (the setup script's apt step needs sudo); only full-page
  background mode needs it.
- Trace viewer: `scripts/view_traces.py --runs .local/raven-runs` finds 0 sessions
  because Korp traces are nested two levels down. A laptop-local
  `.local/trace-viewer/sources.json` with patterns `.local/raven-runs/*/attempt-*` and
  `.local/raven-runs/*` made 23 traces visible.

## Model usage today (laptop)

- Sol: subscription only, no per-token charge.
- Claude Sonnet 5.5: the user's demo runs plus about $1.50 of language replays (section 2)
  and a 16-token key check.
- Qwen + SFT on Modal, provider-reported `prompt_tokens` of complete requests (Qwen
  tokenizer, from `steps.jsonl`): `3ac2f263` 88,297 (attempt 1) + 9,201 (attempt 2),
  `713fa0b2` 9,564, `40fbe096` (Kayak search, 24 steps) 584,017; about 691k in total.
  Billed as Modal GPU time, not per token.
- OpenRouter: no successful calls (the key is a placeholder).
