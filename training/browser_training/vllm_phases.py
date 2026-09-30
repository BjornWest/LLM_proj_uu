"""Guarded decode accounting adapted from inference_stuff's Qwen3.8 report.

Use native vLLM's saved stream-chunk timings and server counters. Never interpret
chunk arrivals (especially MTP bursts) as individual GPU forward passes.
"""
import json
import threading
import time
from pathlib import Path
from urllib.request import urlopen


def parse_metrics(text):
    # Import the locked RL dependency only in the rented worker, not CPU helpers.
    from prometheus_client.parser import text_string_to_metric_families
    values = {}
    for family in text_string_to_metric_families(text):
        for sample in family.samples:
            name = sample.name
            if name == "vllm:prompt_tokens_by_source_total":
                if sample.labels.get("source") != "local_compute":
                    continue
                name = "computed_prompt_tokens"
            if name.startswith("vllm:") or name == "computed_prompt_tokens":
                if not name.endswith(("_bucket", "_created")):
                    values[name] = values.get(name, 0) + sample.value
    return values


class Sampler:
    def __init__(self, url, path, interval=0.5):
        self.url, self.path, self.interval = url, Path(path), interval
        self.stop = threading.Event()
        self.rows = []
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        with self.path.open("w", buffering=1) as out:
            while not self.stop.is_set():
                start = time.perf_counter()  # Same clock as the native client.
                row = {"start": start}
                try:
                    with urlopen(self.url, timeout=2) as response:
                        row["values"] = parse_metrics(response.read().decode())
                except Exception as exc:
                    row["error"] = type(exc).__name__
                row["end"] = time.perf_counter()
                self.rows.append(row)
                out.write(json.dumps(row) + "\n")
                self.stop.wait(max(0, self.interval - (row["end"] - start)))

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.stop.set()
        self.thread.join(timeout=3)


def summarize_phases(native, samples, concurrency, *, guard=1.0, min_decode_seconds=5.0):
    starts, ttfts, itls = (native.get(k, []) for k in ("start_times", "ttfts", "itls"))
    result = {"decode": None, "pure_prefill": None, "max_sampled_kv_fraction": None,
              "method": "full-concurrency guarded server-counter intervals; native chunk timings",
              "guard_seconds": guard, "sampled_occupancy_is_not_forward_batch_size": True}
    if any(len(x) != concurrency for x in (starts, ttfts, itls)) or native.get("failed", 0):
        result["invalid_reason"] = "A simultaneous complete cohort and detailed native timings are required"
        return result
    firsts = [s + t for s, t in zip(starts, ttfts)]
    lasts = [f + sum(gaps) for f, gaps in zip(firsts, itls)]
    begin, end = max(firsts) + guard, min(lasts) - guard
    result["candidate_decode_window"] = [begin, end]
    decode_time = decode_tokens = prefill_time = prefill_tokens = 0
    segments, kv_full = [], []
    preemptions = 0
    for previous, current in zip(samples, samples[1:]):
        before, after = previous.get("values", {}), current.get("values", {})
        if "error" in previous or "error" in current or not before or not after:
            continue
        # Entire HTTP scrape spans must fit inside the guard. Intervals with slow
        # scrapes are excluded rather than assigning counters to uncertain times.
        a, b = previous["end"], current["start"]
        dt = b - a
        if dt <= 0 or current["end"] - previous["start"] > 1.5:
            continue
        keys = ("vllm:generation_tokens_total", "computed_prompt_tokens", "vllm:num_preemptions_total")
        if any(k not in before or k not in after for k in keys):
            continue
        gen, prompt, preempt = [after[k] - before[k] for k in keys]
        if min(gen, prompt, preempt) < 0:
            result["invalid_reason"] = "Engine counter reset inside the case"
            result["decode"] = None
            return result
        preemptions += preempt
        kv = after.get("vllm:kv_cache_usage_perc")
        if kv is not None:
            result["max_sampled_kv_fraction"] = max(result["max_sampled_kv_fraction"] or 0, kv)
        full = all(v.get("vllm:num_requests_running") == concurrency and
                   v.get("vllm:num_requests_waiting") == 0 for v in (before, after))
        # Use scrape midpoints for rate duration: numerator covers the same two
        # counter snapshots. a/b above only gate the complete scrape spans.
        duration = (current["start"] + current["end"] - previous["start"] - previous["end"]) / 2
        if previous["start"] >= begin and current["end"] <= end and full and prompt == 0 and preempt == 0:
            decode_time += duration
            decode_tokens += gen
            segments.append([previous["start"], current["end"]])
            if kv is not None:
                kv_full.append(kv)
        if gen == 0 and prompt > 0 and preempt == 0:
            prefill_time += duration
            prefill_tokens += prompt
    result["observed_preemptions"] = preemptions
    if prefill_time:
        result["pure_prefill"] = {"sampled_seconds": prefill_time, "computed_tokens": prefill_tokens,
                                   "computed_tokens_per_second": prefill_tokens / prefill_time,
                                   "scope": "sampled intervals without decode counter increments; not isolated kernel time"}
    if decode_time >= min_decode_seconds and decode_tokens > 0 and preemptions == 0:
        result["decode"] = {"sampled_seconds": decode_time, "tokens": decode_tokens,
                             "tokens_per_second": decode_tokens / decode_time,
                             "tokens_per_second_per_request": decode_tokens / decode_time / concurrency,
                             "kv_fraction_min": min(kv_full) if kv_full else None,
                             "kv_fraction_max": max(kv_full) if kv_full else None,
                             "segments": segments}
    else:
        result["decode_unavailable_reason"] = "Insufficient clean full-concurrency overlap or observed preemption"
    return result
