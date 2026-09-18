import copy
import json
from pathlib import Path
import tempfile
import unittest

from .annotations import validate_annotation
from .case_library import assemble, search, write_library
from .core import digest


class CaseLibraryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.episode={'episode_id':'a','source_artifacts':{'steps.jsonl':{'sha256':'abc'}},
                      'source':'demo','task':'buy','condition':'clean','goal_sha256':'goal',
                      'outcome_group':'failure','model':'model','source_path':'/traces/a',
                      'flags':[{'code':'repeated_action'}],
                      'timeline':[{'step':0,'action':{'signature':'click-buy','bid':None,'target':None}}]}
        other=copy.deepcopy(self.episode);other['episode_id']='b';other['source_path']='/traces/b'
        self.triage=self.root/'triage.json';self.triage.write_text(json.dumps({'format':'browser-triage-v1','episodes':[self.episode,other]}))
        self.review={'schema':'browser-failure-diagnosis-v1','taxonomy_version':'browser-failure-taxonomy-v1',
                     'episode_id':'a','source_evidence_sha256':digest(self.episode['source_artifacts']),
                     'recorded_outcomes_overridden':False,'status':'reviewed','reviewer':'test',
                     'primary_failure':'unknown_or_ambiguous','secondary_failures':[], 'support':'unresolved',
                     'short_explanation':'Repeated buy, cause unresolved.',
                     'summary':'Repeated buy; feedback causality not established.',
                     'classification_notes':'Repetition alone does not prove navigation misunderstanding.',
                     'evidence':[{'artifact':'steps.jsonl','sha256':'abc','step':0,'claim':'Buy repeated'}],
                     'contradicting_evidence':[], 'tags':['behavior:repeated-buy'],
                     'tag_evidence':{'behavior:repeated-buy':['steps.jsonl']},
                     'alternatives':[{'cause':'navigation_failure','support':'plausible','explanation':'Possibly missed next page.'}]}

    def library(self, review=None, name='review.json'):
        p=self.root/name;p.write_text(json.dumps(review or self.review))
        return assemble([self.triage],[p])

    def test_tags_search_and_hypotheses_separate_from_assigned_types(self):
        library=self.library()
        self.assertEqual(len(search(library,tags=['behavior:repeated-buy'])),1)
        self.assertEqual(search(library,category='navigation_failure'),[])
        result=search(library,category='navigation_failure',include_hypotheses=True)
        self.assertEqual(result[0]['category_match_role'],'hypothesis_only')
        self.assertEqual(library['taxonomy']['navigation_failure']['assigned_review_count'],0)
        self.assertEqual(library['taxonomy']['unknown_or_ambiguous']['assigned_review_count'],1)

    def test_nearest_other_episode_and_no_self_precedent(self):
        library=self.library()
        self.assertEqual(search(library,query_episode='a'),[])
        result=search(library,query_episode='b')
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]['match_reasons']['shared_flags'],['repeated_action'])
        with self.assertRaises(ValueError):search(library,query_episode='absent')

    def test_free_tags_still_require_namespaces_evidence_and_review(self):
        for field,value in [('tags',['cause:bad-reasoning']),('tags',['behavior:Repeated']),
                            ('tag_evidence',{}),('types',['navigation_failure']),('status','unreviewed')]:
            r=copy.deepcopy(self.review);r[field]=value
            with self.subTest(field=field,value=value),self.assertRaises(ValueError):validate_annotation(r,self.episode)
        r=copy.deepcopy(self.review);r['tag_evidence']['behavior:repeated-buy']=['invented.json']
        with self.assertRaises(ValueError):validate_annotation(r,self.episode)

    def test_old_untagged_reviews_compatible_but_blank_templates_ignored(self):
        r=copy.deepcopy(self.review);r.pop('tags');r.pop('tag_evidence')
        self.assertEqual(self.library(r)['cards'][0]['tags'],[])
        r.update(status='unreviewed',primary_failure=None,secondary_failures=[])
        library=self.library(r,name='blank.json')
        self.assertEqual(library['cards'],[]);self.assertEqual(len(library['ignored']),1)

    def test_wrong_snapshot_and_bad_evidence_rejected(self):
        r=copy.deepcopy(self.review);r['source_evidence_sha256']='wrong'
        with self.assertRaises(ValueError):self.library(r)
        r=copy.deepcopy(self.review);r['evidence'][0]['sha256']='wrong'
        with self.assertRaises(ValueError):self.library(r)

    def test_conflicting_reviews_preserved_and_duplicate_bytes_deduplicated(self):
        p=self.root/'one.json';p.write_text(json.dumps(self.review))
        r=copy.deepcopy(self.review);r.update(primary_failure='navigation_failure',support='plausible')
        q=self.root/'two.json';q.write_text(json.dumps(r))
        library=assemble([self.triage],[p,q,p])
        self.assertEqual(len(library['cards']),2)
        self.assertTrue(all(c['classification_disagreement'] for c in library['cards']))

    def test_export_immutable_and_html_escapes_review_text(self):
        r=copy.deepcopy(self.review);r['summary']='</script><script>BAD()</script>'
        library=self.library(r);dest=self.root/'library';write_library(library,dest)
        self.assertNotIn('</script><script>BAD()', (dest/'index.html').read_text())
        c=library['cards'][0]
        self.assertEqual((dest/'reviews'/f"{c['id']}.json").read_bytes(),Path(c['review_path']).read_bytes())
        with self.assertRaises(ValueError):write_library(library,dest)
        for name,h in json.loads((dest/'manifest.json').read_text())['files'].items():
            self.assertEqual(digest((dest/name).read_bytes()),h)

    def test_changed_review_during_export_rejected(self):
        library=self.library();Path(library['cards'][0]['review_path']).write_text('{}')
        with self.assertRaises(ValueError):write_library(library,self.root/'out')

    def test_annotation_author_retained_and_trace_directory_protected(self):
        r=copy.deepcopy(self.review);r['annotation_author']='second reviewer'
        library=self.library(r)
        self.assertEqual(library['cards'][0]['annotation_author'],'second reviewer')
        library['episodes'][0]['source_path']=str(self.root/'original')
        with self.assertRaises(ValueError):write_library(library,self.root/'original'/'catalog')


if __name__=='__main__':unittest.main()
