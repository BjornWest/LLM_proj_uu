#!/usr/bin/env python3
"""Restore this directory's last Codex TUI group; never submit a model turn.

Read-only process/SQLite discovery, optional read-only daemon discovery, local
roster timer and Windows Terminal launcher. See docs/agents/codex-window-recovery.md.
"""
from __future__ import annotations
import argparse
import asyncio
import base64
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time

UUID = re.compile(r"^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$")
STATE = Path(os.environ.get('XDG_STATE_HOME', Path.home() / '.local/state')) / 'codex-windows'
CODEX_HOME = Path(os.environ.get('CODEX_HOME', Path.home() / '.codex'))
SOCKET = CODEX_HOME / 'app-server-control/app-server-control.sock'
SCRIPT = Path(__file__).resolve()
REMOVAL_GRACE_SECONDS = 120
MAX_CAPTURE_GAP_SECONDS = 90

# Read-only UI Automation. Do not select tabs, focus windows or read terminals.
TAB_SNAPSHOT = r'''
$ProgressPreference='SilentlyContinue'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$pids=@(Get-Process WindowsTerminal -ErrorAction SilentlyContinue | ForEach-Object {$_.Id})
$root=[System.Windows.Automation.AutomationElement]::RootElement
$windows=$root.FindAll([System.Windows.Automation.TreeScope]::Children,[System.Windows.Automation.Condition]::TrueCondition)
$out=@()
foreach($w in $windows){
  try {
    if($pids -notcontains $w.Current.ProcessId){continue}
    $cond=New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ControlTypeProperty,[System.Windows.Automation.ControlType]::TabItem)
    $tabs=$w.FindAll([System.Windows.Automation.TreeScope]::Descendants,$cond)
    $index=0
    foreach($t in $tabs){
      $out+=@{window=$w.Current.NativeWindowHandle;index=$index;title=$t.Current.Name}
      $index++
    }
  } catch {throw 'Windows Terminal tab snapshot incomplete'}
}
ConvertTo-Json -InputObject @($out) -Compress -Depth 4
'''


def canonical(path):
    return str(Path(path).resolve())


def state_path(cwd):
    return STATE / (hashlib.sha256(canonical(cwd).encode()).hexdigest()[:24] + '.json')


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.roster-')
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load(path):
    return json.loads(path.read_text()) if path.exists() else None


@contextlib.contextmanager
def locked(path, blocking=True):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with path.open('a') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        yield


def boot_id():
    return Path('/proc/sys/kernel/random/boot_id').read_text().strip()


def processes(proc=Path('/proc')):
    """Only actual Codex TUI processes attached to a terminal, not exec/server jobs."""
    found = []
    for directory in proc.iterdir():
        if not directory.name.isdigit():
            continue
        try:
            argv = directory.joinpath('cmdline').read_bytes().decode().strip('\0').split('\0')
            if not argv or Path(argv[0]).name != 'codex':
                continue
            if not str(directory.joinpath('fd/0').resolve()).startswith('/dev/pts/'):
                continue
            if any(word in argv[1:] for word in ('exec', 'app-server', 'mcp-server', 'review')):
                continue
            ids = [word for word in argv[1:] if UUID.fullmatch(word)]
            found.append({'pid': int(directory.name), 'cwd': canonical(directory / 'cwd'),
                          'thread_id': ids[0] if len(ids) == 1 else None})
        except (OSError, UnicodeError):
            continue
    return found


def thread_rows():
    """Read metadata only. Never modify Codex's DB or read conversation contents."""
    candidates = list(CODEX_HOME.glob('state_*.sqlite'))
    if not candidates:
        raise RuntimeError('No local Codex conversation database found.')
    database = max(candidates, key=lambda p: p.stat().st_mtime)
    with sqlite3.connect(f'file:{database}?mode=ro', uri=True, timeout=3) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute('''SELECT id,name,title,cwd,updated_at_ms,source
            FROM threads WHERE archived=0 AND id NOT IN
            (SELECT child_thread_id FROM thread_spawn_edges)''').fetchall()
    return {r['id']: {'id': r['id'], 'name': r['name'] or r['title'] or r['id'],
                      'cwd': canonical(r['cwd']), 'updated_at_ms': r['updated_at_ms'] or 0}
            for r in rows if r['source'] in ('cli', 'vscode')}


class RPC:
    async def __aenter__(self):
        import websockets
        self.ws = await websockets.unix_connect(str(SOCKET), uri='ws://localhost/rpc',
            compression=None, max_size=32 * 1024 * 1024, open_timeout=5)
        self.sequence = 0
        await self.call('initialize', {'clientInfo': {'name': 'codex_windows', 'version': '1'},
                                       'capabilities': {'experimentalApi': True}})
        await self.ws.send(json.dumps({'method': 'initialized'}))
        return self

    async def __aexit__(self, *_):
        await self.ws.close()

    async def call(self, method, params):
        self.sequence += 1
        request_id = self.sequence
        await self.ws.send(json.dumps({'id': request_id, 'method': method, 'params': params}))
        deadline = time.monotonic() + 20
        while True:
            response = json.loads(await asyncio.wait_for(self.ws.recv(),
                                                         max(.001, deadline - time.monotonic())))
            if response.get('id') == request_id:
                if 'error' in response:
                    raise RuntimeError(f'{method}: {response["error"]}')
                return response['result']


async def loaded_ids():
    if not SOCKET.exists():
        return set()
    async with RPC() as rpc:
        result, cursor = set(), None
        while True:
            page = await rpc.call('thread/loaded/list', {'cursor': cursor})
            result.update(page['data'])
            cursor = page.get('nextCursor')
            if not cursor:
                return result


def identify(cwd, running, rows, loaded):
    """Infer unnamed/picker TUIs only when the loaded root set maps uniquely."""
    here = [p for p in running if p['cwd'] == cwd]
    ids = {p['thread_id'] for p in here if p['thread_id']}
    missing = [p for p in here if not p['thread_id']]
    inferred = set()
    candidates = {i for i in loaded if i in rows and rows[i]['cwd'] == cwd} - ids
    # Multiple anonymous windows cannot be distinguished from cached subscriptions.
    if len(missing) == 1 and len(candidates) == 1:
        inferred = candidates
    unresolved = len(missing) - len(inferred)
    selected = []
    for i in sorted(ids | inferred, key=lambda i: rows.get(i, {}).get('updated_at_ms', 0), reverse=True):
        if i not in rows or rows[i]['cwd'] != cwd:
            continue
        selected.append({'id': i, 'name': rows[i]['name'],
                         'evidence': 'unique_loaded_root' if i in inferred else 'tui_argv'})
    return selected, unresolved


def recent_group(cwd, rows):
    here = sorted([r for r in rows.values() if r['cwd'] == cwd],
                  key=lambda r: r['updated_at_ms'], reverse=True)
    if not here:
        return []
    latest = here[0]['updated_at_ms']
    return [{'id': r['id'], 'name': r['name'], 'evidence': 'recent_metadata_fallback'}
            for r in here if latest - r['updated_at_ms'] <= 3 * 60 * 60 * 1000][:20]


def terminal_tabs():
    """Windows Terminal visual order, or None if not available. Never focus UI."""
    powershell = shutil.which('powershell.exe')
    # The user timer has a Linux-only PATH, unlike an interactive WSL shell.
    if not powershell:
        candidate = Path('/mnt/c/WINDOWS/System32/WindowsPowerShell/v1.0/powershell.exe')
        powershell = str(candidate) if candidate.is_file() else None
    if not powershell:
        return None
    try:
        encoded = base64.b64encode(TAB_SNAPSHOT.encode('utf-16le')).decode('ascii')
        result = subprocess.run([powershell, '-NoProfile', '-NonInteractive',
                                 '-EncodedCommand', encoded], check=True, timeout=10,
                                capture_output=True, cwd='/mnt/c')
        tabs = json.loads(result.stdout.decode('utf-8-sig'))
        if not isinstance(tabs, list) or any(
            not isinstance(t, dict) or not isinstance(t.get('title'), str) or
            type(t.get('index')) is not int or t['index'] < 0 or
            type(t.get('window')) is not int for t in tabs):
            return None
        return tabs
    except (OSError, subprocess.SubprocessError, UnicodeError, ValueError):
        return None


def order_group(cwd, selected, tabs, previous=None):
    """Require unique title matches in one window, otherwise preserve prior order.

    Codex's dynamic title is NAME | DIRECTORY, optionally prefixed by its working
    indicator. Duplicate names/directories, custom tab titles and multiple windows
    are intentionally not guessed. Titles never determine roster membership.
    """
    matched = []
    for thread in selected:
        suffix = thread['name'] + ' | ' + Path(cwd).name
        def matches(title):
            if not title.endswith(suffix):
                return False
            prefix = title[:-len(suffix)]
            # Codex 0.162 adds words before the name when it needs input.
            status = 'Action Required | '
            if prefix.endswith(status):
                prefix = prefix[:-len(status)]
            return not prefix or (prefix.endswith(' ') and bool(prefix.strip()) and
                                  not any(c.isalnum() for c in prefix))
        candidates = [tab for tab in tabs or [] if matches(tab['title'])]
        if len(candidates) != 1:
            break
        matched.append((candidates[0], thread))
    identities = {(tab['window'], tab['index']) for tab, _ in matched}
    if selected and len(matched) == len(selected) and len(identities) == len(selected) and \
            len({tab['window'] for tab, _ in matched}) == 1:
        ordered = [thread for tab, thread in sorted(matched, key=lambda pair: pair[0]['index'])]
        return ordered, {'source': 'windows_terminal_uia', 'observed_at': time.time()}
    # Do not let conversation activity silently reshuffle a previously saved group.
    previous = previous or {}
    positions = {t['id']: i for i, t in enumerate(previous.get('threads', []))}
    known = any(t['id'] in positions for t in selected)
    ordered = sorted(selected, key=lambda t: positions.get(t['id'], len(positions)))
    evidence = {'source': 'saved_relative_order' if known else 'activity_fallback',
                'reason': 'Visual order unavailable or not uniquely matched in one window'}
    if known and previous.get('tab_order', {}).get('observed_at') is not None:
        evidence['observed_at'] = previous['tab_order']['observed_at']
    return ordered, evidence


def record_group(cwd, selected, unresolved, *, force=False, tab_order=None,
                 confirm_removals=False, live_ids=None):
    if unresolved and not force:
        raise RuntimeError(f'{unresolved} Codex window(s) cannot be identified uniquely. '
                           'Previous roster preserved; use save --threads ID ... to select explicitly.')
    if not selected:
        return None  # Never replace the last group with an empty logout/reboot snapshot.
    if len({t['id'] for t in selected}) != len(selected):
        raise RuntimeError('Duplicate conversation IDs; select each thread only once.')
    path = state_path(cwd)
    old = load(path)
    if (old and not (force or confirm_removals) and
            len({t['id'] for t in old['threads']}) != len(old['threads'])):
        raise RuntimeError('Saved roster has duplicate IDs; run codex-windows save to repair it.')
    value = dict(old or {})  # Keep still-live duplicate-launch claims.
    value.update(schema_version=1, cwd=cwd, boot_id=boot_id(), saved_at=time.time(),
                 distro=os.environ.get('WSL_DISTRO_NAME') or (old or {}).get('distro'),
                 threads=selected)
    selected_ids = {t['id'] for t in selected}
    seen = (old or {}).get('live_seen', {})
    observed = set(seen.get('ids', [])) if seen.get('boot_id') == value['boot_id'] else set()
    observed.update(selected_ids if live_ids is None else live_ids)
    value['live_seen'] = {'boot_id': value['boot_id'], 'ids': sorted(observed)}
    value.pop('pending_removal', None)
    if tab_order is not None:
        value['tab_order'] = tab_order
    if old and not (force or confirm_removals):
        missing = {t['id'] for t in old['threads']} - selected_ids
        if missing:
            now = value['saved_at']
            pending = old.get('pending_removal', {})
            same = (pending.get('boot_id') == value['boot_id'] and
                    pending.get('ids') == sorted(t['id'] for t in selected) and
                    0 <= now - pending.get('last_seen', 0) <= MAX_CAPTURE_GAP_SECONDS)
            first = pending['first_seen'] if same else now
            unseen = missing - observed
            if unseen or old.get('restore_until', 0) > now or now - first < REMOVAL_GRACE_SECONDS:
                # Never remove a member not yet seen in this boot (including
                # failed/partial restores). Reorder open members within the
                # old slots while retaining absent members in their old slots.
                visible = iter(selected)
                value['threads'] = [next(visible) if t['id'] in selected_ids else t
                                    for t in old['threads']] + list(visible)
                value['pending_removal'] = {'ids': sorted(selected_ids),
                    'boot_id': value['boot_id'], 'first_seen': first, 'last_seen': now,
                    'never_seen_this_boot': sorted(unseen)}
                if tab_order and tab_order.get('source') == 'windows_terminal_uia':
                    value['tab_order'] = {**tab_order, 'source': 'partial_visual_order',
                        'reason': 'Open tabs observed; absent members retain prior slots'}
    if force:
        value['selection_source'] = 'explicit_selection'
    elif value.get('pending_removal'):
        legacy = old.get('schema_version') is None and 'restore_until' in old
        value['selection_source'] = old.get('selection_source',
            'approximate legacy fallback; membership not verified' if legacy else 'observed_tuis')
    else:
        value['selection_source'] = 'observed_tuis'
    if old:
        history = list(old.get('recent_groups', []))
        if {t['id'] for t in old['threads']} != {t['id'] for t in value['threads']}:
            history.insert(0, {k: old[k] for k in
                ('threads', 'saved_at', 'boot_id', 'distro', 'tab_order', 'selection_source') if k in old})
        if history:
            value['recent_groups'] = history[:8]
    atomic_json(path, value)
    return value


def resolve_group(cwd, rows, running, loaded):
    saved = load(state_path(cwd))
    if saved:
        # Older fallback restores wrote these fields without a schema marker.
        # Repair only that known shape in memory; dry runs remain read-only.
        if (saved.get('schema_version') is None and saved.get('cwd') == cwd and
                'restore_until' in saved and isinstance(saved.get('threads'), list) and
                saved['threads'] and all(isinstance(t, dict) and t.get('id') in rows and
                rows[t['id']]['cwd'] == cwd for t in saved['threads'])):
            saved = {**saved, 'schema_version': 1,
                     'selection_source': 'approximate legacy fallback; membership not verified'}
        if saved.get('schema_version') != 1 or saved.get('cwd') != cwd:
            raise RuntimeError('Invalid workspace roster; no windows opened.')
        label = saved.get('selection_source', '')
        return saved, 'saved window group' + ('; ' + label if label.startswith('approximate') else '')
    selected, unresolved = identify(cwd, running, rows, loaded)
    if selected and not unresolved:
        selected, evidence = order_group(cwd, selected, terminal_tabs())
        return {'schema_version': 1, 'cwd': cwd, 'boot_id': boot_id(), 'saved_at': time.time(),
                'distro': os.environ.get('WSL_DISTRO_NAME'), 'threads': selected,
                'tab_order': evidence, 'selection_source': 'observed_tuis'}, 'open windows'
    selected = recent_group(cwd, rows)
    if not selected:
        raise RuntimeError('No Codex conversations for this exact directory.')
    return {'schema_version': 1, 'cwd': cwd, 'boot_id': boot_id(), 'saved_at': time.time(),
            'distro': os.environ.get('WSL_DISTRO_NAME'), 'threads': selected,
            'selection_source': 'approximate metadata fallback; membership not verified'}, \
        'approximate fallback: root conversations within 3 hours of latest activity'


def terminal_command(thread, cwd, distro):
    # Use argv, never cmd.exe shell interpolation. WT still interprets semicolons.
    title = re.sub(r'[\x00-\x1f;]', ' ', thread['name'])[:100]
    if ';' in cwd or ';' in str(SCRIPT) or ';' in distro:
        raise RuntimeError('Windows Terminal delimiter in directory/distro; refusing ambiguous command.')
    return ['wt.exe', '-w', 'new', 'new-tab', '--title', title, '--useApplicationTitle',
            'wsl.exe', '-d', distro, '--cd', cwd, '--exec', sys.executable,
            str(SCRIPT), 'run', '--cwd', cwd, '--thread', thread['id']]


def terminal_group_command(threads, cwd, distro):
    """One WT launch creates one window, with one named tab per conversation."""
    if not threads:
        raise ValueError('Cannot launch an empty conversation group.')
    command = terminal_command(threads[0], cwd, distro)
    for thread in threads[1:]:
        command.extend([';'] + terminal_command(thread, cwd, distro)[3:])
    return command


def windows_launch(command):
    # WT's execution alias silently drops commands when invoked directly from
    # this WSL setup. Start it on the Windows side with a properly quoted argument
    # string. Encoded PowerShell contains only a literal string, never user code.
    arguments = subprocess.list2cmdline(command[1:]).replace("'", "''")
    script = "$ProgressPreference='SilentlyContinue'; Start-Process -FilePath 'wt.exe' -ArgumentList '" + arguments + "'"
    encoded = base64.b64encode(script.encode('utf-16le')).decode('ascii')
    return ['powershell.exe', '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded]


def codex_binary():
    # --exec does not source .bashrc or NVM. Prefer the stable user-local install.
    local = Path.home() / '.local/bin/codex'
    return str(local) if local.is_file() and os.access(local, os.X_OK) else shutil.which('codex')


async def prepare_permissions(rpc, thread_id, cwd):
    thread = (await rpc.call('thread/read', {'threadId': thread_id, 'includeTurns': False}))['thread']
    if canonical(thread['cwd']) != cwd:
        raise RuntimeError('Stored thread belongs to another directory.')
    if thread['status']['type'] == 'active':
        raise RuntimeError('Conversation is already active; no duplicate client/settings changes.')
    profiles = await rpc.call('permissionProfile/list', {'cwd': cwd})
    if not any(p['id'] == ':danger-full-access' and p['allowed'] for p in profiles['data']):
        raise RuntimeError('Full access is not allowed by current Codex configuration.')
    # Resume overrides can be ignored for an already-loaded idle thread. Load it,
    # use the dedicated settings operation, then verify what an ordinary TUI
    # resume will actually inherit. None of these operations starts a turn.
    await rpc.call('thread/resume', {'threadId': thread_id, 'excludeTurns': True})
    await rpc.call('thread/settings/update', {'threadId': thread_id,
                         'permissions': ':danger-full-access', 'approvalPolicy': 'never'})
    result = await rpc.call('thread/resume', {'threadId': thread_id, 'excludeTurns': True})
    if result.get('approvalPolicy') != 'never' or result.get('sandbox', {}).get('type') != 'dangerFullAccess':
        raise RuntimeError('Server did not confirm full access; no terminal launched.')
    return result


async def capture_all(cwd=None, explicit=None, *, force=False):
    if explicit and len(set(explicit)) != len(explicit):
        raise RuntimeError('Duplicate conversation IDs; select each thread only once.')
    running, rows = processes(), thread_rows()
    loaded = await loaded_ids() if any(not p['thread_id'] for p in running) else set()
    directories = [cwd] if cwd else sorted({p['cwd'] for p in running})
    tabs = terminal_tabs() if directories and not explicit else None
    for directory in directories:
        if explicit:
            selected = []
            for i in explicit:
                if i not in rows or rows[i]['cwd'] != directory:
                    raise RuntimeError(f'Not a root conversation in this directory: {i}')
                selected.append({'id': i, 'name': rows[i]['name'], 'evidence': 'explicit_selection'})
            unresolved = 0
            tab_order = {'source': 'explicit_argument_order'}
        else:
            selected, unresolved = identify(directory, running, rows, loaded)
        try:
            with locked(state_path(directory).with_suffix('.lock'), blocking=False):
                if not explicit:
                    selected, tab_order = order_group(directory, selected, tabs, load(state_path(directory)))
                result = record_group(directory, selected, unresolved,
                                      force=bool(explicit), confirm_removals=force,
                                      tab_order=tab_order, live_ids=(
                                          {p['thread_id'] for p in running
                                           if p['cwd'] == directory and p['thread_id']}
                                          if explicit else None))
            if result:
                pending = result.get('pending_removal', {})
                detail = ('; retaining tabs not yet observed this boot' if pending.get('never_seen_this_boot')
                          else '; waiting for missing tabs to stay closed for two minutes' if pending else '')
                print(f'Saved {len(result["threads"])} windows: {directory} '
                      f'(order={result.get("tab_order", {}).get("source", "unknown")}{detail})')
        except (BlockingIOError, RuntimeError) as error:
            if cwd:
                raise
            print(f'Skipped {directory}: {error}', file=sys.stderr)


async def restore(cwd, dry_run=False):
    with locked(state_path(cwd).with_suffix('.lock'), blocking=False):
        running, rows = processes(), thread_rows()
        loaded = await loaded_ids() if any(not p['thread_id'] for p in running) else set()
        group, source = resolve_group(cwd, rows, running, loaded)
        current, unresolved = identify(cwd, running, rows, loaded)
        if unresolved and not dry_run:
            raise RuntimeError('Unidentified live Codex window(s); refusing possible duplicate launch. '
                               'Close those windows or use save --threads to identify the group.')
        attached = {t['id'] for t in current}
        print(f'{cwd}\nSelected {len(group["threads"])} conversations from {source}.')
        ordering = group.get('tab_order', {}).get('source', 'saved_roster_order')
        print('Tab order: ' + {
            'windows_terminal_uia': 'recorded Windows Terminal left-to-right order',
            'saved_relative_order': 'last saved relative order; current visual order unavailable',
            'partial_visual_order': 'observed open-tab order; absent members retain prior slots',
            'explicit_argument_order': 'explicit save --threads order',
            'activity_fallback': 'activity fallback; visual order not recorded',
            'saved_roster_order': 'saved roster order; visual order not recorded',
        }.get(ordering, 'unrecognized evidence; saved list order'))
        observed = group.get('tab_order', {}).get('observed_at')
        if ordering == 'saved_relative_order' and observed and time.time() - observed > 3600:
            print('Warning: visual order was last captured at ' +
                  time.strftime('%Y-%m-%d %H:%M', time.localtime(observed)) +
                  '; arrange the tabs and run codex-windows save to refresh it.')
        pending = []
        if len({t['id'] for t in group['threads']}) != len(group['threads']):
            raise RuntimeError('Saved roster has duplicate IDs; run codex-windows save to repair it.')
        for position, thread in enumerate(group['threads'], 1):
            if not UUID.fullmatch(thread['id']) or thread['id'] not in rows or rows[thread['id']]['cwd'] != cwd:
                raise RuntimeError('Invalid/stale thread in saved group; no windows opened. '
                                   'Run codex-windows save with the intended tabs open to repair it.')
            status = 'already open — skipped' if thread['id'] in attached else 'restore with full access'
            print(f'  {position}. {thread["name"]} [{thread["id"]}] — {status}')
            if thread['id'] not in attached:
                pending.append(thread)
        if dry_run or not pending:
            return
        distro = os.environ.get('WSL_DISTRO_NAME') or group.get('distro')
        if not distro:
            raise RuntimeError('Run in the WSL distribution you want to restore.')
        terminal_group_command(pending, cwd, distro)  # Validate every argument before mutations.
        for executable in ('wt.exe', 'wsl.exe', 'powershell.exe'):
            if not shutil.which(executable):
                raise RuntimeError(f'{executable} is unavailable; no windows opened.')
        if not codex_binary():
            raise RuntimeError('Codex is unavailable; no windows opened.')
        claims = group.get('launch_claims', {}) if group.get('launch_boot') == boot_id() else {}
        unconfirmed = [t['id'] for t in pending if claims.get(t['id'], 0) > time.time()]
        if unconfirmed:
            raise RuntimeError('Recent launch still unconfirmed. Inspect its window before retrying; '
                               'duplicate launch is blocked for two minutes: ' + ', '.join(unconfirmed))
        subprocess.run([codex_binary(), 'app-server', 'daemon', 'start'], check=True, timeout=25,
                       stdout=subprocess.DEVNULL)
        group['restore_until'] = time.time() + 120
        # A previous attachment earlier in this boot cannot stand in for a new
        # launch. Failed relaunches must stay in the group until seen again.
        seen = group.get('live_seen', {})
        prior_live = seen.get('ids', []) if seen.get('boot_id') == boot_id() else []
        launching_ids = {t['id'] for t in pending}
        group['live_seen'] = {'boot_id': boot_id(),
                             'ids': [i for i in prior_live if i not in launching_ids]}
        atomic_json(state_path(cwd), group)
        launching = []
        async with RPC() as rpc:
            for thread in pending:
                # Recheck argv immediately before changing settings/spawning a window.
                if any(p['thread_id'] == thread['id'] for p in processes()):
                    continue
                await prepare_permissions(rpc, thread['id'], cwd)
                launching.append(thread)
        if launching:
            for thread in launching:
                claims[thread['id']] = time.time() + 120
            group.update(launch_claims=claims, launch_boot=boot_id())
            atomic_json(state_path(cwd), group)
            command = terminal_group_command(launching, cwd, distro)
            subprocess.run(windows_launch(command), check=True, timeout=15, cwd='/mnt/c')
        # A successful WT request is not evidence that Codex attached successfully.
        deadline = time.monotonic() + 25
        expected = {t['id'] for t in pending}
        while time.monotonic() < deadline:
            observed = {p['thread_id'] for p in processes()}
            if expected <= observed:
                print(f'Confirmed {len(expected)} restored CLI attachments. No prompts sent.')
                return
            await asyncio.sleep(.5)
        missing = expected - {p['thread_id'] for p in processes()}
        raise RuntimeError(f'Terminal launch requested, but {len(missing)} attachment(s) not confirmed. '
                           'Inspect the new windows before rerunning: ' + ', '.join(sorted(missing)))


def run_thread(cwd, thread_id):
    if not UUID.fullmatch(thread_id or ''):
        raise RuntimeError('Invalid thread ID.')
    with locked(STATE / ('thread-' + thread_id + '.lock'), blocking=False):
        if any(p['thread_id'] == thread_id for p in processes()):
            raise RuntimeError('This conversation already has an attached Codex TUI.')
        executable = codex_binary()
        if not executable:
            raise RuntimeError('Codex not found in the interactive WSL shell PATH.')
        result = subprocess.run([executable, 'resume', '--remote', 'unix://' + str(SOCKET),
                                 '--cd', cwd, thread_id], cwd=cwd)
        return result.returncode


def install():
    # Explicit user-local installation; do not alter global Codex permissions.
    destination = Path.home() / '.local/bin/codex-windows'
    wrapper = '#!/bin/bash\nexec ' + shlex.join([sys.executable, str(SCRIPT)]) + ' "$@"\n'
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and destination.read_text() != wrapper:
        raise RuntimeError(f'Existing unrelated command at {destination}; refusing overwrite.')
    destination.write_text(wrapper)
    destination.chmod(0o755)
    unit_dir = Path.home() / '.config/systemd/user'
    unit_dir.mkdir(parents=True, exist_ok=True)
    exec_start = ' '.join('"' + s.replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%') + '"'
                          for s in [sys.executable, str(SCRIPT), 'capture', '--all'])
    units = {
        'codex-windows-roster.service': '[Unit]\nDescription=Remember open Codex workspace windows\n'
            '[Service]\nType=oneshot\nExecStart=' + exec_start + '\nTimeoutStartSec=45\n',
        'codex-windows-roster.timer': '[Unit]\nDescription=Remember Codex windows every 30 seconds\n'
            '[Timer]\nOnStartupSec=30\nOnUnitActiveSec=30\nAccuracySec=5\n'
            '[Install]\nWantedBy=timers.target\n'}
    for name, body in units.items():
        path = unit_dir / name
        if path.exists() and path.read_text() != body:
            raise RuntimeError(f'Existing different unit {path}; refusing overwrite.')
        path.write_text(body)
    subprocess.run(['systemctl', '--user', 'daemon-reload'], check=True)
    subprocess.run(['systemctl', '--user', 'enable', '--now', 'codex-windows-roster.timer'], check=True)
    print('Installed codex-windows and automatic 30-second window roster timer.')


def ensure_tracker():
    """Repair a stopped timer on interactive use, without blocking recovery."""
    unit = 'codex-windows-roster.timer'

    def control(*args):
        return subprocess.run(['systemctl', '--user', *args], timeout=5,
                              capture_output=True, text=True, errors='replace')

    try:
        if control('is-active', '--quiet', unit).returncode == 0:
            return True
        result = control('start', unit)
        if result.returncode:
            detail = ' '.join(result.stderr.split())[:300] or 'systemctl start failed'
            raise RuntimeError(detail)
        if control('is-active', '--quiet', unit).returncode:
            raise RuntimeError('timer did not become active after startup')
    except (OSError, subprocess.SubprocessError, RuntimeError) as error:
        print(f'codex-windows: warning: automatic window tracking is unavailable ({error}). '
              'Window recovery will continue. Check systemctl --user status '
              'codex-windows-roster.timer; use codex-windows install if the units are missing.',
              file=sys.stderr)
        return False
    print('Started automatic Codex window tracking.')
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', nargs='?', default='restore',
                        choices=['restore', 'list', 'save', 'capture', 'run', 'install'])
    parser.add_argument('--cwd', default=os.getcwd(), help='Defaults to your current directory.')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--no-tracker', action='store_true',
                        help='Skip automatic tracker startup for this invocation.')
    parser.add_argument('--all', action='store_true', help='Capture all currently open workspace groups.')
    parser.add_argument('--threads', nargs='+', help='Explicit root conversation IDs for save only.')
    parser.add_argument('--thread', help=argparse.SUPPRESS)
    args = parser.parse_args()
    cwd = canonical(args.cwd)
    try:
        if not args.no_tracker and (args.command == 'save' or
                                     (args.command == 'restore' and not args.dry_run)):
            ensure_tracker()
        if args.command == 'install':
            install()
        elif args.command == 'run':
            return run_thread(cwd, args.thread)
        elif args.command in ('capture', 'save'):
            asyncio.run(capture_all(None if args.all else cwd, args.threads,
                                    force=args.command == 'save'))
        else:
            asyncio.run(restore(cwd, args.dry_run or args.command == 'list'))
        return 0
    except (RuntimeError, OSError, subprocess.SubprocessError, TimeoutError) as error:
        print(f'codex-windows: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
