"""Concurrency amendments preserve immutable finite-cohort retry identity."""
import importlib.util,json,tempfile,unittest,sqlite3
from pathlib import Path
from copy import deepcopy
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('amendment_caller',ROOT/'scripts/comparison_suite.py');caller=importlib.util.module_from_spec(spec);spec.loader.exec_module(caller)

class ConcurrencyAmendmentTests(unittest.TestCase):
    def test_pinned_chain_changes_only_cap_without_replacing_history_authorization(self):
        with tempfile.TemporaryDirectory()as temp:
            root=Path(temp)
            def write(name,value):
                p=root/name;p.write_text(json.dumps(value));return caller.pin(p)
            original={'id':'cohort','case_ids':['A','B','C','D'],'max_active_combined':1,'max_input_tokens':150000,'prewarm_count':1,'policy_model':'exact'}
            auth=write('authorization.json',original)
            first={'id':'cap2','schema':'hosted-qwen-finite-authorization-amendment-v1','base_authorization':auth,'previous_amendment':None,'changes':{'max_active_combined':2}}
            one=write('first.json',first);two=write('second.json',{**first,'id':'cap4','previous_amendment':one,'changes':{'max_active_combined':4}})
            s={'authorization':auth,'authorization_amendments':[one,two]}
            effective=caller.hosted_authorization(s)
            self.assertEqual(effective,{**original,'max_active_combined':4})
            self.assertEqual(caller.load(auth['path']),original)
            self.assertEqual(s['authorization'],auth)
            with self.assertRaises(ValueError):caller.hosted_authorization({**s,'authorization_amendments':[two,one]})
            with self.assertRaises(ValueError):caller.hosted_authorization({**s,'authorization_amendments':[one,one]})
            changed=write('bad.json',{**first,'base_authorization':two})
            with self.assertRaises(ValueError):caller.hosted_authorization({**s,'authorization_amendments':[changed]})
            Path(one['path']).write_text('{}')
            with self.assertRaises(ValueError):caller.hosted_authorization(s)

    def test_no_amendment_preserves_defaults_and_invalid_changes_fail_closed(self):
        with tempfile.TemporaryDirectory()as temp:
            root=Path(temp);auth=root/'auth';auth.write_text(json.dumps({'case_ids':['A']*34,'max_active_combined':4}))
            s={'authorization':caller.pin(auth)};self.assertEqual(caller.hosted_authorization(s)['max_active_combined'],4)
            for changes in ({'max_active_combined':True},{'max_active_combined':0},{'max_active_combined':35},{'max_active_combined':10,'max_input_tokens':250000},{}):
                p=root/'bad';p.write_text(json.dumps({'id':'change','schema':'hosted-qwen-finite-authorization-amendment-v1','base_authorization':s['authorization'],'previous_amendment':None,'changes':changes}))
                with self.subTest(changes=changes),self.assertRaises(ValueError):caller.hosted_authorization({**s,'authorization_amendments':[caller.pin(p)]})

    def test_pool_uses_first_pending_root_and_resource_limits_are_finite(self):
        cases=[{'id':'old','root':'old-pool'},{'id':'pending','root':'corrected-pool'}]
        self.assertEqual(caller.pool_source_case({'cases':cases,'start_order':['pending']})['root'],'corrected-pool')
        with self.assertRaises(ValueError):caller.pool_source_case({'cases':cases,'start_order':[]})
        with self.assertRaises(ValueError):caller.pool_source_case({'cases':cases+cases,'start_order':['pending']})
        self.assertEqual(caller.pool_resource_options({}),(3072,512))
        self.assertEqual(caller.pool_resource_options({'pool_memory_mib':6144,'pool_tasks':512}),(6144,512))
        for key,value in [('pool_memory_mib',True),('pool_memory_mib',8193),('pool_tasks',None),('pool_tasks',513)]:
            with self.subTest(key=key),self.assertRaises(ValueError):caller.pool_resource_options({key:value})

    def test_amendment_keeps_measured_native_failure_in_discovered_history(self):
        with tempfile.TemporaryDirectory()as temp:
            root=Path(temp);out=root/'old';trace=out/'qwen-one/live/runs/trace';trace.mkdir(parents=True)
            def write(path,value):
                path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value));return caller.pin(path)
            cases=[{'id':'qwen-one','task_id':'one'},{'id':'qwen-two','task_id':'two'}]
            auth=write(root/'auth',{'case_ids':[c['id']for c in cases],'max_active_combined':1})
            amendment=write(root/'amendment',{'id':'cap2','schema':'hosted-qwen-finite-authorization-amendment-v1','base_authorization':auth,'previous_amendment':None,'changes':{'max_active_combined':2}})
            driver=write(root/'driver',{})
            prior={'runtime_mode':'qwen-openrouter-v1','authorization':auth,'cases':cases,'driver':driver,'caller_commit':'prior','start_order':[c['id']for c in cases],'suite_id':'prior','output':str(out),'completion_db':str(out/'completion.sqlite')}
            with sqlite3.connect(out/'completion.sqlite')as db:
                db.execute('CREATE TABLE suites(id TEXT,episodes TEXT)');db.execute('INSERT INTO suites VALUES(?,?)',('prior',json.dumps(prior['start_order'])))
                db.execute('CREATE TABLE episodes(suite TEXT,id TEXT,state TEXT)');db.executemany('INSERT INTO episodes VALUES(?,?,?)',[('prior','qwen-one','failed'),('prior','qwen-two','not_started')])
            canonical=write(trace/'evaluation.json',{'task_completed':False,'technical_error':None});automatic=write(trace/'automatic-grading.json',{'status':'graded'})
            result=write(out/'qwen-one/result.json',{'case':'qwen-one','scripted':False,'status':'graded_and_projected','caller_driver':driver,'caller_commit':'prior','case_binding_sha256':caller.case_binding(cases[0]),'execution_binding_sha256':caller.execution_binding(prior,cases[0]),'result':{'trace':str(trace),'viewer_projection':{'task_completed':False}}})
            viewer=write(out/'qwen-one/grade-viewer.json',{'status':'verified','task_completed':False,'canonical':canonical,'automatic':automatic})
            specpin=write(root/'launch-spec-approved-v1.json',prior);write(out/'supervisor-start.json',{})
            terminal=write(out/'terminal-artifacts.json',{'suite_id':'prior','source_driver':driver,'rejected_symlinks':[],'files':[{'relative_path':str(path.relative_to(out)),'sha256':caller.pin(path)['sha256']}for path in out.rglob('*')if path.is_file()]})
            spec={**prior,'suite_id':'new','output':str(root/'new'),'start_order':['qwen-two'],'authorization_amendments':[amendment],'resume':[{'spec':specpin,'result':result,'viewer':viewer}],'resume_attempts':[{'spec':specpin,'completion_db':caller.pin(out/'completion.sqlite'),'terminal_inventory':terminal}]}
            effective=caller.hosted_authorization(spec)
            self.assertEqual(effective['max_active_combined'],2)
            self.assertEqual(caller.hosted_attempt_ids(spec,effective),['qwen-two'])
            with self.assertRaisesRegex(ValueError,'Every prior measured'):
                caller.hosted_attempt_ids({**spec,'resume':[],'start_order':['qwen-one','qwen-two']},effective)

    def test_pending_pool_compatibility_rejects_mixed_clients_but_ignores_retained(self):
        with tempfile.TemporaryDirectory()as tmp:
            base=Path(tmp);cases=[]
            names=['intent_browser/chromium_pool.py','intent_browser/assets/chromium_pool.cjs','intent_browser/shared_browsergym.py','intent_browser/browser_shutdown.py','intent_browser/runner.py']
            for ident in ('old','first','second'):
                root=base/ident;hashes={}
                for name in names:
                    p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(ident if ident=='old'else 'matching');hashes[name]=caller.pin(p)['sha256']
                manifest=root/'manifest.json';manifest.write_text(json.dumps({'source_sha256':hashes}))
                cases.append({'id':ident,'root':str(root),'recipe_manifest':caller.pin(manifest)})
            spec={'runtime_mode':'qwen-openrouter-v1','cases':cases,'start_order':['first','second']}
            self.assertEqual(len(caller.check_pool_source_pins(spec)),5)
            p=base/'second/intent_browser/browser_shutdown.py';p.write_text('other client');manifest=base/'second/manifest.json';v=caller.load(manifest);v['source_sha256']['intent_browser/browser_shutdown.py']=caller.pin(p)['sha256'];manifest.write_text(json.dumps(v));cases[-1]['recipe_manifest']=caller.pin(manifest)
            with self.assertRaisesRegex(ValueError,'disagree'):caller.check_pool_source_pins(spec)
            # A declaration which conceals actual source drift also fails.
            v['source_sha256']['intent_browser/browser_shutdown.py']=caller.pin(base/'first/intent_browser/browser_shutdown.py')['sha256'];manifest.write_text(json.dumps(v));cases[-1]['recipe_manifest']=caller.pin(manifest)
            with self.assertRaisesRegex(ValueError,'Pinned input changed'):caller.check_pool_source_pins(spec)
