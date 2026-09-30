"""Port of inference_stuff's read-only, hybrid-aware startup capacity probe."""
import copy
import json
import math
import re

INPUT_LENGTHS = (30_000, 5_000)
OUTPUT_LENGTH = 1_000
LOOKAHEAD = 8
MAX_SEQS = 256
MARKER = "BROWSER_BENCH_CAPACITY "


def probe_capacity(config, cache, original):
    result = {}
    for isl in INPUT_LENGTHS:
        probe = copy.copy(config)
        probe.model_config = copy.copy(config.model_config)
        length = isl + OUTPUT_LENGTH + LOOKAHEAD
        probe.model_config.max_model_len = length
        if config.speculative_config is not None:
            probe.speculative_config = copy.copy(config.speculative_config)
            probe.speculative_config.draft_model_config = copy.copy(config.speculative_config.draft_model_config)
            probe.speculative_config.draft_model_config.max_model_len = length
        nominal = original(probe, cache)
        if not math.isfinite(nominal) or nominal <= 0:
            raise ValueError("Invalid engine capacity estimate")
        blocks = round(cache.num_blocks / nominal)
        if blocks <= 0 or not math.isclose(nominal, cache.num_blocks / blocks):
            raise ValueError("Non-integral per-request cache allocation")
        usable = cache.num_blocks - 1  # vLLM reserves a null block.
        maximum = min(config.scheduler_config.max_num_seqs, usable // blocks)
        if maximum < 1:
            raise ValueError("The selected context cannot fit one complete request")
        result[str(isl)] = {"context_budget": length, "output_reserved": OUTPUT_LENGTH,
                            "pool_blocks": cache.num_blocks, "usable_pool_blocks": usable,
                            "blocks_per_request": blocks, "max_concurrency": maximum,
                            "scheduler_limited": maximum < usable // blocks,
                            "predicted_reserved_fraction": maximum * blocks / usable,
                            "method": "upstream group-aware capacity on copied configs"}
    return result


def read_capacity(log):
    records = re.findall(re.escape(MARKER) + r"(\{[^\n]+\})", log)
    if not records:
        raise ValueError("No hybrid-aware capacity probe; refusing an estimated concurrency")
    result = json.loads(records[-1])
    for isl in INPUT_LENGTHS:
        row = result[str(isl)]
        if row["context_budget"] != isl + OUTPUT_LENGTH + LOOKAHEAD or not 1 <= row["max_concurrency"] <= MAX_SEQS:
            raise ValueError("Invalid startup capacity record")
    return result


def instrument():
    from vllm.v1.core import kv_cache_utils
    original = kv_cache_utils.get_max_concurrency_for_kv_cache_config

    def capacity(config, cache):
        actual = original(config, cache)
        print(MARKER + json.dumps(probe_capacity(config, cache, original)), flush=True)
        return actual

    kv_cache_utils.get_max_concurrency_for_kv_cache_config = capacity
