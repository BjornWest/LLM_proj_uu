# Recover Codex workspace windows after restarting Windows

From the directory whose agents you want to recover, run:

```bash
codex-windows
```

The installed command opens one Windows Terminal window with a tab per
conversation in that directory's last saved window group. Conversations reopen
in the recorded left-to-right order when uniquely matched in one Terminal window.
Tab titles start with recorded agent names and allow Codex's dynamic title/working indicator to replace
them. Each tab resumes its original conversation on the shared local app-server,
with the `:danger-full-access` profile and approval
policy `never`. It sends **no prompt** and does not restart interrupted browser,
model or training jobs. It restores conversations rather than screen positions,
shell history or arbitrary non-Codex windows. Already-running windows are left
alone; the command does not rearrange or move existing terminal tabs.

Normal recovery and `save` check that `codex-windows-roster.timer` is active.
If it is stopped, they start it and verify that it became active. Each service
command has a five-second timeout. A failed start prints a warning and allows
window recovery to continue; it does not silently claim tracking is running.
`list`, `restore --dry-run`, internal tab startup and periodic captures do not
start the timer. Use `--no-tracker` to skip this check for an invocation.

Inspect the selection without launching anything:

```bash
codex-windows list
# Equivalent: codex-windows --dry-run
```

Directories are matched by their canonical absolute path, exactly; running in a
subdirectory selects that subdirectory, not every thread belonging to its Git
repository. The restored windows use the same WSL distribution as the invoking
shell. No thread IDs need to be supplied for normal recovery.

## Installed implementation

`scripts/codex_windows.py` reads TUI process arguments and minimal conversation
metadata from Codex's SQLite database **read-only**. Only terminal-attached Codex
processes qualify; app-server, exec/review jobs and recorded child agents do not.
The tracker includes CLI and VS Code-origin conversations resumed in a TUI.

A user-local timer, `codex-windows-roster.timer`, samples the current window groups
every 30 seconds while WSL is running. Its oneshot service exits between samples;
there is no permanently running additional Python environment. Each group is
stored atomically under `~/.local/state/codex-windows/`, keyed by directory hash.
The roster contains IDs, names, directory, distribution and timestamps, not
conversation content or credentials. Empty logout/reboot samples preserve the
last nonempty group. Automatic samples remove a conversation only after the same
smaller group has been observed continuously for two minutes, with no sampling
gap over 90 seconds or reboot. A missing member must also have been observed
open in this boot, so starting only some conversations after reboot does not
erase the rest. An actual relaunch clears earlier live evidence for the members
it will reopen: a failed launch keeps them until they are observed again.
This prevents closing the first tab during
shutdown from immediately replacing the full recovery group. New members are
recorded immediately. `codex-windows save` confirms the current identified group
immediately; ambiguous unidentified windows still block that operation. The last
eight different accepted memberships remain in the roster's
`recent_groups` metadata for recovery; they contain no conversation text.
Reordering alone does not evict that history. While members are absent, observed
open tabs keep their new relative order and absent members keep their prior slots.

The same sample now reads Windows Terminal's tab strip through read-only Windows
UI Automation. It matches the current Codex `NAME | DIRECTORY` titles, including
their optional working indicator and `Action Required |` status, to the already identified conversations and
records their left-to-right order. Dragging tabs updates the saved order within
the normal 30-second sampling interval; use `codex-windows save` to capture it
immediately before reboot. `codex-windows list` numbers the saved order and states
whether it came from Terminal, an explicit selection or a fallback. Restoring
creates tabs in that sequence, without rearranging any tabs that are already open.

This probe does not select tabs, steal focus, read console contents or change
Terminal settings. Non-Codex tabs are not added to the roster. Unique title
matching is required: duplicate names/directory titles, custom overridden titles,
an unavailable Windows desktop or conversations split across several Terminal
windows retain the last known relative order. New unmatched conversations append
to that order. With no previous order, the activity fallback remains visibly
labeled. Multiple original window layouts and split panes are not reconstructed.

A TUI opened without a thread ID, for example through a picker, can be matched
only if exactly one unmatched loaded **persisted root** conversation exists in
that directory and exactly one TUI needs an ID. This is labeled
`unique_loaded_root`, an inference rather than a direct process-to-thread binding.
Loaded threads can remain cached after a TUI closes, so ambiguous matches do not
overwrite the prior roster. Inspect the service journal if needed:

```bash
systemctl --user status codex-windows-roster.timer
journalctl --user -u codex-windows-roster.service -n 20 --no-pager
```

To save immediately before reboot:

```bash
codex-windows save
```

For an ambiguous picker window, explicitly select the intended group once:

```bash
codex-windows save --threads THREAD_ID_1 THREAD_ID_2
```

These placeholders are literal conversation UUIDs from the Codex status/picker;
they are needed only when automatic identification is ambiguous. Explicitly
saved groups use the specified argument order and are subsequently monitored
normally; a later successful visual sample adopts the actual tab arrangement.
The tracker uses the standard Windows PowerShell path when its systemd service
has no Windows tools on `PATH`. The interactive shell and user timer have
different environments. A previously saved WSL distribution is retained when
the timer has no `WSL_DISTRO_NAME`.

Without a saved group, recovery prefers identifiable currently open windows,
then falls back to root conversations in this exact directory whose last
activity is within three hours of the most recent root conversation. That
fallback is **approximate**, visibly labeled, and capped at 20 conversations;
use `list` first. A fallback saved during a failed launch remains valid and keeps
its approximate-membership label until live capture or explicit selection
establishes the group.

## Duplicate and permission handling

An already attached conversation is skipped. An active server conversation is
also rejected before settings changes. Unidentified live windows block a real
restore to avoid opening a duplicate. Launches are serialized per directory and
per thread; recent unconfirmed launch claims expire after two minutes. A partial
startup cannot shrink the saved group during that grace period.
If a saved conversation has been archived or deleted, restore stops with a
stale-member error. Open the intended conversations and run `codex-windows save`
to confirm the replacement group. Duplicate IDs in explicit selection are
rejected before any roster write.

For a missing window, the helper loads the conversation without starting a turn,
applies `thread/settings/update`, and verifies permissions through an ordinary
`thread/resume`. The dedicated settings operation is necessary: overrides on
resume were ignored for an already-loaded idle thread in the installed server.
Managed configuration that disallows full access causes a clear failure. No
global Codex permissions are changed, and attached agents are left untouched.

The TUI itself resumes with `--remote unix://...` and **without `--yolo`**. Remote
resume permission overrides are rejected by the CLI; permissions are already set
on the server. The launcher starts the existing managed daemon idempotently and
never stops or updates it.

Windows Terminal's execution alias silently did nothing when launched directly
from WSL during testing. The helper therefore uses an encoded PowerShell
`Start-Process` call with literal, Windows-quoted arguments. Window titles are
sanitized for Terminal's semicolon delimiter. `--useApplicationTitle` lets Codex
update them; the original `--suppressApplicationTitle` pinned names and blocked
the title-based working spinner. This correction affects newly restored tabs,
not tabs already opened with suppression enabled. The WSL child invokes Python
without a shell command and then the stable `~/.local/bin/codex` installation,
falling back to PATH. A single Terminal command chains `new-tab` entries, so all
restored agents share one newly opened window. Successful launch requests are
followed by actual process attachment checks; an unconfirmed attachment is
reported, not retried silently.

## Installation and removal

This workstation is installed already. On another WSL machine, install Codex and
Windows Terminal first and ensure the workstation Python has `websockets`:

```bash
python3 -c 'import websockets'
python3 scripts/codex_windows.py install
python3 scripts/codex_windows.py save
```

Keep the user service manager available after WSL restarts (one-time setup):

```bash
sudo loginctl enable-linger "$USER"
systemctl --user enable --now codex-windows-roster.timer
```

Without lingering, WSL can start a shell without starting `user@UID.service`;
then an enabled user timer does not run. Check with
`loginctl show-user "$USER" -p Linger` and the timer status above. This does not
make Windows start WSL or recreate windows automatically; run `codex-windows`
when ready. Journal lines report visual versus preserved order and pending tab
removals. `list` warns if a fallback order's last visual observation is over an
hour old.

The installer creates `~/.local/bin/codex-windows` and the two user systemd units.
It refuses to overwrite an unrelated existing command/unit. Ensure
`~/.local/bin` is on the interactive shell PATH. Installation does not change
Windows startup or power settings.

To disable tracking but retain recovery, stop the timer and skip its automatic
startup on subsequent recovery/save invocations:

```bash
systemctl --user disable --now codex-windows-roster.timer
codex-windows --no-tracker
```

To uninstall, additionally remove the command and those two units, then run
`systemctl --user daemon-reload`. The private roster can be deleted separately
if it is no longer wanted. A moved checkout requires reinstalling the wrapper
and service against its new script path; existing different definitions are
protected against automatic overwrite.

## Validation

The focused tests cover directory separation, anonymous-window ambiguity,
child/server exclusion, nonempty roster preservation, partial restore, locks,
recent launch suppression, literal Windows quoting, active-thread protection,
managed permission rejection and zero-mutation already-attached restores:

```bash
python3 -m unittest discover -s tests -p test_codex_windows.py
```

The focused tests also cover visual reordering, working-indicator/status titles,
unrelated tabs, duplicate-title ambiguity, unavailable/timeout snapshots,
preserved fallback order, delayed removals, bounded roster history, the timer's
Linux-only PATH, explicit ordering and launch sequence. The original read-only
acceptance matched all six then-live project tabs and saved their visual order
without opening or interrupting conversations.

Local acceptance also launches short-lived harmless Windows Terminal commands
back into Ubuntu, including spaces and quoted arguments, and exercises the real
app-server permission update on an isolated synthetic empty conversation without
starting a turn. Receipts are under
`.local/coordination/codex-window-recovery/`. Normal running project agents are
not duplicated or interrupted for tests.

Protocol references: [OpenAI app-server](https://learn.chatgpt.com/docs/app-server),
[OpenAI permission profiles](https://learn.chatgpt.com/docs/permissions),
[Windows Terminal command-line arguments](https://learn.microsoft.com/en-us/windows/terminal/command-line-arguments).
