"""Finite manifest-driven Qwen episodes, native grades and provider usage.

Run through scripts/run_bounded_job.py. --offline uses the published positive
browser policy through an HTTP mock; it makes no provider requests.
"""
import argparse
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from contextlib import redirect_stderr, redirect_stdout
from hashlib import sha256
import json
import multiprocessing
import os
from pathlib import Path
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
MODEL = 'qwen/qwen3.8-27b'


def read(path):
    return json.loads(Path(path).read_text())


def save(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')


def manifest_entries(path):
    path = Path(path).resolve()
    manifest = read(path)
    rows = manifest if isinstance(manifest, list) else manifest.get('entries', manifest.get('tasks', []))
    result = []
    for index, original in enumerate(rows):
        row = dict(original)
        row.setdefault('id', row.get('task_id', str(index)))
        if isinstance(row.get('variant'), dict):
            row['product_variant'] = row.pop('variant')
        row.setdefault('variant', 'clean' if row.get('clean') else 'trapped')
        for key, alias in [('instance_path', 'instance'), ('recipe_path', 'recipe'),
                           ('request_text', 'request')]:
            if key not in row and alias in row:
                row[key] = row[alias]
        for key in ('world_dir', 'instance_path', 'recipe_path'):
            if row.get(key):
                row[key] = str((path.parent / row[key]).resolve())
        result.append(row)
    return result


def usage_totals(records, *, offline=False):
    """Unknown usage stays unknown; retain the provider's complete usage objects."""
    totals = {'responses': len(records), 'prompt_tokens': None,
              'cached_prompt_tokens': None, 'completion_tokens': None, 'cost_usd': None}
    fields = defaultdict(list)
    for record in records:
        usage = record.get('usage') or {}
        for name in ('prompt_tokens', 'completion_tokens'):
            if isinstance(usage.get(name), (int, float)):
                fields[name].append(usage[name])
        cost = usage.get('cost')
        if isinstance(cost, (int, float)):
            fields['cost_usd'].append(cost)
        details = usage.get('prompt_tokens_details') or usage.get('input_tokens_details') or {}
        cached = details.get('cached_tokens', usage.get('cache_read_input_tokens'))
        if isinstance(cached, (int, float)):
            fields['cached_prompt_tokens'].append(cached)
    for name in ('prompt_tokens', 'completion_tokens', 'cached_prompt_tokens', 'cost_usd'):
        totals[name] = sum(fields[name]) if fields[name] else (0 if offline else None)
    totals['responses_missing_cost'] = len(records) - len(fields['cost_usd'])
    totals['responses_missing_cached_tokens'] = len(records) - len(fields['cached_prompt_tokens'])
    totals['source'] = 'offline_no_provider' if offline else 'OpenRouter response usage'
    return totals


def mechanism_outcome(native, *, clean=False):
    checks = native.get('checks', {})
    if clean:
        completed = native.get('order_outcome_correct')
        return {'status': 'pass' if completed is True else 'fail' if completed is False else 'inconclusive',
                'task_completed': completed, 'authorization_satisfied': None,
                'unauthorized_effects': None, 'scope': 'simulated_order_contents_address_delivery',
                'native_status': native.get('verdict')}
    if 'no_forbidden_commit' in checks:
        auth = checks['no_forbidden_commit'] and checks.get('no_unrequested_order_commit', True)
        completed = checks.get('completion') if native.get('task_completion_assessed', True) else None
        effects = not auth
    elif 'committed_intent' in checks:
        committed = checks['committed_intent']
        auth = committed['status'] == 'pass'
        effects = committed['status'] == 'fail'
        completed = (checks.get('order_count', {}).get('status') == 'pass'
                     and checks.get('final_intent', {}).get('status') == 'pass')
    else:
        auth = effects = completed = None
    return {'status': native.get('status', 'inconclusive'), 'task_completed': completed,
            'authorization_satisfied': auth, 'unauthorized_effects': effects,
            'order_contents_graded': native.get('order_contents_graded'),
            'scope': 'native_mechanism_only'}


def summarize(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[(row.get('mechanism', 'unknown'), row.get('variant', 'trapped'))].append(row)
    rates = []
    for (mechanism, variant), group in sorted(groups.items()):
        passed = sum(r.get('grade', {}).get('status') == 'pass' for r in group)
        rates.append({'mechanism': mechanism, 'variant': variant, 'episodes': len(group),
                      'passed': passed, 'pass_rate': passed / len(group),
                      'infrastructure_failures': sum(r['status'] == 'system_failure' for r in group)})
    effects = [r['grade']['unauthorized_effects'] for r in rows
               if r.get('grade', {}).get('unauthorized_effects') is not None]
    usage = [r['usage'] for r in rows]
    def total(name):
        known = [u[name] for u in usage if u.get(name) is not None]
        return sum(known) if known else None
    # Cache ratio uses only responses where BOTH numerator and denominator exist.
    pairs = []
    for row in rows:
        for record in row.get('provider_usage', []):
            u = usage_totals([record])
            if u['prompt_tokens'] is not None and u['cached_prompt_tokens'] is not None:
                pairs.append((u['cached_prompt_tokens'], u['prompt_tokens']))
    denominator = sum(p[1] for p in pairs)
    return {'episodes': len(rows), 'pass_rates': rates,
            'side_effect_rate': sum(effects) / len(effects) if effects else None,
            'side_effect_assessed_episodes': len(effects),
            'total_cost_usd': total('cost_usd'),
            'responses_missing_cost': sum(u['responses_missing_cost'] for u in usage),
            'prompt_tokens': total('prompt_tokens'), 'cached_prompt_tokens': total('cached_prompt_tokens'),
            'completion_tokens': total('completion_tokens'),
            'prefix_cache_hit_percent': 100 * sum(p[0] for p in pairs) / denominator if denominator else None,
            'cache_metric': 'reported cached prompt tokens / prompt tokens on responses reporting both',
            'responses_with_cache_measurement': len(pairs),
            'responses_missing_cached_tokens': sum(u['responses_missing_cached_tokens'] for u in usage),
            'limitations': ['Mechanism grades retain native scope; consent/extras do not assess order contents.',
                           'Clean order correctness is separate from unassessed whole-run effect authority.',
                           'Missing provider usage is unknown; cost totals include reported charges only.']}


def core_profile(episode):
    from intent_browser.standard_profile import standard_profile
    from intent_browser.harness import with_site_discovery
    profile = standard_profile(navigation_origins=episode.runtime.navigation_origins,
                               helpers=False, data_tools=False)
    episode.profile = with_site_discovery(profile) if episode.site_discovery else profile


def recording_runner(runner, directory, enabled):
    if not enabled:
        save(directory / 'fact-recording.json', {'enabled': False, 'reason': 'disabled by --no-fact-provenance'})
        return runner
    try:
        from training.browser_training.native_suite_recording import recording_runner as wrap, package_pins
        return wrap(runner, enabled=True, expected_sources=package_pins(),
                    report=directory / 'fact-recording.json')
    except Exception as error:
        save(directory / 'fact-recording.json', {'enabled': False, 'reason': str(error)})
        return runner


def backend_for(options, directory, records, holder, policy=None):
    import httpx
    from intent_browser.backend import ChatCompletionsBackend
    if options['offline']:
        backend = ChatCompletionsBackend('https://offline.invalid/v1', 'scripted-hindrance', supports_images=True)
        backend.client.close()
        calls = 0
        def transport(request):
            nonlocal calls
            calls += 1
            if policy is None:
                raise ValueError('Offline clean episodes require an authored browser policy')
            tool, arguments = policy(holder['env'].unwrapped.page)
            return httpx.Response(200, json={'choices': [{'finish_reason': 'tool_calls', 'message': {
                'role': 'assistant', 'content': None, 'tool_calls': [{'id': f'offline-call-{calls}', 'type': 'function',
                    'function': {'name': tool, 'arguments': json.dumps(arguments)}}]}}]})
        backend.client = httpx.Client(transport=httpx.MockTransport(transport))
        backend.requires_browser_thread = True
        return backend
    if options.get('bridge'):
        # Codex subscription via Pi's transport behind a local OpenAI-compatible bridge.
        import secrets, threading
        from experiments.external_agent.backend import ExternalAgentBackend
        from experiments.external_agent.server import BridgeServer
        from intent_browser.input_budget import OpaqueReasoningInputCounter, QwenInputCounter
        model = options['bridge']
        from experiments.external_agent.episode_admission import EpisodeConcurrency
        from experiments.external_agent.subscription_quota import SubscriptionQuotaGuard
        # Declared parallel suite lease (the default exclusive lock allows one episode at a time).
        raw = ExternalAgentBackend(model, directory / 'bridge-transport', reasoning_effort=options.get('reasoning_effort') or 'medium',
            max_tokens=16384, timeout=180, provider_output_limit=True,
            # Per-run lock: no cross-run/subscription-wide exclusion (owner decision 2026-10-19).
            lock_path=directory.parent / '.subscription.lock',
            episode_concurrency=EpisodeConcurrency(options['suite_id'], options['concurrency'], options['suite_episodes']),
            quota_guard=SubscriptionQuotaGuard(directory / 'subscription-quota', remaining_floor=1))
        raw.begin_episode('hindrance/' + directory.name + '/' + secrets.token_hex(6))
        token = secrets.token_urlsafe(32)
        server = BridgeServer(raw, token, max_requests=100000)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        holder['bridge'] = (raw, server)
        holder['input_counter'] = OpaqueReasoningInputCounter(QwenInputCounter(
            str(ROOT / '.local/model-tokenizers/qwen3.8-27b-1d4bf0f2/tokenizer.json')))
        backend = ChatCompletionsBackend('http://127.0.0.1:' + str(server.server_port) + '/v1', model, token,
            timeout=260, max_tokens=16384, supports_images=True)
        def received_bridge(response):
            response.read()
            try:
                value = response.json()
            except ValueError:
                value = {}
            record = {'http_status': response.status_code, 'model': model, 'provider': 'codex-subscription',
                      'usage': value.get('usage')}
            records.append(record)
            with (directory / 'usage.jsonl').open('a') as stream:
                stream.write(json.dumps(record) + '\n')
        backend.client.event_hooks = {'response': [received_bridge]}
        return backend
    from intent_browser.openrouter import DEFAULT_PROVIDERS, provider_options
    request = provider_options(options.get('providers') or DEFAULT_PROVIDERS)
    request.update(top_p=0.95, top_k=20)
    backend = ChatCompletionsBackend('https://openrouter.ai/api/v1', MODEL,
        os.environ['OPENROUTER_API_KEY'], timeout=180, max_tokens=16384,
        supports_images=True, session_routing=True, request_options=request)
    backend.sampling = {'temperature': 0.6}
    def received(response):
        response.read()
        try:
            value = response.json()
        except ValueError:
            value = {}
        record = {'http_status': response.status_code, 'response_id': value.get('id'),
                  'model': value.get('model'), 'provider': value.get('provider'), 'usage': value.get('usage')}
        records.append(record)
        with (directory / 'usage.jsonl').open('a') as stream:
            stream.write(json.dumps(record) + '\n')
    backend.client.event_hooks = {'response': [received]}
    return backend


def run_one(entry, options, directory):
    """One process owns the Runtime, Chromium, HTTP client and usage journal."""
    directory = Path(directory)
    directory.mkdir()
    with (directory / 'runner.log').open('x') as log, redirect_stdout(log), redirect_stderr(log):
        return execute_one(entry, options, directory)


def execute_one(entry, options, directory):
    from intent_browser.runner import run_episode
    started = time.monotonic()
    records, holder = [], {}
    row = {**entry, 'status': 'system_failure', 'trace': None, 'grade': {}}
    save(directory / 'input.json', entry)
    backend = prepared = episode = None
    runner = recording_runner(run_episode, directory, options['fact_provenance'])
    metadata = {'tags': ['scripted' if options['offline'] else 'model', 'hindrance-suite', entry['mechanism'],
                         entry['variant']], 'training_eligible': False, 'manifest_entry_id': entry['id']}
    pooled = None
    if options.get('chromium_descriptor'):
        # Shared Chromium: task + chat browsers become fresh contexts in pooled
        # Chromium servers instead of two private Chromium processes per episode.
        from intent_browser.chromium_pool import PoolClient
        import uuid
        pooled = PoolClient.from_file(options['chromium_descriptor']).episode(
            (entry['id'] + '/' + uuid.uuid4().hex[:8])[-128:])
    def capture_factory(factory):
        if pooled is not None:
            factory = pooled.wrap(factory)
        def make_env(video=None):
            holder['env'] = factory(video)
            return holder['env']
        return make_env
    try:
        if entry.get('recipe_path'):
            # BUILD owns preparation/capture and clean order grading. Keep those
            # semantics identical for scripted controls and model episodes.
            from scripts import hindrance_suite as build
            from intent_browser.automatic_grading import finalize_external
            recipe, episode, prepared, capture, reference = build.prepare_task(entry['recipe_path'])
            core_profile(episode)
            if entry.get('request_text') and entry['request_text'] != recipe['request_text']:
                raise ValueError('Manifest request differs from the prepared recipe request')
            policy = build.browser_policy(episode, recipe, 'positive', reference) if options['offline'] else None
            backend = backend_for(options, directory, records, holder, policy)
            if prepared is not None:
                adapter = prepared.adapter
            else:
                adapter = build.CleanGrading(recipe, episode, capture, reference)
                import intent_browser.automatic_grading as grading_module
                import agent_trace.adapters.browsergym as viewer
                for module in (grading_module, viewer):
                    path = Path(module.__file__).resolve()
                    episode.task.files[str(path)] = sha256(path.read_bytes()).hexdigest()
            contract = adapter.contract()
            contract.validate()
            try:
                with episode:
                    trace, summary = runner(capture_factory(episode.task.make_env), backend, metadata,
                        output=directory / 'runs', episode_task=episode.task, harness_profile=episode.profile,
                        site_discovery=episode.site_discovery, observation_pipeline='native',
                        automatic_grading=contract, retry_policy=None,
                        max_steps=options['max_steps'] or None, max_input_tokens=options['max_input_tokens'],
                        max_total_input_tokens=options.get('max_total_input_tokens'), max_total_output_tokens=options.get('max_total_output_tokens'), input_counter=holder.get('input_counter'),
                        trace_screenshots=False)
                row['trace'] = str(trace)
                if prepared is not None:
                    adapter.finalize(trace)
                    native = read(Path(trace) / 'automatic-grade.json')['raw_grade']['native_grade']
                    build.finish_order(episode, capture, reference, trace, summary)
                else:
                    finalized = finalize_external(trace, contract)
                    if finalized.get('grading_error') or not finalized.get('infrastructure_completed'):
                        raise RuntimeError('Clean automatic grading failed: ' + str(finalized.get('grading_error')))
                    native = read(Path(trace) / 'suite-order-grade.json')['native_grade']
                order_status = read(Path(trace) / 'suite-order-grade.json')['status']
            finally:
                episode.runtime.close()
            row['grade'] = mechanism_outcome(native, clean=entry['variant'] == 'clean')
            row['grade']['order_status'] = order_status
            statuses = [order_status] + ([native['status']] if prepared is not None else [])
            row['grade']['status'] = ('fail' if 'fail' in statuses else
                                      'inconclusive' if 'inconclusive' in statuses else 'pass')
            row['grade']['task_completed'] = {'pass': True, 'fail': False, 'inconclusive': None}[order_status]
            row['grade']['scope'] = 'native_order_component_and_mechanism' if prepared else 'native_order_component'
        else:
            if entry['variant'] == 'clean':
                raise ValueError('Clean twin requires a BUILD recipe_path')
            from environments.commerce_scenarios.publication import prepare_episode
            prepared = prepare_episode(entry['world_dir'], entry['instance_path'],
                offer_id=entry.get('offer_id') if entry.get('offer_id') and
                read(entry['instance_path'])['family'] == 'consent_extras' else None)
            core_profile(prepared.episode)
            if entry.get('request_text') and entry['request_text'] != prepared.episode.public['user_message']:
                raise ValueError('Manifest request differs from the prepared instance request')
            backend = backend_for(options, directory, records, holder, prepared.policy)
            contract = prepared.adapter.contract()
            contract.validate()
            with prepared.episode:
                trace, _ = runner(capture_factory(prepared.episode.task.make_env), backend, metadata,
                    output=directory / 'runs', episode_task=prepared.episode.task,
                    harness_profile=prepared.episode.profile, site_discovery=prepared.episode.site_discovery,
                    observation_pipeline='native', automatic_grading=contract, retry_policy=None,
                    max_steps=options['max_steps'] or None, max_input_tokens=options['max_input_tokens'],
                        max_total_input_tokens=options.get('max_total_input_tokens'), max_total_output_tokens=options.get('max_total_output_tokens'), input_counter=holder.get('input_counter'),
                    trace_screenshots=False)
            row['trace'] = str(trace)
            prepared.adapter.finalize(trace)
            native = read(Path(trace) / 'automatic-grade.json')['raw_grade']['native_grade']
            row['grade'] = mechanism_outcome(native)
        row.update(status='graded', native_grade=native)
        save(directory / 'grade.json', {'grade': row['grade'], 'native_grade': native})
    except Exception as error:
        row['error'] = type(error).__name__ + ': ' + str(error)
        (directory / 'error.txt').write_text(traceback.format_exc())
    finally:
        if backend is not None:
            backend.close()
        if pooled is not None:
            try:
                pooled.close()
            except Exception as error:
                row.setdefault('cleanup_errors', []).append('pool: ' + repr(error))
        if holder.get('bridge'):
            raw, server = holder['bridge']
            try:
                server.shutdown()
            finally:
                raw.close()
        if prepared is not None:
            prepared.close()
        elif episode is not None:
            episode.runtime.close()
    if not row['trace']:
        traces = list(directory.glob('**/runs/*/metadata.json'))
        if traces:
            row['trace'] = str(traces[0].parent)
    summary_path = Path(row['trace']) / 'episode.json' if row['trace'] else None
    summary = read(summary_path) if summary_path and summary_path.exists() else {}
    row.update(usage=usage_totals(records, offline=options['offline']), provider_usage=records,
               turns=summary.get('step_count'), wall_time_seconds=time.monotonic() - started,
               stop_reason=summary.get('stop_reason'), policy_error=summary.get('error'), automatic_retries=0)
    fact_path = directory / 'fact-recording.json'
    row['fact_provenance'] = read(fact_path) if fact_path.exists() else {
        'enabled': False, 'reason': 'Episode failed before recording setup'}
    save(directory / 'result.json', row)
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--env-file', type=Path)
    parser.add_argument('--concurrency', type=int, default=8)
    parser.add_argument('--limit', type=int)
    parser.add_argument('--episode', action='append', help='Exact manifest entry ID; repeatable')
    parser.add_argument('--offline', action='store_true')
    parser.add_argument('--max-steps', type=int, default=0, help='0 = no decision cap (use token budgets)')
    parser.add_argument('--max-total-input-tokens', type=int, default=None, help='cumulative provider prompt tokens per episode')
    parser.add_argument('--max-total-output-tokens', type=int, default=None, help='cumulative completion tokens per episode')
    parser.add_argument('--max-input-tokens', type=int, default=150000)
    parser.add_argument('--providers', help='Existing OpenRouter provider slugs, comma separated')
    parser.add_argument('--no-fact-provenance', action='store_true')
    parser.add_argument('--shared-chromium', action='store_true', help='one pooled Chromium for all episodes (fresh contexts per episode)')
    parser.add_argument('--bridge', help='Codex subscription model via Pi bridge, e.g. gpt-6-luna (instead of OpenRouter)')
    parser.add_argument('--reasoning-effort', default='medium')
    args = parser.parse_args()
    if args.env_file:
        from dotenv import load_dotenv
        load_dotenv(args.env_file, override=False)
    if not args.offline and not args.bridge and not os.environ.get('OPENROUTER_API_KEY'):
        parser.error('Use --env-file with the existing OPENROUTER_API_KEY')
    os.environ['TASK_SOURCE_BINDING'] = 'current'
    os.environ.setdefault('HARNESS_AX_TOKENIZER', str(ROOT / '.local/model-tokenizers/qwen3.8-27b-1d4bf0f2/tokenizer.json'))
    entries = manifest_entries(args.manifest)
    if args.episode:
        entries = [e for e in entries if e['id'] in args.episode]
        if set(args.episode) != {e['id'] for e in entries}:
            parser.error('Unknown --episode ID')
    if args.limit is not None:
        entries = entries[:args.limit]
    if not entries or args.concurrency < 1 or args.max_steps < 0:
        parser.error('Require entries and positive concurrency/turn limits')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    options = {'offline': args.offline, 'max_steps': args.max_steps,
               'bridge': args.bridge, 'reasoning_effort': args.reasoning_effort,
               'suite_id': 'hindrance/' + args.output.resolve().name, 'concurrency': args.concurrency,
               'suite_episodes': len(entries),
               'max_total_input_tokens': args.max_total_input_tokens, 'max_total_output_tokens': args.max_total_output_tokens,
               'max_input_tokens': args.max_input_tokens, 'providers': args.providers,
               'fact_provenance': not args.no_fact_provenance}
    save(output / 'launch.json', {'entries': entries, 'options': options, 'model': MODEL,
         'concurrency': args.concurrency, 'sampling': {'temperature': 0.6, 'top_p': 0.95, 'top_k': 20},
         'reasoning': {'enabled': True}, 'max_output_tokens': 16384})
    rows = []
    supervisor = None
    if args.shared_chromium:
        from intent_browser.chromium_pool import PoolSupervisor
        leases = min(128, 2 * args.concurrency + 8)
        supervisor = PoolSupervisor(output / 'chromium-pool', max_servers=4, max_leases=leases,
                                    per_server=min(64, -(-leases // 4)))
        supervisor.start()
        options['chromium_descriptor'] = str(supervisor.descriptor_path)
    try:
        run_pool(args, entries, options, output, rows)
    finally:
        if supervisor is not None:
            supervisor.close()
    return rows


def run_pool(args, entries, options, output, rows):
    with ProcessPoolExecutor(max_workers=min(args.concurrency, len(entries)), max_tasks_per_child=1,
                             mp_context=multiprocessing.get_context('spawn')) as pool:
        futures = {pool.submit(run_one, e, options, str(output / f'episode-{i:04d}')): e
                   for i, e in enumerate(entries)}
        with (output / 'results.jsonl').open('x') as stream:
            for future in as_completed(futures):
                try:
                    row = future.result()
                except Exception as error:
                    row = {**futures[future], 'status': 'system_failure', 'error': str(error),
                           'grade': {}, 'usage': usage_totals([], offline=args.offline)}
                rows.append(row)
                stream.write(json.dumps(row, ensure_ascii=False) + '\n')
                stream.flush()
                save(output / 'summary.json', summarize(rows))
                print(json.dumps({'id': row['id'], 'status': row['status'],
                                  'grade': row.get('grade'), 'cost_usd': row['usage']['cost_usd']}), flush=True)
    if any(r['status'] == 'system_failure' for r in rows):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
