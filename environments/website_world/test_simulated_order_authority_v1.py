"""Finite synthetic authority controls; these do not certify browser effects."""
from copy import deepcopy
from functools import lru_cache
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace, FunctionType
import unittest
from unittest.mock import patch

from .adapter import digest, ROOT
from .catalog_cart_authority import AuthorityError, code_index, file_hash
from .simulated_order_authority_v1 import OrderCommitAuthority, PHASES, NATIVE_AUTHORITY
from .simulated_order_store import OrderStore
from .simulated_order_projection_v1 import project_capsule, forbidden_order_effects, _null_authority_interval

_MUTABLE_TEST_VALUE = {'enabled': True}


def source_probe(value=None):
    return _MUTABLE_TEST_VALUE


def dependency_target():
    return 'native'


def dependency_entry():
    return dependency_target()


class DeclaredDependencyClass:
    def value(self): return 'native'


def class_entry():
    return DeclaredDependencyClass()


_CALLBACKS = {'call': dependency_target}


def container_entry():
    return _CALLBACKS['call']()


@lru_cache(maxsize=2)
def cached_entry(value):
    return value


class SourceBindingTests(unittest.TestCase):
    def validator(self):
        authority = object.__new__(OrderCommitAuthority)
        source = Path(__file__).resolve()
        authority.compiled = {str(source): code_index(compile(source.read_bytes(), str(source), 'exec', dont_inherit=True))}
        authority.direct_bindings = {}
        authority.stdlib_sources = {}
        authority.archives = {str(source.relative_to(ROOT)): source.read_bytes()}
        return authority

    def test_copied_function_namespace_is_rejected(self):
        authority = self.validator()
        authority._function(source_probe)
        foreign = FunctionType(source_probe.__code__, dict(source_probe.__globals__))
        with self.assertRaisesRegex(AuthorityError, 'Foreign function globals'):
            authority._function(foreign)

    def test_mutable_globals_and_defaults_reject_without_changing_function_identity(self):
        for kind in ('global', 'default', 'code'):
            with self.subTest(kind=kind):
                authority = self.validator();authority._function(source_probe)
                defaults, code = source_probe.__defaults__, source_probe.__code__
                try:
                    if kind == 'global': _MUTABLE_TEST_VALUE['enabled'] = False
                    elif kind == 'default': source_probe.__defaults__ = ('changed',)
                    else: source_probe.__code__ = (lambda: None).__code__
                    with self.assertRaises(AuthorityError): authority._function(source_probe)
                finally:
                    _MUTABLE_TEST_VALUE['enabled'] = True
                    source_probe.__defaults__, source_probe.__code__ = defaults, code

    def test_foreign_consumed_function_rejects_before_initial_baseline(self):
        global dependency_target
        original = dependency_target
        try:
            # The donor's code and namespace are both retained. Admission must
            # also bind the callable to the source-declared dependency name.
            dependency_target = source_probe
            with self.assertRaisesRegex(AuthorityError, 'Declared dependency implementation'):
                self.validator()._function(dependency_entry)
        finally:
            dependency_target = original

    def test_thread_registry_contents_may_change_but_identity_is_bound(self):
        import threading
        authority = self.validator()
        registry = {}
        binding = authority._global_binding(threading.Thread._bootstrap_inner, '_active', registry)
        registry[1] = object()
        self.assertEqual(binding, authority._global_binding(threading.Thread._bootstrap_inner, '_active', registry))
        self.assertNotEqual(binding, authority._global_binding(threading.Thread._bootstrap_inner, '_active', {}))
        with self.assertRaisesRegex(AuthorityError, 'lifecycle registry'):
            authority._global_binding(threading.Thread._bootstrap_inner, '_active', [])

    def test_source_declared_class_is_admitted(self):
        self.validator()._function(class_entry)

    def test_intrinsic_types_and_json_pattern_match_are_admitted(self):
        import re, types
        authority = self.validator()
        for value in (types.NoneType, types.CodeType, types.FunctionType, types.MethodType):
            authority._admit_dependency(value)
        authority._admit_dependency(re.compile(r'[ \t\n\r]*').match)
        with self.assertRaisesRegex(AuthorityError, 'Unadmitted interpreter callable'):
            authority._admit_dependency([].append)

    def test_container_and_default_callable_reject_before_baseline(self):
        foreign = FunctionType(compile('def foreign(): return None', '<unretained>', 'exec').co_consts[0], globals())
        old = _CALLBACKS['call'];defaults = source_probe.__defaults__
        try:
            _CALLBACKS['call'] = foreign
            with self.assertRaises(AuthorityError): self.validator()._function(container_entry)
            source_probe.__defaults__ = (foreign,)
            with self.assertRaises(AuthorityError): self.validator()._function(source_probe)
        finally:
            _CALLBACKS['call'] = old;source_probe.__defaults__ = defaults

    def test_foreign_callable_object_and_container_cycles(self):
        class Foreign:
            def __call__(self): return None
        with self.assertRaisesRegex(AuthorityError, 'Unknown executable dependency'):
            self.validator()._admit_dependency(Foreign())
        cycle = [];cycle.append(cycle)
        self.validator()._admit_dependency(cycle)

    def test_source_declared_cache_and_writable_metadata_mismatch(self):
        self.validator()._admit_dependency(cached_entry)
        original = cached_entry.__wrapped__
        try:
            cached_entry.__wrapped__ = source_probe
            with self.assertRaisesRegex(AuthorityError, 'actual function dispatch'):
                self.validator()._admit_dependency(cached_entry)
        finally:
            cached_entry.__wrapped__ = original


    def test_authority_instance_method_override_rejects(self):
        authority = self.validator()
        from . import simulated_order_authority_v1, catalog_cart_authority
        for module in (simulated_order_authority_v1, catalog_cart_authority):
            path = Path(module.__file__).resolve()
            authority.compiled[str(path)] = code_index(compile(path.read_bytes(), str(path), 'exec', dont_inherit=True))
        authority.helper_method_ids = {owner.__module__+'.'+owner.__qualname__+'.'+name: id(fn)
            for owner in type(authority).__mro__ if owner is not object for name, fn in vars(owner).items()
            if isinstance(fn, FunctionType)}
        OrderCommitAuthority._assert_helper(authority)
        authority._surface = lambda: {}
        with self.assertRaisesRegex(AuthorityError, 'instance method override'):
            OrderCommitAuthority._assert_helper(authority)


class LedgerProjectionTests(unittest.TestCase):
    """Native ledger slicing/sealing using a synthetic record maker and transports.

    Source/router checks are replaced ONLY in this isolated unit fixture. Exact
    detached Runtime and HTTP/browser authority need independent acceptance.
    """
    def setUp(self):
        # This class tests ledger/projection logic, not source attestation.
        replacement = patch.object(OrderCommitAuthority, '_assert_helper', return_value=None)
        replacement.start();self.addCleanup(replacement.stop)

    def fixture(self, directory, *, baseline=1, new=2):
        path = Path(directory)
        baskets = SimpleNamespace(adapter=SimpleNamespace(world={'world_id': 'world'}, retailers={'shop': {}}),
                                  plan_id='plan', domain_id='domain')
        def maker(baskets, rid, submission, *, order_id):
            return {'order_id': order_id, 'retailer_id': rid, 'submission': deepcopy(submission),
                    'submission_sha256': digest(submission)}
        store = OrderStore(baskets, runtime_id='runtime', record_maker=maker)
        binding = {'episode_id': 'episode', 'task_sha256': 'a'*64,
                   'source_union_sha256': 'b'*64, 'capture_implementation_sha256': 'c'*64}
        store.bind_episode(binding)
        for n in range(baseline):store.commit('shop', {'idempotency_key': 'baseline'+str(n)})
        before = store.snapshot()
        for n in range(new):store.commit('shop', {'idempotency_key': 'new'+str(n)})
        after = store.snapshot();store.seal(after)
        authority = object.__new__(OrderCommitAuthority)
        authority.capture = SimpleNamespace(sealed=True, trace=SimpleNamespace(episode_id='episode', directory=path))
        host = SimpleNamespace(thread=SimpleNamespace(is_alive=lambda: False),
            server=SimpleNamespace(socket=SimpleNamespace(fileno=lambda: -1),
                                   _BaseServer__is_shut_down=SimpleNamespace(is_set=lambda: True)))
        authority.runtime = SimpleNamespace(sites={'shop': host}, index=host, discovery_mode='index',
            _stack=SimpleNamespace(_exit_callbacks=[]), _browser_bridges=[], baskets=baskets)
        authority.store = store
        authority.source_files, authority.stdlib_sources, authority.inputs = {}, {}, {}
        authority.initial = {'assets': {}, 'html': {}, 'schema': 'synthetic', 'world_sha256': 'd'*64,
            'plan': 'e'*64, 'domain': 'f'*64, 'plan_id': 'plan', 'domain_id': 'domain'}
        authority._surface = lambda: deepcopy(authority.initial)
        authority._check_files = lambda: None
        authority.cleanup_state = {'policy_closed': True, 'runtime_closed': True, 'grade': None}
        authority.phases, authority.failures = {}, []
        setup = path/'synthetic-setup.json';setup.write_text('{"synthetic":true}')
        authority.setup_receipt = {'path': str(setup), 'sha256': file_hash(setup)}
        (path/'steps.jsonl').write_bytes(b'original trace\n')
        capsule = {'schema_version': 'website-simulated-order-capsule-v1', 'episode_id': 'episode',
            'task_sha256': 'a'*64, 'main_trace_sha256': file_hash(path/'steps.jsonl'), 'effect_journal': None}
        for phase, name, snapshot in zip(PHASES, ('before', 'after'), (before, after)):
            value = {'phase': phase, 'order_snapshot': snapshot}
            artifact = path/(name+'.json');artifact.write_text(json.dumps(value))
            authority.phases[phase] = {'capture': {'path': str(artifact), 'sha256': file_hash(artifact)}, 'snapshot': snapshot}
            capsule[name] = value
        raw = path/'order-capsule.private.json';raw.write_text(json.dumps(capsule, indent=1)+'\n')
        authority.sealed = False;authority.receipt = None
        return authority, path, capsule

    def seal(self, authority, path, capsule, *, approval=None, summary=None):
        with patch('environments.website_world.simulated_order_record.validate', return_value='synthetic-validated'):
            return authority.seal(path, summary or {}, capsule, approval=approval)

    def approval(self, authority, path):
        proof = authority.receipt
        evidence = path/'synthetic-evidence.json';evidence.write_text('{"synthetic":true}\n')
        values = {k: proof[k] for k in ('helper_source_sha256', 'source_files', 'stdlib_source_sha256',
            'inputs', 'served_asset_sha256', 'served_html_sha256', 'native_context')}
        approval = path/'synthetic-approval.json'
        approval.write_text(json.dumps({'owner': 'Product', 'status': 'accepted',
            'authority_schema': 'website-generated-order-authority-v1', 'bindings': values,
            'evidence_manifest': {'path': str(evidence), 'sha256': file_hash(evidence)}}))
        return {'path': str(approval), 'sha256': file_hash(approval)}

    def test_all_new_events_survive_baseline_slicing_and_missing_approval_stays_null(self):
        with tempfile.TemporaryDirectory() as directory:
            authority, path, capsule = self.fixture(directory)
            proof = self.seal(authority, path, capsule)
            self.assertEqual([e['sequence'] for e in proof['events']], [2, 3])
            self.assertTrue(all(e['kind'] == 'order_committed' for e in proof['events']))
            self.assertIsNone(proof['native_effect_envelope'])
            self.assertIsNone(project_capsule(authority, raw_path=path/'order-capsule.private.json', output=path/'approved.json'))
            self.assertIsNone(forbidden_order_effects(authority))

    def test_approved_projection_has_strict_inverse_preserves_bytes_and_reports_forbidden_orders(self):
        with tempfile.TemporaryDirectory() as directory:
            authority, path, capsule = self.fixture(directory)
            self.seal(authority, path, capsule)
            approval = self.approval(authority, path)
            # New actual fixture/sealing, not changing an already sealed receipt.
            fresh, _, _ = self.fixture(directory)
            proof = self.seal(fresh, path, capsule, approval=approval)
            raw = path/'order-capsule.private.json';original = raw.read_bytes()
            projected = project_capsule(fresh, raw_path=raw, output=path/'approved.json')
            inverse = deepcopy(projected);inverse['effect_journal'] = None
            self.assertEqual(inverse, capsule);self.assertEqual(raw.read_bytes(), original)
            sidecar = json.loads((path/'approved.binding.json').read_bytes())
            start, end = sidecar['authority_utf8_byte_interval'];encoded = (path/'approved.json').read_bytes()
            self.assertEqual(encoded[:start]+b'null'+encoded[end:], original)
            self.assertEqual(projected['effect_journal'], {'authority': NATIVE_AUTHORITY, 'complete': True, 'events': proof['events']})
            self.assertEqual(forbidden_order_effects(fresh)['verdict'], 'fail')
            with self.assertRaises(FileExistsError):project_capsule(fresh, raw_path=raw, output=path/'approved.json')

    def test_cleanup_errors_missing_phases_transport_or_source_drift_cannot_complete(self):
        for fault in ('policy', 'runtime', 'error', 'missing', 'thread', 'source', 'ledger', 'event', 'receipts'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as directory:
                authority, path, capsule = self.fixture(directory)
                summary = {}
                if fault == 'policy':authority.cleanup_state['policy_closed'] = False
                elif fault == 'runtime':authority.cleanup_state['runtime_closed'] = False
                elif fault == 'error':summary['cleanup_errors'] = ['failed']
                elif fault == 'missing':authority.phases.pop(PHASES[0])
                elif fault == 'thread':authority.runtime.index.thread.is_alive = lambda: True
                elif fault == 'source':authority._surface = lambda: {'changed': True}
                elif fault == 'ledger':authority.store._records.pop()
                elif fault == 'event':authority.store._events[-1]['sequence'] = 100
                elif fault == 'receipts':authority.store._receipts.clear()
                with self.assertRaises(AuthorityError):self.seal(authority, path, capsule, summary=summary)
                self.assertIsNone(authority.receipt)

    def test_sealed_store_rejects_late_commit_and_retains_one_event(self):
        with tempfile.TemporaryDirectory() as directory:
            authority, path, capsule = self.fixture(directory, baseline=0, new=1)
            with self.assertRaisesRegex(ValueError, 'sealed'):
                authority.store.commit('shop', {'idempotency_key': 'new0'})
            proof = self.seal(authority, path, capsule)
            self.assertEqual(len(proof['events']), 1)

    def test_receipt_mutation_and_foreign_approval_reject(self):
        with tempfile.TemporaryDirectory() as directory:
            authority, path, capsule = self.fixture(directory)
            self.seal(authority, path, capsule)
            approval = self.approval(authority, path)
            document = json.loads(Path(approval['path']).read_text());document['authority_schema'] = 'read-only'
            Path(approval['path']).write_text(json.dumps(document));approval['sha256'] = file_hash(approval['path'])
            fresh, _, _ = self.fixture(directory)
            with self.assertRaisesRegex(AuthorityError, 'independent'):
                self.seal(fresh, path, capsule, approval=approval)
            authority.receipt['events'].clear()
            with self.assertRaisesRegex(AuthorityError, 'bindings changed'):
                project_capsule(authority, raw_path=path/'order-capsule.private.json', output=path/'approved.json')


class ProjectionIntervalTests(unittest.TestCase):
    def test_only_top_level_null_is_selected_with_utf8_offsets(self):
        raw = ('{\n "name": "Björn", "nested": {"effect_journal": null},\n'
               ' "effect_journal" : null, "text": "effect_journal: null"\n}\n').encode('utf-8')
        start, end = _null_authority_interval(raw)
        self.assertEqual(raw[start:end], b'null')
        replacement = b'{"complete":true}'
        changed = raw[:start]+replacement+raw[end:]
        self.assertEqual(changed[:start]+b'null'+changed[start+len(replacement):], raw)
        parsed = json.loads(changed)
        self.assertEqual(parsed['effect_journal'], {'complete': True})
        self.assertIsNone(parsed['nested']['effect_journal'])

    def test_ambiguous_missing_or_non_null_authority_rejects(self):
        for raw in (b'{"effect_journal":null,"effect_journal":null}',
                    b'{"nested":{"effect_journal":null}}',
                    b'{"effect_journal":{}}', b'{"effect_journal":null} trailing'):
            with self.subTest(raw=raw), self.assertRaises(AuthorityError):
                _null_authority_interval(raw)


if __name__ == '__main__': unittest.main()
