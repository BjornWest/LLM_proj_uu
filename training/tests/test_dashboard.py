"""Presentation correctness: cohort safety, measured axes and missing data."""
import importlib.util
from pathlib import Path

import pytest

from browser_training.dashboard import EXPERIMENT_FILTER, build_report, sections, selected_filter, signature
from browser_training.metric_catalog import TELEMETRY
from browser_training.monitoring_io import scalar_metrics


def test_every_telemetry_metric_has_a_chart_with_its_own_recorded_axis():
    charts = [c for s in sections() for c in s["charts"]]
    for key in TELEMETRY:
        own = [c for c in charts if f"telemetry/{key}" in c["keys"]]
        assert own, key
        assert all(c["x"] == f"telemetry_step/{key}" for c in own)


def test_outcome_panels_use_real_reducer_keys_and_unknowns_stay_absent(tmp_path):
    source = Path(__file__).resolve().parents[1] / "scripts/validate_metrics.py"
    spec = importlib.util.spec_from_file_location("dashboard_fixture", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _, value = module.build_fixture(tmp_path, "dashboard-test")
    scalars = scalar_metrics(value)
    for section in sections():
        for c in section["charts"]:
            for key in c["keys"]:
                if key.startswith(("outcomes/", "telemetry/", "telemetry_available/", "telemetry_time/", "monitoring/")):
                    assert key in scalars, key
    from browser_training.outcomes import snapshot, Ledger
    empty = scalar_metrics(snapshot(Ledger(tmp_path / "empty.sqlite", run_id="empty", synthetic=True, expected_producers=[])))
    assert "telemetry/trainer/grad_norm" not in empty
    assert empty["telemetry_available/trainer/grad_norm"] == 0


def test_run_filters_use_stable_id_and_explicitly_exclude_synthetic_quality_data():
    expr = pytest.importorskip("wandb_workspaces.expr")
    filt = expr.expr_to_filters(selected_filter(["test-id"]))
    assert filt.key.section == "run" and filt.key.name == "name"  # ID, not displayName
    quality = expr.expr_to_filters(EXPERIMENT_FILTER)
    assert quality.op == "AND"
    assert any(f.key.section == "config" and f.key.name == "synthetic" and f.value is False for f in quality.filters)
    assert any(f.key.name == "tags" and f.op == "NIN" and "exclude-from-model-results" in f.value for f in quality.filters)
    with pytest.raises(ValueError):
        selected_filter(['bad" or True'])


def test_report_keeps_explanations_and_no_aggregation_or_smoothing():
    pytest.importorskip("wandb_workspaces")
    report = build_report("team", "project", ["test-id"], focus_note="SYNTHETIC", availability_note="Missing is not zero")
    spec = signature(report)
    assert any("Missing is not zero" in str(b) for b in spec)
    grids = [b for b in spec if "panels" in b]
    assert grids
    for grid in grids:
        for panel in grid["panels"]:
            if panel["kind"] == "LinePlot":
                assert panel["aggregate"] is False and panel["smoothing"] == "none"
    assert any("policy pinning" in str(b) for b in spec)
