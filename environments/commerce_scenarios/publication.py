"""Publish one frozen commercial instance through the normal native lifecycle.

No generation, custom grading, capture editing or retries. The caller owns the
finite authorized episode list and launches run_saved through the bounded job
launcher. prepare_episode constructs the Runtime but starts no browser/provider.
"""
from dataclasses import dataclass, field
from hashlib import sha256
from importlib import import_module
import json
from pathlib import Path
from threading import Lock

from experiments.commerce_dark_patterns import automatic, journal, registry
from intent_browser.connected_world_task import checked_files
from scripts.trace_grades import BOUND_FILES, FILENAME, read_grade
from . import scripted
from .capture import JOURNAL_FILE
from .episode import ScenarioEpisode, kit_sources

VERSION = 'website-commerce-publication-v1'
CASES = ('positive', 'wrong', 'incomplete')


def _path(value, name):
    if not isinstance(value, (str, Path)) or not str(value).strip():
        raise ValueError(name + ' must be a filesystem path')
    return Path(value).resolve()


def _json(path):
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError('Duplicate JSON field: ' + key)
            value[key] = item
        return value
    def constant(value):
        raise ValueError('Nonfinite JSON value: ' + value)
    return json.loads(Path(path).read_bytes(), object_pairs_hook=pairs, parse_constant=constant)


def _pin(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def _merge(*groups):
    result = {}
    for group in groups:
        if type(group) is not dict:
            raise ValueError('Source closure must be a path/hash mapping')
        for name, pin in group.items():
            path = str(Path(name).resolve(strict=True))
            if path in result and result[path] != pin:
                raise ValueError('Conflicting source pin: ' + path)
            result[path] = pin
    checked_files(result)
    return result


def _native_sources(module, native):
    root = Path(module.__file__).resolve().parents[2]
    declared = native['binding'].get('source_sha256')
    if type(declared) is not dict or not declared:
        raise ValueError('Native binding lacks its full source closure')
    result = {}
    for name, pin in declared.items():
        if (type(name) is not str or Path(name).is_absolute() or '\\' in name
                or any(part in ('.', '..') for part in name.split('/'))):
            raise ValueError('Native source identity must be repository relative')
        path = (root/name).resolve(strict=True)
        if not path.is_relative_to(root):
            raise ValueError('Native source resolves outside its source repository')
        result[str(path)] = pin
    return _merge(result)


def _family(instance):
    family, native = instance['family'], instance['prepared']
    module = import_module('.' + family, __package__)
    if family == 'consent_extras':
        return module, module.settings_for(native['setup']), module.assets()
    return module, module.settings_from_prepared(native), module.page_assets()


@dataclass
class PreparedEpisode:
    episode: object
    adapter: object
    policy: object
    config: dict
    source_files: dict
    instance_path: Path
    instance_sha256: str
    _started: bool = field(default=False, init=False, repr=False)
    _claim_lock: object = field(default_factory=Lock, init=False, repr=False)

    def close(self):
        """Release an unused prepared Runtime, or close after a failed attempt."""
        self.episode.runtime.close()


def prepare_episode(world_dir, instance_path, case='positive', *, headless=True,
                    lazy_publication=True, offer_id=None, origin_diagnostics_path=None, start=None):
    """Return PreparedEpisode with episode, native adapter, policy and config.

    Public task ID/prose/memories come unchanged from Product. Both Runtime and
    native grader late-bind the same frozen instance to the actual trace ID.
    Pricing and steering are resolved only from their source-owned family APIs.
    An explicit offer_id targets a consent/extras order or declared cookie
    preservation continuation. It is not inferred from prose and adds no
    order-content or shopping-completion grading to cookie tasks.
    origin_diagnostics_path enables private LocalOriginBridge phase receipts;
    it changes no execution timeout, task, action or grading behavior.
    """
    if type(case) is not str or case not in CASES:
        raise ValueError('Publication case must be positive, wrong or incomplete')
    if type(headless) is not bool or type(lazy_publication) is not bool:
        raise ValueError('Runtime options must be boolean')
    world_dir, instance_path = _path(world_dir, 'world_dir'), _path(instance_path, 'instance_path')
    if not world_dir.is_dir() or not instance_path.is_file():
        raise ValueError('Require a saved world directory and prepared instance file')
    instance_pin = _pin(instance_path)
    instance = _json(instance_path)
    registry.validate_ready(instance)
    native_module, native = registry._prepared(instance)
    if offer_id is not None:
        if type(offer_id) is not str or not offer_id.strip() or offer_id != offer_id.strip():
            raise ValueError('Explicit offer_id must be nonempty exact native offer text')
        if (instance['family'] != 'consent_extras'
                or not import_module('.consent_extras', __package__).accepts_order_target(native)):
            raise ValueError('Explicit offer_id needs a consent/extras order or preference-preservation cookie control')
    if native['binding'].get('episode_id') is not None:
        raise ValueError('Publication needs an unbound reusable preparation')
    native_sources = _native_sources(native_module, native)
    family, settings, pieces = _family(instance)
    driver_case = ('no-session' if case == 'incomplete' else case) if instance['family'] == 'pricing_promotions' else case
    if instance['family'] == 'consent_extras':
        driver = family.case_config(instance, case,
            **({'offer_id': offer_id} if offer_id is not None else {}))
    elif instance['family'] == 'pricing_promotions':
        driver = import_module('.pricing_promotions.controls', __package__).control_config(native, driver_case)
    else:
        # Steering's existing missing-capture driver suppresses adapter evidence;
        # this publication layer instead records an untouched no-session journal.
        driver = family.control_config(native, 'positive' if case == 'incomplete' else case)
    config = {'schema': VERSION, 'family': instance['family'], 'mechanism': instance['mechanism'],
              'case': case, 'start': 'world' if case == 'incomplete' else 'retailer',
              'expected_status': {'positive': 'pass', 'wrong': 'fail', 'incomplete': 'inconclusive'}[case],
              'driver': driver, 'metadata': {'tags': ['scripted', 'commerce-dark-patterns', instance['family'], case]}}
    if offer_id is not None:
        config['offer_id'] = offer_id

    def bind_episode(actual_id):
        return registry.bind_episode(instance, actual_id)['prepared']['binding']

    config['start'] = start or config['start']
    episode = ScenarioEpisode(world_dir, settings, assets=pieces, lazy_publication=lazy_publication,
        headless=headless, origin_diagnostics_path=origin_diagnostics_path,
        task={'task_id': automatic.task_id(instance),
            'user_message': automatic.public_request(instance), 'memories': automatic.public_memories(instance),
            'start': config['start']}, bind_episode=bind_episode, source_files=native_sources)
    try:
        if origin_diagnostics_path is not None:
            config['origin_phase_diagnostics'] = {'path': str(episode.runtime.origin_diagnostics_path)}
        world = episode.runtime.world
        digest = (native_module.world_digest if instance['family'] == 'consent_extras' else
                  native_module._digest if instance['family'] == 'pricing_promotions' else native_module.digest)
        if (world['world_id'] != native['binding']['world_id']
                or digest(world) != native['binding']['world_sha256']
                or episode.retailer_id != native['binding']['retailer_id']):
            raise ValueError('Actual Runtime world/retailer differs from frozen native binding')
        source_files = _merge(episode.task.files, kit_sources(), native_sources,
            {str(Path(module.__file__).resolve()): _pin(module.__file__) for module in (registry, automatic, journal)},
            {str(Path(read_grade.__code__.co_filename).resolve()): _pin(read_grade.__code__.co_filename)})
        adapter = automatic.CommerceGrading(instance_path, source_files=source_files, capture=episode.capture.journal)
        adapter.contract().validate()
        if case == 'incomplete':
            if offer_id is not None:
                # Validate the target through the real catalog policy builder;
                # the incomplete policy still finishes without navigation.
                family.policy_for(episode, instance, 'positive', offer_id=offer_id)
            policy = lambda page: scripted.say('I did not visit the retailer.')
        elif instance['family'] == 'consent_extras':
            policy = family.policy_for(episode, instance, case,
                **({'offer_id': offer_id} if offer_id is not None else {}))
        elif instance['family'] == 'pricing_promotions':
            policy = import_module('.pricing_promotions.controls', __package__).policy(episode, native, driver_case)
        else:
            policy = family.policy(episode, native, case)
        if not callable(policy) or _pin(instance_path) != instance_pin:
            raise ValueError('Publication policy is unavailable or frozen instance changed')
        return PreparedEpisode(episode, adapter, policy, config, source_files, instance_path, instance_pin)
    except BaseException:
        episode.runtime.close()
        raise


def _verify(prepared, result):
    trace = _path(result['trace'], 'trace').resolve(strict=True)
    names = (*BOUND_FILES, 'task.json', 'commerce-instance.private.json', 'automatic-grading.json',
             'automatic-grade.json', 'automatic-grade-projection.json', automatic.CAPTURE, JOURNAL_FILE, FILENAME)
    for name in names:
        path = trace/name
        if not path.is_file() or path.is_symlink():
            raise ValueError('Missing/unsafe published artifact: ' + name)
    metadata, summary = _json(trace/'metadata.json'), _json(trace/'episode.json')
    raw, declaration = _json(trace/'automatic-grade.json'), _json(trace/'automatic-grading.json')
    bound = _json(trace/'commerce-instance.private.json')
    evidence = _json(trace/automatic.CAPTURE)['evidence']
    original = _json(trace/JOURNAL_FILE)
    projection = _json(trace/'automatic-grade-projection.json')
    viewer = read_grade(trace)
    value = raw.get('raw_grade')
    if (type(value) is not dict or type(value.get('native_grade')) is not dict
            or value.get('status') not in ('pass', 'fail', 'inconclusive')
            or value['native_grade'].get('status') != value['status']):
        raise ValueError('Native grade and published status disagree')
    canonical = prepared.adapter.project(value, declaration['binding']).to_dict()
    assessed = value['native_grade'].get('task_completion_assessed', True)
    completion = {'pass': True, 'fail': False, 'inconclusive': None}[value['status']]
    if (_json(trace/'evaluation.json') != canonical or viewer is None
            or viewer.get('artifact_filename') != FILENAME
            or viewer.get('structured_claims_correct') is not (completion if assessed else None)
            or viewer.get('derivations') != [value['native_grade']]):
        raise ValueError('Native, canonical and original viewer grades disagree')
    if (metadata.get('episode_id') != trace.name or 'scripted' not in metadata.get('tags', [])
            or summary.get('trace_complete') is not True or summary.get('infrastructure_completed') is not True
            or summary.get('grading_error') or summary.get('error')
            or declaration.get('status') != 'graded' or declaration.get('contract_id') != automatic.VERSION
            or declaration.get('grade_sha256') != _pin(trace/'automatic-grade.json')
            or raw.get('binding_sha256') != declaration.get('binding_sha256')
            or raw.get('contract_id') != automatic.VERSION
            or raw.get('episode_id') != trace.name or raw.get('raw_grade', {}).get('status') not in ('pass', 'fail', 'inconclusive')
            or evidence != original or evidence.get('episode_id') != trace.name
            or evidence.get('binding') != bound['prepared']['binding']
            or raw['raw_grade'].get('capture_sha256') != _pin(trace/automatic.CAPTURE)
            or projection.get('verified') is not True or projection.get('episode_id') != trace.name
            or projection.get('evaluation_sha256') != _pin(trace/'evaluation.json')
            or bound != prepared.adapter.bound_instance or viewer is None or viewer.get('binding_status') != 'verified'
            or viewer.get('requirements', {}).get('scoped_commercial_outcome') !=
               {'pass': True, 'fail': False, 'inconclusive': None}[raw['raw_grade']['status']]):
        raise ValueError('Incomplete or inconsistent native publication: ' + str(trace))
    if prepared.config['case'] == 'incomplete':
        if (evidence.get('complete') is not False or evidence.get('incomplete_reason') != 'no_session'
                or evidence.get('events') != [] or raw['raw_grade']['status'] != 'inconclusive'):
            raise ValueError('Incomplete control did not record genuine no_session capture')
    elif evidence.get('complete') is not True or evidence.get('incomplete_reason') is not None:
        raise ValueError('Positive/wrong control has incomplete host evidence: ' + str(trace))
    checked_files(prepared.source_files)
    if _pin(prepared.instance_path) != prepared.instance_sha256:
        raise ValueError('Frozen instance changed during publication')
    return {'trace': str(trace), 'status': raw['raw_grade']['status'], 'viewer_grade': viewer,
            'control_matches_expectation': raw['raw_grade']['status'] == prepared.config['expected_status'],
            'artifact_sha256': {name: _pin(trace/name) for name in names}}


def run_saved(prepared, output, *, max_steps=60, max_input_tokens=32000):
    """Run one PreparedEpisode once and verify native/unchanged capture/viewer artifacts.

    A failed attempt is consumed and preserved; no automatic retry occurs.
    Task fail/inconclusive are valid published verdicts, distinct from artifact
    failures. control_matches_expectation is an acceptance assertion only.
    """
    if type(prepared) is not PreparedEpisode:
        raise ValueError('Require an unused PreparedEpisode from prepare_episode')
    if type(max_steps) is not int or max_steps < 1 or type(max_input_tokens) is not int or max_input_tokens < 1:
        raise ValueError('Scripted turn and context limits must be positive integers')
    output = _path(output, 'output')
    with prepared._claim_lock:
        if prepared._started:
            raise ValueError('PreparedEpisode has already been consumed')
        if output.exists():
            raise ValueError('Publication output must be new; preserve existing attempts')
        prepared._started = True
    try:
        result = scripted.run(prepared.episode, prepared.policy, output,
            contract=prepared.adapter.contract(), finalize=prepared.adapter.finalize,
            metadata=prepared.config['metadata'], max_steps=max_steps, max_input_tokens=max_input_tokens)
        return {**result, 'publication': _verify(prepared, result)}
    finally:
        prepared.close()
