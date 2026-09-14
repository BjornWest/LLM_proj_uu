import copy
import json
import tempfile
import unittest
from pathlib import Path

from intent_browser.pilot import PilotTask, load_pilot, preflight


ROOT = Path(__file__).resolve().parents[1]


class PilotTests(unittest.TestCase):
    def test_policy_projection_excludes_grader_evidence_and_keeps_source_key(self):
        record = {'id': 'P-test', 'source': 'trickyarena', 'source_task_id': 'ShoppingTask.TEST',
                  'source_revision': 'pinned', 'original_prompt': 'original dispatch text',
                  'policy_input': {'goal': 'clarified user goal', 'private': 'should not enter prompt'},
                  'proposed_grader': {'expected_state': 'secret answer'},
                  'upstream_verifier': {'raw_susceptibility': True}}
        task = PilotTask(record)
        self.assertEqual(task.policy_input, {'goal': 'clarified user goal'})
        self.assertEqual(task.source_key, ('trickyarena', 'ShoppingTask.TEST', 'pinned'))
        changed = copy.deepcopy(record)
        changed['policy_input']['goal'] = 'another user goal'
        self.assertEqual(PilotTask(changed).source_key, task.source_key)
        self.assertEqual(task.grader_input['original_prompt'], 'original dispatch text')
        grader_copy = task.grader_input
        grader_copy['original_prompt'] = 'changed copy'
        self.assertEqual(task.grader_input['original_prompt'], 'original dispatch text')

    def test_real_manifest_has_eight_unexecuted_paired_cases(self):
        tasks, fingerprint = load_pilot(ROOT / 'data/curation/pilot_manifest.json')
        report = preflight(tasks, fingerprint, ROOT / 'data/curation/inventory.jsonl')
        self.assertEqual(report['candidate_count'], 12)
        self.assertEqual(report['ready_count'], 0)
        self.assertTrue(all(row['inventory_matches'] for row in report['candidates']))
        plan = report['first_four_episode_plan']
        self.assertEqual(len(plan), 8)
        self.assertEqual({row['candidate_id'] for row in plan}, {'P01', 'P07', 'P10', 'P11'})
        for candidate in ('P01', 'P07', 'P10', 'P11'):
            pair = [row for row in plan if row['candidate_id'] == candidate]
            self.assertEqual(pair[0]['policy_input'], pair[1]['policy_input'])
            self.assertTrue(all(row['execution_status'] == 'not_run' for row in pair))
        health = next(row for row in report['candidates'] if row['id'] == 'P10')
        self.assertIn('T-HEALTH-01', health['defect_evidence_ids'])

    def test_missing_policy_goal_is_rejected_without_original_prompt_fallback(self):
        manifest = json.loads((ROOT / 'data/curation/pilot_manifest.json').read_text())
        manifest['candidates'][0]['policy_input'] = {}
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'manifest.json'
            path.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, 'policy_input.goal'):
                load_pilot(path)


if __name__ == '__main__':
    unittest.main()
