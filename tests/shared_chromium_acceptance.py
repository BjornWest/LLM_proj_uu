"""Explicit model-free shared-browser qualification, never a model suite launcher."""
import argparse
import json
import multiprocessing as mp
from pathlib import Path
import tempfile
import os
import signal
import subprocess
import sys
from unittest.mock import patch
import time
import unittest

from shared_chromium_controls import factory, worker, graded_worker
from intent_browser.chromium_pool import PoolClient, PoolError, PoolSupervisor


class Lifecycle(unittest.TestCase):
    def test_isolation_reset_popups_capture_chat_and_late_attachment(self):
        with tempfile.TemporaryDirectory()as tmp:
            supervisor=PoolSupervisor(Path(tmp)/'pool')
            with supervisor as client:
                a,b=client.episode('red'),client.episode('blue')
                first,second=a.wrap(factory('red'))(),b.wrap(factory('blue'))()
                try:
                    obs,_=first.reset(seed=1);second.reset(seed=2)
                    self.assertTrue(obs['axtree_object']['nodes'])
                    self.assertTrue(obs['dom_object']['documents'])
                    self.assertEqual(first.page.title(),'red');self.assertEqual(second.page.title(),'blue')
                    self.assertEqual(len(client.status()['groups']),2)
                    self.assertEqual(len(client.status()['leases']),4)
                    bid=first.page.locator('#buy').get_attribute('bid')
                    self.assertIsNotNone(bid)
                    action_obs,*_=first.step(f"click({bid!r})")
                    self.assertEqual(action_obs['last_action_error'],'')
                    self.assertEqual(first.page.evaluate("localStorage.getItem('basket')"),'red')
                    self.assertIsNone(second.page.evaluate("localStorage.getItem('basket')"))
                    self.assertEqual(second.context.cookies(),[])
                    ids={x['context_id']for x in a.metadata()['contexts']}
                    self.assertEqual(len(ids),2)
                    self.assertTrue(ids.isdisjoint({x['context_id']for x in b.metadata()['contexts']}))
                    with first.context.expect_page()as popup:
                        first.page.locator('#popup').click()
                    popup.value.wait_for_load_state();self.assertEqual(popup.value.title(),'red')
                    self.assertEqual(len(second.context.pages),1)
                    popup.value.close()
                    first._active_page_check()
                    first.page.once('dialog',lambda dialog:dialog.accept())
                    first.page.evaluate("alert('fixture')")
                    self.assertTrue(first.page.screenshot().startswith(b'\x89PNG'))
                    first.context.tracing.start(screenshots=True,snapshots=True)
                    first.page.locator('#buy').click()
                    first.context.tracing.stop(path=Path(tmp)/'trace.zip')
                    self.assertGreater((Path(tmp)/'trace.zip').stat().st_size,100)
                    first.chat.add_message('assistant','red-only')
                    first.chat.page.evaluate("send_user_message('hello human')")
                    self.assertTrue(any(x['message']=='hello human'for x in first.chat.messages))
                    self.assertFalse(any(x['message']=='red-only'for x in second.chat.messages))
                    first.reset(seed=3)
                    self.assertIsNone(first.page.evaluate("localStorage.getItem('basket')"))
                    self.assertEqual(first.context.cookies(),[])
                    new={x['context_id']for x in a.metadata()['contexts']if not x['released']}
                    self.assertTrue(new.isdisjoint(ids))
                    first.close();a.close()
                    self.assertEqual(second.page.title(),'blue')
                    c=client.episode('green');third=c.wrap(factory('green'))()
                    try:
                        third.reset(seed=4)
                        self.assertEqual(third.page.title(),'green')
                        self.assertEqual(len(client.status()['groups']),2)
                        with self.assertRaises(PoolError):client.request('shutdown')
                        lease=b.leases[0].record
                        with self.assertRaises(PoolError):client.request('release',{'lease_id':lease['lease_id'],
                            'owner':'foreign','release_token':lease['release_token']})
                        self.assertEqual(second.page.title(),'blue')
                    finally:third.close();c.close()
                finally:
                    first.close();second.close();a.close();b.close()
                self.assertEqual(client.status()['leases'],[])

    def test_profile_capacity_duplicate_owner_and_generation_drain(self):
        with tempfile.TemporaryDirectory()as tmp:
            supervisor=PoolSupervisor(Path(tmp)/'pool',max_servers=2,max_leases=4,per_server=2)
            with supervisor as client:
                a=client.episode('capacity');env=a.wrap(factory('red'))()
                try:
                    env.reset(seed=1)
                    record=a.leases[0].record
                    with self.assertRaises(PoolError):
                        client.request('acquire',{'owner':'capacity','role':'task',
                            'options':{'headless':True,'slow_mo':0,'args':[]}})
                    with self.assertRaises(PoolError):
                        client.request('acquire',{'owner':'foreign','role':'task',
                            'options':{'headless':True,'args':['--different-profile']}})
                    supervisor.drain(record['group'])
                    self.assertEqual(env.page.title(),'red')
                    env.close();a.close()
                    deadline=time.monotonic()+5
                    while next(x for x in client.status()['groups']if x['id']==record['group'])['state']!='closed':
                        self.assertLess(time.monotonic(),deadline);time.sleep(.025)
                    b=client.episode('after-drain');later=b.wrap(factory('blue'))()
                    try:
                        later.reset(seed=2)
                        self.assertNotEqual(record['generation'],b.leases[0].record['generation'])
                        self.assertEqual(later.page.title(),'blue')
                    finally:later.close();b.close()
                finally:env.close();a.close()

    def test_idle_profile_eviction_and_late_authenticated_release(self):
        with tempfile.TemporaryDirectory() as tmp, PoolSupervisor(Path(tmp)/'pool',max_servers=1) as client:
            first=client.request('acquire',{'owner':'first','role':'task','options':{'headless':True}})
            client.request('release',{'lease_id':first['lease_id'],'owner':'first','release_token':first['release_token']})
            for index in range(258):
                owner='history-'+str(index)
                record=client.request('acquire',{'owner':owner,'role':'task',
                    'options':{'headless':True,'args':['--new-profile']}})
                client.request('release',{'lease_id':record['lease_id'],'owner':owner,'release_token':record['release_token']})
            self.assertTrue(client.request('release',{'lease_id':first['lease_id'],'owner':'first',
                'release_token':first['release_token']})['history_expired'])
            with self.assertRaises(PoolError):client.request('release',{'lease_id':first['lease_id'],
                'owner':'foreign','release_token':first['release_token']})
            self.assertLessEqual(sum(x['state']=='ready'for x in client.status()['groups']),1)



class Recording(unittest.TestCase):
    def test_video_local_paths_finalize_and_background_direct_identity(self):
        with tempfile.TemporaryDirectory()as tmp,PoolSupervisor(Path(tmp)/'pool')as client:
            e=client.episode('recording',background=True)
            env=e.wrap(factory('red'))(str(Path(tmp)/'video'))
            try:
                _,info=env.reset(seed=1)
                paths=[Path(info['recording_file']),Path(info['chat']['recording_file'])]
                self.assertEqual(len({x['context_id']for x in e.metadata()['contexts']}),2)
                env.page.locator('#buy').click()
                env.chat.add_message('assistant','done')
            finally:env.close();e.close()
            for p in paths:
                self.assertTrue(p.is_file(),str(p));self.assertGreater(p.stat().st_size,100)
            self.assertEqual(client.status()['leases'],[])

    def test_ephemeral_popup_download_and_artifact_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifacts = Path(tmp)/'artifacts'; artifacts.mkdir()
            supervisor = PoolSupervisor(Path(tmp)/'pool')
            with patch.dict(os.environ, {'TMPDIR': str(artifacts)}), supervisor as client:
                episode = client.episode('short-video', background=True)
                env = episode.wrap(factory('red'))(str(Path(tmp)/'video'))
                try:
                    _, info = env.reset(seed=1)
                    page = env.page
                    env.context.new_page().close()
                    page.evaluate("window.open('about:blank').close()")
                    env.context.route('**/file', lambda route: route.fulfill(body='fixture', headers={
                        'Content-Type': 'application/octet-stream',
                        'Content-Disposition': 'attachment; filename=fixture.txt'}))
                    with page.expect_download():
                        page.evaluate("() => { const a=document.createElement('a'); a.href='/file'; a.target='_blank'; a.click(); }")
                    page.screenshot()
                finally: env.close(); episode.close()
                self.assertTrue(Path(info['recording_file']).is_file())
                self.assertTrue(Path(info['chat']['recording_file']).is_file())
                self.assertFalse(list(artifacts.rglob('*.webm')))
                recordings=[v for lease in episode.metadata()['contexts']for v in lease['recordings']]
                self.assertTrue(any(v['kind']=='probe'for v in recordings))
                self.assertTrue(all(v['path']for v in recordings if v['kind']=='episode_page'))
                self.assertTrue(all('id' not in row for row in client.status()['ended']))
                events=[json.loads(line) for line in (Path(tmp)/'pool/events.jsonl').read_text().splitlines()]
                for lease in episode.leases:
                    ack=[x for x in events if x['kind']=='lease_release_acknowledged' and x['lease_id']==lease.record['lease_id']]
                    self.assertEqual(len(ack),1); self.assertEqual(ack[0]['reason'],'released')


    def test_video_save_failure_is_preserved_in_error_and_metadata(self):
        from playwright.sync_api import Error
        with tempfile.TemporaryDirectory() as tmp,PoolSupervisor(Path(tmp)/'pool') as client:
            episode=client.episode('save-error');env=episode.wrap(factory('red'))(str(Path(tmp)/'video'))
            env.reset(seed=1)
            def failed_save(path):raise Error('synthetic transfer failure')
            env.page.video.save_as=failed_save
            with self.assertRaisesRegex(PoolError,'synthetic transfer failure'):env.close()
            episode.close()
            recordings=[v for lease in episode.metadata()['contexts']for v in lease['recordings']]
            failures=[v for v in recordings if v['status']=='failed']
            self.assertTrue(failures);self.assertTrue(all('synthetic transfer failure'in v['error']for v in failures))
            self.assertTrue(all(v['kind']=='episode_page'and v['path']for v in failures))
            self.assertEqual(client.status()['leases'],[])



class Failure(unittest.TestCase):
    def test_worker_death_reaps_only_its_contexts(self):
        context=mp.get_context('spawn')
        with tempfile.TemporaryDirectory()as tmp:
          supervisor=PoolSupervisor(Path(tmp)/'pool')
          with supervisor as client:
            pipes=[];processes=[]
            try:
                for name in ('victim','survivor'):
                    parent,child=context.Pipe();proc=context.Process(target=worker,
                        args=(str(Path(tmp)/'pool/descriptor.json'),name,child));proc.start();child.close()
                    pipes.append(parent);processes.append(proc)
                    self.assertTrue(parent.poll(30));self.assertTrue(parent.recv()['ready'])
                self.assertEqual(len(client.status()['leases']),4)
                processes[0].kill();processes[0].join(10)
                deadline=time.monotonic()+10
                while len(client.status()['leases'])!=2:
                    self.assertLess(time.monotonic(),deadline);time.sleep(.05)
                for group in client.status()['groups']:
                    deadline=time.monotonic()+5
                    while len(supervisor.inspect_contexts(group['id'])['browserContextIds'])!=1:
                        self.assertLess(time.monotonic(),deadline);time.sleep(.025)
                pipes[1].send('act');self.assertTrue(pipes[1].poll(10))
                self.assertEqual(pipes[1].recv()['basket'],'survivor')
                self.assertTrue(all(x['owner']=='survivor'for x in client.status()['leases']))
                pipes[1].send('close');processes[1].join(10);self.assertEqual(processes[1].exitcode,0)
            finally:
                for p in processes:
                    if p.is_alive():p.kill();p.join(10)
                for p in pipes:p.close()


    def test_cli_sigterm_closes_service_and_records_shutdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            pool = Path(tmp)/'pool'
            process = subprocess.Popen([sys.executable, '-m', 'intent_browser.chromium_pool',
                                        '--directory', str(pool)], stdout=subprocess.DEVNULL)
            try:
                deadline=time.monotonic()+20
                while not (pool/'descriptor.json').exists():
                    self.assertIsNone(process.poll()); self.assertLess(time.monotonic(),deadline);time.sleep(.025)
                client=PoolClient.from_file(pool/'descriptor.json')
                record=client.request('acquire', {'owner':'cli-stop','role':'task',
                    'options':{'headless':True}})
                process.send_signal(signal.SIGTERM); process.wait(timeout=25)
                self.assertEqual(process.returncode,0)
                with self.assertRaises(PoolError):client.status()
                events=[json.loads(line)for line in (pool/'events.jsonl').read_text().splitlines()]
                self.assertTrue(any(x.get('reason')=='supervisor_shutdown'for x in events))
            finally:
                if process.poll() is None:process.kill();process.wait(timeout=5)



    def test_cli_process_group_sigint_is_clean_with_live_browser(self):
        with tempfile.TemporaryDirectory() as tmp:
            pool=Path(tmp)/'pool'
            process=subprocess.Popen([sys.executable,'-m','intent_browser.chromium_pool',
                '--directory',str(pool)],stdout=subprocess.DEVNULL,start_new_session=True)
            try:
                deadline=time.monotonic()+20
                while not (pool/'descriptor.json').exists():
                    self.assertIsNone(process.poll());self.assertLess(time.monotonic(),deadline);time.sleep(.025)
                client=PoolClient.from_file(pool/'descriptor.json')
                client.request('acquire',{'owner':'ctrl-c','role':'task','options':{'headless':True}})
                os.killpg(process.pid,signal.SIGINT);process.wait(timeout=25)
                self.assertEqual(process.returncode,0)
                with self.assertRaises(PoolError):client.status()
                events=[json.loads(line)for line in (pool/'events.jsonl').read_text().splitlines()]
                self.assertTrue(any(x.get('reason')=='supervisor_shutdown'for x in events))
            finally:
                if process.poll()is None:os.killpg(process.pid,signal.SIGKILL);process.wait(timeout=5)

    def test_controller_death_stops_broker_without_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            pool=Path(tmp)/'pool'
            process=subprocess.Popen([sys.executable,'-m','intent_browser.chromium_pool',
                '--directory',str(pool)],stdout=subprocess.DEVNULL)
            try:
                deadline=time.monotonic()+20
                while not (pool/'descriptor.json').exists():
                    self.assertIsNone(process.poll());self.assertLess(time.monotonic(),deadline);time.sleep(.025)
                client=PoolClient.from_file(pool/'descriptor.json')
                client.request('acquire',{'owner':'owner-died','role':'task','options':{'headless':True}})
                socket_path=Path(client.descriptor['socket'])
                process.kill();process.wait(timeout=5)
                deadline=time.monotonic()+20
                while socket_path.exists():
                    self.assertLess(time.monotonic(),deadline);time.sleep(.025)
                with self.assertRaises(PoolError):client.status()
                events=[json.loads(line)for line in (pool/'events.jsonl').read_text().splitlines()]
                self.assertTrue(any(x.get('reason')=='supervisor_shutdown'for x in events))
                socket_path.parent.rmdir()  # abrupt parent death leaves its empty private directory
            finally:
                if process.poll() is None:process.kill();process.wait(timeout=5)

    def test_supervisor_loss_has_no_local_launch_fallback(self):
        with tempfile.TemporaryDirectory()as tmp:
            supervisor=PoolSupervisor(Path(tmp)/'pool');client=supervisor.start()
            episode=client.episode('service-loss');env=episode.wrap(factory('red'))()
            try:
                env.reset(seed=1);supervisor.process.kill();supervisor.process.wait(timeout=5)
                with self.assertRaises(PoolError):client.status()
                with self.assertRaises(Exception):env.page.title()
                with self.assertRaises(PoolError):env.close()
            finally:
                with self.assertRaises(PoolError):supervisor.close()

    def test_browser_crash_is_an_error_and_other_pool_member_survives(self):
        with tempfile.TemporaryDirectory()as tmp:
            supervisor=PoolSupervisor(Path(tmp)/'pool',per_server=1)
            with supervisor as client:
                a,b=client.episode('crash'),client.episode('survivor')
                first,second=a.wrap(factory('red'))(),b.wrap(factory('blue'))()
                try:
                    first.reset(seed=1);second.reset(seed=2)
                    group=a.leases[0].record['group'];supervisor.abort_browser(group)
                    with self.assertRaises(Exception):first.page.title()
                    self.assertEqual(second.page.title(),'blue')
                    deadline=time.monotonic()+5
                    while not any(x['reason']=='browser_crashed'for x in client.status()['ended']):
                        self.assertLess(time.monotonic(),deadline);time.sleep(.025)
                finally:
                    for env in (first,second):
                        try:env.close()
                        except PoolError:pass
                    a.close();b.close()


class Graded(unittest.TestCase):
    def test_parallel_correct_wrong_missing_actual_runner_and_projection(self):
        context=mp.get_context('spawn')
        with tempfile.TemporaryDirectory()as tmp,PoolSupervisor(Path(tmp)/'pool')as client:
            jobs=[]
            try:
                for case in ('correct','wrong','missing'):
                    parent,child=context.Pipe();process=context.Process(target=graded_worker,
                        args=(str(Path(tmp)/'pool/descriptor.json'),case,str(Path(tmp)/case),child))
                    process.start();child.close();jobs.append((case,process,parent))
                for case,process,parent in jobs:
                    self.assertTrue(parent.poll(45));result=parent.recv();process.join(10)
                    self.assertEqual(process.exitcode,0);self.assertIsNone(result['summary']['error'])
                    trace=Path(result['trace']);metadata=json.loads((trace/'metadata.json').read_text())
                    self.assertIn('scripted',metadata['tags']);self.assertEqual(len(metadata['shared_chromium']['contexts']),2)
                    self.assertTrue(all(x['released']for x in metadata['shared_chromium']['contexts']))
                    self.assertTrue(json.loads((trace/'automatic-grade-projection.json').read_text())['verified'])
                    grade=json.loads((trace/'automatic-grade.json').read_text())['raw_grade']
                    self.assertTrue(grade['closed']);self.assertEqual(grade['state']['answered'],case!='missing')
                    self.assertEqual(grade['state']['basket'],'red'if case!='wrong'else None)
                self.assertEqual(client.status()['leases'],[])
            finally:
                for _,process,parent in jobs:
                    if process.is_alive():process.kill();process.join(10)
                    parent.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--case',choices=['lifecycle','recording','failure','graded'],required=True)
    args=parser.parse_args()
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(
        {'lifecycle':Lifecycle,'recording':Recording,'failure':Failure,'graded':Graded}[args.case]))
    raise SystemExit(not result.wasSuccessful())
