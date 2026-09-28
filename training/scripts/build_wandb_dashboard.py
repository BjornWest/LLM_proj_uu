#!/usr/bin/env python3
"""Build/update the annotated W&B report. Read-only unless --publish is supplied.

Does not start training, create runs, alter metrics or enable public sharing.
The saved state records the report URL so subsequent publications update it.
"""
import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from browser_training.dashboard import build_overview, build_diagnostics, sections, signature
from browser_training.metric_catalog import TELEMETRY
from browser_training.monitoring_io import credentials_from_project_env, load_wandb_snapshot, scalar_metrics


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", action="append", help="Explicit focus run(s); experiment panels always exclude synthetic runs")
    parser.add_argument("--project", default="browser-training")
    parser.add_argument("--entity")
    parser.add_argument("--browser-suite")
    parser.add_argument("--generic-suite")
    parser.add_argument("--state", type=Path, default=ROOT / "configs/wandb_dashboard.json")
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/dashboard")
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args()
    credentials_from_project_env(ROOT.parent)
    saved = json.loads(args.state.read_text()) if args.state.exists() else {}
    args.browser_suite = args.browser_suite or saved.get("browser_suite", "browser-dev")
    args.generic_suite = args.generic_suite or saved.get("generic_suite", "generic-dev")
    entity = args.entity or os.environ.get("WANDB_ENTITY")
    ids = args.run_id or saved.get("focus_run_ids")
    if not entity or not ids:
        parser.error("Set WANDB_ENTITY and supply --run-id on the first invocation")
    if saved and (saved["entity"], saved["project"]) != (entity, args.project):
        parser.error("Existing report belongs to another project; use a separate --state path")
    import wandb
    import wandb_workspaces.reports.v2 as wr
    api = wandb.Api(timeout=30)
    evidence = []
    notes = []
    availability = []
    for run_id in ids:
        snapshot, run = load_wandb_snapshot(f"{entity}/{args.project}/{run_id}", api=api)
        values = scalar_metrics(snapshot)
        # The authoritative current snapshot, not potentially retained summary scalars.
        if not all(isinstance(run.summary.get(k), (int,float)) and
                   math.isclose(run.summary[k], v, rel_tol=1e-12, abs_tol=1e-12) for k,v in values.items()):
            raise ValueError("Scalar/snapshot mismatch (beyond JSON floating-point roundoff)")
        utc = datetime.fromtimestamp(snapshot["snapshot_at"], timezone.utc).isoformat()
        status = run.summary.get("qualification/status", "No qualification verdict recorded")
        notes.append(f"{run.name} ({run.id}): {run.state}; snapshot {utc}; qualification {status}. "
                     + ("INFRASTRUCTURE/SYNTHETIC COHORT — excluded from model-quality comparisons. " if snapshot["synthetic"] else "Experiment cohort. "))
        if run.summary.get("qualification/learning_demonstrated") is False:
            notes.append("This run did not demonstrate learning. ")
        missing = [TELEMETRY[k]["title"] for k,v in snapshot["telemetry"].items() if v is None or v.get("inherited")]
        availability.append(f"At report publication, {run.id} has no current measurement for: {', '.join(missing) or 'none'}. "
                            f"Recent window: {snapshot['window_s']} seconds. No fixed-suite results in this snapshot. "
                            if not snapshot.get("evaluations") else
                            f"At report publication, {run.id} missing telemetry: {', '.join(missing) or 'none'}. Recent window: {snapshot['window_s']} seconds. ")
        # Explicit counts explain the displayed tiny P11 sample without inventing a curve.
        metrics = snapshot.get("cohorts", {}).get("rl_train", {}).get("all", {}).get("metrics", {})
        if metrics:
            safe = metrics["safe_completion"]
            notes.append(f"Cumulative safe completion: {safe['numerator']}/{safe['denominator']} decidable episodes; "
                         f"{metrics['episodes']['value']} logical slots. This is a training cohort, not a held-out benchmark. ")
        expected = {k for s in sections(args.browser_suite,args.generic_suite) if s["scope"] == "focus" for c in s["charts"] for k in c["keys"]}
        evidence.append(dict(run_id=run_id, state=run.state, synthetic=snapshot["synthetic"], snapshot_id=snapshot["snapshot_id"],
                             watermark=snapshot["watermark"], checked_scalars=len(values),
                             plotted_keys_available=sorted(expected & values.keys()), plotted_keys_absent=sorted(expected-values.keys()),
                             missing_telemetry=missing))
    common=dict(focus_note=" ".join(notes), availability_note=" ".join(availability),
                browser_suite=args.browser_suite, generic_suite=args.generic_suite)
    state = dict(saved, entity=entity, project=args.project, focus_run_ids=ids,
                 browser_suite=args.browser_suite, generic_suite=args.generic_suite, sdk="wandb-workspaces==0.4.11",
                 layout_version=2, diagnostic_urls=dict(saved.get("diagnostic_urls",{})))
    report = build_overview(entity,args.project,ids,diagnostic_urls=state["diagnostic_urls"],**common)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "definition.json").write_text(json.dumps(signature(report), indent=2)+"\n")
    (args.output / "coverage.json").write_text(json.dumps(evidence, indent=2)+"\n")
    if not args.publish:
        print(json.dumps(dict(status="PREPARED_NOT_PUBLISHED", output=str(args.output), panels=sum(len(x.get("panels",[])) for x in signature(report)))))
        return

    def publish(report, key):
        expected=signature(report)
        url=state.get("url") if key=="overview" else state["diagnostic_urls"].get(key)
        if url:
            existing=wr.Report.from_url(url)
            if (existing.entity,existing.project,existing.title)!=(entity,args.project,report.title):
                raise ValueError("Saved URL no longer identifies this managed dashboard")
            (args.output/f"{key}-before.json").write_text(json.dumps(signature(existing),indent=2)+"\n")
            existing.blocks,existing.description,existing.width=report.blocks,report.description,report.width
            report=existing
        report.save()
        if key=="overview":state["url"]=report.url
        else:state["diagnostic_urls"][key]=report.url
        # Persist every identity before readback; retries update instead of duplicating reports.
        args.state.parent.mkdir(parents=True,exist_ok=True)
        args.state.write_text(json.dumps(state,indent=2)+"\n")
        observed=signature(wr.Report.from_url(report.url))
        (args.output/f"{key}-definition.json").write_text(json.dumps(expected,indent=2)+"\n")
        (args.output/f"{key}-readback.json").write_text(json.dumps(observed,indent=2)+"\n")
        if observed!=expected:
            raise ValueError(f"{key} semantic readback differs; inspect saved definitions")
        return sum(len(x.get("panels",[])) for x in expected)

    if not state.get("url"):
        publish(report,"overview")
    detail_counts={}
    for key,detail in build_diagnostics(entity,args.project,ids,overview_url=state["url"],**common).items():
        detail_counts[key]=publish(detail,key)
    report=build_overview(entity,args.project,ids,diagnostic_urls=state["diagnostic_urls"],**common)
    overview_count=publish(report,"overview")
    verification = dict(status="PASS_API_READBACK", url=state["url"], focus=evidence,
        panel_count=overview_count,diagnostic_panel_counts=detail_counts,diagnostic_urls=state["diagnostic_urls"],
        checked_at=datetime.now(timezone.utc).isoformat(),
        limits=["Browser rendering requires the user's signed-in W&B session; API checks do not establish visual rendering.",
                "Historical runs have sparse uploaded snapshots; no intermediate history was synthesized.",
                "Availability text is as of report publication; charts query W&B history."])
    (args.output / "verification.json").write_text(json.dumps(verification,indent=2)+"\n")
    print(json.dumps(verification))


if __name__ == "__main__":
    main()
