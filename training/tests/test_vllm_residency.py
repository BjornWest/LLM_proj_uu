import json
from types import SimpleNamespace

import pytest

from browser_training.vllm_capacity import MARKER, probe_capacity, read_capacity
from browser_training.vllm_phases import summarize_phases
from browser_training.vllm_speed import residency_cases, residency_server_command, residency_bench_command
from browser_training.browser_benchmark_prompts import write_dataset


def test_hybrid_capacity_keeps_live_and_draft_configs_unchanged():
    config = SimpleNamespace(model_config=SimpleNamespace(max_model_len=31008),
        speculative_config=SimpleNamespace(draft_model_config=SimpleNamespace(max_model_len=31008)),
        scheduler_config=SimpleNamespace(max_num_seqs=256))
    cache = SimpleNamespace(num_blocks=1209)

    def original(cfg, pool):
        assert cfg.model_config.max_model_len == cfg.speculative_config.draft_model_config.max_model_len
        # Include fixed hybrid state, not attention-only inverse-length scaling.
        blocks = (cfg.model_config.max_model_len + 1071) // 1072 + 3
        return pool.num_blocks / blocks

    result = probe_capacity(config, cache, original)
    assert config.model_config.max_model_len == 31008
    assert config.speculative_config.draft_model_config.max_model_len == 31008
    assert result['30000']['max_concurrency'] == 1208 // 32
    assert result['5000']['max_concurrency'] == 1208 // 9
    assert result['30000']['predicted_reserved_fraction'] <= 1
    assert read_capacity(MARKER + json.dumps(result)) == result


def test_scheduler_limit_reported_instead_of_claiming_full_memory():
    cfg = SimpleNamespace(model_config=SimpleNamespace(max_model_len=31008),
                          speculative_config=None, scheduler_config=SimpleNamespace(max_num_seqs=256))
    result = probe_capacity(cfg, SimpleNamespace(num_blocks=10000), lambda c, p: 1000)
    assert result['5000']['max_concurrency'] == 256
    assert result['5000']['scheduler_limited']
    assert result['5000']['predicted_reserved_fraction'] < 0.3


def test_residency_cohorts_have_no_turnover_and_reserve_decode_growth():
    capacities = {'30000': {'max_concurrency': 40}, '5000': {'max_concurrency': 170}}
    cases = residency_cases(capacities)
    assert [(c.input_tokens, c.output_tokens, c.concurrency) for c in cases] == [
        (30000, 1000, 40), (5000, 1000, 170), (30000, 1, 40), (5000, 1, 170), (5000, 1000, 85)]
    assert all(c.requests == c.concurrency for c in cases)
    cmd = residency_bench_command('vllm', cases[0], output='results', dataset='browser.jsonl', tokenizer='snapshot')
    assert cmd[cmd.index('--num-warmups') + 1] == '0'
    assert cmd[cmd.index('--ready-check-timeout-sec') + 1] == '0'
    assert '--no-oversample' in cmd and '--skip-chat-template' in cmd
    server = residency_server_command('vllm')
    assert server[server.index('--max-num-seqs') + 1] == '256'
    assert server[server.index('--max-model-len') + 1] == '31008'
    assert '--no-enable-prefix-caching' in server


def sample(t, generated, prompt=0, running=2, waiting=0, preemptions=0):
    return {'start': t, 'end': t, 'values': {'vllm:generation_tokens_total': generated,
        'computed_prompt_tokens': prompt, 'vllm:num_requests_running': running,
        'vllm:num_requests_waiting': waiting, 'vllm:num_preemptions_total': preemptions,
        'vllm:kv_cache_usage_perc': 0.96}}


def native():
    return {'start_times': [0, 0], 'ttfts': [1, 2], 'itls': [[10], [10]], 'failed': 0}


def test_decode_excludes_prefill_ramp_drain_and_requires_full_concurrency():
    samples = [sample(i, i * 20, prompt=30000 if i < 3 else 60000) for i in range(13)]
    samples[6]['values']['vllm:num_requests_waiting'] = 1
    report = summarize_phases(native(), samples, 2)
    assert report['decode']['sampled_seconds'] == 5  # [3,10] minus two intervals touching waiting.
    assert report['decode']['tokens_per_second'] == 20
    assert report['decode']['tokens_per_second_per_request'] == 10
    assert report['decode']['kv_fraction_min'] == 0.96


def test_no_clean_window_is_reported_as_missing_not_e2e_decode():
    samples = [sample(t, t * 10, running=1) for t in range(13)]
    report = summarize_phases(native(), samples, 2)
    assert report['decode'] is None
    assert report['decode_unavailable_reason']


def test_preemption_and_counter_reset_invalidate_decode():
    samples = [sample(t, t * 10, preemptions=int(t >= 5)) for t in range(13)]
    assert summarize_phases(native(), samples, 2)['decode'] is None
    samples[7]['values']['vllm:generation_tokens_total'] = 0
    assert 'counter reset' in summarize_phases(native(), samples, 2)['invalid_reason']


def test_prefill_only_uses_intervals_without_generated_counter_increments():
    samples = [sample(0, 0, prompt=0), sample(1, 0, prompt=5000), sample(2, 1, prompt=10000)]
    report = summarize_phases(native(), samples, 2)
    assert report['pure_prefill']['computed_tokens'] == 5000
    assert report['pure_prefill']['computed_tokens_per_second'] == 5000


def test_incomplete_timings_not_accepted():
    d = native();d['ttfts'] = [1]
    assert summarize_phases(d, [], 2)['invalid_reason']


def test_browser_dataset_exact_native_token_lengths(tmp_path):
    class CharTokenizer:
        def apply_chat_template(self, messages, **kwargs):
            return messages[0]['content'] + messages[1]['content'] + 'ASSISTANT:'
        def encode(self, text, **kwargs):
            return list(map(ord, text))
        def decode(self, ids, **kwargs):
            return ''.join(map(chr, ids))
        def __call__(self, text):
            return SimpleNamespace(input_ids=self.encode(text))
    path = tmp_path / 'browser.jsonl'
    metadata = write_dataset(CharTokenizer(), path, 5000, 3)
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert len(rows) == 3
    assert all(len(row['prompt']) == 5000 for row in rows)  # Character tokenizer, not Qwen token inference.
    assert all('Current goal:' in row['prompt'] and row['prompt'].endswith('ASSISTANT:') for row in rows)
    assert len(set(metadata['token_sha256'])) == 3
