"""Offline query boundaries; synthetic fixtures are not model evidence."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT=Path(__file__).with_name('query_traces.py')
ROOT=SCRIPT.resolve().parents[4]
sys.path.insert(0,str(ROOT))
from data.curation.trace_triage import test_triage as fixtures
from data.curation.trace_triage.run import build


class QueryTests(unittest.TestCase):
    setUp=fixtures.TriageTests.setUp
    episode=fixtures.TriageTests.episode

    def cohort(self):
        a=self.episode('failed',actions=["click('1')","click('1')"],bodies=["[1] button 'Buy'"]*2)
        b=self.episode('passed',safe=True)
        c=self.episode('unknown',safe=None,task='different')
        self.out=self.root/'report';self.report=build([(p,None) for p in (a,b,c)],self.out)

    def query(self,*args,ok=True):
        result=subprocess.run([sys.executable,str(SCRIPT),*args,'--triage',str(self.out/'triage.json')],text=True,capture_output=True)
        if ok:
            self.assertEqual(result.returncode,0,result.stderr);return json.loads(result.stdout)
        self.assertNotEqual(result.returncode,0);return result

    def test_filter_pagination_and_unknown_usage(self):
        self.cohort()
        self.assertEqual(self.query('list','--outcome','failure','--flag','repeated_action')['matched'],1)
        self.assertEqual(self.query('list','--min-tokens','0')['matched'],0)
        page=self.query('list','--limit','1','--offset','1')
        self.assertEqual((page['matched'],page['returned'],page['omitted']),(3,1,2))
        self.assertEqual(self.query('summary')['outcomes'],{'failure':1,'success':1,'unknown':1})

    def test_groups_members_and_missing_group_rejection(self):
        self.cohort();groups=self.query('groups','--kind','trajectory')['items']
        group=groups[0]
        members=self.query('list','--group-kind','trajectory','--group-key',group['key'])
        self.assertEqual(members['matched'],group['count'])
        self.query('list','--group-kind','trajectory','--group-key','missing',ok=False)

    def test_comparison_no_self_or_cross_task_and_correct_divergence(self):
        self.cohort()
        neighbors=self.query('neighbors','--episode','failed','--outcome','success')
        self.assertEqual([x['right'] for x in neighbors['items']],['passed'])
        pair=self.query('compare','--left','failed','--right','passed')['pair']
        self.assertEqual(pair['common_action_prefix'],1)
        self.assertEqual(pair['first_action_divergence']['left_steps'],[1])
        self.assertEqual(pair['outcomes'],['failure','success'])
        self.query('compare','--left','passed','--right','passed',ok=False)
        self.query('compare','--left','failed','--right','unknown',ok=False)

    def test_queries_preserve_export_and_keep_coverage_counts(self):
        self.cohort();before={str(p):p.read_bytes() for p in self.out.rglob('*') if p.is_file()}
        self.query('summary');self.query('groups');self.query('list','--queue','sampled')
        self.assertEqual(before,{str(p):p.read_bytes() for p in self.out.rglob('*') if p.is_file()})
        self.query('list','--limit','101',ok=False)


if __name__=='__main__':unittest.main()
