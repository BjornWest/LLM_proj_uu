"""Regression fixtures for evidence boundaries, comparisons, and immutable output."""
import json
from pathlib import Path
import tempfile
import unittest

from .core import analyze, ax_nodes, action_info, compare, digest, feedback, group_and_compare
from .run import build, report_html
from .review import validate


def obs(body, port=1234):
    return f"URL: http://127.0.0.1:{port}/shop\nLast action error: \nAccessibility tree:\n{body}"


def write(path, value):
    path.write_text(json.dumps(value))


class TriageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def episode(self, name, bodies=None, actions=None, safe=False, goal="Buy one laptop, no warranty.",
                posts=None, overrides=None, **metadata):
        directory = self.root / name
        directory.mkdir()
        bodies = bodies or ["[1] button 'Buy'"]
        actions = actions or ["click('1')"] * len(bodies)
        evaluation = {"task_completed": safe, "authorization_satisfied": True,
                      "safe_success": safe, "technical_error": None, "limitations": ["scoped fixture"]}
        meta = {"episode_id": name, "source": "fixture", "task": "buy", "model": "test",
                "evaluation": evaluation, "step_count": len(actions), "stop_reason": "agent_finished",
                "development_case": {"condition": "clean"}, **metadata}
        write(directory / 'episode.json', meta)
        write(directory / 'evaluation.json', evaluation)
        steps = []
        for i, (body, action) in enumerate(zip(bodies, actions)):
            text = obs(body)
            textfile = f'decision-observation-{i:03d}.txt'
            (directory / textfile).write_text(text)
            postfile = f'observation-{i+1:03d}.txt'
            (directory / postfile).write_text(obs(posts[i] if posts else body))
            step = {"step": i, "observation": {"text": textfile},
                    "next_observation": {"text": postfile}, "action": action,
                    "model_output": action, "model_response": {"choices": [{"finish_reason": "stop"}]},
                    "model_request": {"messages": [{"role": "user", "content": f"USER GOAL: {goal}\nRecent actions: []\n{text}"}]}}
            step.update((overrides or {}).get(i, {}))
            steps.append(step)
        (directory / 'steps.jsonl').write_text(''.join(json.dumps(s)+'\n' for s in steps))
        return directory

    def test_ids_normalized_but_quantity_price_and_ancestry_retained(self):
        a = ax_nodes("[10] listitem 'Laptop $900'\n\t[11] button 'Buy'")
        b = ax_nodes("[20] listitem 'Laptop $900'\n\t[21] button 'Buy'")
        self.assertEqual(action_info("click('11')", a)['signature'], action_info("click('21')", b)['signature'])
        c = ax_nodes("[20] listitem 'Laptop $901'\n\t[21] button 'Buy'")
        self.assertNotEqual(action_info("click('11')", a)['signature'], action_info("click('21')", c)['signature'])
        self.assertNotEqual(action_info("fill('11','1')", a)['signature'], action_info("fill('11','2')", a)['signature'])

    def test_no_eval_or_unknown_is_not_failure_or_success(self):
        p = self.episode('unknown', safe=None)
        e, _ = analyze(p)
        self.assertEqual(e['outcome_group'], 'unknown')
        self.assertIsNone(e['recorded_evaluation']['safe_success'])
        (p/'evaluation.json').unlink()
        m = json.loads((p/'episode.json').read_text());m.pop('evaluation');write(p/'episode.json',m)
        e, _ = analyze(p)
        self.assertEqual(e['outcome_group'], 'unknown')
        self.assertIsNone(e['recorded_evaluation'])

    def test_conflicting_evaluations_are_withheld(self):
        p = self.episode('conflict', safe=True)
        write(p/'evaluation.json', {'safe_success': False})
        e, _ = analyze(p)
        self.assertEqual(e['outcome_group'], 'unknown')
        self.assertIn('evaluation_conflict', [f['code'] for f in e['flags']])

    def test_retained_messages_required_not_prepared_messages(self):
        p = self.episode('missing', overrides={0:{'model_request': None,'messages':[{'content':'made up'}]}})
        e, _ = analyze(p)
        self.assertIsNone(e['timeline'][0]['observation_in_retained_request'])
        self.assertIsNone(e['timeline'][0]['action']['target'])
        self.assertNotIn('target_absent_from_input', [f['code'] for f in e['flags']])

    def test_selected_capture_mismatch_not_used_for_target_resolution(self):
        p = self.episode('wrong-capture', overrides={0:{'model_request':{'messages':[{'content':"[2] button 'Other'"}]}}})
        e, _ = analyze(p)
        self.assertIn('observation_not_in_request', [f['code'] for f in e['flags']])
        self.assertIsNone(e['timeline'][0]['action']['target'])

    def test_feedback_absent_checks_all_messages_and_only_status_alert(self):
        alert = "[1] button 'Add'\n[3] alert ''\n\tStaticText 'Item added to cart'"
        p = self.episode('gap', bodies=["[1] button 'Add'"]*2, posts=[alert,alert])
        e, _ = analyze(p)
        gaps = [f for f in e['flags'] if f['code']=='feedback_not_in_next_input']
        self.assertEqual(len(gaps),1)
        self.assertEqual(gaps[0]['after_step'],0)
        steps = [json.loads(s) for s in (p/'steps.jsonl').read_text().splitlines()]
        steps[1]['model_request']['messages'].append({'role':'user','content':'Previous action: Item added to cart'})
        (p/'steps.jsonl').write_text(''.join(json.dumps(s)+'\n' for s in steps))
        e, _ = analyze(p)
        self.assertNotIn('feedback_not_in_next_input',[f['code'] for f in e['flags']])
        self.assertEqual(feedback("[1] button 'Purchase succeeded'"),[])

    def test_reused_id_different_semantics(self):
        p = self.episode('reuse', bodies=["[1] button 'Cancel appointment A'","[1] button 'Cancel appointment B'"])
        e, _ = analyze(p)
        fs = [f for f in e['flags'] if f['code']=='target_id_semantics_changed']
        self.assertEqual([f['step'] for f in fs],[1])
        self.assertIsNone(fs[0]['causal_label'])
        self.assertNotIn('repeated_action',[f['code'] for f in e['flags']])

    def test_missing_target_is_not_claim_of_stale_dom(self):
        e, _ = analyze(self.episode('missing-bid',actions=["click('99')"]))
        fs = [f for f in e['flags'] if f['code']=='target_absent_from_input']
        self.assertEqual(len(fs),1)
        self.assertIn('not proof',fs[0]['detail'])

    def test_malformed_output_and_transport_phase_retained(self):
        p = self.episode('parse', actions=['<click>1</click>'], overrides={0:{'action':None,'error':'ParseError: XML', 'failure_phase':'action_parse'}})
        e, _ = analyze(p)
        self.assertEqual(e['timeline'][0]['model_output'],'<click>1</click>')
        self.assertEqual([f['phase'] for f in e['flags'] if f['code']=='decision_error'],['action_parse'])
        self.assertIsNone(e['diagnosis']['primary_failure'])

    def test_successful_recovery_keeps_error_flags_and_success(self):
        p = self.episode('recovery',safe=True,overrides={0:{'action_error':'TimeoutError: blocked control'}})
        e, _ = analyze(p)
        self.assertEqual(e['outcome_group'],'success')
        self.assertIn('action_error',[f['code'] for f in e['flags']])

    def test_alignment_insertion_and_equal_actions_different_effect(self):
        a,_ = analyze(self.episode('a',bodies=["[1] button 'A'","[2] button 'B'"],actions=["click('1')","click('2')"]))
        b,_ = analyze(self.episode('b',bodies=["[9] button 'A'","[8] button 'Wait'","[7] button 'B'"],actions=["click('9')","click('8')","click('7')"],safe=True))
        c = compare(a,b)
        self.assertEqual(c['common_action_prefix'],1)
        self.assertEqual(c['first_action_divergence']['kind'],'insert')
        self.assertEqual(c['first_action_divergence']['right_steps'],[1])
        d,_ = analyze(self.episode('d',bodies=["[1] button 'A'","[2] button 'B'"],actions=["click('1')","click('2')"],posts=["[1] button 'FAILED'","[2] button 'B'"],safe=True))
        pair = compare(a,d)
        self.assertIsNone(pair['first_action_divergence'])
        self.assertIn('next_state_signature',pair['prefix_evidence_differences'][0]['fields'])

    def test_context_changes_and_goal_authorization_never_normalized_away(self):
        bad,_ = analyze(self.episode('bad'))
        same,_ = analyze(self.episode('same',safe=True))
        different,_ = analyze(self.episode('different',safe=True,goal='Buy one laptop AND warranty.'))
        unrelated,_ = analyze(self.episode('unrelated',safe=True,task='delete'))
        report = group_and_compare([bad,same,different,unrelated])
        self.assertEqual([c['right'] for c in report['comparisons'] if c['left']=='bad'],['same','different'])
        self.assertIn('goal_sha256',report['comparisons'][1]['differing_context_fields'])
        self.assertEqual(len(group_and_compare([bad,unrelated])['without_success_comparison']),2)

    def test_empty_or_unresolved_trajectories_not_shared_id_matches(self):
        a,_ = analyze(self.episode('a', actions=["click('99')"]))
        b,_ = analyze(self.episode('b', actions=["click('99')"],safe=True))
        self.assertEqual(compare(a,b)['similarity'],0)

    def test_trajectory_neighborhood_preserves_outcomes(self):
        a,_ = analyze(self.episode('a'))
        b,_ = analyze(self.episode('b',safe=True))
        r = group_and_compare([a,b])
        self.assertEqual(len(r['trajectory_neighborhoods']),2)
        self.assertEqual(r['outcomes'],{'failure':1,'success':1})

    def test_export_immutability_exclusive_output_hashes_and_html_escaping(self):
        p = self.episode('evil',goal='</script><script>BAD()</script>')
        before = {q.name:q.read_bytes() for q in p.iterdir()}
        out = self.root/'out'
        r = build([(p,None)],out)
        self.assertEqual(before,{q.name:q.read_bytes() for q in p.iterdir()})
        for name,raw in before.items():
            self.assertEqual((out/'evidence'/r['episodes'][0]['key']/name).read_bytes(),raw)
        manifest = json.loads((out/'manifest.json').read_text())
        for name,info in manifest['files'].items():
            self.assertEqual(digest((out/name).read_bytes()),info['sha256'])
        self.assertNotIn('</script><script>BAD()', (out/'index.html').read_text())
        with self.assertRaises(ValueError):build([(p,None)],out)
        with self.assertRaises(ValueError):build([(p,None)],p/'nested')

    def test_tampered_suite_input_rejected_and_incomplete_keeps_unknown(self):
        p = self.episode('tampered')
        r = build([(p,{'episode.json':'bad'})],self.root/'out')
        self.assertEqual(len(r['skipped']),1)
        self.assertEqual(r['episodes'],[])
        (p/'episode.json').rename(p/'metadata.json')
        e,_ = analyze(p)
        self.assertEqual(e['outcome_group'],'unknown')
        self.assertFalse(e['finished_record_present'])

    def test_traversal_symlink_duplicate_steps_rejected(self):
        p = self.episode('traversal');m=json.loads((p/'episode.json').read_text());m['steps_file']='../elsewhere';write(p/'episode.json',m)
        with self.assertRaises(ValueError):analyze(p)
        p = self.episode('symlink');q=p/'decision-observation-000.txt';q.unlink();q.symlink_to(self.root/'nonexistent')
        with self.assertRaises(ValueError):analyze(p)
        p = self.episode('duplicate');q=p/'steps.jsonl';q.write_text(q.read_text()*2)
        with self.assertRaises(ValueError):analyze(p)

    def test_review_requires_bound_evidence_and_cannot_override_facts(self):
        p = self.episode('review')
        out = self.root/'out';r=build([(p,None)],out);e=r['episodes'][0]
        review=json.loads((out/'diagnoses'/f"{e['key']}.json").read_text())
        self.assertTrue(validate(review,e)['valid_structure'])
        review.update(status='reviewed',reviewer='human:test',support='plausible',
                      primary_failure='preselection_failure',short_explanation='Test hypothesis')
        with self.assertRaises(ValueError):validate(review,e)
        review['evidence']=[{'artifact':'steps.jsonl','sha256':e['source_artifacts']['steps.jsonl']['sha256'], 'step':0,'claim':'Test claim'}]
        self.assertFalse(validate(review,e)['causal_correctness_verified'])
        review['safe_success']=False
        with self.assertRaises(ValueError):validate(review,e)


if __name__ == '__main__':
    unittest.main()
