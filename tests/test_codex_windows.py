"""Window recovery tests use fake processes/RPC; never open Codex or send prompts."""
import asyncio
import base64
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('codex_windows', Path(__file__).resolve().parents[1] / 'scripts/codex_windows.py')
cw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cw)
A = '00000000-0000-0000-0000-000000000001'
B = '00000000-0000-0000-0000-000000000002'
C = '00000000-0000-0000-0000-000000000003'


class FakeRPC:
    def __init__(self, cwd='/tmp', active=False, denied=False, bad_result=False):
        self.cwd, self.active, self.denied, self.bad_result = cwd, active, denied, bad_result
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        pass

    async def call(self, method, params):
        self.calls.append((method, params))
        if method == 'thread/read':
            return {'thread': {'cwd': self.cwd, 'status': {'type': 'active' if self.active else 'notLoaded'}}}
        if method == 'permissionProfile/list':
            return {'data': [{'id': ':danger-full-access', 'allowed': not self.denied}]}
        if method == 'thread/resume':
            return {'approvalPolicy': 'never', 'sandbox': {'type': 'readOnly' if self.bad_result else 'dangerFullAccess'}}
        if method == 'thread/settings/update':
            return {}
        raise AssertionError(method)


class Recovery(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.state_patch = patch.object(cw, 'STATE', self.root / 'state')
        self.state_patch.start()
        self.cwd = '/tmp/project'
        self.rows = {A: {'id': A, 'cwd': self.cwd, 'name': 'main', 'updated_at_ms': 100},
                     B: {'id': B, 'cwd': self.cwd, 'name': 'ui', 'updated_at_ms': 99},
                     C: {'id': C, 'cwd': '/tmp/other', 'name': 'other', 'updated_at_ms': 101}}

    def tearDown(self):
        self.state_patch.stop()
        self.temp.cleanup()

    def test_exact_directory_only(self):
        group, unresolved = cw.identify(self.cwd, [{'cwd': self.cwd, 'thread_id': A},
                                       {'cwd': '/tmp/other', 'thread_id': C}], self.rows, set())
        self.assertEqual([t['id'] for t in group], [A])
        self.assertEqual(unresolved, 0)

    def test_unique_picker_mapping(self):
        group, unresolved = cw.identify(self.cwd, [{'cwd': self.cwd, 'thread_id': A},
                      {'cwd': self.cwd, 'thread_id': None}], self.rows, {A, B, C})
        self.assertEqual({t['id'] for t in group}, {A, B})
        self.assertEqual(group[1]['evidence'], 'unique_loaded_root')
        self.assertEqual(unresolved, 0)

    def test_ambiguous_picker_does_not_guess(self):
        group, unresolved = cw.identify(self.cwd, [{'cwd': self.cwd, 'thread_id': None}], self.rows, {A, B})
        self.assertEqual(group, [])
        self.assertEqual(unresolved, 1)

    def test_loaded_without_tui_not_in_roster(self):
        group, unresolved = cw.identify(self.cwd, [], self.rows, {A, B})
        self.assertEqual(group, [])
        self.assertEqual(unresolved, 0)

    def test_empty_logout_preserves_roster(self):
        cw.record_group(self.cwd, [{'id': A, 'name': 'main'}], 0)
        before = cw.state_path(self.cwd).read_bytes()
        cw.record_group(self.cwd, [], 0)
        self.assertEqual(cw.state_path(self.cwd).read_bytes(), before)

    def test_ambiguous_capture_preserves_roster(self):
        cw.record_group(self.cwd, [{'id': A, 'name': 'main'}], 0)
        before = cw.state_path(self.cwd).read_bytes()
        with self.assertRaisesRegex(RuntimeError, 'cannot be identified'):
            cw.record_group(self.cwd, [{'id': B}], 1)
        self.assertEqual(cw.state_path(self.cwd).read_bytes(), before)

    def test_partial_restore_does_not_shrink_group(self):
        cw.record_group(self.cwd, [{'id': A}, {'id': B}], 0)
        p = cw.state_path(self.cwd)
        value = cw.load(p)
        value['restore_until'] = cw.time.time() + 120
        cw.atomic_json(p, value)
        cw.record_group(self.cwd, [{'id': A}], 0)
        self.assertEqual(len(cw.load(p)['threads']), 2)

    def test_saved_group_wins_over_latest_activity(self):
        cw.record_group(self.cwd, [{'id': A}], 0)
        group, source = cw.resolve_group(self.cwd, self.rows, [], set())
        self.assertEqual(group['threads'], [{'id': A}])
        self.assertEqual(source, 'saved window group')

    def test_metadata_fallback_is_bounded_and_workspace_scoped(self):
        self.rows[A]['updated_at_ms'] = 20_000_000
        self.rows[B]['updated_at_ms'] = 0
        self.assertEqual([t['id'] for t in cw.recent_group(self.cwd, self.rows)], [A])

    def test_visual_tab_order_overrides_activity_order_and_handles_spinner(self):
        selected = [{'id': A, 'name': 'main'}, {'id': B, 'name': 'ui'}]
        tabs = [{'window': 1, 'index': 1, 'title': '⠋ main | project'},
                {'window': 1, 'index': 0, 'title': 'ui | project'}]
        ordered, proof = cw.order_group(self.cwd, selected, tabs)
        self.assertEqual([t['id'] for t in ordered], [B, A])
        self.assertEqual(proof['source'], 'windows_terminal_uia')
        command = cw.terminal_group_command(ordered, self.cwd, 'Ubuntu')
        self.assertLess(command.index(B), command.index(A))
        tabs[0]['index'], tabs[1]['index'] = 0, 1
        ordered, _ = cw.order_group(self.cwd, selected, tabs)
        self.assertEqual([t['id'] for t in ordered], [A, B])

    def test_unrelated_tabs_do_not_change_roster_or_codex_relative_order(self):
        selected = [{'id': A, 'name': 'main'}, {'id': B, 'name': 'ui'}]
        tabs = [{'window': 1, 'index': 0, 'title': 'ui | project'},
                {'window': 1, 'index': 1, 'title': 'PowerShell'},
                {'window': 1, 'index': 2, 'title': 'main | project'}]
        ordered, proof = cw.order_group(self.cwd, selected, tabs)
        self.assertEqual([t['id'] for t in ordered], [B, A])
        self.assertEqual(proof['source'], 'windows_terminal_uia')

    def test_unavailable_or_ambiguous_visual_order_preserves_saved_order(self):
        selected = [{'id': A, 'name': 'main'}, {'id': B, 'name': 'ui'}]
        previous = {'threads': list(reversed(selected)),
                    'tab_order': {'source': 'windows_terminal_uia', 'observed_at': 100}}
        base = [{'window': 1, 'index': 0, 'title': 'main | project'},
                {'window': 1, 'index': 1, 'title': 'ui | project'}]
        for tabs in (None, [], [base[0]], base + [dict(base[0], window=2)],
                     [base[0], dict(base[1], window=2)],
                     [base[0], dict(base[1], title='other ui | project')],
                     [base[0], dict(base[1], title='ui | other-project')]):
            with self.subTest(tabs=tabs):
                ordered, proof = cw.order_group(self.cwd, selected, tabs, previous)
                self.assertEqual([t['id'] for t in ordered], [B, A])
                self.assertEqual(proof['source'], 'saved_relative_order')
                self.assertEqual(proof['observed_at'], 100)

    def test_duplicate_conversation_names_are_not_guessed(self):
        selected = [{'id': A, 'name': 'same'}, {'id': B, 'name': 'same'}]
        ordered, proof = cw.order_group(self.cwd, selected,
            [{'window': 1, 'index': 0, 'title': 'same | project'}])
        self.assertEqual(ordered, selected)
        self.assertEqual(proof['source'], 'activity_fallback')

    def test_action_required_title_does_not_freeze_visual_order(self):
        selected = [{'id': A, 'name': 'main'}, {'id': B, 'name': 'ui'}]
        for prefix in ('Action Required | ', '[ . ] Action Required | ', '⠋ Action Required | '):
            with self.subTest(prefix=prefix):
                ordered, proof = cw.order_group(self.cwd, selected, [
                    {'window': 1, 'index': 1, 'title': prefix + 'main | project'},
                    {'window': 1, 'index': 0, 'title': 'ui | project'}])
                self.assertEqual([t['id'] for t in ordered], [B, A])
                self.assertEqual(proof['source'], 'windows_terminal_uia')

    def test_other_text_prefix_is_not_a_status_title(self):
        selected = [{'id': A, 'name': 'main'}]
        _, proof = cw.order_group(self.cwd, selected, [
            {'window': 1, 'index': 0, 'title': 'other Action Required | main | project'}])
        self.assertEqual(proof['source'], 'activity_fallback')

    def record_at(self, timestamp, ids, **kwargs):
        with patch.object(cw.time, 'time', return_value=timestamp):
            return cw.record_group(self.cwd, [{'id': i, 'name': i} for i in ids], 0, **kwargs)

    def test_shutdown_first_tab_close_preserves_full_group(self):
        self.record_at(1000, [A, B])
        result = self.record_at(1030, [A])
        self.assertEqual([t['id'] for t in result['threads']], [A, B])
        self.assertEqual(result['pending_removal']['ids'], [A])
        self.record_at(1060, [])
        self.assertEqual(len(cw.load(cw.state_path(self.cwd))['threads']), 2)

    def test_continuously_closed_tab_removed_after_grace(self):
        self.record_at(1000, [A, B])
        for t in (1030, 1060, 1090, 1120):
            self.assertEqual(len(self.record_at(t, [A])['threads']), 2)
        result = self.record_at(1150, [A])
        self.assertEqual([t['id'] for t in result['threads']], [A])
        self.assertNotIn('pending_removal', result)
        self.assertEqual(len(result['recent_groups'][0]['threads']), 2)

    def test_reappearing_tab_cancels_removal(self):
        self.record_at(1000, [A, B])
        self.record_at(1030, [A])
        result = self.record_at(1060, [B, A])
        self.assertNotIn('pending_removal', result)
        self.assertEqual([t['id'] for t in result['threads']], [B, A])

    def test_sampling_gap_restarts_removal_grace(self):
        self.record_at(1000, [A, B])
        self.record_at(1030, [A])
        result = self.record_at(1300, [A])
        self.assertEqual(len(result['threads']), 2)
        self.assertEqual(result['pending_removal']['first_seen'], 1300)

    def test_reboot_restarts_removal_grace(self):
        self.record_at(1000, [A, B])
        self.record_at(1030, [A])
        with patch.object(cw, 'boot_id', return_value='new-boot'):
            result = self.record_at(1200, [A])
        self.assertEqual(len(result['threads']), 2)
        self.assertEqual(result['pending_removal']['boot_id'], 'new-boot')

    def test_additions_are_saved_while_removals_are_pending(self):
        self.record_at(1000, [A, B])
        result = self.record_at(1030, [A, C])
        self.assertEqual([t['id'] for t in result['threads']], [A, B, C])

    def test_manual_save_can_confirm_removal_without_waiting(self):
        self.record_at(1000, [A, B])
        result = self.record_at(1030, [A], confirm_removals=True)
        self.assertEqual([t['id'] for t in result['threads']], [A])

    def test_manual_save_still_refuses_unidentified_windows(self):
        self.record_at(1000, [A, B])
        with self.assertRaisesRegex(RuntimeError, 'cannot be identified'):
            cw.record_group(self.cwd, [{'id': A}], 1, confirm_removals=True)
        self.assertEqual(len(cw.load(cw.state_path(self.cwd))['threads']), 2)

    def test_history_is_bounded_without_recursive_snapshots(self):
        for i in range(12):
            self.record_at(1000 + i, [A, B] if i % 2 else [A], confirm_removals=True)
        result = cw.load(cw.state_path(self.cwd))
        self.assertEqual(len(result['recent_groups']), 8)
        self.assertTrue(all('recent_groups' not in row for row in result['recent_groups']))

    def test_reorders_do_not_evict_previous_memberships(self):
        self.record_at(1000, [A, B, C])
        self.record_at(1030, [A, B], confirm_removals=True)
        for i in range(12):
            self.record_at(1060 + i, [B, A] if i % 2 else [A, B])
        history = cw.load(cw.state_path(self.cwd))['recent_groups']
        self.assertEqual(len(history), 1)
        self.assertEqual({t['id'] for t in history[0]['threads']}, {A, B, C})

    def test_after_reboot_unseen_members_cannot_expire(self):
        with patch.object(cw, 'boot_id', return_value='old-boot'):
            self.record_at(1000, [A, B])
        with patch.object(cw, 'boot_id', return_value='new-boot'):
            for t in range(2000, 2600, 30):
                result = self.record_at(t, [A])
                self.assertEqual(len(result['threads']), 2)
            self.assertEqual(result['pending_removal']['never_seen_this_boot'], [B])
            self.record_at(2600, [A, B])
            for t in range(2630, 2780, 30):
                result = self.record_at(t, [A])
            self.assertEqual([t['id'] for t in result['threads']], [A])

    def test_failed_restore_members_are_retained_after_both_grace_periods(self):
        group = self.record_at(1000, [A, B], force=True, live_ids=[])
        group['restore_until'] = 1120
        cw.atomic_json(cw.state_path(self.cwd), group)
        for t in range(1030, 1630, 30):
            result = self.record_at(t, [A])
        self.assertEqual([t['id'] for t in result['threads']], [A, B])
        self.assertEqual(result['pending_removal']['never_seen_this_boot'], [B])

    def test_failed_same_boot_relaunch_requires_fresh_live_observation(self):
        self.record_at(900, [A, B])  # Both were attached earlier in this boot.
        from subprocess import CompletedProcess
        with patch.object(cw, 'processes', return_value=[]), \
             patch.object(cw, 'thread_rows', return_value=self.rows), \
             patch.object(cw.shutil, 'which', return_value='/bin/true'), \
             patch.dict(cw.os.environ, {'WSL_DISTRO_NAME': 'Ubuntu'}), \
             patch.object(cw.time, 'time', return_value=1000), \
             patch.object(cw, 'RPC', return_value=FakeRPC(cwd=self.cwd)), \
             patch.object(cw.subprocess, 'run', side_effect=[
                 CompletedProcess([], 0), RuntimeError('terminal launch failed')]):
            with self.assertRaisesRegex(RuntimeError, 'terminal launch failed'):
                asyncio.run(cw.restore(self.cwd))
        self.assertEqual(cw.load(cw.state_path(self.cwd))['live_seen']['ids'], [])
        for t in range(1030, 1630, 30):
            result = self.record_at(t, [A])
        self.assertEqual([t['id'] for t in result['threads']], [A, B])
        self.assertEqual(result['pending_removal']['never_seen_this_boot'], [B])

    def test_partial_capture_preserves_legacy_fallback_uncertainty(self):
        cw.atomic_json(cw.state_path(self.cwd), {'cwd': self.cwd,
            'threads': [{'id': A}, {'id': B}], 'restore_until': 0})
        self.record_at(1000, [A])
        group, label = cw.resolve_group(self.cwd, self.rows, [], set())
        self.assertIn('approximate', label)
        self.assertIn('approximate', group['selection_source'])

    def test_duplicate_explicit_selection_is_rejected_before_mutation(self):
        self.record_at(1000, [A, B])
        before = cw.state_path(self.cwd).read_bytes()
        with self.assertRaisesRegex(RuntimeError, 'Duplicate conversation IDs'):
            asyncio.run(cw.capture_all(self.cwd, [A, A, B]))
        self.assertEqual(cw.state_path(self.cwd).read_bytes(), before)

    def test_manual_save_can_repair_old_duplicate_roster(self):
        cw.atomic_json(cw.state_path(self.cwd), {'schema_version': 1,
            'cwd': self.cwd, 'threads': [{'id': A}, {'id': A}, {'id': B}]})
        with self.assertRaisesRegex(RuntimeError, 'duplicate IDs'):
            self.record_at(1000, [A])
        result = self.record_at(1030, [A], confirm_removals=True)
        self.assertEqual([t['id'] for t in result['threads']], [A])

    def test_partial_capture_keeps_observed_order_and_missing_slots(self):
        self.record_at(1000, [A, B, C], tab_order={'source': 'windows_terminal_uia', 'observed_at': 1000})
        result = self.record_at(1030, [C, A], tab_order={'source': 'windows_terminal_uia', 'observed_at': 1030})
        self.assertEqual([t['id'] for t in result['threads']], [C, B, A])
        self.assertEqual(result['tab_order']['observed_at'], 1030)
        self.assertEqual(result['tab_order']['source'], 'partial_visual_order')

    def test_capture_preserves_launch_claims_past_restore_grace(self):
        group = self.record_at(1000, [A])
        group.update(restore_until=1100, launch_boot=cw.boot_id(), launch_claims={B: 1125})
        cw.atomic_json(cw.state_path(self.cwd), group)
        result = self.record_at(1110, [A])
        self.assertEqual(result['launch_claims'], {B: 1125})
        self.assertEqual(result['launch_boot'], cw.boot_id())

    def test_fallback_restore_failure_keeps_valid_labeled_roster(self):
        with patch.object(cw, 'processes', return_value=[]), \
             patch.object(cw, 'thread_rows', return_value=self.rows), \
             patch.object(cw.shutil, 'which', return_value='/bin/true'), \
             patch.dict(cw.os.environ, {'WSL_DISTRO_NAME': 'Ubuntu'}), \
             patch.object(cw.subprocess, 'run'), \
             patch.object(cw, 'RPC', side_effect=RuntimeError('daemon RPC failed')):
            with self.assertRaisesRegex(RuntimeError, 'daemon RPC failed'):
                asyncio.run(cw.restore(self.cwd))
            group = cw.load(cw.state_path(self.cwd))
            self.assertEqual(group['schema_version'], 1)
            self.assertIn('approximate', group['selection_source'])
            asyncio.run(cw.restore(self.cwd, dry_run=True))

    def test_known_old_schema_less_fallback_can_be_read_without_mutation(self):
        path = cw.state_path(self.cwd)
        cw.atomic_json(path, {'cwd': self.cwd, 'threads': [{'id': A, 'name': 'main'}], 'restore_until': 123})
        before = path.read_bytes()
        group, label = cw.resolve_group(self.cwd, self.rows, [], set())
        self.assertEqual(group['schema_version'], 1)
        self.assertIn('approximate', label)
        self.assertEqual(path.read_bytes(), before)

    def test_unknown_roster_schema_is_not_migrated(self):
        cw.atomic_json(cw.state_path(self.cwd), {'schema_version': 2, 'cwd': self.cwd,
            'threads': [{'id': A, 'name': 'main'}], 'restore_until': 123})
        with self.assertRaisesRegex(RuntimeError, 'Invalid workspace roster'):
            cw.resolve_group(self.cwd, self.rows, [], set())

    def test_main_distinguishes_manual_save_from_automatic_capture(self):
        seen = []
        async def capture(*args, **kwargs):
            seen.append(kwargs['force'])
        with patch.object(cw, 'capture_all', new=capture):
            for command in ('save', 'capture'):
                with patch.object(cw.sys, 'argv', ['codex-windows', command]):
                    self.assertEqual(cw.main(), 0)
        self.assertEqual(seen, [True, False])

    def test_timer_preserves_known_distribution_when_environment_lacks_it(self):
        with patch.dict(cw.os.environ, {'WSL_DISTRO_NAME': 'Ubuntu'}):
            self.record_at(1000, [A])
        with patch.dict(cw.os.environ, {}, clear=True):
            self.assertEqual(self.record_at(1030, [A])['distro'], 'Ubuntu')

    def test_new_threads_append_to_preserved_order(self):
        previous = {'threads': [{'id': B}, {'id': A}]}
        selected = [{'id': C, 'name': 'new'}, {'id': A, 'name': 'main'}, {'id': B, 'name': 'ui'}]
        ordered, proof = cw.order_group(self.cwd, selected, None, previous)
        self.assertEqual([t['id'] for t in ordered], [B, A, C])
        self.assertEqual(proof['source'], 'saved_relative_order')

    def test_capture_records_actual_tab_order_and_fallback_preserves_it(self):
        running = [{'cwd': self.cwd, 'thread_id': A}, {'cwd': self.cwd, 'thread_id': B}]
        with patch.object(cw, 'processes', return_value=running), \
             patch.object(cw, 'thread_rows', return_value=self.rows), \
             patch.object(cw, 'terminal_tabs', return_value=[
                 {'window': 1, 'index': 1, 'title': 'main | project'},
                 {'window': 1, 'index': 0, 'title': 'ui | project'}]):
            asyncio.run(cw.capture_all(self.cwd))
        saved = cw.load(cw.state_path(self.cwd))
        self.assertEqual([t['id'] for t in saved['threads']], [B, A])
        self.assertEqual(saved['tab_order']['source'], 'windows_terminal_uia')
        with patch.object(cw, 'processes', return_value=running), \
             patch.object(cw, 'thread_rows', return_value=self.rows), \
             patch.object(cw, 'terminal_tabs', return_value=None):
            asyncio.run(cw.capture_all(self.cwd))
        self.assertEqual([t['id'] for t in cw.load(cw.state_path(self.cwd))['threads']], [B, A])

    def test_explicit_save_order_does_not_probe_windows(self):
        with patch.object(cw, 'processes', return_value=[]), \
             patch.object(cw, 'thread_rows', return_value=self.rows), \
             patch.object(cw, 'terminal_tabs', side_effect=AssertionError('Explicit order wins')):
            asyncio.run(cw.capture_all(self.cwd, [B, A]))
        saved = cw.load(cw.state_path(self.cwd))
        self.assertEqual([t['id'] for t in saved['threads']], [B, A])
        self.assertEqual(saved['tab_order']['source'], 'explicit_argument_order')
        self.assertEqual(saved['live_seen']['ids'], [])

    def test_native_snapshot_handles_unicode_and_rejects_invalid_data(self):
        payload = [{'window': 1, 'index': 0, 'title': '⠋ main | project'}]
        from subprocess import CompletedProcess
        with patch.object(cw.shutil, 'which', return_value='powershell.exe'), \
             patch.object(cw.subprocess, 'run', return_value=CompletedProcess([],0,
                json.dumps(payload, ensure_ascii=False).encode('utf-8'), b'')) as run:
            self.assertEqual(cw.terminal_tabs(), payload)
            self.assertEqual(run.call_args.kwargs['timeout'], 10)
        for value in ({}, [{'index': -1}], [{'window': 1, 'index': False, 'title': 'main'}]):
            with self.subTest(value=value), patch.object(cw.shutil, 'which', return_value='powershell.exe'), \
                 patch.object(cw.subprocess, 'run', return_value=CompletedProcess([],0,
                    json.dumps(value).encode('utf-8'),b'')):
                self.assertIsNone(cw.terminal_tabs())

    def test_native_snapshot_timeout_does_not_disrupt_tracking(self):
        import subprocess
        with patch.object(cw.shutil, 'which', return_value='powershell.exe'), \
             patch.object(cw.subprocess, 'run', side_effect=subprocess.TimeoutExpired('powershell.exe', 10)):
            self.assertIsNone(cw.terminal_tabs())

    def test_timer_can_probe_tabs_without_windows_in_path(self):
        from subprocess import CompletedProcess
        payload = [{'window': 1, 'index': 0, 'title': 'main | project'}]
        with patch.object(cw.shutil, 'which', return_value=None), \
             patch.object(cw.Path, 'is_file', return_value=True), \
             patch.object(cw.subprocess, 'run', return_value=CompletedProcess([], 0,
                 json.dumps(payload).encode(), b'')) as run:
            self.assertEqual(cw.terminal_tabs(), payload)
            self.assertEqual(run.call_args.args[0][0],
                '/mnt/c/WINDOWS/System32/WindowsPowerShell/v1.0/powershell.exe')

    def test_missing_powershell_has_no_subprocess_side_effects(self):
        with patch.object(cw.shutil, 'which', return_value=None), \
             patch.object(cw.Path, 'is_file', return_value=False), \
             patch.object(cw.subprocess, 'run', side_effect=AssertionError('No binary')):
            self.assertIsNone(cw.terminal_tabs())

    def test_tui_detection_ignores_server_exec_and_other_executables(self):
        proc = self.root / 'proc'
        proc.mkdir()
        for pid, argv, tty in [(1, ['codex', 'resume', A], True),
                               (2, ['codex', 'app-server'], True),
                               (3, ['codex', 'exec', 'hello'], True),
                               (4, ['python', 'codex'], True),
                               (5, ['codex', 'resume', B], False)]:
            folder = proc / str(pid)
            (folder / 'fd').mkdir(parents=True)
            (folder / 'cmdline').write_bytes('\0'.join(argv).encode() + b'\0')
            (folder / 'cwd').symlink_to(self.root)
            (folder / 'fd/0').symlink_to('/dev/pts/99' if tty else '/dev/null')
        self.assertEqual([p['thread_id'] for p in cw.processes(proc)], [A])

    def test_window_command_avoids_shell_and_yolo(self):
        command = cw.terminal_command({'id': A, 'name': 'Main; "quoted"'}, '/tmp/project with spaces', 'Ubuntu')
        self.assertEqual(command[:4], ['wt.exe', '-w', 'new', 'new-tab'])
        self.assertIn('/tmp/project with spaces', command)
        self.assertNotIn('--yolo', command)
        self.assertNotIn('-c', command)
        self.assertEqual(command[-1], A)
        self.assertNotIn(';', command[command.index('--title') + 1])
        self.assertIn('--useApplicationTitle', command)
        self.assertNotIn('--suppressApplicationTitle', command)

    def test_group_opens_one_window_with_named_tabs(self):
        command = cw.terminal_group_command([{'id': A, 'name': 'main'},
                                             {'id': B, 'name': 'ui; literal'}], '/tmp', 'Ubuntu')
        self.assertEqual(command[:4], ['wt.exe', '-w', 'new', 'new-tab'])
        self.assertEqual(command.count('-w'), 1)
        self.assertEqual(command.count('new-tab'), 2)
        self.assertEqual(command.count(';'), 1)
        self.assertEqual(command[command.index(';') + 1], 'new-tab')
        self.assertIn('ui  literal', command)
        self.assertEqual(command.count(A), 1)
        self.assertEqual(command.count(B), 1)
        self.assertEqual(command.count('--useApplicationTitle'), 2)

    def test_empty_group_rejected(self):
        with self.assertRaises(ValueError):
            cw.terminal_group_command([], '/tmp', 'Ubuntu')

    def test_windows_transport_quotes_literals(self):
        command = cw.terminal_command({'id': A, 'name': "O'Brien $(bad) & title"}, '/tmp/space dir', 'Ubuntu')
        transport = cw.windows_launch(command)
        script = base64.b64decode(transport[-1]).decode('utf-16le')
        self.assertIn("O''Brien", script)
        self.assertIn('"/tmp/space dir"', script)
        self.assertIn("-ArgumentList '", script)
        self.assertEqual(transport[0], 'powershell.exe')

    def test_wt_delimiter_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'delimiter'):
            cw.terminal_command({'id': A, 'name': 'main'}, '/tmp/x;y', 'Ubuntu')

    def test_lock_conflict_is_detected(self):
        p = self.root / 'lock'
        with cw.locked(p):
            with self.assertRaises(BlockingIOError):
                with cw.locked(p, blocking=False):
                    self.fail('Duplicate lock acquired')

    def test_permissions_verified_without_turn(self):
        rpc = FakeRPC()
        asyncio.run(cw.prepare_permissions(rpc, A, '/tmp'))
        self.assertEqual([m for m, _ in rpc.calls], ['thread/read', 'permissionProfile/list',
                         'thread/resume', 'thread/settings/update', 'thread/resume'])
        self.assertEqual(rpc.calls[-2][1]['permissions'], ':danger-full-access')
        self.assertEqual(rpc.calls[-2][1]['approvalPolicy'], 'never')

    def test_active_thread_never_resumed_or_changed(self):
        rpc = FakeRPC(active=True)
        with self.assertRaisesRegex(RuntimeError, 'already active'):
            asyncio.run(cw.prepare_permissions(rpc, A, '/tmp'))
        self.assertEqual(len(rpc.calls), 1)

    def test_cross_directory_thread_rejected_before_resume(self):
        rpc = FakeRPC(cwd='/elsewhere')
        with self.assertRaisesRegex(RuntimeError, 'another directory'):
            asyncio.run(cw.prepare_permissions(rpc, A, '/tmp'))
        self.assertEqual(len(rpc.calls), 1)

    def test_managed_permission_denial_no_resume(self):
        rpc = FakeRPC(denied=True)
        with self.assertRaisesRegex(RuntimeError, 'not allowed'):
            asyncio.run(cw.prepare_permissions(rpc, A, '/tmp'))
        self.assertEqual(len(rpc.calls), 2)

    def test_server_permission_mismatch_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'did not confirm'):
            asyncio.run(cw.prepare_permissions(FakeRPC(bad_result=True), A, '/tmp'))

    def test_already_attached_restore_makes_no_mutations(self):
        cw.record_group(self.cwd, [{'id': A, 'name': 'main'}], 0)
        with patch.object(cw, 'processes', return_value=[{'thread_id': A, 'cwd': self.cwd}]), \
             patch.object(cw, 'thread_rows', return_value=self.rows), \
             patch.object(cw.subprocess, 'run', side_effect=AssertionError('No subprocess expected')):
            asyncio.run(cw.restore(self.cwd))

    def test_recent_launch_is_not_repeated(self):
        group = cw.record_group(self.cwd, [{'id': A, 'name': 'main'}], 0)
        group.update(launch_boot=cw.boot_id(), launch_claims={A: cw.time.time()+100})
        cw.atomic_json(cw.state_path(self.cwd), group)
        with patch.object(cw, 'processes', return_value=[]), patch.object(cw, 'thread_rows', return_value=self.rows), \
             patch.object(cw.shutil, 'which', return_value='/bin/true'), \
             patch.object(cw.subprocess, 'run', side_effect=AssertionError('No repeated launch')):
            with self.assertRaisesRegex(RuntimeError, 'still unconfirmed'):
                asyncio.run(cw.restore(self.cwd))

    def test_restore_uses_single_windows_launch_for_two_threads(self):
        cw.record_group(self.cwd, [{'id': A, 'name': 'main'}, {'id': B, 'name': 'ui'}], 0)
        rpc = FakeRPC(cwd=self.cwd)
        with patch.object(cw, 'processes', side_effect=[[], [], [],
                [{'thread_id': A}, {'thread_id': B}]]), \
             patch.object(cw, 'thread_rows', return_value=self.rows), \
             patch.object(cw.shutil, 'which', return_value='/bin/true'), \
             patch.dict(cw.os.environ, {'WSL_DISTRO_NAME': 'Ubuntu'}), \
             patch.object(cw, 'RPC', return_value=rpc), \
             patch.object(cw.subprocess, 'run') as run:
            asyncio.run(cw.restore(self.cwd))
        launches = [call.args[0] for call in run.call_args_list if call.args[0][0] == 'powershell.exe']
        self.assertEqual(len(launches), 1)
        script = base64.b64decode(launches[0][-1]).decode('utf-16le')
        self.assertEqual(script.count('new-tab'), 2)
        self.assertEqual(script.count('-w new'), 1)


if __name__ == '__main__':
    unittest.main()
