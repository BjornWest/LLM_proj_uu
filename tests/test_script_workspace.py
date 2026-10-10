"""Saved-source edits, schema parity, execution bindings and checkpoint inheritance."""
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from intent_browser.backend import Completion
from intent_browser.data_tools import DataConfig, DataSession, DockerPython
from intent_browser.harness import with_data_tools
from intent_browser.script_workspace import ScriptWorkspace
from intent_browser.standard_profile import standard_profile
from tests.test_data_tools import explorer


def parse(tools, name, args):
    return tools.parse_batch(Completion('', {'choices':[{'finish_reason':'tool_calls','message':{
        'role':'assistant','content':None,'tool_calls':[{'type':'function','id':'test-call',
        'function':{'name':name,'arguments':json.dumps(args)}}]}}]}))[0][0]


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.workspace = ScriptWorkspace(self.tmp.name)

    def create(self, text='x = 1\nprint(x)\n'):
        return self.workspace.execute('create','analysis.py',content=text)

    def test_create_view_exact_edit_and_retained_versions(self):
        first = self.create()
        viewed = self.workspace.execute('view','analysis.py',start_line=2,limit=1)
        self.assertEqual(viewed['content'],'2: print(x)')
        second = self.workspace.execute('edit','analysis.py',expected_revision=viewed['revision'],
            old_string='x = 1',new_string='x = 2')
        self.assertEqual(self.workspace.read('analysis.py',second['revision'])[0],'x = 2\nprint(x)\n')
        self.assertEqual((Path(self.tmp.name)/first['path']).read_text(),'x = 1\nprint(x)\n')
        self.assertEqual(second['version'],2)

    def test_ambiguous_whitespace_and_stale_edits_have_no_effect(self):
        first = self.create('print(1)\nprint(1)\n')
        for args, error in [({'old_string':'print(1)','new_string':'print(2)'},'matches 2'),
                            ({'old_string':'print( 1)','new_string':'print(2)'},'not found'),
                            ({'old_string':'print(1)','new_string':'print(1)'},'differ')]:
            with self.subTest(args=args), self.assertRaisesRegex(ValueError,error):
                self.workspace.execute('edit','analysis.py',expected_revision=first['revision'],**args)
        second = self.workspace.execute('edit','analysis.py',expected_revision=first['revision'],
            old_string='print(1)',new_string='print(2)',replace_all=True)
        self.assertEqual(second['replacements'],2)
        with self.assertRaisesRegex(ValueError,'revision changed'):
            self.workspace.execute('edit','analysis.py',expected_revision=first['revision'],old_string='print(2)',new_string='')
        self.assertEqual(len(list(Path(self.tmp.name).glob('*.py'))),2)

    def test_filenames_create_conflicts_and_storage_limits(self):
        for path in ('../secret.py','/tmp/test.py','a/b.py','x.txt','a.py\n','-x.py'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.workspace.execute('create',path,content='print(1)')
        first=self.create()
        with self.assertRaisesRegex(ValueError,'already exists'):self.create('replacement')
        self.assertEqual(self.workspace.read('analysis.py')[1]['revision'],first['revision'])
        limited=ScriptWorkspace(self.tmp.name,max_bytes=3,total_bytes=5,max_files=1)
        created=limited.execute('create','tiny.py',content='é')
        with self.assertRaisesRegex(ValueError,'storage'):limited.execute('create','huge.py',content='éé')
        with self.assertRaisesRegex(ValueError,'count'):limited.execute('create','other.py',content='x')
        limited.execute('edit','tiny.py',expected_revision=created['revision'],old_string='é',new_string='abc')
        with self.assertRaisesRegex(ValueError,'storage'):
            limited.execute('edit','tiny.py',expected_revision=limited.files['tiny.py']['revision'],old_string='abc',new_string='x')

    def test_competing_artifact_and_tampering_rejected(self):
        (Path(self.tmp.name)/'script-analysis.py-v001.py').write_text('competitor')
        with self.assertRaises(FileExistsError):self.create()
        self.assertFalse(self.workspace.files)
        self.assertEqual((Path(self.tmp.name)/'script-analysis.py-v001.py').read_text(),'competitor')
        (Path(self.tmp.name)/'script-analysis.py-v001.py').unlink()
        first=self.create();(Path(self.tmp.name)/first['path']).write_text('modified')
        with self.assertRaisesRegex(ValueError,'artifact changed'):self.workspace.read('analysis.py')

    def test_line_pagination_empty_files_and_deletion(self):
        first=self.create('one\ntwo\nthree\n')
        self.assertEqual(self.workspace.execute('view','analysis.py',limit=2)['next_line'],3)
        self.workspace.execute('edit','analysis.py',expected_revision=first['revision'],old_string='one\ntwo\nthree\n',new_string='')
        view=self.workspace.execute('view','analysis.py')
        self.assertEqual(view['line_count'],0);self.assertEqual(view['content'],'');self.assertIsNone(view['next_line'])


class IntegrationTests(unittest.TestCase):
    def session(self, root, **kwargs):
        return DataSession(DataConfig(script_workspace=True,**kwargs),root,explorer())

    def test_native_commands_are_exclusive_and_old_profile_unchanged(self):
        current=standard_profile();old=with_data_tools(standard_profile(data_tools=False),DataConfig())
        definitions={d['function']['name']:d['function'] for d in current.tools.definitions()}
        self.assertIn('script_file',definitions);self.assertIn('script_file',current.describe()['tools'])
        old_defs={d['function']['name']:d['function'] for d in old.tools.definitions()}
        self.assertNotIn('script_file',old_defs)
        self.assertEqual(old_defs['run_python']['parameters']['required'],['code'])
        self.assertNotIn('file_path',old_defs['run_python']['parameters']['properties'])
        for name,args in [('script_file',{'command':'create','file_path':'a.py','content':''}),
                          ('script_file',{'command':'view','file_path':'a.py'}),
                          ('script_file',{'command':'edit','file_path':'a.py','expected_revision':'v1:x','old_string':'x','new_string':''}),
                          ('run_python',{'file_path':'a.py','expected_revision':'v1:x'}),
                          ('run_python',{'code':'print(1)'})]:
            self.assertEqual(parse(current.tools,name,args).name,name)
        for name,args in [('script_file',{'command':'create','file_path':'a.py','content':'','old_string':'x'}),
                          ('script_file',{'command':'edit','file_path':'a.py','old_string':'x','new_string':'y'}),
                          ('script_file',{'command':'view','file_path':'../../a.py'}),
                          ('run_python',{'file_path':'a.py'}),
                          ('run_python',{'code':'print(1)','file_path':'a.py','expected_revision':'v1:x'}),
                          ('run_python',{'code':'print(1)','expected_revision':'v1:x'})]:
            with self.subTest(args=args),self.assertRaises(Exception):parse(current.tools,name,args)
        self.assertEqual(replace(current.tools,allow_spawn=False).definitions(),
            [d for d in current.tools.definitions() if d['function']['name']!='spawn_agent'])

    def test_datasets_and_saved_script_execution_then_debug_edit(self):
        with tempfile.TemporaryDirectory() as root:
            session=self.session(root);x=session.explorer
            for i in range(2):session.execute('extract_page',{'ref':x.ref(0),'format':'table'},i)
            created,_=session.execute('script_file',{'command':'create','file_path':'analysis.py',
                'content':'print(len(datasets))'},2,no_browser=True)
            with patch.object(session.executor,'run',return_value={'execution':'completed','stdout':'2','error':None}) as run:
                result,_=session.execute('run_python',{'file_path':'analysis.py','expected_revision':created['revision'],
                    'datasets':['data1','data2']},3,no_browser=True)
                self.assertEqual(run.call_args.args[0],'print(len(datasets))')
                self.assertEqual(set(run.call_args.args[1]),{'data1','data2'})
                self.assertEqual(result['saved_script']['sha256'],created['sha256'])
                self.assertEqual((Path(root)/result['script']).read_text(),'print(len(datasets))')
            edited,_=session.execute('script_file',{'command':'edit','file_path':'analysis.py','expected_revision':created['revision'],
                'old_string':'len(datasets)','new_string':'list(datasets)'},4)
            with patch.object(session.executor,'run') as run:
                result,_=session.execute('run_python',{'file_path':'analysis.py','expected_revision':created['revision']},5)
                self.assertIn('revision changed',result['error']);run.assert_not_called()
            self.assertNotEqual(edited['revision'],created['revision'])

    def test_disabled_workspace_and_changed_files_never_execute(self):
        with tempfile.TemporaryDirectory() as root:
            old=DataSession(DataConfig(),root,explorer())
            result,_=old.execute('script_file',{'command':'create','file_path':'a.py','content':'print(1)'},0)
            self.assertEqual(result['execution'],'failed')
            session=self.session(root)
            created,_=session.execute('script_file',{'command':'create','file_path':'a.py','content':'print(1)'},1)
            (Path(root)/created['path']).write_text('print(2)')
            with patch.object(session.executor,'run') as run:
                result,_=session.execute('run_python',{'file_path':'a.py','expected_revision':created['revision']},2)
                self.assertIn('artifact changed',result['error']);run.assert_not_called()

    def test_checkpoint_inherits_source_and_datasets_without_changing_parent(self):
        with tempfile.TemporaryDirectory() as parent_root,tempfile.TemporaryDirectory() as child_root:
            parent=self.session(parent_root);x=parent.explorer
            parent.execute('extract_page',{'ref':x.ref(0),'format':'table'},0)
            first,_=parent.execute('script_file',{'command':'create','file_path':'a.py','content':'print(1)'},1)
            state=parent.checkpoint_state()
            import shutil
            shutil.copytree(parent_root,Path(child_root)/'inherited')
            child=self.session(child_root);child.restore_state(state)
            second,_=child.execute('script_file',{'command':'edit','file_path':'a.py','expected_revision':first['revision'],
                'old_string':'print(1)','new_string':'print(2)'},2)
            self.assertEqual(parent.scripts.read('a.py')[0],'print(1)')
            self.assertEqual(child.scripts.read('a.py')[0],'print(2)')
            self.assertEqual(second['version'],2)
            with patch.object(child.executor,'run',return_value={'stdout':'2'}) as run:
                child.execute('run_python',{'file_path':'a.py','expected_revision':second['revision'],'datasets':['data1']},3)
                self.assertEqual(run.call_args.args[1]['data1']['rows'][0][1],'$40.32')
            # Historical dataset-only checkpoints remain readable.
            child.restore_state({'datasets':state['datasets'],'bytes':state['bytes']})

    def test_feedback_view_is_bounded_and_never_claims_full_delivery(self):
        with tempfile.TemporaryDirectory() as root:
            session=self.session(root,feedback_tokens=500)
            content='print("long line repeated many times")\n'*100
            created,_=session.execute('script_file',{'command':'create','file_path':'a.py','content':content},0)
            viewed,artifact=session.execute('script_file',{'command':'view','file_path':'a.py','limit':100},1)
            self.assertTrue(viewed['feedback_truncated']);self.assertIsNone(viewed['next_line'])
            self.assertIn('smaller limit',viewed['view_note'])
            self.assertLessEqual(session.explorer.tokens(json.dumps(viewed,ensure_ascii=False)),500)
            raw=json.loads((Path(root)/artifact).read_text())
            self.assertIn('100: print(',raw['content'])
            self.assertEqual(session.scripts.read('a.py')[0],content)


if __name__=='__main__':unittest.main()
