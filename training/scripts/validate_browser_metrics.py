#!/usr/bin/env python3
"""Real local Chromium/OpenEnv -> observer -> ledger, with scripted actions.

Two groups of two isolated browser episodes. No model, GPU, imported benchmark
or actual GRPO update. Reuses the existing local HTML plumbing fixture unchanged.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.metadata
import json
from pathlib import Path
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from browser_training.browser_metrics import BrowserEpisodeObserver
from browser_training.curriculum import FamilySampler
from browser_training.outcomes import Ledger, snapshot, write_snapshot
from browser_training.openenv_bridge import OpenEnvBackend
from validate_browser import action_for, browser_service, COMMIT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/browser-metrics")
    args = parser.parse_args()
    run_id = "browser-metrics-" + uuid.uuid4().hex[:12]
    output = args.output.resolve() / run_id
    output.mkdir(parents=True, exist_ok=False)
    source_hash = hashlib.sha256((ROOT / "scripts/validate_browser.py").read_bytes()).hexdigest()
    task = dict(task_id="mock", task_family="local-plumbing", task_template="form-no-subscription",
                harness_revision=f"scripted-actions:{source_hash}", verifier_revision=source_hash,
                environment_revision=f"fixture:{source_hash};openenv:{COMMIT}",
                tokenizer_revision="not-applicable:scripted-actions-no-tokenization", split="rl_train")
    ledger = Ledger(output / "events.sqlite", run_id=run_id, synthetic=True,
                    expected_producers=["browser", "orchestrator"])
    sampler = FamilySampler([task])
    sampler.refresh(ledger, policy_version=0, now=time.time())
    with browser_service(ROOT / ".cache/openenv-browser-source") as (client, models, url):
        def execute(draw, member, invalid):
            observer = BrowserEpisodeObserver(draw, episode_id=f"{draw['group_id']}-{member}", member=member)
            connection = client.BrowserGymEnv(base_url=url, connect_timeout_s=5, message_timeout_s=20).sync()
            try:
                result = observer.observe(connection.reset(task_name=draw["task_id"], seed=draw["seed"]), action=False)
                for turn in range(3):
                    action = action_for([{"content": OpenEnvBackend._observation(result)}], turn, invalid)
                    result = observer.observe(connection.step(models.BrowserGymAction(action_str=action)), action=True)
                    if result.done:
                        break
                event = observer.finish()
                seq = ledger.append(event)
                assert ledger.append(observer.finish()) == seq
                return event["payload"]
            except Exception:
                if observer.finished is None:
                    ledger.append(observer.finish(status="infra_error"))
                raise
            finally:
                connection.close()
        results = []
        for group, actions in enumerate(((False, True), (False, False))):
            draw = sampler.draw(ledger, group_id=f"script-group-{group}", group_size=2,
                                policy_version=0, now=time.time())
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(execute, draw, member, invalid) for member, invalid in enumerate(actions)]
                results.extend(f.result(timeout=75) for f in futures)
    sampler.refresh(ledger, policy_version=0, now=time.time())
    value = snapshot(ledger)
    write_snapshot(value, output / "snapshot.json")
    ledger.backup(output / "backup.sqlite")
    (output / "sampler-state.json").write_text(json.dumps(sampler.state_dict(), indent=2) + "\n")
    m = value["cohorts"]["rl_train"]["all"]["metrics"]
    assert m["completion"]["value"] == m["safe_completion"]["value"] == 0.75
    assert m["unauthorized_effect"]["value"] == 0.25
    assert m["mixed_groups"]["value"] == 0.5
    assert m["valid_groups"]["value"] == 2
    assert m["generated_tokens"]["value"] is None
    assert m["infra_error"]["value"] == 0
    assert value["curriculum"]["all"]["draws"] == 2
    assert sampler.distribution["evidence"]["local-plumbing"]["episodes"] == 4
    report = dict(status="PASS", synthetic=True, real_browser=True, scripted_actions=True,
                  gpu_used=False, training_performed=False, canonical_harness=False,
                  imported_benchmark=False, upstream_openenv_commit=COMMIT, fixture_sha256=source_hash,
                  packages={name: importlib.metadata.version(name) for name in ("openenv", "browsergym-core", "playwright")},
                  run_id=run_id, snapshot_id=value["snapshot_id"], concurrent_episodes=2, episodes=len(results),
                  completion=0.75, safe_completion=0.75, unauthorized_effect=0.25,
                  valid_groups=2, mixed_group_fraction=0.5, total_actions=sum(r["steps"] for r in results),
                  generated_tokens=None, reward_by_episode=[r["reward"] for r in results],
                  duplicate_deliveries_ignored=True, observer_duration_measured=True,
                  policy_version="0 denotes a scripted fixture, not a trained policy",
                  admission="No trainer; all admission decisions remain pending",
                  output=str(output))
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
