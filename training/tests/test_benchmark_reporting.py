"""Regressions observed in actual Modal Axolotl runs, without a GPU."""
import importlib.util
import json
from pathlib import Path

spec = importlib.util.spec_from_file_location('benchmark', Path(__file__).parents[1] / 'scripts/benchmark.py')
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


def test_resume_counters_and_reset_memory_peak(tmp_path):
    rows = [
        {'step': 1, 'tokens/trainable': 5, 'peak_vram_gib': 19.2, 'memory/max_allocated (GiB)': 24.91},
        {'step': 2, 'tokens/trainable': 10, 'peak_vram_gib': 19.2,
         'memory/max_allocated (GiB)': 25.74, 'tokens/train_per_sec_per_gpu': 0.77},
        {'step': 2, 'tokens/trainable': 5, 'peak_vram_gib': 19.19,
         'memory/max_allocated (GiB)': 25.73, 'tokens/train_per_sec_per_gpu': -0.47},
    ]
    (tmp_path / 'metrics.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
    report = benchmark.summarize(tmp_path, 160, 0)
    assert report['peak_vram_gib'] == 25.74
    assert report['token_counter_reset_detected']
    assert report['supervised_tokens_per_wall_second'] is None
    assert report['seconds_per_million_supervised_tokens'] is None
    assert 'tokens/train_per_sec_per_gpu' not in report['metric_means']
    assert not report['warmup_excluded']


def test_uninterrupted_run_keeps_valid_rates(tmp_path):
    rows = [{'step': i, 'tokens/trainable': i*10, 'tokens/train_per_sec_per_gpu': 5.0}
            for i in range(1, 8)]
    (tmp_path / 'metrics.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
    report = benchmark.summarize(tmp_path, 14, 0)
    assert report['supervised_tokens_per_wall_second'] == 5
    assert report['metric_means']['tokens/train_per_sec_per_gpu'] == 5
    assert report['peak_vram_gib'] is None
    assert not report['token_counter_reset_detected']
    assert report['warmup_excluded']
