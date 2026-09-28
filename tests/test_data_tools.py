import json
from pathlib import Path
import tempfile
import unittest
from dataclasses import replace
from unittest.mock import patch
from intent_browser.data_tools import DataConfig, DataSession, extract
from intent_browser.ax_context import AXContext
from intent_browser.ax_explorer import AXConfig
from intent_browser.standard_profile import standard_profile, tokenizer_path
from intent_browser.backend import Completion


def explorer():
    raw=[]
    def add(role,name='',children=None,**extra):
        ident=str(len(raw));n={'nodeId':ident,'role':{'value':role},'name':{'value':name},'childIds':[],**extra};raw.append(n)
        for child in children or []: n['childIds'].append(add(*child))
        return ident
    add('table','Orders',[
        ('row','',[('columnheader','Status'),('columnheader','Total'),('columnheader','Total')]),
        ('row','',[('cell','Complete'),('cell','$40.32'),('cell','')]),
        ('row','',[('cell','Complete'),('cell','$12.99'),('cell','N/A')]),
        ('row','',[('cell','Pending'),('cell','$9,999.00'),('cell','N/A')])])
    raw.append({'nodeId':'hidden','ignored':True,'role':{'value':'none'},'name':{'value':'HIDDEN_SENTINEL'}})
    x=AXContext(AXConfig(tokenizer_path(),incremental=True))
    x.capture({'url':'http://fixture/','axtree_object':{'nodes':raw}})
    return x


class DataTests(unittest.TestCase):
    def test_table_preserves_strings_duplicate_headers_empty_values_and_source(self):
        x=explorer();d=extract(x,x.ref(0),'table')
        self.assertEqual(d['columns'],['Status','Total','Total'])
        self.assertEqual(d['rows'],[['Complete','$40.32',''],['Complete','$12.99','N/A'],['Pending','$9,999.00','N/A']])
        self.assertNotIn('HIDDEN_SENTINEL',json.dumps(d))
        self.assertTrue(all(isinstance(v,str) for row in d['rows'] for v in row))
        self.assertNotIn('metadata',d['nodes'][0])
        self.assertIn('metadata',extract(x,x.ref(0),'tree',True)['nodes'][0])

    def test_invalid_and_stale_refs_and_non_tables_fail_explicitly(self):
        x=explorer()
        with self.assertRaises(ValueError):extract(x,'unknown','table')
        with self.assertRaisesRegex(ValueError,'not an accessible table'):extract(x,x.ref(2),'table')
        with self.assertRaises(ValueError):extract(x,x.ref(0),'csv')

    def test_text_retains_node_boundaries_and_tree_all_fields(self):
        x=explorer();d=extract(x,x.ref(0),'text')
        lines=[json.loads(s) for s in d['text'].splitlines()]
        self.assertEqual(len(lines),len(d['nodes']))
        self.assertIn('$9,999.00',[n['name'] for n in lines])
        self.assertEqual(len({n['ref'] for n in d['nodes']}),len(d['nodes']))

    def test_immutable_dataset_hashes_bounded_feedback_and_no_browser_errors(self):
        x=explorer()
        with tempfile.TemporaryDirectory() as tmp:
            session=DataSession(DataConfig(),tmp,x)
            result,_=session.execute('extract_page',{'ref':x.ref(0),'format':'table'},0,{'text':'decision-observation-000.txt'})
            self.assertEqual(result['row_count'],3)
            with patch.object(session.executor,'run',return_value={'stdout':'53.31\n','stderr':'','error':None}) as run:
                result,_=session.execute('run_python',{'code':'print(1)','datasets':['data1']},1)
                self.assertEqual(run.call_args.args[1]['data1']['rows'][0][1],'$40.32')
                self.assertIsNone(result['error'])
            (Path(tmp)/'dataset-data1.json').write_text('{}')
            with patch.object(session.executor,'run') as run:
                result,_=session.execute('run_python',{'code':'print(1)','datasets':['data1']},2)
                self.assertIn('changed',result['error']);run.assert_not_called()
            result,_=session.execute('extract_page',{'ref':x.ref(0),'format':'table'},3,no_browser=True)
            self.assertIn('No browser',result['error'])
            clipped=session.bounded_feedback({'stdout':'large '*10000,'stderr':'error '*10000,'artifact':'saved.json'})
            self.assertLessEqual(x.tokens(json.dumps(clipped,ensure_ascii=False)),session.config.feedback_tokens)
            self.assertTrue(clipped['feedback_truncated'])

    def test_oversized_extraction_has_no_partial_dataset(self):
        with tempfile.TemporaryDirectory() as tmp:
            x=explorer();session=DataSession(DataConfig(dataset_bytes=100),tmp,x)
            result,_=session.execute('extract_page',{'ref':x.ref(0),'format':'table'},0)
            self.assertIn('limit',result['error']);self.assertFalse(session.datasets)
            self.assertFalse(list(Path(tmp).glob('dataset-*')))

    def test_native_schema_ablation_and_helper_registry(self):
        p=standard_profile();names=[d['function']['name'] for d in p.tools.definitions()]
        self.assertIn('extract_page',names);self.assertIn('run_python',names)
        old=standard_profile(data_tools=False)
        self.assertNotIn('run_python',[d['function']['name'] for d in old.tools.definitions()])
        self.assertEqual(replace(p.tools,allow_spawn=False).definitions(),[d for d in p.tools.definitions() if d['function']['name']!='spawn_agent'])
        def response(args):
            return Completion('',{'choices':[{'finish_reason':'tool_calls','message':{'role':'assistant','content':None,
                'tool_calls':[{'type':'function','id':'x','function':{'name':'run_python','arguments':json.dumps(args)}}]}}]})
        calls,_=p.tools.parse_batch(response({'code':'print("hello")','datasets':[]}))
        self.assertEqual(calls[0].name,'run_python')
        with self.assertRaises(Exception):p.tools.parse_batch(response({'code':'print(1)','datasets':['../../metadata.json']}))


if __name__=='__main__':unittest.main()
