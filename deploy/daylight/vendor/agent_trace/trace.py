"""Local diagnostic traces. Measures transport text, not a model context window."""
from __future__ import annotations

import datetime as dt
import html
import json
import re
from pathlib import Path

from .adapters import civ5


def utc_now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def text_bytes(value):
    return len(value.encode("utf-8"))


def result_details(stdout, stderr, exit_code):
    if exit_code is None:
        return "unknown", "Completion was not recorded"
    if exit_code != 0:
        return "error", "Tool process failed; inspect the result before retrying"
    return "returned", "Tool process returned; inspect results for environment effects"


def assemble(events, *, environment=None):
    calls = {}
    for event in events:
        if event['type'] == 'message':
            continue
        key = event["call_id"]
        if event["type"] == "call_started":
            if key in calls:
                raise ValueError(f"Duplicate call ID: {key}")
            calls[key] = {"id": key, "name": event["name"], "context": event.get("context"),
                          "request": event.get("request"), "turn": event.get("turn"),
                          "turn_source": "request" if event.get("turn") is not None else "unknown",
                          "started_at": event.get("at"), "status": "pending",
                          "detail": "No finish event recorded; completion unknown", "stdout": "", "stderr": "",
                          "duration_ms": None, "exit_code": None, "source": event.get("source"),
                          "provenance": event.get("provenance", "live_capture"),
                          "model_exposure": "unknown", "provider_usage": None,
                          "_environment": environment or event.get("environment", "civ5")}
        elif event["type"] == "call_finished":
            if key not in calls or calls[key]["status"] != "pending":
                raise ValueError(f"Missing or duplicate start for {key}")
            call = calls[key]
            call.update({k: event.get(k) for k in ("stdout", "stderr", "duration_ms", "exit_code")})
            call["stdout"] = call["stdout"] or ""
            call["stderr"] = call["stderr"] or ""
            interpret = civ5.result_details if call['_environment'] == 'civ5' else result_details
            call["status"], call["detail"] = interpret(call["stdout"], call["stderr"], call["exit_code"])
            if event.get('status') is not None:
                if event['status'] not in ('returned', 'error', 'timeout', 'unknown', 'unverified'):
                    raise ValueError('Unknown completion status')
                call['status'] = event['status']
                call['detail'] = event.get('detail') or call['detail']
    previous_turn = None
    duplicates = {}
    total = 0
    for call in calls.values():
        is_civ5 = call.pop("_environment") == "civ5"
        observed = civ5.observation_turn(call["stdout"]) if is_civ5 else None
        if observed is not None:
            call["turn"], call["turn_source"] = observed, "observed"
        elif is_civ5 and call["turn"] is None and previous_turn is not None:
            call["turn"], call["turn_source"] = previous_turn, "last observed (inferred)"
        if is_civ5 and call["turn"] is not None:
            previous_turn = call["turn"]
        call["request_bytes"] = text_bytes(call["request"]) if call["request"] is not None else None
        call["response_bytes"] = text_bytes(call["stdout"]) + text_bytes(call["stderr"])
        total += call["response_bytes"]
        call["cumulative_response_bytes"] = total
        call["duplicate_of"] = None
        if is_civ5 and call["name"] == "status" and call["status"] == "returned":
            normalized = civ5.normalized_response(call["stdout"])
            if normalized in duplicates:
                call["duplicate_of"] = duplicates[normalized]
            else:
                duplicates[normalized] = call["id"]
    return list(calls.values())


def legacy_events(directory):
    """Import numbered captures only. Do not guess requests from rewritten .lua files."""
    files = []
    for path in Path(directory).iterdir():
        match = re.fullmatch(r"(\d+)-(.+)\.txt", path.name)
        if match:
            files.append((int(match[1]), match[2], path))
    events = []
    for seq, name, path in sorted(files):
        text = path.read_bytes().decode("utf-8", errors="replace")
        events.append(dict(type="call_started", call_id=seq, name=name, request=None,
                           source=path.name, provenance="legacy_import", at=None))
        # Old files combined stdout/stderr. Preserve the entire capture in stdout.
        events.append(dict(type="call_finished", call_id=seq, stdout=text, stderr="",
                           exit_code=None, duration_ms=None))
    return events


def read_events(path):
    events = []
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            if i == len(lines) - 1:  # Writer may still be flushing the last event.
                break
            raise
    return events


def render_report(events, output, title="Agent trace", notices=None):
    calls = assemble(events)
    data = {"title": title, "generated_at": utc_now(), "calls": calls,
            "notices": notices or [], "scope": "Harness transport trace; not a captured model prompt."}
    # Escape '<' so even an untrusted game label cannot close this script element.
    payload = json.dumps(data, ensure_ascii=True).replace("<", "\\u003c")
    template = Path(__file__).with_name("trace_viewer.html").read_text(encoding="utf-8")
    result = template.replace("__TITLE__", html.escape(title)).replace("__TRACE_DATA__", payload)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(result, encoding="utf-8")
    temporary.replace(output)
    return calls


class TraceRecorder:
    """Append events before submission and after completion; flush pending calls too."""

    def __init__(self, directory, *, environment="generic"):
        self.environment = environment
        self.directory = Path(directory)
        self.path = self.directory / "trace.jsonl"
        self.directory.mkdir(parents=True, exist_ok=True)
        # Claim a fresh stream before copying metadata; reopening must not regroup it.
        self._stream = self.path.open("x", encoding="utf-8")
        active = self.directory.parent / 'active-session.json'
        if active.exists():
            try:
                metadata = json.loads(active.read_text(encoding='utf-8'))
                (self.directory / 'session.json').write_text(json.dumps(metadata), encoding='utf-8')
            except Exception:
                self._stream.close()
                self.path.unlink()
                raise
        self.events = []

    def append(self, event):
        assemble([*self.events, event])  # Reject invalid events before they corrupt the log.
        self._stream.write(json.dumps(event, ensure_ascii=False) + "\n")
        self._stream.flush()
        self.events.append(event)
        render_report(self.events, self.directory / "trace.html", title=self.directory.name)

    def start(self, call_id, name, context, request, turn=None):
        self.append(dict(type="call_started", call_id=call_id, name=name, context=context,
                         request=request, turn=turn, at=utc_now(), environment=self.environment))

    def finish(self, call_id, stdout, stderr, exit_code, duration_ms, *, status=None, detail=None):
        self.append(dict(type="call_finished", call_id=call_id, stdout=stdout, stderr=stderr,
                         exit_code=exit_code, duration_ms=duration_ms, at=utc_now(),
                         **({"status": status, "detail": detail} if status is not None else {})))

    def close(self):
        self._stream.close()

    def message(self, kind, text, *, rationale=None, action=None, provenance='operator_note'):
        if kind not in ('user', 'prompt', 'agent', 'decision', 'note'):
            raise ValueError('Unknown message kind')
        if not text.strip() or (kind == 'decision' and not (rationale or '').strip()):
            raise ValueError('Messages need text; decisions also need a brief rationale')
        if kind == 'decision' and (not isinstance(action, dict) or
                                   not isinstance(action.get('type'), str) or not action['type'].strip()):
            raise ValueError('Decisions need a concrete action with a type')
        if kind != 'decision' and action is not None:
            raise ValueError('Only decisions carry action metadata')
        if kind == 'prompt' and provenance not in ('actual_outbound_input', 'selected_context'):
            raise ValueError('Label prompts as actual outbound input or selected context')
        self.append(dict(type='message', kind=kind, text=text, rationale=rationale, action=action,
                         provenance=provenance, at=utc_now(), environment=self.environment))
