"""Compound runtime binding and a single grounded extraction after policy close.

The readiness auditor is an explicit integration seam, not a native-truth
fallback. Its actual public-document implementation/acceptance remains separate.
"""
from copy import deepcopy
from hashlib import sha256
import json
import inspect
from pathlib import Path

from experiments.accepted_catalog_commerce.execution import _bind
from experiments.answer_grading import task_answer
from experiments.footwear_world_pilot.model import digest
from intent_browser.connected_world_task import checked_files, TERMINAL_INSTRUCTION
from . import generation as shared, unified_generation as unified
from . import comparison_stock_execution as lifecycle
from .adapter import digest as publication_digest
from .catalog_compare_review_grading import CatalogCompareReviewGrader
from .generation_configs import execution_options
from .generation_configs import observation_runner_options

VERSION = 'website-catalog-compare-review-execution-v1'
RECIPE = 'website-catalog-compare-review-publication-v1'


def check_auditor_source(auditor, sources):
    """Pin the invoked callable's implementation, not an unrelated readable file."""
    if not callable(auditor) or type(sources) is not dict or not sources:
        raise ValueError('Require a source-pinned public-readiness auditor')
    checked_files(sources)
    target = auditor if inspect.isfunction(auditor) or inspect.ismethod(auditor) else type(auditor).__call__
    path = inspect.getsourcefile(target)
    if path is None or sources.get(str(Path(path).resolve())) != sha256(Path(path).read_bytes()).hexdigest():
        raise ValueError('Invoked readiness auditor implementation is missing from its source pins')


def check_saved_public_task(trace, public):
    saved = json.loads((Path(trace)/'policy-task.json').read_bytes())
    keys = ('task_id', 'user_message', 'memories', 'environment_context')
    if any(key not in public or key not in saved or saved[key] != public[key] for key in keys):
        raise ValueError('Saved public task identity, request, memories or context changed')


def check_policy_outcome(returned, saved):
    """Trace.finish may add completeness only to the persisted summary.

    A missing successful runner-return field is valid only when the saved trace
    explicitly completed. An explicit returned failure or persisted recording
    failure must never be treated as a successful finish.
    """
    if type(returned) is not dict or type(saved) is not dict:
        raise ValueError('Require returned and saved policy outcome objects')
    if (saved.get('trace_complete') is not True or saved.get('recording_error')
            or ('trace_complete' in returned and returned['trace_complete'] is not True)):
        raise ValueError('Returned policy outcome or saved browser trace is incomplete')
    if any(saved.get(key) != returned.get(key) for key in
           ('stop_reason', 'error', 'execution_error', 'cleanup_errors')):
        raise ValueError('Returned policy outcome differs from its saved browser trace')


def extract_saved_deferred(*, trace, inputs, output, grader_factory, backend_factory,
                           source_paths, before_model_dispatch):
    """One shared extraction, keeping publication after canonical finalization.

    Unlike saved-trace grading, this prospective external lifecycle still owns
    the pending episode/evaluation artifacts. Their original bytes and pins are
    retained; no derived sidecar is published against those transient artifacts.
    """
    from scripts.trace_grades import BOUND_FILES
    from experiments.answer_grading import listed_offer, extraction
    trace, output = Path(trace).resolve(), Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    paths = [trace/name for name in BOUND_FILES] + [Path(p).resolve() for p in inputs.values()]
    paths += [Path(p).resolve() for p in source_paths]
    paths += [Path(m.__file__).resolve() for m in (task_answer, listed_offer, extraction)]
    hashes = {str(p): listed_offer.sha(p) for p in paths}
    def checked():
        checked_files(hashes)
    natural = json.loads((trace/'natural-answer.json').read_bytes())
    if natural.get('stop_reason') != 'agent_finished' or natural.get('technical_error') or not natural.get('text'):
        raise ValueError('No complete uninterrupted final answer for compound extraction')
    shared.save(output/'source-hashes-before-finalization.json', hashes)
    for name in ('episode.json', 'evaluation.json'):
        (output/('before-finalization-'+name)).write_bytes((trace/name).read_bytes())
    grader = grader_factory(**{name: json.loads(Path(p).read_bytes()) for name,p in inputs.items()})
    public = json.loads((trace/'policy-task.json').read_bytes())
    if public.get('user_message') != grader.task['user_message'] or public.get('memories') != grader.task['memories']:
        raise ValueError('Saved public request differs from its native/accepted grader')
    checked(); before_model_dispatch()
    backend = backend_factory(output/'transport')
    try:
        dispatched = False
        def before():
            nonlocal dispatched
            checked()
            if not dispatched:
                before_model_dispatch(); dispatched = True
        grade = task_answer.extract_and_grade(grader, public, natural['text'], output/'extraction',
                                              backend, before_dispatch=before)
        checked()
        shared.save(output/'extracted-publication-pending.json', {'status':'graded_publication_pending',
            'requests':1,'grading_version':grade['grading_version']})
        return {'grade':grade,'source_hashes':hashes,'output':str(output),'trace':str(trace)}
    finally:
        backend.close()


def publish_finalized_answer(deferred, *, contract_id):
    """Publish once against final artifacts, preserving the declared transition."""
    if deferred.get('kind') == 'missing_answer':
        from .compound_missing_output_v1 import publish
        from scripts.trace_grades import read_grade
        path = publish(trace=deferred['trace'], source_directory=deferred['output'], contract_id=contract_id)
        if read_grade(deferred['trace'])['binding_status'] != 'verified':
            raise ValueError('Final missing-output sidecar is not bound to the final trace')
        marker = Path(deferred['output'])/'completed.json'
        with marker.open('x', encoding='utf-8') as stream:
            json.dump({'status':'graded_and_published','requests':0,
                'outcome_kind':'required_answer_not_delivered','sidecar':str(path)}, stream, indent=2)
        return deferred['grade']
    from experiments.answer_grading import listed_offer
    from scripts.trace_grades import read_grade
    trace, output = Path(deferred['trace']), Path(deferred['output'])
    declaration = json.loads((trace/'automatic-grading.json').read_bytes())
    final = json.loads((trace/'episode.json').read_bytes())
    raw = json.loads((trace/'automatic-grade.json').read_bytes())
    if (declaration['contract_id'] != contract_id or declaration['status'] != 'graded'
            or declaration['phase'] != 'external' or not final.get('infrastructure_completed')
            or final.get('grading_error') or raw['raw_grade']['native_grade'] != deferred['grade']
            or listed_offer.sha(trace/'automatic-grade.json') != declaration['grade_sha256']):
        raise ValueError('Cannot publish an answer outside its finalized prospective native grade')
    hashes = deepcopy(deferred['source_hashes']); transitions = {}
    for name in ('episode.json','evaluation.json'):
        key = str(trace/name); original = output/('before-finalization-'+name)
        if listed_offer.sha(original) != hashes[key]:
            raise ValueError('Original pre-finalization evidence changed')
        transitions[name] = {'before_sha256':hashes[key], 'after_sha256':listed_offer.sha(trace/name)}
        hashes[key] = transitions[name]['after_sha256']
    checked_files(hashes)
    shared.save(output/'finalization-binding-transition.json', {'schema':'compound-external-finalization-v1',
        'contract_id':contract_id,'artifacts':transitions,
        'automatic_grade_sha256':declaration['grade_sha256'],
        'qualification':'First prospective publication after declared external finalization; no historical sidecar is rebound'})
    listed_offer.publish(trace, output/'extraction', deferred['grade'], mode='live', source_hashes=hashes)
    if read_grade(trace)['binding_status'] != 'verified':
        raise ValueError('Final compound answer sidecar is not bound to the final trace')
    shared.save(output/'completed.json', {'status':'graded_and_published','requests':1,
        'source_hashes_unchanged_except_declared_finalization':True,
        'structured_claims_correct':deferred['grade']['structured_claims_correct']})
    return deferred['grade']


def instance_binding(runtime, manifest, output, episode):
    """Named canonical JSON identities and actual-byte pins, without normalization."""
    output = Path(output)
    return {'world_json_digest': digest(runtime.world),
        'world_file_sha256': sha256((output/'pin/world.private.json').read_bytes()).hexdigest(),
        'native_task_file_sha256': sha256((output/'catalog-compare-review-task.private.json').read_bytes()).hexdigest(),
        'native_reference_file_sha256': sha256((output/'catalog-compare-review-reference.private.json').read_bytes()).hexdigest(),
        'source_sha256': deepcopy(manifest['source_sha256']),
        'setup_files_sha256': deepcopy(manifest['files']),
        'original_episode_json_digest': digest(episode), 'routes_json_digest': digest(runtime.bindings)}


def make_public_request_declaration(native_task, native_reference, original_public_task, *, user_message, binding):
    """Declare a proposed exact instance; this does not approve its prose."""
    if type(user_message) is not str or not user_message.strip():
        raise ValueError('Author a nonempty natural request')
    if (original_public_task.get('task_id') != native_task['task_id']
            or original_public_task.get('user_message') != native_task['user_message']
            or original_public_task.get('memories') != native_task['memories']
            or type(original_public_task.get('environment_context')) is not dict):
        raise ValueError('Original public task must retain native text/memories and actual context')
    required = {'world_json_digest', 'world_file_sha256', 'native_task_file_sha256',
        'native_reference_file_sha256', 'source_sha256', 'setup_files_sha256',
        'original_episode_json_digest', 'routes_json_digest'}
    if type(binding) is not dict or set(binding) != required:
        raise ValueError('Pin the complete named source/setup/world/route binding')
    declaration = {'schema': 'website-compare-review-public-request-v1',
        'native_task_json_digest': digest(native_task),
        'native_reference_json_digest': digest(native_reference),
        'original_public_task': deepcopy(original_public_task), 'binding': deepcopy(binding),
        'public_request': {'user_message': user_message, 'memories': deepcopy(original_public_task['memories']),
                           'environment_context': deepcopy(original_public_task['environment_context'])}}
    declaration['public_instance_id'] = 'catalog-compare-review-public-'+digest(declaration)[:24]
    return declaration


def _semantics(task):
    return {'operation': task['kind'],
        'model_roles': {role: t['subject']['product_id'] for role, t in task['review_tasks'].items()},
        'comparison_fields': deepcopy(task['comparison_task']['fields']),
        'review_operations': {role: {'operation': t['operation'], 'topic': deepcopy(t.get('topic'))}
                              for role, t in task['review_tasks'].items()}}


class AcceptedPublicRequestGrader:
    """Native validators first; only accepted policy text/identity is adapted."""
    def __init__(self, native_grader, declaration, acceptance, *, original_public_task, binding,
                 declaration_file_sha256):
        native_task, native_reference = native_grader.task, native_grader.reference
        if (type(declaration) is not dict or type(declaration.get('public_request')) is not dict):
            raise ValueError('Public request declaration must be an object')
        expected = make_public_request_declaration(native_task, native_reference, original_public_task,
            user_message=declaration.get('public_request', {}).get('user_message'), binding=binding)
        if declaration != expected:
            raise ValueError('Public declaration/native task/reference/request/context/binding changed')
        if (type(acceptance) is not dict or acceptance.get('schema') != 'website-compare-review-public-request-acceptance-v1'
                or acceptance.get('owner') != 'Product' or acceptance.get('status') != 'accepted'
                or acceptance.get('declaration_json_digest') != digest(declaration)
                or acceptance.get('declaration_file_sha256') != declaration_file_sha256
                or acceptance.get('native_task_json_digest') != digest(native_task)
                or acceptance.get('native_task_file_sha256') != binding['native_task_file_sha256']
                or acceptance.get('semantics') != _semantics(native_task)):
            raise ValueError('Missing exact Product instance suitability acceptance')
        self.native_grader = native_grader
        self.native_task = deepcopy(native_task)
        self.task = deepcopy(native_task)
        self.task.update(task_id=declaration['public_instance_id'],
                         user_message=declaration['public_request']['user_message'])
        self.schema = native_grader.schema
        self.extraction_instructions = native_grader.extraction_instructions
        self.contract = native_grader.contract
        self.reference = native_grader.reference
        from .compound_missing_answer_native_v1 import input_digest
        self._missing_answer_public = deepcopy(original_public_task)
        self._missing_answer_public.update(task_id=self.task['task_id'],
                                          user_message=self.task['user_message'])
        self._missing_answer_adapted_inputs = {
            'public_declaration': input_digest(declaration),
            'public_acceptance': input_digest(acceptance),
            'original_public_task': input_digest(original_public_task),
            'public_instance_binding': input_digest(binding)}

    def grade(self, claims, answer):
        return self.native_grader.grade(claims, answer)

    def grade_missing_answer(self, terminal_evidence):
        if (type(terminal_evidence) is not dict or type(terminal_evidence.get('binding')) is not dict
                or type(terminal_evidence['binding'].get('source_files')) is not dict
                or str(Path(__file__).absolute()) not in terminal_evidence['binding']['source_files']):
            raise ValueError('Accepted public adapter absent from actual source union')
        return self.native_grader._grade_missing_answer(terminal_evidence,
            expected_public=self._missing_answer_public,
            adapted_input_digests=self._missing_answer_adapted_inputs)



def load_public_request(record):
    """Only explicit exact external sidecars; no mutation of frozen recipes."""
    if type(record) is not dict or set(record) != {'declaration', 'acceptance'}:
        raise ValueError('Public request requires declaration and Product acceptance file pins')
    files = {}
    values = {}
    for key, pin in record.items():
        if (type(pin) is not dict or set(pin) != {'path', 'sha256'}
                or type(pin['path']) is not str or not Path(pin['path']).is_absolute()
                or type(pin['sha256']) is not str or len(pin['sha256']) != 64
                or any(c not in '0123456789abcdef' for c in pin['sha256'])):
            raise ValueError('Invalid exact public instance file pin')
        if pin['path'] in files:
            raise ValueError('Public declaration and acceptance must be separate artifacts')
        files[pin['path']] = pin['sha256']
    checked_files(files)
    for key, pin in record.items():
        values[key] = json.loads(Path(pin['path']).read_bytes())
        if type(values[key]) is not dict:
            raise ValueError('Public declaration/acceptance must be objects')
    if values['acceptance'].get('owner') != 'Product' or values['acceptance'].get('status') != 'accepted':
        raise ValueError('Public request has no accepted Product instance receipt')
    return values, files


def public_binding(runtime):
    """Bind an audit to the complete actual publication, including sampled pages."""
    return publication_digest({'world': runtime.world, 'bindings': runtime.bindings,
        'site_registry': runtime.site_registry, 'compositions': runtime.compositions,
        'public_catalogs': runtime.public_catalogs, 'review_products': runtime.review_products})


def check_readiness(report, *, runtime, task, reference):
    """Fail closed on missing/foreign/partial public roles and unpinned evidence.

    'known' is never satisfied by a missing field. Unknown and NA declarations
    remain distinct, and cannot be substituted for a pruned known fact. Each
    role needs a locator in an actual hashed public-document artifact. This
    validates the audit envelope; it does not implement its semantic audit.
    """
    if (type(report) is not dict or report.get('schema') != 'website-compare-review-readiness-v1'
            or report.get('status') != 'sufficient' or report.get('task_id') != task['task_id']
            or report.get('runtime_binding_sha256') != public_binding(runtime)):
        raise ValueError('Missing sufficient public audit for the actual compound runtime')
    files, rows = report.get('files'), report.get('roles')
    if type(files) is not dict or not files or type(rows) is not list:
        raise ValueError('Public audit requires pinned documents and every structured role')
    if any(type(path) is not str or not Path(path).is_absolute() or
           type(h) is not str or len(h) != 64 or any(c not in '0123456789abcdef' for c in h)
           for path, h in files.items()):
        raise ValueError('Invalid public audit document pins')
    checked_files(files)
    by_role = {}
    for row in rows:
        if type(row) is not dict or type(row.get('role_id')) is not str or row['role_id'] in by_role:
            raise ValueError('Public audit roles must be unique')
        by_role[row['role_id']] = row
    expected = {r['role_id']: r for r in task['required_obligations']}
    if set(by_role) != set(expected):
        raise ValueError('Public audit does not cover exactly the compound obligations')
    facts = {m['product_id']: m['facts'] for m in reference['comparison']['models']}
    for role_id, obligation in expected.items():
        row = by_role[role_id]
        status = (facts[obligation['product_id']][obligation['field']]['status']
                  if obligation['source_family'] == 'retailer' else 'known')
        if (row.get('status') != status or row.get('product_id') != obligation['product_id']
                or row.get('source_family') != obligation['source_family']
                or row.get('document') not in files
                or type(row.get('locator')) is not str or not row['locator'].strip()):
            raise ValueError('Public audit status, subject, source family or locator changed: '+role_id)
    return deepcopy(report)


class CatalogCompareReviewEpisode(lifecycle.ComparisonStockEpisode):
    def __init__(self, output, *, readiness_auditor, readiness_sources, lazy_publication=True, public_request=None):
        check_auditor_source(readiness_auditor, readiness_sources)
        public_values, public_files = load_public_request(public_request) if public_request is not None else ({}, {})
        self.public_request_record = deepcopy(public_request)
        from .runtime import Runtime
        from intent_browser.standard_profile import standard_profile
        from intent_browser.connected_world_task import public_projection
        from .comparison_sku_task import episode_task
        self.output = Path(output).resolve()
        self.manifest = shared.load(self.output)
        if self.manifest.get('recipe') != RECIPE:
            raise ValueError('Not a frozen compound comparison/review recipe')
        read = lambda name: json.loads((self.output/name).read_bytes())
        binding = read('compare-review-binding.private.json')
        if binding.get('status') != 'bound' or binding.get('world_repaired') is not False:
            raise ValueError('An unsupported compound subject/publication cannot launch')
        episode, native = read('episode.json'), read('catalog-compare-review-task.private.json')
        if public_request is not None and episode.get('readable_origins') is not True:
            raise ValueError('Preaccepted public requests require stable readable origins')
        self.native_task, self.reference = native, read('catalog-compare-review-reference.private.json')
        if (episode['task_id'] != native['task_id'] or episode['manual_task'] != {
                'user_message': native['user_message'], 'memories': native['memories']}
                or read('required-obligations.private.json') != native['required_obligations']):
            raise ValueError('Public compound task or private obligation binding changed')
        self.surrounding = read('surrounding.private.json')
        coverage = {role: [s['site_id'] for s in self.surrounding['sites']
            if s['kind'] == 'product_reviews' and t['subject']['product_id'] in s['product_ids']]
            for role, t in native['review_tasks'].items()}
        if binding != {'status': 'bound', 'publication_ids': coverage, 'world_repaired': False} or not all(coverage.values()):
            raise ValueError('Compound review publication identity coverage changed')
        self.runtime = Runtime(self.output/'pin', presentation=read('presentation.json'),
            surrounding=self.surrounding, basket_plan=read('basket-plan.private.json'),
            checkout_domain=read('checkout-domain.private.json'),
            delivery_plan=read('delivery-plan.private.json') if (self.output/'delivery-plan.private.json').exists() else None,
            discovery_mode='tool' if episode['start']['kind'] == 'tool_discovery' else 'index',
            readable_origins=episode.get('readable_origins', False), lazy_publication=lazy_publication)
        try:
            if read('compositions.private.json') != self.runtime.compositions:
                raise ValueError('Runtime composition differs from sampled pages')
            self.answer_grader = CatalogCompareReviewGrader(self.runtime.world, native, self.reference,
                self.runtime.bindings, self.runtime.site_registry, surrounding=self.surrounding)
            self.public_readiness = check_readiness(readiness_auditor(
                runtime=self.runtime, task=deepcopy(native), reference=deepcopy(self.reference)),
                runtime=self.runtime, task=native, reference=self.reference)
            checked_files(readiness_sources)
            self.original_public = public_projection(unified.bind_task(self.runtime, episode))
            self.instance_binding = instance_binding(self.runtime, self.manifest, self.output, episode)
            self.public = deepcopy(self.original_public)
            if public_request is not None:
                self.answer_grader = AcceptedPublicRequestGrader(self.answer_grader, **public_values,
                    original_public_task=self.original_public, binding=self.instance_binding,
                    declaration_file_sha256=public_request['declaration']['sha256'])
                self.public.update(task_id=self.answer_grader.task['task_id'],
                                   user_message=self.answer_grader.task['user_message'])
                self.public = public_projection(self.public)
            self.profile = standard_profile(navigation_origins=self.runtime.navigation_origins, helpers=False)
            self.site_discovery = None
            if episode['start']['kind'] == 'tool_discovery':
                from intent_browser.harness import with_site_discovery
                self.profile = with_site_discovery(self.profile)
                self.site_discovery = self.runtime.site_discovery.search
            files = {str(self.output/name): h for name, h in self.manifest['files'].items()}
            files.update({str(shared.ROOT/name): h for name, h in self.manifest['source_sha256'].items()})
            for additional in (readiness_sources, self.public_readiness['files'], public_files):
                for name, h in additional.items():
                    if name in files and files[name] != h:
                        raise ValueError('Readiness evidence conflicts with frozen source/input: '+name)
                    files[name] = h
            files[str(self.output/'manifest.json')] = sha256((self.output/'manifest.json').read_bytes()).hexdigest()
            self.task = episode_task(self.runtime, self.public, self.profile, files=files,
                attachments={name: str(self.output/name) for name in (
                    'catalog-compare-review-task.private.json', 'catalog-compare-review-reference.private.json',
                    'compare-review-binding.private.json', 'required-obligations.private.json')})
            self.task.site_discovery_callback = self.site_discovery
        except BaseException:
            self.runtime.close()
            raise

    def export_private_runtime(self, output):
        manifest = _bind(lifecycle.ComparisonStockEpisode.export_private_runtime, VERSION=VERSION)(self, output)
        output = Path(output)
        for name, value in (('original-public-task.private.json', self.original_public),
            ('public-instance-binding.private.json', self.instance_binding),
            ('task-identities.private.json', {'native_task_id': self.native_task['task_id'],
                'public_task_id': self.public['task_id'], 'public_request_files': self.public_request_record})):
            shared.save(output/name, value)
            manifest['files'][name] = sha256((output/name).read_bytes()).hexdigest()
        (output/'manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False)+'\n')
        return manifest


def run(output, run_directory, *, policy_session, metadata, runner_options, viewer_projection,
        readiness_auditor, readiness_sources, quota_guard=None, extraction_backend_factory=None, runner=None,
        public_request=None, missing_answer_reader_sha256=None):
    """Prospective external grading, finalized after policy and Runtime cleanup.

    A fresh adopted recipe explicitly pins its reviewed missing-output reader.
    The default retains the earlier complete-answer-only path.
    """
    runner_options = observation_runner_options(runner_options)
    from intent_browser.automatic_grading import AutomaticGrading, finalize_external, canonical_viewer_check
    from intent_browser.evaluation import Evaluation
    from intent_browser.connected_world_task import policy_goal
    if not all(callable(f) for f in (policy_session, viewer_projection)):
        raise ValueError('Attach policy and viewer projection before dispatch')
    public_request = deepcopy(public_request)
    if missing_answer_reader_sha256 is not None:
        if (type(missing_answer_reader_sha256) is not str or len(missing_answer_reader_sha256) != 64
                or any(c not in '0123456789abcdef' for c in missing_answer_reader_sha256)):
            raise ValueError('Require the exact adopted missing-output reader source pin')
        from scripts import trace_grades
        reader = Path(trace_grades.__file__).resolve()
        if sha256(reader.read_bytes()).hexdigest() != missing_answer_reader_sha256:
            raise ValueError('Missing-output reader differs from the explicitly adopted source')
    readiness_sources = deepcopy(readiness_sources)
    check_auditor_source(readiness_auditor, readiness_sources)
    if extraction_backend_factory is not None and not callable(extraction_backend_factory):
        raise ValueError('Configured extraction backend must be callable')
    if type(runner_options) is not dict or any(type(runner_options.get(k)) is not int or runner_options[k] <= 0
                                               for k in ('max_steps', 'max_input_tokens')):
        raise ValueError('Declare finite positive request and context limits')
    if set(runner_options) & {'env_factory', 'backend', 'metadata', 'output', 'episode_task', 'harness_profile',
            'site_discovery', 'terminal_response_instruction',
            'automatic_grading', 'allow_ungraded', 'ungraded_reason', 'agent_runtime', 'agent_actor'}:
        raise ValueError('Runner options cannot replace compound episode or automatic grading bindings')
    runner_options = deepcopy(runner_options)
    output, destination = Path(output).resolve(), Path(run_directory).resolve()
    manifest = shared.load(output)
    record = json.loads((output/'execution.private.json').read_bytes())
    options = execution_options({'validation': record['validation'], 'answer_grading': record.get('answer_grading'),
                                **record.get('runtime_options', {})})
    grading = options['answer_grading']
    if grading['mode'] != 'subscription-post-run':
        raise ValueError('Automatic compound extraction must be attached before provider dispatch')
    destination.mkdir(parents=True, exist_ok=False)
    if quota_guard is None:
        from experiments.external_agent.subscription_quota import SubscriptionQuotaGuard
        quota_guard = SubscriptionQuotaGuard(destination/'subscription-quota', remaining_floor=1)
    if not callable(quota_guard):
        raise ValueError('Quota guard must be callable')
    if runner is None:
        from intent_browser.runner import run_episode
        runner = run_episode
    shared.save(destination/'execution-plan.private.json', {'schema': VERSION, 'runner_options': runner_options,
        'source_sha256': manifest['source_sha256'], 'automatic_grading_retries': 0, 'extraction_requests_max': 1})
    execution_plan_pin = None
    if missing_answer_reader_sha256 is not None:
        plan = destination/'execution-plan.private.json'
        execution_plan_pin = {'path':str(plan), 'sha256':sha256(plan.read_bytes()).hexdigest()}
    state = {'policy_closed': False, 'runtime_closed': False, 'grade': None, 'projection': None}
    trace = None; summary = None
    try:
        with CatalogCompareReviewEpisode(output, readiness_auditor=readiness_auditor,
                readiness_sources=readiness_sources, lazy_publication=options['lazy_publication'],
                public_request=public_request) as episode:
            runtime_directory = destination/'runtime-binding'
            runtime_export = episode.export_private_runtime(runtime_directory)
            if type(runtime_export) is not dict or type(runtime_export.get('files')) is not dict:
                raise ValueError('Require a pinned complete runtime export before dispatch')
            for name, h in runtime_export['files'].items():
                path = (runtime_directory/name).resolve()
                if not path.is_relative_to(runtime_directory):
                    raise ValueError('Runtime export file escaped its binding directory')
                if str(path) in episode.task.files and episode.task.files[str(path)] != h:
                    raise ValueError('Runtime export conflicts with frozen episode input')
                episode.task.files[str(path)] = h
            episode.task.files[str(runtime_directory/'manifest.json')] = sha256((runtime_directory/'manifest.json').read_bytes()).hexdigest()
            shared.save(destination/'public-readiness.private.json', episode.public_readiness)
            episode.task.files[str(destination/'public-readiness.private.json')] = sha256(
                (destination/'public-readiness.private.json').read_bytes()).hexdigest()
            expected_public = deepcopy(episode.public)
            if missing_answer_reader_sha256 is not None:
                plan_path = execution_plan_pin['path']
                if (plan_path in episode.task.files
                        and episode.task.files[plan_path] != execution_plan_pin['sha256']):
                    raise ValueError('Execution plan conflicts with retained source union')
                episode.task.files[plan_path] = execution_plan_pin['sha256']
                checked_files({plan_path:execution_plan_pin['sha256']})
                native = getattr(episode.answer_grader, 'native_grader', episode.answer_grader)
                if not callable(getattr(native, 'grade_missing_answer', None)):
                    raise ValueError('Reviewed native missing-answer callable must be installed before dispatch')
            inputs = {
                'world': output/'pin/world.private.json',
                'task': output/'catalog-compare-review-task.private.json',
                'reference': output/'catalog-compare-review-reference.private.json',
                'surrounding': output/'surrounding.private.json',
                'bindings': runtime_directory/'bindings.private.json',
                'site_registry': runtime_directory/'site-registry.private.json'}
            grader_factory = CatalogCompareReviewGrader
            if public_request is not None:
                inputs.update(public_declaration=Path(public_request['declaration']['path']),
                    public_acceptance=Path(public_request['acceptance']['path']),
                    original_public_task=runtime_directory/'original-public-task.private.json',
                    public_instance_binding=runtime_directory/'public-instance-binding.private.json')
                def grader_factory(*, public_declaration, public_acceptance, original_public_task,
                                  public_instance_binding, **kwargs):
                    native_grader = CatalogCompareReviewGrader(**kwargs)
                    return AcceptedPublicRequestGrader(native_grader, public_declaration, public_acceptance,
                        original_public_task=original_public_task, binding=public_instance_binding,
                        declaration_file_sha256=public_request['declaration']['sha256'])
            reference_files = {str(Path(path).resolve()): sha256(Path(path).read_bytes()).hexdigest()
                               for path in inputs.values()}
            def bind(env, actual_trace, observation):
                if observation['goal'] != policy_goal(expected_public):
                    raise ValueError('Displayed compound goal differs from the bound public task')
                if missing_answer_reader_sha256 is not None:
                    from .compound_terminal_capture_v1 import bind_capture_artifacts
                    bind_capture_artifacts(source_files=episode.task.files,
                        execution_plan_pin=execution_plan_pin,
                        policy_task_path=Path(actual_trace.directory)/'policy-task.json',
                        expected_public=expected_public)
                value = {'task_id': expected_public['task_id'],
                    'goal_sha256': sha256(observation['goal'].encode()).hexdigest(),
                    'reference_files': deepcopy(reference_files), 'source_files': deepcopy(episode.task.files)}
                if missing_answer_reader_sha256 is not None:
                    value['initial_chat_messages_excluded'] = len(episode.task.initial_chat_messages)
                    state['captured_binding'] = deepcopy(value)
                return value
            def native_grade(env, actual_trace, outcome):
                if not state['policy_closed'] or not state['runtime_closed']:
                    raise ValueError('Compound grading requires policy and Runtime cleanup first')
                if outcome.get('error') or outcome.get('execution_error') or outcome.get('cleanup_errors'):
                    raise ValueError('Policy/setup/cleanup failed; automatic grade unavailable')
                checked_files(episode.task.files)
                check_saved_public_task(actual_trace.directory, expected_public)
                if missing_answer_reader_sha256 is not None:
                    from .compound_answer_delivery_v1 import select_answer_path
                    natural = json.loads((actual_trace.directory/'natural-answer.json').read_bytes())
                    if select_answer_path(natural, outcome) == 'missing_answer':
                        from .compound_terminal_capture_v1 import capture_terminal
                        checked_files(reference_files)
                        captured = state['captured_binding']
                        evidence = capture_terminal(trace=actual_trace.directory, run_root=destination,
                            native_task_id=episode.native_task['task_id'], public_task_id=expected_public['task_id'],
                            contract_id=contract.contract_id, input_files=inputs, source_files=episode.task.files,
                            actual_goal_sha256=captured['goal_sha256'],
                            actual_initial_count=captured['initial_chat_messages_excluded'])
                        grader = grader_factory(**{key:json.loads(Path(path).read_bytes()) for key,path in inputs.items()})
                        grade = grader.grade_missing_answer(evidence)
                        checked_files(episode.task.files); checked_files(reference_files)
                        with (destination/'native-grade.json').open('x', encoding='utf-8') as stream:
                            json.dump(grade, stream, indent=2, ensure_ascii=False, allow_nan=False)
                        state['deferred'] = {'kind':'missing_answer','grade':grade,
                            'output':str(destination),'trace':str(actual_trace.directory)}
                        state['grade'] = grade
                        return {'task_id':expected_public['task_id'],'native_grade':grade}
                factory = extraction_backend_factory or task_answer.SubscriptionTaskExtractor(quota_guard=quota_guard,
                    model=grading['model'], reasoning_effort=grading['reasoning_effort']).backend
                deferred = extract_saved_deferred(trace=actual_trace.directory, inputs=inputs,
                    output=destination/'answer-grading', grader_factory=grader_factory,
                    backend_factory=factory, source_paths=list(episode.task.files), before_model_dispatch=quota_guard)
                state['deferred'] = deferred
                grade = deferred['grade']
                state['grade'] = grade
                # Native adapter grades native IDs; outer automatic contract retains
                # the separately accepted public identity without changing the grade.
                return {'task_id': expected_public['task_id'], 'native_grade': grade}
            def project(raw, binding):
                grade = raw['native_grade']
                return Evaluation('catalog-compare-review-native', VERSION, trust='native_reference',
                    task_completed=grade['structured_claims_correct'],
                    evidence=[str(destination/('native-grade.json' if grade.get('outcome_kind') ==
                        'required_answer_not_delivered' else 'answer-grading/completed.json'))],
                    limitations=[*grade.get('limitations', []),
                        'Whole-run effect authorization is not established by answer grading'])
            def viewer_check(actual_trace, evaluation):
                return canonical_viewer_check(actual_trace, evaluation)
            contract = AutomaticGrading(VERSION, bind, native_grade, project, phase='external', viewer_check=viewer_check)
            contract.validate()
            # Pin the installed shared viewer and grading implementation as trusted
            # integration dependencies before the prospective first dispatch.
            for module in ('intent_browser.automatic_grading', 'intent_browser.evaluation', 'agent_trace.adapters.browsergym'):
                import importlib
                source = Path(importlib.import_module(module).__file__).resolve()
                pin = sha256(source.read_bytes()).hexdigest()
                if str(source) in episode.task.files and episode.task.files[str(source)] != pin:
                    raise ValueError('Automatic grading integration source differs from frozen binding')
                episode.task.files[str(source)] = pin
            if missing_answer_reader_sha256 is not None:
                from scripts import trace_grades
                from . import compound_answer_delivery_v1, compound_missing_output_v1, compound_terminal_capture_v1
                from . import compound_missing_answer_native_v1, catalog_compare_review_grading
                for module in (trace_grades, compound_answer_delivery_v1, compound_missing_output_v1,
                               compound_terminal_capture_v1, compound_missing_answer_native_v1,
                               catalog_compare_review_grading):
                    source = Path(module.__file__).resolve()
                    pin = sha256(source.read_bytes()).hexdigest()
                    if module is trace_grades and pin != missing_answer_reader_sha256:
                        raise ValueError('Explicitly adopted missing-output reader changed before bind')
                    if str(source) in episode.task.files and episode.task.files[str(source)] != pin:
                        raise ValueError('Missing-output source differs from retained fresh recipe')
                    episode.task.files[str(source)] = pin
            if not contract.callable_sources() <= episode.task.files.keys():
                raise ValueError('Automatic compound callbacks are absent from the source union')
            def before_dispatch():
                checked_files(episode.task.files)
                checked_files(reference_files)
                quota_guard()
            before_dispatch()
            with policy_session(before_dispatch=before_dispatch) as backend:
                bound_metadata = {**metadata, 'native_task_id': episode.native_task['task_id'],
                                  'public_task_id': expected_public['task_id']}
                trace, summary = runner(episode.task.make_env, backend, bound_metadata, output=destination/'runs',
                    episode_task=episode.task, harness_profile=episode.profile, site_discovery=episode.site_discovery,
                    terminal_response_instruction=TERMINAL_INSTRUCTION,
                    automatic_grading=contract, **runner_options)
            state['policy_closed'] = True
            trace = Path(trace).resolve()
            if trace == destination/'runs' or not trace.is_relative_to(destination/'runs'):
                raise ValueError('Returned compound trace escaped its declared run directory')
            shared.save(destination/'policy-result.json', {'trace': str(trace), 'summary': summary})
            checked_files(episode.task.files)  # No post-policy quota check suppresses a native grade.
        state['runtime_closed'] = True
        saved_summary = json.loads((trace/'episode.json').read_bytes())
        check_policy_outcome(summary, saved_summary)
        summary = finalize_external(trace, contract)
        if summary.get('grading_error') or not summary.get('infrastructure_completed'):
            raise ValueError('External automatic grading failed: '+str(summary.get('grading_error')))
        publish_finalized_answer(state['deferred'], contract_id=contract.contract_id)
        projected = viewer_projection(trace=trace, grade=state['grade'])
        if type(projected) is not dict or projected.get('status') != 'verified':
            raise ValueError('Final automatic compound grade viewer projection is missing/unverified')
        state['projection'] = projected
        result = {'schema': VERSION, 'status': 'graded_and_projected', 'trace': str(trace),
            'answer_grading': state['grade'], 'task_completed': state['grade']['structured_claims_correct'],
            'viewer_projection': state['projection'], 'policy_summary': summary, 'automatic_retries': 0}
    except Exception as error:
        result = {'schema': VERSION, 'status': 'system_failure', 'trace': str(trace) if trace else None,
            'task_completed': None, 'policy_summary': summary, 'error_type': type(error).__name__,
            'reason': str(error), 'policy_closed': state['policy_closed'],
            'runtime_closed': state['runtime_closed'], 'automatic_retries': 0}
    shared.save(destination/'execution-result.json', result)
    return result
