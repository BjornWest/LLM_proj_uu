"""Annotated W&B report definition. No GPU dependencies or mutations on import."""
import json

from .metric_catalog import TELEMETRY

TITLE = "Browser training — progress and health"
EXPERIMENT_FILTER = 'Config("synthetic") == False and Tags not in ["exclude-from-model-results"]'
X = "monitoring/watermark"
DIAGNOSTICS = {
    "behavior": ("Browser training — behavior diagnostics", {"1", "2", "7", "9"}),
    "updates": ("Browser training — GRPO diagnostics", {"3", "4"}),
    "throughput": ("Browser training — throughput diagnostics", {"5", "6", "8"}),
}


def selected_filter(run_ids):
    if not run_ids or any(not r or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for c in r) for r in run_ids):
        raise ValueError("Select explicit W&B run IDs")
    return " or ".join(f"ID == {json.dumps(r)}" for r in run_ids)


def chart(title, keys, unit, *, labels=None, x=X, fraction=False):
    return dict(title=title, keys=keys, unit=unit, labels=labels or keys, x=x, fraction=fraction)


def rate(prefix, metric, title):
    base = f"{prefix}/{metric}"
    return chart(title, [f"{base}/{s}" for s in ("value", "ci95_low", "ci95_high")],
                 "fraction (0–1)", labels=["Rate", "95% lower", "95% upper"], fraction=True)


def outcome(metric, stat="value", window="recent"):
    return f"outcomes/rl_train/{window}/{metric}/{stat}"


def sections(browser_suite="browser-dev", generic_suite="generic-dev"):
    """Declarative chart keys also drive coverage/readback checks."""
    recent = "outcomes/rl_train/recent"
    result = [dict(title="1. Is browser behavior improving?", scope="experiments",
        note="Fixed held-out suites are the quality test. These charts exclude synthetic/infrastructure runs. "
             "Empty means no eligible evaluation is logged. Compare only reports with eligibility 1 and inherited 0, "
             "using the same suite identity. Rates use verified outcomes; read denominators and unknowns. "
             "The three lines are rate and descriptive Wilson 95% bounds, not three models. "
             "Related episodes are not independent trials. The x-axis is evaluated policy version, not optimizer step.",
        charts=[
            {**rate(f"evaluation/{browser_suite}", "safe_completion", "Fixed browser dev: intent-preserving completion"), "x": f"evaluation/{browser_suite}/policy_version"},
            {**rate(f"evaluation/{browser_suite}", "completion", "Fixed browser dev: task completion"), "x": f"evaluation/{browser_suite}/policy_version"},
            chart("Fixed dev: verification and eligibility", [f"evaluation/{browser_suite}/{k}" for k in
                  ("valid_for_comparison", "inherited", "unknown_safe/value", "infra_error/value")],
                  "flags / fraction", labels=["Eligible (1=yes)", "Inherited (1=old policy)", "Unknown safety", "Infrastructure errors"],
                  x=f"evaluation/{browser_suite}/policy_version", fraction=True),
            chart("Fixed dev: evaluated sample counts", [f"evaluation/{browser_suite}/{k}/denominator" for k in ("completion", "safe_completion")],
                  "verified episodes", labels=["Goal verified", "Safety decidable"], x=f"evaluation/{browser_suite}/policy_version"),
            {**rate(f"evaluation/{generic_suite}", "safe_completion", "Generic/tool-use dev: forgetting check"), "x": f"evaluation/{generic_suite}/policy_version"},
            chart("Generic dev: eligibility and sample count", [f"evaluation/{generic_suite}/{k}" for k in
                  ("valid_for_comparison", "inherited", "safe_completion/denominator")], "flag / episodes",
                  labels=["Eligible (1=yes)", "Inherited (1=old policy)", "Verified episodes"], x=f"evaluation/{generic_suite}/policy_version"),
        ]),
        dict(title="2. What is happening in the browser?", scope="focus",
        note="Recent means the snapshot's configured window (normally one hour); cumulative counts include all history. "
             "These are training outcomes, not held-out scores. Retries replace logical slots for rates but all attempts count toward cost. "
             "Unknown verification and infrastructure errors are excluded from policy-success denominators. "
             "Unauthorized effects should fall without completion falling. A changing task mix can change pass rates without learning.",
        charts=[rate(recent, "safe_completion", "Recent intent-preserving completion"),
                rate(recent, "completion", "Recent task completion"),
                rate(recent, "unauthorized_effect", "Recent unauthorized effects — lower is better"),
                chart("Recent verified denominators", [outcome(k, "denominator") for k in ("completion", "safe_completion", "unauthorized_effect")],
                      "episodes", labels=["Goal known", "Safety decidable", "Side effects known"]),
                chart("Recent errors, cancellations and unknown safety", [outcome(k) for k in ("infra_error", "cancelled", "unknown_safe")],
                      "fraction (different denominators)", labels=["Infrastructure / all slots", "Cancelled / all slots", "Unknown safety / completed slots"], fraction=True),
                chart("Cumulative episodes and unsuccessful execution attempts", [outcome(k, window="all") for k in ("episodes", "attempts", "infra_error_attempts", "cancelled_attempts")],
                      "episodes / attempts", labels=["Logical slots", "All attempts", "Infrastructure-failed attempts", "Cancelled attempts"]),
                chart("Cumulative browser actions and generated tokens", [outcome(k, window="all") for k in ("steps", "generated_tokens")],
                      "actions / tokens", labels=["Browser actions", "Generated tokens (run tokenizer)"]),
                chart("Interventions: measured total and missing coverage", [outcome("interventions", s, "all") for s in ("value", "measured_attempts", "missing_attempts")],
                      "interventions / attempts", labels=["Interventions", "Measured attempts", "Unmeasured attempts"]),
        ]),
        dict(title="3. Is GRPO getting useful updates?", scope="focus",
        note="Mixed groups have unequal rewards and can supply a group-relative advantage. All-success/all-failure binary groups cannot. "
             "This group statistic covers complete verified generated groups, not necessarily groups consumed by the optimizer. "
             "Rows can pass several lifecycle stages: do not add the counters together. Applied means the optimizer step completed, "
             "not that weights changed. Read gradient norm alongside group signal; inspect checkpoint differences for proof. "
             "Policy age is version distance, not seconds. Discarded work is not a browser failure.",
        charts=[rate(recent, "mixed_groups", "Recent groups with reward variation"),
                chart("Gradient norm — zero means no measured gradient", ["telemetry/trainer/grad_norm"], "L2 norm",
                      labels=["Gradient norm"], x="telemetry_step/trainer/grad_norm"),
                chart("Recent GRPO groups: signal denominator and extremes", [outcome(k) for k in ("valid_groups", "all_success_groups", "all_failure_groups")],
                      "complete groups", labels=["Verified groups", "All rewards = 1", "All rewards = 0"]),
                chart("Training rows: accepted → backward → applied", [f"training_rows/totals/{k}" for k in ("admitted", "backward", "applied")],
                      "cumulative rows", labels=["Accepted", "Backward completed", "In completed optimizer steps"]),
                chart("Training rows: waiting, discarded or lost on resume", [f"training_rows/totals/{k}" for k in ("pending", "discarded", "skipped", "abandoned")],
                      "cumulative rows", labels=["Pending decision", "Discarded", "Skipped optimizer", "Abandoned on resume"]),
                chart("Policy age at admission", [outcome("policy_age", s) for s in ("value", "maximum")], "versions",
                      labels=["Mean age", "Maximum age"]),
        ]),
    ]
    groups = [
        ("4. Trainer diagnostics", "GRPO loss need not decrease monotonically. Entropy describes token-level diversity. "
         "Behavior KL compares against the behavior policy; it is not an SFT-reference penalty. Clipping is a diagnostic, not a quality score. "
         "Telemetry charts use each metric's recorded step, whose meaning is defined by its producer; not every axis is an optimizer step.",
         ["rl/loss", "rl/entropy", "rl/behavior_kl", "rl/clipped_token_fraction", "trainer/learning_rate"]),
        ("5. Where is time going?", "Look for a waiting trainer, slow browser workers or a saturated rollout GPU before changing batch sizes. "
         "Update duration is optimizer-only; compute includes forward/backward. Async intervals can overlap, so do not sum these into a percentage pie. "
         "Snapshot publication samples telemetry; these charts do not reconstruct unuploaded intermediate steps. Missing throughput is not zero.",
         ["trainer/step_s", "trainer/compute_s", "trainer/update_s", "trainer/rollout_wait_s", "trainer/adapter_sync_s",
          "policy/publication_s", "trainer/trained_tokens_per_s", "rollout/generated_tokens_per_s", "browser/episodes_per_min",
          "trainer/forwarded_tokens_per_step", "trainer/trained_tokens_per_step"]),
        ("6. Hardware and browser capacity", "VRAM/utilization are sampled per physical device, separately for trainer and rollout. "
         "A latest sample is not a peak. PyTorch allocation has a different scope. CPU is cores used (1 = one busy core); RAM is process-tree PSS. "
         "Consult availability below: a previous point can remain visible after a reading becomes unavailable.",
         ["trainer/vram_gib", "rollout/vram_gib", "trainer/gpu_utilization_pct", "rollout/gpu_utilization_pct",
          "trainer/peak_allocated_gib", "browser/cpu_cores", "browser/ram_gib", "trainer/cpu_cores", "trainer/ram_gib",
          "rollout/cpu_cores", "rollout/ram_gib"]),
        ("7. SFT fitting", "These panels use only non-synthetic experiments. Loss is measured on the configured supervised tokens. "
         "Compare held-out demonstration loss with training loss, then check browser-dev behavior. Missing SFT measurements during an RL run are expected.",
         ["sft/train_loss", "sft/validation_loss"]),
    ]
    for title, note, keys in groups:
        result.append(dict(title=title, note=note, scope="experiments" if keys[0].startswith("sft/") else "focus",
            charts=[chart(TELEMETRY[k]["title"], [f"telemetry/{k}"], TELEMETRY[k]["unit"],
                          labels=[TELEMETRY[k]["title"]], x=f"telemetry_step/{k}",
                          fraction=TELEMETRY[k]["maximum"] == 1) for k in keys]))
    result.append(dict(title="8. Availability and publication", scope="focus",
        note="Availability 0 means no current non-inherited measurement; 1 means a measurement exists, not that it is fresh. "
             "Check the measurement timestamps and run state too. Finished-run data naturally becomes old. "
             "Event watermark counts ledger events, not optimizer steps. It can stay unchanged across publication retries. "
             "Cumulative resumed runs share history: never sum their totals. Use the agent reader for live age, producer status and exact missing reasons.",
        charts=[chart("GPU measurements available?", [f"telemetry_available/{k}" for k in ("trainer/vram_gib", "rollout/vram_gib", "trainer/gpu_utilization_pct", "rollout/gpu_utilization_pct")],
                      "flag (1=available)", fraction=True),
                chart("Throughput measurements available?", [f"telemetry_available/{k}" for k in ("trainer/trained_tokens_per_s", "rollout/generated_tokens_per_s", "browser/episodes_per_min")],
                      "flag (1=available)", fraction=True),
                chart("Snapshot timestamp", ["monitoring/snapshot_at"], "Unix seconds"),
                chart("Trainer and GPU measurement timestamps", [f"telemetry_time/{k}" for k in ("trainer/grad_norm", "trainer/vram_gib", "rollout/vram_gib")], "Unix seconds"),
                chart("Unmatched admissions and future-dated events", ["monitoring/unmatched_admissions", "monitoring/future_events"], "events",
                      labels=["Unmatched admissions", "Future-dated events"])]))
    return result


def build_report(entity, project, run_ids, *, focus_note, availability_note, browser_suite="browser-dev", generic_suite="generic-dev"):
    import wandb_workspaces.reports.v2 as wr
    report = wr.Report(entity=entity, project=project, title=TITLE, width="fluid",
                       description="Task quality, GRPO signal, throughput and resource health, with definitions beside the charts.")
    blocks = [wr.H1("Start here"), wr.P(focus_note),
        wr.P("Read in this order: fixed-dev safe completion → verification coverage → useful reward groups and gradients → discarded work → timing and resources. "
             "Fractions run from 0 to 1 (0.9 = 90%). No smoothing or averaging across runs is applied. "
             "Dots can be single published snapshots, not learning curves. Charts are live W&B queries; this explanatory text is versioned at dashboard publication."),
        wr.P(availability_note), wr.TableOfContents()]
    for section in sections(browser_suite, generic_suite):
        blocks.extend([wr.H1(section["title"]), wr.P(section["note"])])
        panels = []
        for i, c in enumerate(section["charts"]):
            panels.append(wr.LinePlot(title=c["title"], x=c["x"], y=c["keys"],
                title_x="Ledger event watermark" if c["x"] == X else ("Evaluated policy version" if c["x"].endswith("policy_version") else "Producer-recorded step"),
                title_y=c["unit"], range_y=(0, 1) if c["fraction"] else (None, None),
                smoothing_type="none", smoothing_factor=0, aggregate=False, ignore_outliers=False,
                line_titles=dict(zip(c["keys"], c["labels"])), line_marks={k: "points" for k in c["keys"]},
                layout=wr.Layout(x=(i % 2)*12, y=(i//2)*6, w=12, h=6)))
        runset = wr.Runset(entity=entity, project=project,
            name="Experiments only — no synthetic tests" if section["scope"] == "experiments" else "Selected monitored run(s)",
            filters=EXPERIMENT_FILTER if section["scope"] == "experiments" else selected_filter(run_ids))
        grid = wr.PanelGrid(runsets=[runset], panels=panels)
        if section["scope"] == "experiments" or section["title"][0] in "4568":
            # Keep the main browser/signal overview short; details expand in place.
            blocks.pop()
            blocks.pop()
            blocks.append(wr.H1(section["title"], collapsed_blocks=[wr.P(section["note"]), grid]))
        else:
            blocks.append(grid)
    blocks.extend([wr.H1("9. Task families and curriculum"),
        wr.P("Family table: read split and window, then completion/safe completion with their verified sample counts. "
             "Curriculum table: requested probability is intended allocation; realized fraction is actual draws. "
             "Smoothed pass rate is a sampler heuristic, not benchmark performance. The P11 single-task test does not validate adaptive curriculum. "
             "Empty tables mean no applicable data. Template details and discard reasons remain in the immutable snapshot."),
        wr.PanelGrid(runsets=[wr.Runset(entity=entity, project=project, name="Selected monitored run(s)", filters=selected_filter(run_ids))],
            panels=[wr.MediaBrowser(title="Outcomes by family — latest published table", media_keys=["monitoring/families"], layout=wr.Layout(w=24,h=8)),
                    wr.MediaBrowser(title="Curriculum allocation — latest published table", media_keys=["monitoring/curriculum"], layout=wr.Layout(y=8,w=24,h=8))]),
        wr.H1("What still requires the underlying evidence?"),
        wr.P("This report does not certify correct policy pinning, adapter eviction, checkpoint weight changes or grader correctness. "
             "Inspect policy events, original traces and qualification records for those claims. No monetary cost is inferred from GPU utilization. "
             "Dark-pattern/failure taxonomy breakdowns and clickable episode drill-downs are not wired here yet. "
             "The agent reader uses the same hashed snapshot and can retrieve exact values without accessing a GPU node."),
        wr.P(["W&B API reference: ", wr.Link("Reports API", "https://docs.wandb.ai/models/ref/wandb_workspaces/reports")])])
    report.blocks = blocks
    return report


def overview_cards():
    """Six simultaneous operational signals; improvements still require fixed dev."""
    return [
        dict(title="Agent score: recent safe completion", key=outcome("safe_completion"), fraction=True,
             unit="fraction of decidable episodes", diagnostic="behavior",
             note="Higher is better, but task mix can change this rate. If it changes, inspect verified counts, unknowns, side effects and task families."),
        dict(title="GRPO update: gradient norm", key="telemetry/trainer/grad_norm", fraction=False,
             unit="L2 norm", diagnostic="updates",
             note="Zero can mean equal rewards in the trained group. Nonzero shows a gradient, not improved behavior. If it changes, inspect group signal, applied rows, clipping and KL."),
        dict(title="Rollout speed: generated tokens/s", key="telemetry/rollout/generated_tokens_per_s", fraction=False,
             unit="generated tokens/second", diagnostic="throughput",
             note="Compare similar contexts and concurrency; no universal good threshold. If it drops, inspect rollout GPU load, memory, browser speed and synchronization."),
        dict(title="Learning opportunities: mixed-reward groups", key=outcome("mixed_groups"), fraction=True,
             unit="fraction of complete verified groups", diagnostic="updates",
             note="Low means little group-relative signal. These are generated groups, not necessarily trained groups. Inspect all-success/all-failure counts, admission and policy age."),
        dict(title="Browser speed: episodes/min", key="telemetry/browser/episodes_per_min", fraction=False,
             unit="terminal episodes/minute", diagnostic="throughput",
             note="If tokens/s is healthy but this falls, inspect browser CPU/RAM, task length and errors. Faster episodes do not necessarily mean better decisions."),
        dict(title="Trainer idle time: waiting for rollouts", key="telemetry/trainer/rollout_wait_s", fraction=False,
             unit="seconds per reported update", diagnostic="throughput",
             note="Rising wait can mean generation or browser bottlenecks. Compare step/compute/sync durations and stale discards before raising concurrency."),
    ]


def build_overview(entity, project, run_ids, *, focus_note, availability_note, diagnostic_urls,
                   browser_suite="browser-dev", generic_suite="generic-dev"):
    import wandb_workspaces.reports.v2 as wr
    report = wr.Report(entity=entity, project=project, title=TITLE, width="fluid",
                       description="One overview of agent scores, GRPO learning signals and rollout speed. Follow a chart's diagnostic link when it changes.")
    panels = []
    for i,c in enumerate(overview_cards()):
        x,y = (i%3)*8,(i//3)*10
        panels.append(wr.LinePlot(title=c["title"], x="WallTime", y=[c["key"]],
            title_x="Publication time", title_y=c["unit"], range_y=(0,1) if c["fraction"] else (None,None),
            smoothing_type="none", smoothing_factor=0, aggregate=False, ignore_outliers=False,
            line_marks={c["key"]:"points"}, line_titles={c["key"]:c["title"]},
            layout=wr.Layout(x=x,y=y,w=8,h=6)))
        target=diagnostic_urls.get(c["diagnostic"])
        link=f"[Investigate this signal →]({target})" if target else "Diagnostic link appears after publication."
        # One paragraph with a hard line break: blockquotes and separate
        # paragraphs introduce vertical margins in W&B's Markdown renderer.
        panels.append(wr.MarkdownPanel(markdown=f"&emsp;{link}  \n&emsp;{c['note']}",layout=wr.Layout(x=x,y=y+6,w=8,h=4)))
    blocks=[wr.H1("Training at a glance"),
        wr.P("Read across: agent score → GRPO update → rollout speed. Read down for reward signal, browser throughput and trainer waiting. "
             "All six charts use publication time so changes can be compared. Measurements can have different ages; this does not establish causation. "
             "Missing is not zero. Fractions use 0–1; no smoothing or averaging across runs."),
        wr.P(focus_note),
        wr.PanelGrid(runsets=[wr.Runset(entity=entity,project=project,name="Selected monitored run(s)",filters=selected_filter(run_ids))],panels=panels),
        wr.H1("Do those updates improve the policy?"),
        wr.P("The evidence is improving safe completion on the SAME fixed held-out suite. "
             "Read this alongside the six operational signals above: gradients and training scores alone do not establish learning. "
             "These panels use only the selected non-synthetic runs. Check sample counts, eligibility and unknown outcomes in behavior diagnostics before comparing. "
             "Empty means no eligible fixed-suite result has been uploaded."),
    ]
    quality=[]
    for i,(suite,title) in enumerate(((browser_suite,"Held-out browser score: safe completion"),(generic_suite,"Generic/tool-use score: forgetting check"))):
        c=rate(f"evaluation/{suite}","safe_completion",title)
        quality.append(wr.LinePlot(title=title,x=f"evaluation/{suite}/policy_version",y=c["keys"],
            title_x="Evaluated policy version",title_y="fraction + descriptive 95% bounds",range_y=(0,1),
            smoothing_type="none",smoothing_factor=0,aggregate=False,ignore_outliers=False,
            line_titles=dict(zip(c["keys"],c["labels"])),line_marks={k:"points" for k in c["keys"]},
            layout=wr.Layout(x=i*12,y=0,w=12,h=6)))
    blocks.append(wr.PanelGrid(runsets=[wr.Runset(entity=entity,project=project,name="Selected experiments — synthetic excluded",
        filters=f"({selected_filter(run_ids)}) and {EXPERIMENT_FILTER}")],panels=quality))
    blocks.append(wr.H1("Follow a change"))
    for key,label in [("behavior","Agent score or safety changed → counts, verification, task mix, generic evaluation and SFT"),
                      ("updates","Updates look ineffective or unstable → reward groups, gradients, applied/discarded rows, KL and clipping"),
                      ("throughput","Rollouts slowed or trainer is waiting → generation, browser workers, synchronization, GPU/CPU/RAM and freshness")]:
        blocks.append(wr.P([wr.Link(label,diagnostic_urls[key])]) if key in diagnostic_urls else wr.P(label))
    blocks.append(wr.H1("Measurement availability and scope",collapsed_blocks=[wr.P(availability_note),
        wr.P("Availability text is as of report publication. Charts query stored W&B history; finished P11 has a single snapshot, not a learning curve. "
             "Timing charts describe sampled measurements, not all events between uploads. Diagnostic views retain native step/event axes and freshness details. "
             "Adapter changes, pinning and eviction still require checkpoint/policy-event evidence.")]))
    report.blocks=blocks
    return report


def build_diagnostics(entity, project, run_ids, *, overview_url, **kwargs):
    """Retain all previous detailed panels behind three stable drill-down URLs."""
    import wandb_workspaces.reports.v2 as wr
    full=build_report(entity,project,run_ids,**kwargs)
    reports={}
    for key,(title,numbers) in DIAGNOSTICS.items():
        report=wr.Report(entity=entity,project=project,title=title,width="fluid")
        blocks=[wr.P([wr.Link("← Back to the training overview",overview_url)]),
                wr.P(kwargs["focus_note"]),wr.TableOfContents()]
        active=False
        for block in full.blocks:
            if isinstance(block,wr.H1):
                active=str(block.text).split(".")[0] in numbers or block.text=="What still requires the underlying evidence?"
            if active:
                if isinstance(block,wr.H1) and block.collapsed_blocks:
                    blocks.extend([wr.H1(block.text),*block.collapsed_blocks])
                else:
                    blocks.append(block)
        if key=="throughput":
            blocks.append(wr.P(kwargs["availability_note"]))
        report.blocks=blocks
        reports[key]=report
    return reports


def signature(report):
    """Stable semantic fields for API readback; exclude generated layout IDs."""
    import wandb_workspaces.reports.v2 as wr
    from wandb_workspaces import expr
    def metric(value):
        if isinstance(value, list):
            return [metric(v) for v in value]
        return value.name if hasattr(value, "name") else value
    result = []
    def visit(blocks):
        for block in blocks:
            yield block
            if getattr(block, "collapsed_blocks", None):
                yield from visit(block.collapsed_blocks)
    for block in visit(report.blocks):
        if isinstance(block, wr.PanelGrid):
            result.append(dict(filters=[expr.expr_to_filters(r.filters).model_dump(exclude_none=True) for r in block.runsets], panels=[
                dict(kind=type(p).__name__, title=getattr(p,"title",None), markdown=getattr(p,"markdown",None), x=metric(getattr(p, "x", None)),
                     y=metric(getattr(p, "y", None)), media=getattr(p, "media_keys", None),
                     aggregate=getattr(p, "aggregate", None), smoothing=getattr(p, "smoothing_type", None),
                     title_x=getattr(p, "title_x", None),title_y=getattr(p,"title_y",None),
                     range_y=list(getattr(p,"range_y",[])), layout=dict(x=p.layout.x,y=p.layout.y,w=p.layout.w,h=p.layout.h))
                for p in block.panels]))
        elif isinstance(block, (wr.H1, wr.P)):
            result.append(dict(kind=type(block).__name__, text=str(block.text)))
    return result
