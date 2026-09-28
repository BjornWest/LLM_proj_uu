# Windows browser launch and window layout

`intent_browser.windows_browser.WindowsChrome` is the shared WSL-to-Windows
launcher for **future** BrowserGym launchers. It preserves the previous isolated
Chrome profile/CDP relay. Visible chat now uses a second isolated Windows Chrome
profile, because WSLg activates chat windows despite Chromium background opening.
Task and chat still have separate browser instances and contexts. Historical cohort launchers are
frozen copies and are not changed retroactively.

```python
from intent_browser.windows_browser import WindowsChrome
from intent_browser.windows_layout import load_layout

chrome = WindowsChrome(output_dir, port=19229,
    layout=load_layout('/home/bjorn/code/LLM_proj_uu/.local/windows-browser-layout.json'))
try:
    with chrome.bind_environment():
        # Existing BrowserEnv factory / run_episode call.
        ...
finally:
    chrome.close()
```

By default (`background=True`), Windows Chrome starts with `--no-startup-window`,
so no unused blank window is created. New isolated task/chat pages use
`Target.createTarget(background=True)` with their exact newly created context ID.
No input lock is installed: deliberate user selection and clicking still work.
The wrapper applies to subsequent explicit `context.new_page()` calls too. It is
not a global focus lock against arbitrary website popups or other applications.

If a startup page does exist (e.g. legacy `background=False`), the binding closes
the launcher's original empty `about:blank` page **after**
BrowserGym creates its replacement task page. It retains a startup page if it
has acquired a URL, title or body content, and never searches unrelated browser
profiles for blank tabs. Errors are recorded without retrying the close.

## Saved workstation preference

`.local/windows-browser-layout.json` selects Windows device `\\.\DISPLAY6`
(the left display at configuration time), with `browser_fraction: 0.7`.
Browser: left 1344 pixels; chat: adjacent right 576 pixels; both now use 80% of the screen's
1032-pixel working height (826 pixels), leaving the bottom 206 usable pixels plus
the taskbar free for Codex. This is saved as `height_fraction: 0.8`; missing values
preserve the old full-height layout. The primary/right
screen is untouched. Display IDs can change after a cable/display configuration
change; a missing device records a placement failure rather than moving to an
arbitrary monitor.

The canonical launcher loads this file by default from the checkout. Frozen
source copies should pass the explicit configuration path and record its hash.
Pass `layout={}` to disable placement; `headless=True` supports offline checks.
`background=False, windows_chat=False` selects the older launching behavior.
These are launcher options, not changes to model tools. Normal visible operation
uses `background=True, windows_chat=True`. The helper acquires a free loopback
debug port for its separate chat browser and records launch details under
`windows-chat/`. A port conflict fails rather than attaching to a foreign browser.

Placement happens once, before task setup. Windows matches a random temporary
page-title marker to exactly one native window, including WSLg's prefixed chat
title. The original title is restored before BrowserGym captures the task's
observation. It does not insert task controls, change browser viewport settings,
continually reposition windows, or deliberately activate a window. Normal browser
startup was tested without foreground activation using this Windows launcher.
Manually moving either window afterward is allowed.

Reports: `windows-startup-cleanup.json` and `windows-layout-result.json` alongside
`windows-started.json`. Layout failures do not abort episodes.

## Local acceptance

`tests/test_windows_browser.py` covers retained/navigated/closed/error startup
pages, one-shot cleanup, negative monitor coordinates and title restoration.
`scripts/verify_windows_launcher.py` exercises actual Windows Chrome plus WSL
BrowserGym chat against a local form, with no model or public website calls.

Saved evidence under `.local/windows-launcher-v1/`:

- `headless/report.json`: startup closed; task/chat remain usable; fill/click and screenshot.
- `layout-final/report.json`: Windows and WSLg native rectangles both exactly match
  the requested left-screen positions; title markers absent from task AX.
- `retained/report.json`: a modified startup page remains open while the agent works.

The first layout attempt did not find WSLg's prefixed title. It is preserved under
`layout/`; final matching uses the unique nonce anywhere in the window title.
No active research episode was modified, restarted or replayed.

## Background-opening acceptance

`scripts/verify_windows_focus.py` uses a Windows foreground-event hook for 40
seconds covering launch, placement, autofocus, fill/click, a new tab, and close.
This desktop-focus check runs sequentially because foreground focus is shared OS
state. No synthetic OS keystrokes or clicks are sent to the user's applications.

`.local/windows-focus-v1/combined-handover/report.json` records **zero foreground
changes**, exact window placement, functional task actions/screenshots, chat
messages and handover Start/Finished callbacks while the Python owner thread is
blocked. Thus moving chat from WSLg did not break its localhost control panel on
this workstation. Twelve focused unit tests also pass. No model or external-site
calls. Earlier WSLg probes are retained as negative evidence under the same folder.

Historical cohorts and active browser sessions are not updated in place; future
frozen launchers must include `windows_browser.py`, `windows_layout.py` and
`background_pages.py`, plus the selected layout configuration in provenance.

The placement report name was changed from `windows-layout.json` to
`windows-layout-result.json` because a cohort used the former for its input
configuration. Existing historical placement files remain unchanged; do not
rewrite them to hide the collision. The updated helper leaves input bytes intact.
The shorter layout affects future launches only, not an already running browser.
