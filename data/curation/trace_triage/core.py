"""Evidence extraction and trajectory comparison, deliberately without causal labels."""
from __future__ import annotations

import ast
from collections import Counter, defaultdict
from difflib import SequenceMatcher
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlsplit, urlunsplit
from .metrics import request_metrics, aggregate, metric_flags, thresholds

VERSION = "browser-triage-v1"
MAX_BYTES = 64 * 1024 * 1024
MAX_STEPS = 2000
BID_LINE = re.compile(r"^(\s*)\[([^\]]+)\]\s+(.*)$")
NAME = re.compile(r'''^(\w+)\s+('(?:\\.|[^'\\])*'|"(?:\\.|[^"\\])*")''')
TARGET_ACTIONS = {"click", "dblclick", "hover", "fill", "clear", "select_option",
                  "check", "uncheck", "focus", "press", "upload_file"}
PRIORITIES = {"evaluation_conflict": 100, "decision_error": 95,
              "authorization_check_failed": 90, "action_error": 85,
              "target_id_semantics_changed": 80, "target_absent_from_input": 80,
              "feedback_not_in_next_input": 70, "output_truncated": 70,
              "observation_not_in_request": 75, "input_evidence_unavailable": 65,
              "repeated_action": 50, "state_revisit": 40, "step_limit_reached": 35,
              "task_incomplete": 30}


def digest(value):
    if not isinstance(value, bytes):
        value = json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    return hashlib.sha256(value).hexdigest()


class Evidence:
    """Bounded local reads; retain exact bytes for immutable derivative exports."""
    def __init__(self, directory):
        self.root = Path(directory).resolve()
        self.files = {}
        self.total = 0

    def read(self, name, optional=False):
        if not isinstance(name, str) or not name or Path(name).is_absolute() or ".." in Path(name).parts:
            raise ValueError("Invalid trace-relative artifact path")
        path = self.root / name
        if any(p.is_symlink() for p in [path, *path.parents] if p != self.root.parent):
            raise ValueError(f"Symlink artifact rejected: {name}")
        if not path.exists() and optional:
            return None
        if not path.is_file():
            raise ValueError(f"Missing/non-file artifact: {name}")
        if name not in self.files:
            if self.total + path.stat().st_size > MAX_BYTES:
                raise ValueError("Trace read budget exceeded")
            data = path.read_bytes()
            self.total += len(data)
            if self.total > MAX_BYTES:
                raise ValueError("Trace read budget exceeded")
            self.files[name] = data
        return self.files[name]

    def json(self, name, optional=False):
        raw = self.read(name, optional)
        return json.loads(raw) if raw is not None else None

    def text(self, name):
        return self.read(name).decode("utf-8")

    def unchanged(self):
        return all(not (self.root / n).is_symlink() and
                   (self.root / n).read_bytes() == b for n, b in self.files.items())


def message_text(messages):
    """Only retained request content, including text parts of multimodal inputs."""
    parts = []
    for m in messages:
        if not isinstance(m, dict):
            continue
        content = m.get("content")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            parts.extend(p["text"] for p in content if isinstance(p, dict)
                         and p.get("type") in ("text", "input_text") and isinstance(p.get("text"), str))
    return "\n".join(parts)


def ax_nodes(text):
    """Conservative AX role/name + named ancestor identity; retain original line."""
    nodes, stack = {}, []
    for line in text.splitlines():
        match = BID_LINE.match(line)
        if not match:
            continue
        indent, bid, body = match.groups()
        depth = len(indent.expandtabs(4))
        while stack and stack[-1][0] >= depth:
            stack.pop()
        named = NAME.match(body)
        if named:
            role = named[1]
            try:
                name = ast.literal_eval(named[2])
            except (ValueError, SyntaxError):
                name = named[2]
            identity = f"{role} {json.dumps(name, ensure_ascii=False)}"
        else:
            role, name, identity = body.split(" ", 1)[0], "", body
        ancestors = [x[1] for x in stack if x[2]][-2:]
        node = {"role": role, "name": name, "identity": identity,
                "ancestors": ancestors, "line": line.strip(), "bid": bid}
        if bid in nodes:  # Ambiguous flattening must not choose one target silently.
            nodes[bid] = None
        else:
            nodes[bid] = node
        stack.append((depth, identity, bool(name)))
    return nodes


def url_key(text):
    line = next((s[5:] for s in text.splitlines() if s.startswith("URL: ")), "")
    try:
        u = urlsplit(line)
        # Local ephemeral ports are incidental; query values and paths are not.
        host = "local-fixture" if u.hostname in ("localhost", "127.0.0.1", "::1") else u.netloc
        return urlunsplit((u.scheme, host, u.path, u.query, u.fragment))
    except ValueError:
        return line


def state_key(text):
    tree = text.split("Accessibility tree:\n", 1)[-1]
    tree = re.sub(r"(?m)^(\s*)\[[^\]]+\] ", r"\1", tree)
    tree = re.sub(r", focused(?=,|$)", "", tree, flags=re.M)
    return digest([url_key(text), tree]) if text else None


def action_info(code, nodes):
    result = {"raw": code, "tool": None, "target": None, "bid": None,
              "parseable": False, "signature": None}
    if not isinstance(code, str):
        return result
    try:
        call = ast.parse(code.strip(), mode="eval").body
        if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name):
            return result
        args = [ast.literal_eval(a) for a in call.args]
        kwargs = {k.arg: ast.literal_eval(k.value) for k in call.keywords if k.arg is not None}
        if any(k.arg is None for k in call.keywords):
            return result
        tool = call.func.id
        bid = str(args[0]) if tool in TARGET_ACTIONS and args else str(kwargs["bid"]) if tool in TARGET_ACTIONS and "bid" in kwargs else None
        node = nodes.get(bid) if bid is not None else None
        semantic_args = list(args)
        semantic_kwargs = dict(kwargs)
        if bid is not None:
            target = {"identity": node["identity"], "ancestors": node["ancestors"]} if node else {"unresolved_bid": bid}
            if args:
                semantic_args[0] = target
            else:
                semantic_kwargs["bid"] = target
        result.update(tool=tool, bid=bid, target=node, parseable=True,
                      signature=json.dumps([tool, semantic_args, semantic_kwargs], sort_keys=True, ensure_ascii=False))
    except (SyntaxError, ValueError, TypeError, RecursionError):
        pass
    return result


def feedback(text):
    """Only AX alert/status subtree text; no generic success-word inference."""
    found, active, depth = [], False, -1
    for line in text.splitlines():
        match = BID_LINE.match(line)
        current_depth = len(line[:len(line)-len(line.lstrip())].expandtabs(4))
        if active and line.strip() and current_depth <= depth:
            active = False
        body = match[3] if match else line.strip()
        if re.match(r"(?:alert|status)(?:\s|$)", body):
            active, depth = True, current_depth
        if active:
            named = NAME.match(body)
            if named:
                try:
                    value = ast.literal_eval(named[2])
                    if value and value not in found:
                        found.append(value)
                except (SyntaxError, ValueError):
                    pass
    return found


def analyze(directory, metric_thresholds=None):
    ev = Evidence(directory)
    meta = ev.json("episode.json", optional=True)
    finished = meta is not None
    if meta is None:
        meta = ev.json("metadata.json")
    if not isinstance(meta, dict):
        raise ValueError("Episode metadata must be an object")
    steps_name = meta.get("steps_file", "steps.jsonl")
    steps = [json.loads(line) for line in ev.text(steps_name).splitlines() if line.strip()]
    if len(steps) > MAX_STEPS or any(not isinstance(s, dict) for s in steps):
        raise ValueError("Unsupported step count/shape")
    indices = [s.get("step") for s in steps]
    if any(type(x) is not int for x in indices) or indices != sorted(set(indices)):
        raise ValueError("Step IDs must be unique ordered integers")
    evaluation_file = meta.get("evaluation_file", "evaluation.json")
    evaluation = ev.json(evaluation_file, optional=True)
    if evaluation is not None and not isinstance(evaluation, dict):
        raise ValueError("Evaluation must be an object")
    recorded = evaluation if evaluation is not None else meta.get("evaluation")
    if recorded is not None and not isinstance(recorded, dict):
        raise ValueError("Embedded evaluation must be an object")
    case = meta.get("development_case") or meta.get('suite_case') or {}
    if not isinstance(case, dict):
        case = {}
    flags, timeline, metric_rows = [], [], []
    metric_config = thresholds(metric_thresholds)
    additional_evidence = {}
    for name in (recorded or {}).get('evidence', []) or []:
        if isinstance(name, str):
            try:
                raw = ev.read(name, optional=True)
                additional_evidence[name] = 'retained' if raw is not None else 'missing'
            except ValueError:
                additional_evidence[name] = 'unavailable_or_unsafe_path'
    # Supplemental graders are evidence, never substitutes for the original verdict.
    if ev.read('native-evaluation.json', optional=True) is not None:
        additional_evidence['native-evaluation.json'] = 'retained_supplemental_not_promoted'

    def flag(code, step, detail, artifacts, **extra):
        flags.append({"code": code, "step": step, "priority": PRIORITIES.get(code, 50),
                      "detail": detail, "evidence": artifacts, "causal_label": None, **extra})

    conflict = evaluation is not None and meta.get("evaluation") is not None and evaluation != meta["evaluation"]
    if conflict:
        flag("evaluation_conflict", None, "episode.json and evaluation artifact differ; comparison outcome withheld.",
             ["episode.json", evaluation_file])
    safe = (recorded or {}).get("safe_success")
    if safe is not None and type(safe) is not bool:
        raise ValueError("safe_success must be boolean or null")
    outcome = "success" if safe is True else "failure" if safe is False else "unknown"
    if conflict or not finished:
        outcome = "unknown"
    goal, previous, prior_nodes = None, None, {}
    states = {}
    for s in steps:
        i = s["step"]
        ref = s.get("observation") or {}
        text_name = ref.get("text")
        text = ev.text(text_name) if text_name else ""
        request = s.get("model_request")
        messages = request.get("messages") if isinstance(request, dict) else None
        have_request = isinstance(messages, list)
        delivered = message_text(messages) if have_request else None
        present = text in delivered if text and have_request else None
        if goal is None and have_request:
            for m in messages:
                if isinstance(m, dict) and m.get("role") == "user" and isinstance(m.get("content"), str):
                    match = re.search(r"^USER GOAL: (.*?)(?:\nRecent actions:|\Z)", m["content"], re.S)
                    if match:
                        goal = match[1]
                        break
        if not have_request:
            flag("input_evidence_unavailable", i, "No retained request messages; no claim about delivered observation.", [steps_name])
        elif text and not present:
            flag("observation_not_in_request", i, "Selected observation is not an exact substring of retained request text.", [steps_name, text_name])
        # Resolve against the selected AX ONLY when its delivery is evidenced.
        nodes = ax_nodes(text) if present else {}
        info = action_info(s.get("action"), nodes)
        bid, target = info["bid"], info["target"]
        if bid is not None and present and bid not in nodes:
            flag("target_absent_from_input", i, "Action target ID absent from selected AX included in the request; not proof of DOM staleness.", [steps_name, text_name], bid=bid)
        if target and bid in prior_nodes and prior_nodes[bid] and (target["identity"], target["ancestors"]) != (prior_nodes[bid]["identity"], prior_nodes[bid]["ancestors"]):
            flag("target_id_semantics_changed", i, "Selected ID refers to a different role/name/context than in previous decision; the action may still be intentional.",
                 [steps_name, previous["observation_text"], text_name], before=prior_nodes[bid], after=target)
        if s.get("action_error"):
            flag("action_error", i, str(s["action_error"]), [steps_name])
        if s.get("error"):
            flag("decision_error", i, str(s["error"]), [steps_name], phase=s.get("failure_phase"))
        raw = s.get("model_response")
        choices = raw.get("choices") if isinstance(raw, dict) else None
        if isinstance(choices, list) and any(isinstance(c, dict) and c.get("finish_reason") == "length" for c in choices):
            flag("output_truncated", i, "Provider reported finish_reason=length; no inference about why.", [steps_name])
        state = state_key(text) if present else None
        if state is not None and state in states:
            flag("state_revisit", i, "AX text and URL repeat after removing element IDs/focus and local port; hidden state may differ.",
                 [states[state][1], text_name], previous_step=states[state][0])
        if state:
            states[state] = (i, text_name)
        if previous and info["signature"] and info["signature"] == previous["action"]["signature"]:
            flag("repeated_action", i, "Consecutive semantic action repeats; may be required by the goal or recovery.", [steps_name], previous_step=previous["step"])
        if previous and have_request and previous["next_observation_text"]:
            post_name = previous["next_observation_text"]
            post = ev.text(post_name)
            missing = [f for f in feedback(post) if f not in delivered]
            if missing:
                flag("feedback_not_in_next_input", i, "Alert/status text after previous action is absent from all retained next-request text. Notification is not transaction proof.",
                     [post_name, steps_name] + ([text_name] if text_name else []), after_step=previous["step"], missing_text=missing)
        next_ref = s.get("next_observation") or {}
        next_name = next_ref.get("text")
        if next_name:
            ev.read(next_name)
        row = {"step": i, "action": info, "model_output": s.get("model_output"),
               "observation_text": text_name, "next_observation_text": next_name,
               "observation_in_retained_request": present,
               "request_evidence": "retained_request" if have_request else "unknown",
               "backend_completion_recorded": (s.get("model_response") is not None
                                               and s.get("model_output") is not None
                                               and s.get("failure_phase") != "model"),
               "url": url_key(text), "state_signature": state,
               "next_state_signature": state_key(ev.text(next_name)) if next_name else None,
               "action_error": s.get("action_error"), "error": s.get("error"),
               "failure_phase": s.get("failure_phase"), "screenshot": ref.get("screenshot"),
               "browser_stepped": s.get("browser_stepped")}
        metric = request_metrics(s)
        metric_rows.append(metric)
        if isinstance(s.get('batch_calls'), list):
            row['batch_actions'] = []
            for member in s['batch_calls']:
                if not isinstance(member, dict): continue
                item = {key:member.get(key) for key in ('batch_call','tool_call_id','execution_index',
                    'not_executed','browser_stepped','action_error','tool_error','error')}
                item['action'] = action_info(member.get('action'), nodes)
                # Resolve against selected, delivered AX only. A refreshed guard
                # is review evidence, not newly delivered target information.
                item['target_resolution_scope'] = 'selected decision AX only; historical tool results not indexed'
                row['batch_actions'].append(item)
                if member.get('action_error') or member.get('tool_error') or member.get('error'):
                    flag('action_error', i, str(member.get('action_error') or member.get('tool_error') or member.get('error')),
                         [steps_name], batch_call=member.get('batch_call'))
        row['usage'] = metric
        row['native_tool_calls'] = (s.get('assistant_tool_message') or {}).get('tool_calls')
        row['policy_delivery'] = s.get('policy_delivery')
        timeline.append(row)
        previous, prior_nodes = row, nodes
    if (recorded or {}).get("authorization_satisfied") is False:
        flag("authorization_check_failed", None, "Recorded verifier reports authorization=false; do not infer a specific side effect or its first step without journal evidence.", [evaluation_file if evaluation is not None else "episode.json"])
    if (recorded or {}).get("task_completed") is False:
        flag("task_incomplete", None, "Recorded verifier reports task_completed=false.", [evaluation_file if evaluation is not None else "episode.json"])
    if meta.get("stop_reason") == "max_steps" or (finished and type(meta.get("max_steps")) is int and len(steps) >= meta["max_steps"] and meta.get("stop_reason") not in ("agent_finished", "terminated", "error")):
        flag("step_limit_reached", indices[-1] if indices else None, "Recorded run reached its configured step limit; mechanism unresolved.", ["episode.json"])
    metrics = aggregate(metric_rows)
    for code, step, detail in metric_flags(metric_rows, metrics, metric_config):
        flag(code, step, detail, [steps_name], layer='operational')
    apparent_success = safe is True or (recorded or {}).get('task_completed') is True
    if apparent_success:
        if safe is True and ((recorded or {}).get('task_completed') is False or (recorded or {}).get('authorization_satisfied') is False):
            flag('success_verdict_contradiction', None, 'Recorded safe success contradicts a recorded completion/authorization check. Review grader integrity; no grade changed.', [evaluation_file if evaluation is not None else 'episode.json'], layer='integrity')
        if any(s['error'] or s['action_error'] or any(m['error'] or m['action_error'] or m['tool_error'] for m in s.get('batch_actions',[])) for s in timeline):
            flag('completion_with_errors', None, 'Recorded completion/pass coexists with an error. Recovery may be valid; inspect the outcome evidence.', [steps_name], layer='integrity')
        if not any(m['action']['parseable'] and not m.get('not_executed') and
                   m['action']['tool'] not in ('send_msg_to_user','noop','web_search','ax_read','ax_search','ax_changes','screenshot','release_image')
                   for s in timeline for m in s.get('batch_actions',[s])):
            flag('completion_without_state_action', None, 'No parsed state-changing action recorded before completion/pass. Read-only goals or valid initial state can explain this.', [steps_name], layer='integrity')
    flags.sort(key=lambda f: (-f["priority"], f["step"] if f["step"] is not None else -1, f["code"]))
    source, task = meta.get("source") or case.get("source") or case.get('family'), meta.get("task") or case.get("task")
    if any(v is not None and not isinstance(v, str) for v in (source, task)):
        raise ValueError('Unsupported non-string source/task identity')
    if not isinstance(meta.get('episode_id', ev.root.name), str):
        raise ValueError('Episode identity must be a string')
    technical = (recorded or {}).get("technical_error") or meta.get("error")
    result = {"format": VERSION, "episode_id": meta.get("episode_id", ev.root.name),
              "source_path": str(ev.root), "source": source, "task": task,
              "condition": case.get("condition"), "case_id": case.get("case_id"),
              "pair_id": case.get("pair_id"), "goal": goal, "goal_sha256": digest(goal) if goal is not None else None,
              "model": meta.get("model"), "generation": meta.get("generation"),
              "runtime": meta.get("runtime"), "profile_sha256": meta.get("profile_sha256"),
              "harness_profile": meta.get('harness_profile'), 'driver': meta.get('driver'),
              'suite_profile_sha256': meta.get('suite_profile_sha256'),
              'operational_metrics': metrics, 'metric_thresholds': metric_config,
              'resolved_providers': metrics['providers'], 'resolved_models': metrics['resolved_models'],
              'apparent_success': apparent_success, 'additional_evidence': additional_evidence,
              "recorded_evaluation": recorded, "evaluation_recomputed": False,
              'action_counts': {
                  'recorded':sum(m['action']['parseable'] for s in timeline for m in s.get('batch_actions',[s])),
                  'skipped':sum(bool(m.get('not_executed')) for s in timeline for m in s.get('batch_actions',[s])),
                  'returned_browser_steps':sum(m.get('browser_stepped') is True and not m.get('not_executed') for s in timeline for m in s.get('batch_actions',[s]))},
              "outcome_group": outcome, "technical_error": technical, "finished_record_present": finished,
              "evaluation_conflict": conflict, "flags": flags, "timeline": timeline,
              "diagnosis": {"status": "unreviewed", "primary_failure": None, "secondary_failures": [],
                            "first_suspicious_step": None, "first_violation_step": None,
                            "irreversible_step": None, "recovery": None},
              "source_artifacts": {n: {"sha256": digest(b), "bytes": len(b)} for n, b in sorted(ev.files.items())}}
    return result, ev


def tokens(episode):
    # One comparison token per model decision keeps alignment indices valid.
    # Batch identity includes ordered members and skipped status; unresolved BIDs
    # never match different episodes just because their incidental IDs agree.
    result=[]
    for s in episode['timeline']:
        values=[]
        for ordinal,m in enumerate(s.get('batch_actions',[s])):
            action=m['action']
            value=(action['signature'] if action['signature'] and not
                   (action['bid'] is not None and action['target'] is None) else
                   f"unresolved:{episode['source_path']}:{s['step']}" + (f":{ordinal}" if 'batch_actions' in s else ''))
            values.append(('skipped:' if m.get('not_executed') else '')+value)
        result.append('batch:'+digest(values) if 'batch_actions' in s else values[0])
    return result


def compare(left, right):
    a, b = tokens(left), tokens(right)
    alignment = SequenceMatcher(None, a, b, autojunk=False)
    prefix = 0
    for x, y in zip(a, b):
        if x != y:
            break
        prefix += 1
    blocks, divergence = [], None
    for op, i, j, k, l in alignment.get_opcodes():
        row = {"kind": op, "left_steps": [s["step"] for s in left["timeline"][i:j]],
               "right_steps": [s["step"] for s in right["timeline"][k:l]]}
        blocks.append(row)
        if op != "equal" and divergence is None:
            divergence = row
    prefix_differences = []
    for i in range(prefix):
        x, y = left["timeline"][i], right["timeline"][i]
        changed = [key for key in ("state_signature", "next_state_signature", "action_error", "error") if x[key] != y[key]]
        if changed:
            prefix_differences.append({"left_step": x["step"], "right_step": y["step"], "fields": changed})
    same_goal = left["goal_sha256"] is not None and left["goal_sha256"] == right["goal_sha256"]
    differences = [k for k in ("goal_sha256", "condition", "model", "generation", "runtime", "profile_sha256", 'suite_profile_sha256', 'harness_profile', 'driver', 'resolved_providers', 'resolved_models') if left.get(k) != right.get(k)]
    return {"left": left["episode_id"], "right": right["episode_id"],
            "similarity": round(alignment.ratio(), 4), "common_action_prefix": prefix,
            "first_action_divergence": divergence, "prefix_evidence_differences": prefix_differences,
            "alignment": blocks, "same_goal": same_goal, "differing_context_fields": differences,
            "causal_comparison": False,
            "warning": "Sequence similarity is a review aid, not a causal explanation. Equal actions may see different states or produce different effects."}


def group_and_compare(episodes, neighbors=3):
    groups = defaultdict(list)
    for e in episodes:
        for code in sorted({f["code"] for f in e["flags"]}):
            groups[("flag", code)].append(e["episode_id"])
        groups[("outcome", e["outcome_group"])].append(e["episode_id"])
        groups[('driver', str(e.get('driver') or 'unknown'))].append(e['episode_id'])
        for provider in e.get('resolved_providers', []):
            groups[('provider', provider)].append(e['episode_id'])
        groups[("task", json.dumps([e["source"], e["task"]]))].append(e["episode_id"])
        # Exact semantic sequences, not raw IDs. Unknown signatures are episode-unique.
        groups[("trajectory", digest(tokens(e)))].append(e["episode_id"])
        for s in e["timeline"]:
            if s["action_error"] or s["error"]:
                error = s["action_error"] or s["error"]
                groups[("error", error.splitlines()[0])].append(e["episode_id"])
    # Neighborhoods have explicit center-to-member thresholds, not transitive
    # clusters that could group endpoints with no actual similarity.
    buckets = defaultdict(list)
    for e in episodes:
        if e['task']:
            buckets[(e['source'], e['task'])].append(e)
    neighborhoods = []
    for bucket in buckets.values():
        for center in bucket:
            members = []
            for other in bucket:
                if other is center:
                    continue
                c = compare(center, other)
                if c['similarity'] >= 0.75:
                    members.append({'episode_id': other['episode_id'], 'similarity': c['similarity'],
                                    'same_goal': c['same_goal'], 'differing_context_fields': c['differing_context_fields']})
            if members:
                neighborhoods.append({'center': center['episode_id'], 'threshold': 0.75, 'members': members})
                groups[('trajectory_neighborhood', center['episode_id'])] = [center['episode_id']] + [m['episode_id'] for m in members]
    comparisons, unmatched = [], []
    for e in episodes:
        candidates = []
        for good in episodes:
            if good is e or good["outcome_group"] != "success" or not e["task"] or (good["source"], good["task"]) != (e["source"], e["task"]):
                continue
            if good["technical_error"] or good["evaluation_conflict"]:
                continue
            c = compare(e, good)
            c["comparison_scope"] = "same_goal" if c["same_goal"] else "same_task_different_or_unknown_goal"
            c['comparison_kind'] = 'success_integrity' if e.get('apparent_success') else 'failure_or_unknown_to_success'
            c['source_identity_known'] = bool(e['source'])
            candidates.append(c)
        candidates.sort(key=lambda c: (-int(c["same_goal"]), -c["similarity"], -c["common_action_prefix"], c["right"]))
        comparisons.extend(candidates[:neighbors])
        if not candidates:
            unmatched.append({"episode_id": e["episode_id"], "reason": "No recorded safe success in the same known source/task; no cross-task substitute chosen."})
    return {"groups": [{"kind": k[0], "key": k[1], "episodes": sorted(set(v))} for k, v in sorted(groups.items())],
            "comparisons": comparisons, "trajectory_neighborhoods": neighborhoods,
            "without_success_comparison": unmatched,
            "outcomes": dict(Counter(e["outcome_group"] for e in episodes))}
