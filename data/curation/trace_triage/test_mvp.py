"""Boundary tests for native intake, usage coverage, and success integrity."""
import json
from pathlib import Path
import unittest

from . import test_triage as fixtures
from .test_triage import write
from .core import analyze, digest, group_and_compare
from .metrics import request_metrics, aggregate, metric_flags, thresholds
from .intake import suite_inputs, review_queue
from .run import build
from .review import validate


class MVPTests(unittest.TestCase):
    setUp = fixtures.TriageTests.setUp
    episode = fixtures.TriageTests.episode

    def metric(self, i=0, **usage):
        return request_metrics({'step':i,'model_request':{'model':'test'},
                                'model_response':{'model':'test-resolved','provider':'P','usage':usage}})

    def test_usage_subsets_partial_and_zero(self):
        a=self.metric(prompt_tokens=1000,completion_tokens=100,
                      prompt_tokens_details={'cached_tokens':800},
                      completion_tokens_details={'reasoning_tokens':70}, cost=.01)
        b=self.metric(1,prompt_tokens=100,completion_tokens=0,cost=0)
        c=self.metric(2)
        m=aggregate([a,b,c]);t=m['totals']
        self.assertEqual(t['total_tokens']['known_sum'],1200)
        self.assertEqual(t['reasoning_tokens']['known_sum'],70)
        self.assertEqual(t['uncached_tokens']['known_sum'],200)
        self.assertEqual(t['cost_usd']['known_sum'],'0.01')
        self.assertEqual(t['total_tokens']['missing_requests'],1)
        self.assertFalse(t['total_tokens']['complete'])
        self.assertEqual(m['cache_fraction_known_pairs'],.8)
        self.assertEqual(m['cache_paired_requests'],1)

    def test_missing_or_invalid_counters_do_not_become_cache_misses(self):
        rows=[self.metric(prompt_tokens=1000,prompt_tokens_details={'cached_tokens':2000}),
              self.metric(1,prompt_tokens=True,completion_tokens=-1),self.metric(2)]
        m=aggregate(rows)
        self.assertIsNone(m['cache_fraction_known_pairs'])
        self.assertEqual(m['longest_reported_zero_cache_streak'],0)
        flags=metric_flags(rows,m,thresholds())
        self.assertEqual([f[0] for f in flags],['usage_counter_inconsistent'])

    def test_configured_flags_and_unknown_breaks_streak(self):
        rows=[self.metric(i,prompt_tokens=1000,completion_tokens=400,
                         prompt_tokens_details={'cached_tokens':0},
                         completion_tokens_details={'reasoning_tokens':300}) for i in range(3)]
        cfg=thresholds({'high_episode_tokens':4000,'large_request_tokens':1000,'long_reasoning_tokens':300})
        codes={f[0] for f in metric_flags(rows,aggregate(rows),cfg)}
        self.assertTrue({'reported_zero_cache_streak','low_reported_cache_fraction','large_request_context','long_reasoning_output','high_episode_token_use'}<=codes)
        self.assertEqual(aggregate([rows[0],self.metric(1),rows[2]])['longest_reported_zero_cache_streak'],1)
        with self.assertRaises(ValueError):thresholds({'cache_min_requests':False})

    def test_native_goal_action_and_actual_provider(self):
        p=self.episode('native',actions=["click(bid='1')"],source=None)
        rows=[json.loads(x) for x in (p/'steps.jsonl').read_text().splitlines()]
        text=(p/'decision-observation-000.txt').read_text()
        rows[0]['model_request']={'messages':[{'role':'user','content':'USER GOAL: Inspect the catalog.'},{'role':'tool','content':text}]}
        rows[0]['model_response']['provider']='P'
        rows[0]['assistant_tool_message']={'tool_calls':[{'id':'call1','function':{'name':'click','arguments':'{"bid":"1"}'}}]}
        (p/'steps.jsonl').write_text(json.dumps(rows[0])+'\n')
        e,_=analyze(p)
        self.assertEqual(e['goal'],'Inspect the catalog.')
        self.assertEqual(e['timeline'][0]['action']['target']['name'],'Buy')
        self.assertEqual(e['resolved_providers'],['P'])
        self.assertEqual(e['timeline'][0]['native_tool_calls'][0]['id'],'call1')

    def test_suite_intake_both_formats_and_unfinished(self):
        p=self.episode('old');q=self.episode('new');suite=self.root/'suite';(suite/'cases').mkdir(parents=True)
        write(suite/'cases/a.json',{'status':'completed','episode':str(p),'artifact_sha256':{'x':'y'}})
        write(suite/'cases/b.json',{'status':'finished','trace':str(q),'artifacts_sha256':{'z':'w'}})
        write(suite/'cases/c.json',{'status':'started','trace':'never read'})
        inputs,notes=suite_inputs(suite,self.root)
        self.assertEqual(inputs,[(p,{'x':'y'}),(q,{'z':'w'})])
        self.assertEqual(notes[-1]['disposition'],'not imported; unfinished case')

    def test_empty_suite_inventory_does_not_bypass_checks(self):
        p=self.episode('bad-inventory');r=build([(p,{})],self.root/'out')
        self.assertEqual(len(r['episodes']),0)
        self.assertIn('hash mismatch',r['skipped'][0]['error'])

    def test_success_compares_to_other_success_and_control_sample(self):
        a,_=analyze(self.episode('good-a',safe=True));b,_=analyze(self.episode('good-b',safe=True))
        pairs=group_and_compare([a,b])['comparisons']
        self.assertEqual({(p['left'],p['right']) for p in pairs},{('good-a','good-b'),('good-b','good-a')})
        q=review_queue([a,b]);self.assertEqual(q['sampled_success_count'],1)
        self.assertEqual(q,review_queue([b,a]))
        self.assertIn('sampled_apparent_success',q['items'][0]['reasons'])

    def test_unknown_safe_completion_never_promoted(self):
        p=self.episode('completion',safe=None)
        ev=json.loads((p/'evaluation.json').read_text());ev['task_completed']=True
        meta=json.loads((p/'episode.json').read_text());meta['evaluation']=ev
        write(p/'episode.json',meta);write(p/'evaluation.json',ev)
        e,_=analyze(p);self.assertTrue(e['apparent_success']);self.assertEqual(e['outcome_group'],'unknown')

    def test_supplemental_verdict_is_retained_not_substituted(self):
        p=self.episode('supplemental',safe=None)
        write(p/'native-evaluation.json',{'result':{'score':1}})
        e,_=analyze(p)
        self.assertEqual(e['outcome_group'],'unknown')
        self.assertIn('native-evaluation.json',e['source_artifacts'])

    def test_integrity_review_cannot_change_grade_or_assert_without_evidence(self):
        p=self.episode('review-success',safe=True);out=self.root/'out';r=build([(p,None)],out);e=r['episodes'][0]
        review=json.loads(next((out/'diagnoses').glob('*.json')).read_text())
        self.assertTrue(validate(review,e)['valid_structure'])
        review.update(status='reviewed',reviewer='test',support='supported',short_explanation='Scoped integrity test')
        review['integrity_review']={'status':'confirmed_issue','scope':'verifier check','findings':['Synthetic contradiction'],'evidence':[]}
        with self.assertRaises(ValueError):validate(review,e)
        review['integrity_review']['evidence']=[{'artifact':'evaluation.json','sha256':e['source_artifacts']['evaluation.json']['sha256'],'claim':'Test only'}]
        self.assertTrue(validate(review,e)['valid_structure'])
        review['safe_success']=False
        with self.assertRaises(ValueError):validate(review,e)
        self.assertTrue(json.loads((p/'evaluation.json').read_text())['safe_success'])


if __name__=='__main__':unittest.main()
