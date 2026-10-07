"""Authored offline consumer controls; no browser, provider or world draw."""
from contextlib import contextmanager
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from environments.website_world import catalog_compare_review_publication as publication
from environments.website_world import catalog_compare_review_execution as execution
from environments.website_world.test_catalog_compare_review_task import fixture


class Backend:
    """Owned offline formatter fixture; no dependency on another test package."""
    def __init__(self, claims, events):
        self.claims, self.events = claims, events
        self.model = 'scripted-formatter'

    def complete(self, prompt):
        self.events.append(('dispatch', prompt))
        text = json.dumps(self.claims)
        raw = {'model': self.model, 'provider': 'offline', 'usage': {},
               'choices': [{'finish_reason': 'stop', 'message': {'content': text}}]}
        return SimpleNamespace(text=text, raw=raw, request={'messages': prompt})

    def close(self):
        self.events.append(('close', None))


@pytest.mark.parametrize('bound', [True, False])
def test_freeze_private_roles_nulls_and_native_bindings_without_second_draw(tmp_path, monkeypatch, bound):
    _, task, reference, *_ = fixture()
    records = {'catalog_compare_review_task': task if bound else None,
        'catalog_compare_review_reference': reference if bound else None,
        'compare_review_task_binding': {'status': 'bound' if bound else 'unsupported_fewer_than_two_carried_models',
                                      'world_repaired': False},
        'compare_review_field_inventory': {'source_hashes': {}},
        'compare_review_topic_inventory': {'topics': []},
        'required_obligations': task['required_obligations'] if bound else []}
    calls = []
    def generated(*a, **kw): calls.append(True); return deepcopy(records)
    monkeypatch.setattr(publication, 'generate', generated)
    def freeze(request, output, **kw):
        result = generate(request)  # replaced globals of the inherited writer
        assert result['feature_offer_reference']['status'] == records['compare_review_task_binding']['status']
        output.mkdir(); files = {}
        for name, key in [('feature-offer-task.private.json', 'feature_offer_task'),
                          ('feature-offer-reference.private.json', 'feature_offer_reference'),
                          ('feature-field-inventory.private.json', 'feature_field_inventory')]:
            (output/name).write_text(json.dumps(result[key])); files[name] = sha256((output/name).read_bytes()).hexdigest()
        return {'files': files}
    monkeypatch.setattr(publication.feature, 'prepare', freeze)
    output = tmp_path/'fresh'
    result = publication.prepare({}, output, answer_grading={'mode': 'subscription-post-run'})
    assert calls == [True]
    assert json.loads((output/'catalog-compare-review-task.private.json').read_text()) == records['catalog_compare_review_task']
    assert json.loads((output/'catalog-compare-review-reference.private.json').read_text()) == records['catalog_compare_review_reference']
    assert json.loads((output/'required-obligations.private.json').read_text()) == records['required_obligations']
    assert result['automatic_grader_supported'] is bound
    assert result['public_readiness'] == 'requires_separate_runtime_audit'
    assert not list(output.glob('feature-*'))
    for name, h in result['files'].items(): assert sha256((output/name).read_bytes()).hexdigest() == h


def test_preparation_cannot_disable_automatic_grading(tmp_path, monkeypatch):
    def forbidden(*a, **kw): raise AssertionError('No sampling')
    monkeypatch.setattr(publication, 'generate', forbidden)
    with pytest.raises(ValueError, match='automatic'): publication.prepare({}, tmp_path/'world')


def readiness_fixture(tmp_path):
    world, task, reference, bindings, *_ = fixture()
    runtime = SimpleNamespace(world=world, bindings=bindings, site_registry=[], compositions={},
                              public_catalogs={}, review_products={})
    document = tmp_path/'public.html'; document.write_text('<main>Authored public witness fixture</main>')
    facts = {row['product_id']: row['facts'] for row in reference['comparison']['models']}
    rows = [{**{k: r[k] for k in ('role_id', 'product_id', 'source_family')},
             'status': facts[r['product_id']][r['field']]['status'] if r['source_family'] == 'retailer' else 'known',
             'document': str(document), 'locator': '#authored-'+str(n)}
            for n, r in enumerate(task['required_obligations'])]
    return runtime, task, reference, {'schema': 'website-compare-review-readiness-v1', 'status': 'sufficient',
        'task_id': task['task_id'], 'runtime_binding_sha256': execution.public_binding(runtime),
        'files': {str(document): sha256(document.read_bytes()).hexdigest()}, 'roles': rows}


@pytest.mark.parametrize('change', ['partial', 'duplicate', 'foreign_model', 'known_omitted',
    'wrong_family', 'locator', 'runtime', 'document', 'insufficient'])
def test_readiness_rejects_partial_stale_or_logically_changed_public_roles(tmp_path, change):
    runtime, task, reference, report = readiness_fixture(tmp_path)
    if change == 'partial': report['roles'].pop()
    elif change == 'duplicate': report['roles'][-1] = deepcopy(report['roles'][0])
    elif change == 'foreign_model': report['roles'][0]['product_id'] = 'foreign'
    elif change == 'known_omitted': report['roles'][0]['status'] = 'unknown'
    elif change == 'wrong_family': report['roles'][0]['source_family'] = 'product_reviews'
    elif change == 'locator': report['roles'][0]['locator'] = ''
    elif change == 'runtime': runtime.compositions['r'] = {'changed': True}
    elif change == 'document': Path(next(iter(report['files']))).write_text('changed')
    else: report['status'] = 'insufficient'
    with pytest.raises(ValueError): execution.check_readiness(report, runtime=runtime, task=task, reference=reference)


def test_readiness_envelope_preserves_every_role_and_does_not_mutate_native_inputs(tmp_path):
    runtime, task, reference, report = readiness_fixture(tmp_path)
    before = deepcopy((task, reference, report))
    assert execution.check_readiness(report, runtime=runtime, task=task, reference=reference) == report
    assert (task, reference, report) == before
    # This is only an envelope test; the authored HTML contains no genuine fact
    # witnesses. It cannot be used as a real semantic-audit acceptance receipt.


def run_fixture(tmp_path, monkeypatch):
    output = tmp_path/'world'; output.mkdir()
    (output/'execution.private.json').write_text(json.dumps({'validation': 'off',
        'runtime_options': {'lazy_publication': True}, 'answer_grading': {'mode': 'subscription-post-run'}}))
    events = []
    _, native_task, reference, *_ = fixture()
    public = {'schema_version':'connected-world-manual-v1','start_url':'https://index.test/',
              'task_id': native_task['task_id'], 'user_message': native_task['user_message'],
              'memories': native_task['memories'], 'environment_context': {'currency': 'SEK'}}
    for filename, value in {'pin/world.private.json': {},
        'catalog-compare-review-task.private.json': native_task,
        'catalog-compare-review-reference.private.json': reference,
        'surrounding.private.json': {}}.items():
        path = output/filename; path.parent.mkdir(exist_ok=True);path.write_text(json.dumps(value))
    class Episode:
        def __init__(self, *a, **kw):
            events.append('public-audit'); self.public_readiness = {'test': True}
            source=Path(execution.__file__).resolve()
            self.task = SimpleNamespace(files={str(source): sha256(source.read_bytes()).hexdigest()}, make_env=lambda: None)
            self.profile = SimpleNamespace(name='test'); self.site_discovery = None
            self.native_task = native_task; self.public = deepcopy(public)
            self.task.public=self.public
            self.original_public=self.public;self.instance_binding={}
        def __enter__(self): return self
        def __exit__(self, *a): events.append('runtime-close')
        def export_private_runtime(self, output):
            output.mkdir(); files={}
            for name in ('bindings.private.json','site-registry.private.json',
                         'original-public-task.private.json','public-instance-binding.private.json'):
                value=(self.original_public if name=='original-public-task.private.json' else
                       self.instance_binding if name=='public-instance-binding.private.json' else {})
                path=output/name;path.write_text(json.dumps(value));files[name]=sha256(path.read_bytes()).hexdigest()
            (output/'manifest.json').write_text(json.dumps({'files': files}))
            return {'files': files}
    monkeypatch.setattr(execution, 'CatalogCompareReviewEpisode', Episode)
    monkeypatch.setattr(execution.shared, 'load', lambda _: {'source_sha256': {}})
    source = tmp_path/'auditor.py'; source.write_text('# authored source fixture')
    source_pins = {str(source): sha256(source.read_bytes()).hexdigest(),
                   str(Path(__file__).resolve()): sha256(Path(__file__).read_bytes()).hexdigest()}
    @contextmanager
    def policy(*, before_dispatch):
        before_dispatch(); events.append('policy-open')
        try: yield object()
        finally: events.append('policy-close')
    def runner(*a, **kw):
        from intent_browser.automatic_grading import GradingGate, validate_options
        from intent_browser.connected_world_task import policy_goal
        contract=kw['automatic_grading'];validate_options(contract,False,None)
        trace = kw['output']/'actual'; trace.mkdir(parents=True)
        actual=SimpleNamespace(directory=trace,episode_id=trace.name)
        displayed=kw['episode_task'].public
        gate=GradingGate(actual,contract);gate.bind(None,{'goal':policy_goal(displayed)})
        gate.pending_external()
        (trace/'policy-task.json').write_text(json.dumps(displayed))
        summary={'stop_reason':'agent_finished','trace_complete':True,'error':None}
        (trace/'episode.json').write_text(json.dumps(summary))
        events.append('policy-return'); return trace, summary
    def grade(**kw):
        assert events[-1] == 'runtime-close'
        assert kw['grader_factory'] is execution.CatalogCompareReviewGrader
        assert set(kw['inputs']) == {'world', 'task', 'reference', 'bindings', 'site_registry', 'surrounding'}
        assert kw['inputs']['task'] == output/'catalog-compare-review-task.private.json'
        assert kw['inputs']['site_registry'] == tmp_path/'run/runtime-binding/site-registry.private.json'
        assert kw['trace'] == tmp_path/'run/runs/actual'
        events.append('compound-grade'); return {'structured_claims_correct': True}
    monkeypatch.setattr(execution, 'extract_saved_deferred', lambda **kw:{'grade':grade(**kw)})
    monkeypatch.setattr(execution, 'publish_finalized_answer', lambda deferred,**kw:deferred['grade'])
    from intent_browser import automatic_grading
    def canonical(trace,evaluation):
        return {'schema':'automatic-grade-projection-v1','episode_id':trace.episode_id,
                'evaluation_sha256':sha256((trace.directory/'evaluation.json').read_bytes()).hexdigest(),
                'verified':True}
    monkeypatch.setattr(automatic_grading,'canonical_viewer_check',canonical)
    # This suite tests the actual shared gate with an explicitly authored viewer
    # fixture. Deployed agent_trace/HTTP acceptance is a separate integration gate.
    import sys
    monkeypatch.setitem(sys.modules,'agent_trace.adapters.browsergym',
                        SimpleNamespace(__file__=str(Path(__file__).resolve())))
    def viewer(**kw): events.append('viewer'); return {'status': 'verified'}
    args = dict(policy_session=policy, metadata={}, runner_options={'max_steps': 5, 'max_input_tokens': 100000},
        viewer_projection=viewer, readiness_auditor=lambda **kw: {}, readiness_sources=source_pins,
        extraction_backend_factory=lambda p: object(), quota_guard=lambda: None, runner=runner)
    return output, events, args


def test_one_compound_grade_after_policy_close_with_required_viewer(tmp_path, monkeypatch):
    output, events, args = run_fixture(tmp_path, monkeypatch)
    result = execution.run(output, tmp_path/'run', **args)
    assert result['status'] == 'graded_and_projected' and result['task_completed']
    assert events == ['public-audit', 'policy-open', 'policy-return', 'policy-close', 'runtime-close', 'compound-grade', 'viewer']
    with pytest.raises(FileExistsError): execution.run(output, tmp_path/'run', **args)


@pytest.mark.parametrize('change', ['missing_grade', 'viewer', 'execution_error'])
def test_system_failures_never_become_task_verdicts(tmp_path, monkeypatch, change):
    output, events, args = run_fixture(tmp_path, monkeypatch)
    if change == 'missing_grade': monkeypatch.setattr(execution, 'extract_saved_deferred', lambda **kw: None)
    elif change == 'viewer': args['viewer_projection'] = lambda **kw: {'status': 'unverified'}
    else:
        original = args['runner']
        def failure(*a, **kw):
            trace, summary = original(*a, **kw); return trace, {**summary, 'execution_error': 'test'}
        args['runner'] = failure
    result = execution.run(output, tmp_path/'run', **args)
    assert result['status'] == 'system_failure' and result['task_completed'] is None
    assert result['automatic_retries'] == 0
    if change == 'execution_error': assert 'compound-grade' not in events


def test_missing_public_auditor_blocks_before_runtime_or_dispatch(tmp_path):
    with pytest.raises(ValueError, match='readiness'):
        execution.CatalogCompareReviewEpisode(tmp_path, readiness_auditor=None, readiness_sources={})


@pytest.mark.parametrize('change', ['unsupported', 'roles', 'public_task', 'coverage'])
def test_actual_episode_preflight_rejects_binding_drift_before_host_start(tmp_path, monkeypatch, change):
    from environments.website_world import runtime as runtime_module
    _, task, reference, *_ = fixture()
    site = {'kind': 'product_reviews', 'site_id': 'r',
            'product_ids': [m['product_id'] for m in task['comparison_task']['models']]}
    binding = {'status': 'bound', 'world_repaired': False,
               'publication_ids': {'model_1': ['r'], 'model_2': ['r']}}
    episode = {'task_id': task['task_id'], 'manual_task': {
        'user_message': task['user_message'], 'memories': task['memories']}, 'start': {'kind': 'directory'}}
    roles = deepcopy(task['required_obligations'])
    if change == 'unsupported': binding['status'] = 'unsupported_no_review_publication'
    elif change == 'roles': roles.pop()
    elif change == 'public_task': episode['manual_task']['user_message'] = 'A different task'
    else: site['product_ids'].pop()
    for name, value in {'episode.json': episode, 'catalog-compare-review-task.private.json': task,
        'catalog-compare-review-reference.private.json': reference, 'required-obligations.private.json': roles,
        'compare-review-binding.private.json': binding, 'surrounding.private.json': {'sites': [site]}}.items():
        (tmp_path/name).write_text(json.dumps(value))
    source = tmp_path/'auditor.py'; source.write_text('# fixture')
    monkeypatch.setattr(execution.shared, 'load', lambda _: {'recipe': execution.RECIPE})
    def forbidden(*a, **kw): raise AssertionError('No host may start')
    monkeypatch.setattr(runtime_module, 'Runtime', forbidden)
    with pytest.raises(ValueError):
        execution.CatalogCompareReviewEpisode(tmp_path, readiness_auditor=lambda **kw: {},
            readiness_sources={str(source): sha256(source.read_bytes()).hexdigest(),
                               str(Path(__file__).resolve()):sha256(Path(__file__).read_bytes()).hexdigest()})


def test_foreign_returned_trace_is_never_extracted(tmp_path, monkeypatch):
    output, events, args = run_fixture(tmp_path, monkeypatch)
    args['runner'] = lambda *a, **kw: (tmp_path/'foreign', {})
    result=execution.run(output, tmp_path/'run', **args)
    assert result['status']=='system_failure' and 'escaped' in result['reason']
    assert 'compound-grade' not in events


@pytest.mark.parametrize('omit_review_count', [False, True])
def test_real_once_only_shared_extraction_and_viewer_sidecar_over_authored_fixture(tmp_path, omit_review_count):
    from scripts.trace_grades import BOUND_FILES, read_grade
    world, task, reference, bindings, inventory, review_inventory, _, answer, claims = fixture()
    if omit_review_count:
        claims['reviews']['model_2']['rating_count'] = {'value': None, 'evidence': None}
    # Use the exact surrounding fixture that supplies the native grader's joins.
    from environments.website_world import ecosystem
    surrounding = ecosystem.generate(world, {'comparison_count': 0, 'review_count': 2})
    registry = [{**{k: site[k] for k in ('kind', 'site_id', 'name')},
                 'origin': 'https://reviews'+str(n)+'.test'} for n, site in enumerate(surrounding['sites'])]
    trace = tmp_path/'trace'; trace.mkdir(); inputs = {}
    for name, value in {'world': world, 'task': task, 'reference': reference, 'bindings': bindings,
                        'site_registry': registry, 'surrounding': surrounding}.items():
        path = tmp_path/(name+'.json'); path.write_text(json.dumps(value)); inputs[name] = path
    for name in BOUND_FILES:
        value = ({'user_message': task['user_message'], 'memories': task['memories']}
                 if name == 'policy-task.json' else
                 {'text': answer, 'stop_reason': 'agent_finished', 'technical_error': None}
                 if name == 'natural-answer.json' else {})
        (trace/name).write_text(json.dumps(value))
    events = []
    def factory(**kwargs):
        return execution.CatalogCompareReviewGrader(**kwargs, inventory=inventory, review_inventory=review_inventory)
    args = dict(trace=trace, inputs=inputs, output=tmp_path/'grading', grader_factory=factory,
                backend_factory=lambda p: Backend(claims, events), source_paths=[Path(execution.__file__)])
    result = execution.task_answer.grade_saved_once(**args)
    assert result['structured_claims_correct'] is (not omit_review_count)
    assert len(result['native_subreports']) == 3
    assert read_grade(trace)['binding_status'] == 'verified'
    assert events[-1][0] == 'close'
    assert sum(e[0] == 'dispatch' for e in events) == 1
    with pytest.raises(FileExistsError): execution.task_answer.grade_saved_once(**args)
    assert sum(e[0] == 'dispatch' for e in events) == 1


def public_instance_fixture(tmp_path):
    world, task, reference, bindings, inventory, review_inventory, grader, answer, claims = fixture()
    original = {'schema_version': 'connected-world-manual-v1', 'task_id': task['task_id'],
        'user_message': task['user_message'], 'memories': task['memories'],
        'environment_context': {'currency': 'SEK', 'scenario_date': '2026-09-30'}, 'start_url': 'https://index.test/'}
    binding = {'world_json_digest': execution.digest(world),
        'world_file_sha256': sha256(json.dumps(world).encode()).hexdigest(),
        'native_task_file_sha256': sha256(json.dumps(task).encode()).hexdigest(),
        'native_reference_file_sha256': sha256(json.dumps(reference).encode()).hexdigest(),
        'source_sha256': {}, 'setup_files_sha256': {}, 'original_episode_json_digest': execution.digest(original),
        'routes_json_digest': execution.digest(bindings)}
    request = 'Compare the cushioning, reference mass in g and fastening of these two models, and summarize both rating distributions.'
    declaration = execution.make_public_request_declaration(task, reference, original, user_message=request, binding=binding)
    path = tmp_path/'declaration.json'; path.write_text(json.dumps(declaration))
    # Authored acceptance exercises the protocol only; it is not a Product
    # suitability receipt for a live instance or a dispatch permission.
    acceptance = {'schema': 'website-compare-review-public-request-acceptance-v1', 'owner': 'Product', 'status': 'accepted',
        'declaration_json_digest': execution.digest(declaration), 'declaration_file_sha256': sha256(path.read_bytes()).hexdigest(),
        'native_task_json_digest': execution.digest(task), 'native_task_file_sha256': binding['native_task_file_sha256'],
        'semantics': execution._semantics(task)}
    return grader, original, binding, declaration, acceptance, path, answer, claims, inventory, review_inventory


@pytest.mark.parametrize('change', ['request', 'memories', 'context', 'source', 'routes', 'task', 'reference',
    'owner', 'status', 'operation', 'models', 'fields', 'review_operation', 'declaration_bytes', 'missing'])
def test_exact_public_request_adapter_rejects_stale_or_unaccepted_instance(tmp_path, change):
    grader, original, binding, declaration, acceptance, path, *_ = public_instance_fixture(tmp_path)
    if change == 'request': declaration['public_request']['user_message'] += ' Just one model.'
    elif change == 'memories': declaration['public_request']['memories'] = ['Changed preference']
    elif change == 'context': declaration['public_request']['environment_context']['currency'] = 'USD'
    elif change == 'source': declaration['binding']['source_sha256']['changed.py'] = '0'*64
    elif change == 'routes': declaration['binding']['routes_json_digest'] = '0'*64
    elif change == 'task': grader.task['task_id'] = 'wrong-native'
    elif change == 'reference': grader.reference['completion'] = 'different'
    elif change == 'owner': acceptance['owner'] = 'Website'
    elif change == 'status': acceptance['status'] = 'pending'
    elif change == 'operation': acceptance['semantics']['operation'] = 'other'
    elif change == 'models': acceptance['semantics']['model_roles']['model_1'] = 'wrong-model'
    elif change == 'fields': acceptance['semantics']['comparison_fields'].pop()
    elif change == 'review_operation': acceptance['semantics']['review_operations']['model_2']['operation'] = 'topic_counts'
    elif change == 'declaration_bytes': acceptance['declaration_file_sha256'] = '0'*64
    else: acceptance = None
    with pytest.raises(ValueError):
        execution.AcceptedPublicRequestGrader(grader, declaration, acceptance, original_public_task=original,
            binding=binding, declaration_file_sha256=sha256(path.read_bytes()).hexdigest())


@pytest.mark.parametrize('missing_part', [False, True])
def test_public_adapter_preserves_native_grade_and_private_contract(tmp_path, missing_part):
    grader, original, binding, declaration, acceptance, path, answer, claims, *_ = public_instance_fixture(tmp_path)
    before = deepcopy((grader.task, grader.reference, original, binding))
    adapter = execution.AcceptedPublicRequestGrader(grader, declaration, acceptance, original_public_task=original,
        binding=binding, declaration_file_sha256=sha256(path.read_bytes()).hexdigest())
    if missing_part: claims['reviews']['model_1']['rating_count'] = {'value': None, 'evidence': None}
    assert adapter.grade(claims, answer) == grader.grade(claims, answer)
    assert adapter.grade(claims, answer)['structured_claims_correct'] is (not missing_part)
    assert adapter.schema is grader.schema and adapter.contract is grader.contract
    assert adapter.reference is grader.reference and adapter.extraction_instructions == grader.extraction_instructions
    changed = {k for k in adapter.task if adapter.task[k] != grader.task[k]}
    assert changed == {'task_id', 'user_message'}
    assert (grader.task, grader.reference, original, binding) == before


@pytest.mark.parametrize('mismatched_policy', [False, True])
def test_real_shared_formatter_public_equality_and_once_only_native_grade_with_adapter(tmp_path, mismatched_policy):
    from scripts.trace_grades import BOUND_FILES, read_grade
    grader, original, binding, declaration, acceptance, path, answer, claims, inventory, reviews = public_instance_fixture(tmp_path)
    native_task, reference, world = grader.task, grader.reference, fixture()[0]
    from environments.website_world import ecosystem
    surrounding = ecosystem.generate(world, {'comparison_count': 0, 'review_count': 2})
    registry = [{**{k: site[k] for k in ('kind', 'site_id', 'name')},
                 'origin': 'https://reviews'+str(n)+'.test'} for n, site in enumerate(surrounding['sites'])]
    bindings = fixture()[3]
    values = {'world': world, 'task': native_task, 'reference': reference, 'bindings': bindings,
        'site_registry': registry, 'surrounding': surrounding, 'declaration': declaration, 'acceptance': acceptance,
        'original_public_task': original, 'binding': binding}
    inputs = {}
    for name, value in values.items():
        p = tmp_path/(name+'.json'); p.write_text(json.dumps(value)); inputs[name] = p
    trace = tmp_path/'trace'; trace.mkdir()
    for name in BOUND_FILES:
        public = {**original, 'task_id': declaration['public_instance_id'],
                  'user_message': original['user_message'] if mismatched_policy else declaration['public_request']['user_message']}
        value = (public if name == 'policy-task.json' else
                 {'text': answer, 'stop_reason': 'agent_finished', 'technical_error': None}
                 if name == 'natural-answer.json' else {})
        (trace/name).write_text(json.dumps(value))
    events = []
    def factory(*, declaration, acceptance, original_public_task, binding, **kwargs):
        native = execution.CatalogCompareReviewGrader(**kwargs, inventory=inventory, review_inventory=reviews)
        return execution.AcceptedPublicRequestGrader(native, declaration, acceptance,
            original_public_task=original_public_task, binding=binding, declaration_file_sha256=sha256(path.read_bytes()).hexdigest())
    args = dict(trace=trace, inputs=inputs, output=tmp_path/'grading', grader_factory=factory,
                backend_factory=lambda p: Backend(claims, events), source_paths=[Path(execution.__file__)])
    if mismatched_policy:
        with pytest.raises(ValueError, match='public task'): execution.task_answer.grade_saved_once(**args)
        assert not events
    else:
        result = execution.task_answer.grade_saved_once(**args)
        assert result == grader.grade(claims, answer)
        assert result['structured_claims_correct']
        assert read_grade(trace)['binding_status'] == 'verified'
        assert events[-1][0] == 'close' and sum(e[0] == 'dispatch' for e in events) == 1
        with pytest.raises(FileExistsError): execution.task_answer.grade_saved_once(**args)


def test_adapted_run_passes_exact_sidecars_to_post_policy_factory_and_records_both_ids(tmp_path, monkeypatch):
    grader, original, binding, declaration, acceptance, path, answer, claims, inventory, reviews = public_instance_fixture(tmp_path)
    accept_path = tmp_path/'acceptance.json'; accept_path.write_text(json.dumps(acceptance))
    public_request = {'declaration': {'path': str(path), 'sha256': sha256(path.read_bytes()).hexdigest()},
                      'acceptance': {'path': str(accept_path), 'sha256': sha256(accept_path.read_bytes()).hexdigest()}}
    output, events, args = run_fixture(tmp_path, monkeypatch)
    original_episode = execution.CatalogCompareReviewEpisode
    class Episode(original_episode):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self.native_task = grader.task
            self.public = {**original, 'task_id': declaration['public_instance_id'],
                           'user_message': declaration['public_request']['user_message']}
            self.task.public=self.public
            self.original_public=original;self.instance_binding=binding
    monkeypatch.setattr(execution, 'CatalogCompareReviewEpisode', Episode)
    from environments.website_world import ecosystem
    world, _, _, bindings, *_ = fixture()
    surrounding = ecosystem.generate(world, {'comparison_count': 0, 'review_count': 2})
    registry = [{**{k: site[k] for k in ('kind', 'site_id', 'name')},
                 'origin': 'https://reviews'+str(n)+'.test'} for n, site in enumerate(surrounding['sites'])]
    real_factory = execution.CatalogCompareReviewGrader
    monkeypatch.setattr(execution, 'CatalogCompareReviewGrader', lambda **kw:
        real_factory(**kw, inventory=inventory, review_inventory=reviews))
    def grade(**kw):
        assert events[-1] == 'runtime-close'
        assert kw['inputs']['public_declaration'] == path
        assert kw['inputs']['public_acceptance'] == accept_path
        assert kw['inputs']['original_public_task'] == tmp_path/'run/runtime-binding/original-public-task.private.json'
        adapter = kw['grader_factory'](world=world, task=grader.task, reference=grader.reference,
            bindings=bindings, site_registry=registry, surrounding=surrounding,
            public_declaration=declaration, public_acceptance=acceptance,
            original_public_task=original, public_instance_binding=binding)
        assert adapter.task['user_message'] == declaration['public_request']['user_message']
        assert adapter.grade(claims, answer) == grader.grade(claims, answer)
        events.append('compound-grade'); return adapter.grade(claims, answer)
    monkeypatch.setattr(execution, 'extract_saved_deferred', lambda **kw:{'grade':grade(**kw)})
    original_runner = args['runner']
    def runner(make_env, backend, metadata, **kw):
        assert metadata['native_task_id'] == grader.task['task_id']
        assert metadata['public_task_id'] == declaration['public_instance_id']
        return original_runner(make_env, backend, metadata, **kw)
    args.update(public_request=public_request, runner=runner)
    result = execution.run(output, tmp_path/'run', **args)
    assert result['status'] == 'graded_and_projected' and result['task_completed']
    assert events.count('compound-grade') == 1 and events[-1] == 'viewer'


@pytest.mark.parametrize('key', ['automatic_grading','allow_ungraded','ungraded_reason','agent_runtime','agent_actor'])
def test_caller_cannot_replace_or_escape_required_compound_grading(tmp_path,monkeypatch,key):
    output,events,args=run_fixture(tmp_path,monkeypatch)
    args['runner_options'][key]=True
    with pytest.raises(ValueError,match='bindings'):execution.run(output,tmp_path/'run',**args)
    assert events==[]


def test_runtime_cleanup_failure_is_system_failure_and_skips_formatter(tmp_path,monkeypatch):
    output,events,args=run_fixture(tmp_path,monkeypatch)
    parent=execution.CatalogCompareReviewEpisode
    class Broken(parent):
        def __exit__(self,*a):
            super().__exit__(*a)
            raise ValueError('Actual Runtime cleanup failed')
    monkeypatch.setattr(execution,'CatalogCompareReviewEpisode',Broken)
    result=execution.run(output,tmp_path/'run',**args)
    assert result['status']=='system_failure' and result['task_completed'] is None
    assert not result['runtime_closed'] and 'compound-grade' not in events
    assert json.loads((tmp_path/'run/execution-result.json').read_bytes())==result


@pytest.mark.parametrize('key,value',[('task_id','other'),('environment_context',{'currency':'USD'})])
def test_saved_policy_identity_or_context_drift_blocks_formatter(tmp_path,monkeypatch,key,value):
    output,events,args=run_fixture(tmp_path,monkeypatch)
    original=args['runner']
    def changed(*a,**kw):
        path,summary=original(*a,**kw)
        public=json.loads((path/'policy-task.json').read_bytes());public[key]=value
        (path/'policy-task.json').write_text(json.dumps(public))
        return path,summary
    args['runner']=changed
    result=execution.run(output,tmp_path/'run',**args)
    assert result['status']=='system_failure' and 'compound-grade' not in events
    assert 'identity' in result['reason']


def test_unrelated_auditor_pin_does_not_bind_invoked_callable(tmp_path):
    source=tmp_path/'unrelated.py';source.write_text('# Unrelated source')
    with pytest.raises(ValueError,match='auditor implementation'):
        execution.check_auditor_source(lambda **kw:{},{str(source):sha256(source.read_bytes()).hexdigest()})


def test_external_gate_publishes_once_after_both_owner_cleanup_phases(tmp_path,monkeypatch):
    output,events,args=run_fixture(tmp_path,monkeypatch)
    result=execution.run(output,tmp_path/'run',**args)
    assert result['status']=='graded_and_projected'
    path=Path(result['trace'])
    declaration=json.loads((path/'automatic-grading.json').read_bytes())
    assert declaration['phase']=='external' and declaration['status']=='graded'
    assert (path/'automatic-grading-finalization.lock').exists()
    native=json.loads((path/'automatic-grade.json').read_bytes())
    assert native['raw_grade']['native_grade']==result['answer_grading']
    assert declaration['binding']['task_id']==native['raw_grade']['task_id']
    assert json.loads((path/'automatic-grade-projection.json').read_bytes())['verified']
    assert events.index('runtime-close')<events.index('compound-grade')


@pytest.mark.parametrize('omit_count',[False,True])
def test_real_shared_extraction_external_finalization_and_final_sidecar_bindings(tmp_path,monkeypatch,omit_count):
    """Actual shared extraction/gate/sidecar; explicitly authored viewer only."""
    from scripts.trace_grades import BOUND_FILES,read_grade
    real_extract=execution.extract_saved_deferred;real_publish=execution.publish_finalized_answer
    output,events,args=run_fixture(tmp_path,monkeypatch)
    monkeypatch.setattr(execution,'extract_saved_deferred',real_extract)
    monkeypatch.setattr(execution,'publish_finalized_answer',real_publish)
    world,task,reference,bindings,inventory,reviews,grader,answer,claims=fixture()
    if omit_count:claims['reviews']['model_2']['rating_count']={'value':None,'evidence':None}
    from environments.website_world import ecosystem
    surrounding=ecosystem.generate(world,{'comparison_count':0,'review_count':2})
    registry=[{**{k:site[k] for k in ('kind','site_id','name')},
               'origin':'https://reviews'+str(n)+'.test'} for n,site in enumerate(surrounding['sites'])]
    for filename,value in {'pin/world.private.json':world,
        'catalog-compare-review-task.private.json':task,
        'catalog-compare-review-reference.private.json':reference,
        'surrounding.private.json':surrounding}.items():
        (output/filename).write_text(json.dumps(value))
    parent=execution.CatalogCompareReviewEpisode
    class Episode(parent):
        def export_private_runtime(self,output):
            record=super().export_private_runtime(output)
            for filename,value in {'bindings.private.json':bindings,'site-registry.private.json':registry}.items():
                path=output/filename;path.write_text(json.dumps(value))
                record['files'][filename]=sha256(path.read_bytes()).hexdigest()
            (output/'manifest.json').write_text(json.dumps(record))
            return record
    monkeypatch.setattr(execution,'CatalogCompareReviewEpisode',Episode)
    native_factory=execution.CatalogCompareReviewGrader
    monkeypatch.setattr(execution,'CatalogCompareReviewGrader',lambda **kw:
        native_factory(**kw,inventory=inventory,review_inventory=reviews))
    original_runner=args['runner'];contracts=[]
    def runner(*a,**kw):
        contracts.append(kw['automatic_grading'])
        path,summary=original_runner(*a,**kw)
        for filename in BOUND_FILES:
            if filename in ('episode.json','policy-task.json'):continue
            value=({'text':answer,'stop_reason':'agent_finished','technical_error':None}
                   if filename=='natural-answer.json' else {'episode_id':path.name})
            (path/filename).write_text('' if filename=='steps.jsonl' else json.dumps(value))
        return path,summary
    transport=[]
    def viewer(*,trace,grade):
        assert read_grade(trace)['binding_status']=='verified'
        return {'status':'verified','qualification':'Authored offline viewer; no HTTP/browser acceptance'}
    args.update(runner=runner,extraction_backend_factory=lambda p:Backend(claims,transport),viewer_projection=viewer)
    result=execution.run(output,tmp_path/'run',**args)
    assert result['status']=='graded_and_projected',result
    assert result['task_completed'] is (not omit_count)
    path=Path(result['trace']);view=read_grade(path)
    assert view['binding_status']=='verified' and view['structured_claims_correct'] is (not omit_count)
    transition=json.loads((tmp_path/'run/answer-grading/finalization-binding-transition.json').read_bytes())
    for filename in ('episode.json','evaluation.json'):
        before=tmp_path/'run/answer-grading'/('before-finalization-'+filename)
        assert sha256(before.read_bytes()).hexdigest()==transition['artifacts'][filename]['before_sha256']
        assert view['episode_artifact_sha256'][filename]==transition['artifacts'][filename]['after_sha256']
    assert sum(e[0]=='dispatch' for e in transport)==1 and transport[-1][0]=='close'
    from intent_browser.automatic_grading import finalize_external
    with pytest.raises(ValueError):finalize_external(path,contracts[0])
    assert sum(e[0]=='dispatch' for e in transport)==1 and read_grade(path)['binding_status']=='verified'
