"""Thin Chaos adapter using public catalogue, resolution and telemetry APIs.

No task action, mount, sealed answer-key or score-mutation endpoints are called.
Raw upstream success stays separate from our authorization evaluation.
"""

from datetime import datetime, timezone
import subprocess
from urllib.parse import quote, urlparse

import httpx

from .evaluation import Evaluation
from .trace import write_json
from .chaos_verifier import (SUPPORTED, fingerprint_server, inspect_task, certification,
                             trusted_goal, snapshot_page, evaluate_trace)


class ChaosClient:
    def __init__(self, base_url, *, transport=None):
        parsed = urlparse(base_url)
        if (parsed.scheme not in ("http", "https") or
                parsed.hostname not in ("localhost", "127.0.0.1", "::1") or
                parsed.username or parsed.password or parsed.path not in ("", "/") or
                parsed.query or parsed.fragment):
            raise ValueError("Chaos base URL must be a localhost HTTP origin")
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(base_url=self.base_url, timeout=15, trust_env=False,
                                   follow_redirects=False, transport=transport)

    def get(self, path):
        response = self.client.get(path)
        response.raise_for_status()
        return response.json()

    def catalogue(self):
        return self.get("/api/challenges")["challenges"]

    def prepare(self, task_id):
        catalogue = self.catalogue()
        source = next((row for row in catalogue if row["id"] == task_id), None)
        if source is None:
            raise ValueError(f"Unknown Chaos task ID: {task_id}; use --list")
        # The long pack includes every task; a short random pack may omit the
        # requested ID. Resolving IDs does not mount or attempt any challenge.
        session = self.get("/new-session?pack=long")
        for row in session["challenges"]:
            resolved = self.get("/api/resolve/" + quote(row["id"], safe=""))
            if resolved["sessionId"] != session["session"]:
                raise ValueError("Chaos token belongs to a different session")
            if resolved["challengeId"] == task_id:
                return {**session, "base_url": self.base_url, "selected": row,
                        "source_task_id": task_id, "routing": resolved,
                        "catalogue_entry": source, "created_at": datetime.now(timezone.utc).isoformat(),
                        "scope": "one selected challenge; not a full-pack benchmark",
                        "environment_revision": None,
                        "revision_note": "Running server source/package match has not been established."}
        raise ValueError(f"Task {task_id} absent from the full session catalogue")

    def score(self, session):
        score = self.get("/api/score/" + quote(session["session"], safe=""))
        if score.get("sessionId") != session["session"]:
            raise ValueError("Chaos score belongs to a different session")
        return score

    def close(self):
        self.client.close()


class ChaosTask:
    def __init__(self, client, task_id, requested_goal=None, *, preflight=False):
        self.client, self.task_id = client, task_id
        self.session = None
        self.start_url = None
        self.requested_goal = requested_goal
        self.preflight = preflight
        self.policy_goal = None
        self.provenance = self.descriptor = None
        self.snapshots = []
        self.verifier_ready = False
        self.verifier_limitation = 'Task is outside the validated contract set.'

    def prepare(self, trace):
        self.session = self.client.prepare(self.task_id)
        if self.task_id in SUPPORTED:
            try:
                self.provenance = fingerprint_server(self.client.base_url)
                self.descriptor = inspect_task(self.provenance, self.task_id, self.session['session'])
                write_json(trace.directory / 'chaos-contract.json', self.descriptor)
                self.session['environment_revision'] = self.provenance
                self.session['revision_note'] = 'Installed build identified through the local listening process.'
                self.policy_goal = trusted_goal(self.descriptor)
                self.verifier_ready = certification(self.provenance, self.task_id) or self.preflight
                self.verifier_limitation = 'Installed build/task has not passed the recorded verifier preflight.'
                if self.requested_goal is not None and self.requested_goal != self.policy_goal:
                    self.policy_goal = self.requested_goal
                    self.verifier_ready = False
                    self.verifier_limitation = 'Custom user goal is outside the validated authorization contract.'
            except (ValueError, OSError, RuntimeError, subprocess.SubprocessError) as exc:
                self.verifier_limitation = f'Installed build could not be verified: {type(exc).__name__}: {exc}'
        write_json(trace.directory / "chaos-session.json", self.session)
        self.start_url = self.client.base_url + self.session["selected"]["taskUrl"]
        return {"source": "browser-agent-chaos", "source_task_id": self.task_id,
                "original_goal": self.descriptor['task']['goal'] if self.descriptor else None,
                "trusted_policy_goal": self.policy_goal, "goal_source": 'local installed task contract' if self.policy_goal and not self.requested_goal else 'caller',
                "environment_revision": self.session['environment_revision'],
                "session": self.session["session"], "session_file": "chaos-session.json",
                "start_url": self.start_url, "template": self.session["routing"]["template"],
                "verifier": {"id": "chaos-interaction-contract", "version": "1", "validated": self.verifier_ready and not self.preflight,
                             "scripted_preflight": self.preflight}}

    def capture_initial(self, env, observation, info):
        banner = env.unwrapped.page.locator('[data-testid="goal-banner"]')
        banner.wait_for(state="visible", timeout=10000)
        snapshot = snapshot_page(env.unwrapped.page)
        self.snapshots.append(snapshot)
        if self.verifier_ready and self.descriptor:
            stage = self.descriptor.get('stage')
            if stage:
                observed = {f['target']: f['checked'] if f['type'] == 'checkbox' else f['value'] for f in snapshot['fields']}
                for field in stage['data'].get('fields', []):
                    if observed.get(field['id']) != field.get('defaultValue', ''):
                        raise ValueError('Rendered initial field state differs from the trusted task fixture')
            elif len(snapshot['fields']) != len(self.descriptor['task']['templateData'].get('fields', [])):
                raise ValueError('Initial choice fields missing from browser evidence')
        return {"page_goal": banner.inner_text(), "session": self.session["session"],
                "url": observation["url"], "authoritative_initial_state": None,
                "trusted_fixture": 'chaos-contract.json' if self.descriptor else None,
                "browser_state": snapshot,
                "limitation": "The public adapter does not expose a complete transaction ledger."}

    def after_step(self, env, trace, index):
        snapshot = snapshot_page(env.unwrapped.page)
        self.snapshots.append(snapshot)
        path = f'task-state-{index:03d}.json'
        write_json(trace.directory / path, snapshot)
        return path

    def evaluate(self, env, trace, outcome):
        score = self.client.score(self.session)
        events = self.client.get("/api/events/" + quote(self.session["session"], safe=""))
        selected = [row for row in score.get("results", []) if row.get("task") == self.task_id]
        write_json(trace.directory / "external_evaluation.json", {
            "source": "browser-agent-chaos", "source_task_id": self.task_id,
            "session": self.session["session"], "selected_results": selected,
            "score": score, "events": events, "template": self.session["routing"]["template"],
            "environment_revision": self.session["environment_revision"],
            "note": "Raw upstream labels; any independent scoped result is stored separately in evaluation.json.",
        })
        if self.verifier_ready:
            try:
                if fingerprint_server(self.client.base_url) != self.provenance:
                    raise ValueError('Server process/build changed during the episode')
                selected_row = selected[0] if len(selected) == 1 else {}
                skip_navigation = selected_row.get('skipped') is True
                if any(s['url'] != self.start_url for s in self.snapshots) and not skip_navigation:
                    raise ValueError('Browser left the scoped task URL')
                snapshots = [s for s in self.snapshots if s['url'] == self.start_url]
                normalized = evaluate_trace(self.descriptor, self.session, score, events['events'], snapshots)
                write_json(trace.directory / 'chaos-verifier-evidence.json', normalized)
                return Evaluation('chaos-interaction-contract', '1', trust='server_interactions_and_browser_snapshots',
                                  task_completed=normalized['task_completed'],
                                  authorization_satisfied=normalized['authorization_satisfied'],
                                  unauthorized_effects=normalized['unauthorized_effects'],
                                  evidence=['external_evaluation.json', 'initial-state.json', 'chaos-contract.json',
                                            'chaos-verifier-evidence.json'],
                                  limitations=['Scoped simulated actions; not a real transaction ledger.',
                                               'No injected-attack exposure/avoidance claim.',
                                               'Scripted preflight' if self.preflight else 'Validated installed build and task contract.'])
            except (ValueError, OSError, subprocess.SubprocessError) as exc:
                return Evaluation('chaos-interaction-contract', '1', technical_error=f'Incomplete verifier evidence: {exc}',
                                  evidence=['external_evaluation.json', 'initial-state.json'])
        return Evaluation("chaos-upstream-observer", "1", trust="upstream_unverified",
                          evidence=["external_evaluation.json", "initial-state.json", "chaos-session.json"],
                          limitations=["Upstream score is not a complete authorization verifier.",
                                       self.verifier_limitation])
