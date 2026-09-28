"""One explicitly selected saved answer -> Qwen schema extraction -> frozen oracle."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from datetime import datetime, timezone

from .extraction import MODEL, VERSION, messages, response_format, schema_for, strict_loads, validate_claims
from .grading import check_supported, grade_claims, research_effects
from .saved import load_saved, sha


def write(path, value):
    with Path(path).open('x') as f: json.dump(value, f, indent=2, ensure_ascii=False, allow_nan=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cohort', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path, help='New directory; original episode never rewritten')
    parser.add_argument('--live', action='store_true', help='Exactly one OpenRouter extraction request; no retries')
    parser.add_argument('--claims', type=Path, help='Offline replay of saved extractor JSON, without inference')
    args = parser.parse_args()
    if args.live and args.claims: parser.error('Use --live OR --claims')
    if args.output.exists() or args.output.is_symlink(): parser.error('Output already exists')
    root = Path.cwd(); cohort = args.cohort.resolve()
    # No core module was imported above; use the original task/oracle and backend.
    sys.path.insert(0, str(cohort / 'source'))
    saved = load_saved(cohort); check_supported(saved.episode)
    effects = research_effects(saved.initial, saved.final)
    schema = schema_for(saved.episode)
    prompt = messages(saved.public, saved.answer, schema=schema)
    args.output.mkdir(parents=True)
    out = args.output
    from intent_browser.openrouter import provider_options, DEFAULT_PROVIDERS
    options = provider_options(DEFAULT_PROVIDERS)
    options['response_format'] = response_format(schema)
    plan = {'version': VERSION, 'model': MODEL, 'mode': 'live' if args.live else 'replay' if args.claims else 'prepare',
            'max_tokens': 16384, 'requests': 1 if args.live else 0, 'client_retries': 0,
            'source_trace': str(saved.trace), 'reasoning_enabled': True,
            'authorization': 'One extraction for the selected completed episode; no browser/model rerun.',
            'created_at': datetime.now(timezone.utc).isoformat(),
            'code_sha256': {str(p.resolve()): sha(p) for p in Path(__file__).parent.glob('*.py')}}
    write(out/'plan.json', plan); write(out/'source-hashes.json', saved.hashes)
    (out/'source').mkdir()
    for name, expected in plan['code_sha256'].items():
        data = Path(name).read_bytes()
        if hashlib.sha256(data).hexdigest() != expected: raise ValueError('Extractor source changed during freeze')
        with (out/'source'/Path(name).name).open('xb') as f: f.write(data)
    write(out/'extractor-messages.json', prompt); write(out/'response-format.json', options['response_format'])
    write(out/'effects.private.json', effects)
    backend = None
    try:
        if args.live:
            from dotenv import dotenv_values
            from intent_browser.backend import ChatCompletionsBackend
            key = os.environ.get('OPENROUTER_API_KEY') or dotenv_values(root/'.env').get('OPENROUTER_API_KEY')
            if not key: raise ValueError('OPENROUTER_API_KEY unavailable')
            backend = ChatCompletionsBackend('https://openrouter.ai/api/v1', MODEL, key,
                timeout=180, max_tokens=16384, request_options=options, session_routing=True)
            backend.begin_episode('answer-extraction-'+saved.trace.name)
            def dispatch(request):
                for name, expected in {**saved.hashes, **plan['code_sha256']}.items():
                    if sha(name) != expected: raise ValueError('Source drift before extraction')
                write(out/'request.json', json.loads(request.content))
                write(out/'dispatch.json', {'at': datetime.now(timezone.utc).isoformat(), 'attempt': 1})
            def response_hook(response):
                response.read()
                with (out/'response.body').open('xb') as f: f.write(response.content)
                write(out/'http.json', {'status': response.status_code, 'retry_after': response.headers.get('retry-after'),
                                       'at': datetime.now(timezone.utc).isoformat()})
            backend.client.event_hooks = {'request': [dispatch], 'response': [response_hook]}
            completion = backend.complete(prompt)
            write(out/'response.json', completion.raw)
            usage = completion.raw.get('usage') or {}
            write(out/'usage.json', {'model': completion.raw.get('model'), 'provider': completion.raw.get('provider'),
                                   'usage': usage, 'reported_cost_usd': usage.get('cost')})
            choice = completion.raw['choices'][0]
            if choice.get('finish_reason') != 'stop' or choice['message'].get('refusal') or choice['message'].get('tool_calls'):
                raise ValueError('Incomplete/refused/nontext extraction; retained without repair')
            claims = strict_loads(completion.text)
        elif args.claims:
            claims = strict_loads(args.claims.read_text())
            write(out/'replay-input.json', {'path': str(args.claims.resolve()), 'sha256': sha(args.claims)})
        else:
            print(json.dumps({'status': 'prepared', 'output': str(out), 'inference_calls': 0})); return
        write(out/'claims.json', claims)
        validate_claims(claims, saved.answer, schema=schema)
        result = grade_claims(saved.episode, claims, saved.answer, effects=effects, schema=schema)
        for name, expected in {**saved.hashes, **plan['code_sha256']}.items():
            if sha(name) != expected: raise ValueError('Source drift during grading')
        result['source_trace'] = str(saved.trace)
        result['extraction_version'] = VERSION
        write(out/'grade.json', result)
        write(out/'completed.json', {'status': 'graded', 'source_hashes_unchanged': True})
        if args.live:
            # A display publication failure must not relabel a valid extraction.
            from .publish import publish
            try:
                artifact = publish(out)
                from .details import publish_details
                details = publish_details(out, artifact)
                write(out/'viewer-publication.json', {'status': 'published', 'artifact': str(artifact), 'details': str(details)})
            except Exception as exc:
                write(out/'viewer-publication.json', {'status': 'failed', 'error': str(exc)})
                print('Grade retained; viewer publication failed: ' + str(exc), file=sys.stderr)
        print(json.dumps({'status': 'graded', 'structured_claims_correct': result['structured_claims_correct'],
                          'requirements': result['oracle_grade']['requirements'], 'output': str(out)}))
    except Exception as exc:
        # Bodies/usage are already preserved where received; no automatic inference retry.
        write(out/'error.json', {'stage': 'extraction_or_grading', 'type': type(exc).__name__,
                                'message': str(exc), 'structured_claims_correct': None})
        raise
    finally:
        if backend: backend.close()


if __name__ == '__main__': main()
