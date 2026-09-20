"""Interpret historical Civ5 FireTuner captures without contacting the game."""
import re
import json


def decision_labels(messages):
    """Add display-only labels from earlier Civ5 observations in the same stream.

    Short RPC handles are scoped to a recording stream, not a whole game. Never
    backfill earlier decisions from later observations or parse narrative guesses.
    """
    streams = {}
    for message in messages:
        units = streams.setdefault(message['source'], {})
        if message['kind'] == 'result' and message.get('at'):
            try:
                payload = json.loads(message.get('text') or '')
            except (ValueError, TypeError):
                continue
            if not isinstance(payload, dict) or not isinstance(payload.get('result'), dict):
                continue
            result = payload['result']
            if isinstance(result.get('units'), list):
                units.clear()  # A fresh roster supersedes obsolete/reused handles.

            def observe(value):
                if isinstance(value, list):
                    for child in value:
                        observe(child)
                elif isinstance(value, dict):
                    ref, kind = value.get('unit'), value.get('type')
                    if (isinstance(ref, str) and re.fullmatch(r'u\d+', ref)
                            and value.get('owner', 'self') == 'self'):
                        if value.get('lost'):
                            units.pop(ref, None)
                        elif isinstance(kind, str) and kind.strip():
                            units[ref] = (kind, message['id'])
                    for key, child in value.items():
                        if key not in ('remembered', 'memory'):
                            observe(child)

            observe(result)
        elif message['kind'] == 'decision':
            action = message.get('action') or {}
            labels = {}
            for key, value in action.items():
                if isinstance(value, str) and re.match(r'^(TECH_|POLICY_|BUILDING_|UNIT_)', value):
                    labels[key] = re.sub(r'^(TECH_|POLICY_BRANCH_|POLICY_|BUILDING_|UNIT_)', '', value).replace('_', ' ').title()
            ref = action.get('unit')
            if message.get('at') and isinstance(ref, str) and ref in units:
                kind, source = units[ref]
                if kind.startswith('UNIT_'):
                    kind = kind.removeprefix('UNIT_').replace('_', ' ').title()
                labels['unit'] = f'{kind} ({ref})'
                message['action_label_sources'] = {'unit': source}
            if labels:
                message['action_labels'] = labels

def result_details(stdout, stderr, exit_code):
    # Match printed markers, never marker strings embedded in echoed Lua source.
    marker = re.compile(r"^\s*(?:[\w ]+:\s*)?CIV5_\w+_END[ \t]+(true|false)\s*$", re.M)
    matches = marker.findall(stdout)
    if any(message in stdout + stderr for message in ("No completed result within", "Host subprocess timed out")):
        return "timeout", "Completion unknown; inspect before retrying"
    if exit_code not in (None, 0) or (matches and matches[-1] == "false"):
        return "error", "Call failed; earlier effects may have occurred"
    if matches and matches[-1] == "true":
        return "returned", "Lua returned; queued action needs observation"
    if exit_code == 0:
        return "unverified", "Process exited; no complete Lua marker"
    return "unknown", "Legacy record has no complete result marker"


def observation_turn(stdout):
    match = re.search(r"^\s*(?:\w+:\s*)?(?:S|STATE|TURN)\t(\d+)\t", stdout, re.M)
    return int(match[1]) if match else None


def normalized_response(stdout):
    """Only ignore framing UUIDs/prefixes for duplicate detection; preserve data."""
    lines = []
    for line in stdout.splitlines():
        line = re.sub(r"^\s*\w+:\s*", "", line)
        if re.fullmatch(r"CIV5_\w+_(?:BEGIN|END)(?:\s+(?:true|false))?", line.strip()):
            continue
        if line.strip():
            lines.append(line.rstrip())
    return "\n".join(lines)
