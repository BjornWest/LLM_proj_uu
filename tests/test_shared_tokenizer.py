"""Synthetic RPC lifecycle/failure tests; no model, browser, downloads or quota."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest

from tokenizers import Tokenizer, models, pre_tokenizers
from intent_browser.ax_explorer import AXConfig, AXExplorer
from intent_browser.input_budget import QwenInputCounter, OpaqueReasoningInputCounter
from intent_browser.shared_tokenizer import (SharedTokenizerConfig, SharedTokenizer,
    SharedTokenizerError, asset_digest, load_tokenizer, send_frame, receive_frame,
    PROTOCOL, VERSION)
from intent_browser.tokenizer_service import TokenizerService


class ServiceFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / 'tokenizer.json'
        tokenizer = Tokenizer(models.WordLevel({'[UNK]': 0, 'hello': 1, 'world': 2,
                                                'å': 3, '[SEP]': 4}, unk_token='[UNK]'))
        tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
        tokenizer.add_special_tokens(['[SEP]'])
        tokenizer.save(str(self.path))
        self.asset = {'path': str(self.path), 'sha256': asset_digest(self.path), 'normalization': 'raw'}
        self.local = Tokenizer.from_file(str(self.path))
        self.services = []
        self.addCleanup(self.stop_services)
        self.config, self.service = self.start()

    def start(self, **limits):
        path = self.root / ('service%d.sock' % len(self.services))
        service = TokenizerService(path, [self.asset, self.asset], **limits)
        ready = threading.Event()
        thread = threading.Thread(target=service.serve, args=(ready,), daemon=True)
        self.services.append((service, thread))
        thread.start()
        self.assertTrue(ready.wait(3))
        return SharedTokenizerConfig(str(path), timeout_seconds=2), service

    def stop_services(self):
        for service, thread in self.services:
            service.stop(); thread.join(3)
            self.assertFalse(thread.is_alive())

    def client(self, config=None):
        return SharedTokenizer(config or self.config, self.asset['sha256'])

    def test_ids_decode_counts_flags_and_single_immutable_load(self):
        client = self.client()
        for text in ['', 'hello world', 'å [SEP] world', '☃ unknown\nhello']:
            for special in (False, True):
                ids = self.local.encode(text, add_special_tokens=special).ids
                self.assertEqual(client.encode(text, special).ids, ids)
                self.assertEqual(client.count(text, special), len(ids))
                for skip in (False, True):
                    self.assertEqual(client.decode(ids, skip), self.local.decode(ids, skip_special_tokens=skip))
        self.assertEqual(client._rpc('describe')['loads'], 1)
        self.assertEqual(client._rpc('describe')['request_cache_entries'], 0)

    def test_batch_parity_and_aggregate_bounds(self):
        texts=['hello world','å [SEP]','unknown','']
        client=self.client()
        for special in (False,True):
            expected=[e.ids for e in self.local.encode_batch(texts,add_special_tokens=special)]
            self.assertEqual([e.ids for e in client.encode_batch(texts,special)],expected)
            self.assertEqual(client.decode_batch(expected,False),
                             self.local.decode_batch(expected,skip_special_tokens=False))
        self.assertEqual(client.count_batch(texts),[len(self.local.encode(t,add_special_tokens=False).ids) for t in texts])
        self.assertEqual(client.encode_batch([]),[])
        with self.assertRaises(SharedTokenizerError):client.encode_batch(['hello']*257)
        config,_=self.start(max_text_bytes=10,max_ids=2)
        with self.assertRaises(SharedTokenizerError):self.client(config).encode_batch(['hello','world','hello'])

    def test_concurrent_late_attachment_and_client_close_isolated(self):
        def run(index):
            client = self.client()
            for _ in range(12):
                self.assertEqual(client.count('hello world'), 2)
            client.close()
            with self.assertRaisesRegex(SharedTokenizerError, 'closed'):
                client.count('hello')
            return index
        with ThreadPoolExecutor(max_workers=3) as executor:
            self.assertEqual(list(executor.map(run, range(3))), list(range(3)))
        self.assertEqual(self.client().count('world'), 1)
        self.assertEqual(self.service.load_count, 1)

    def test_no_local_tokenizer_import_in_separate_client_process(self):
        code = ('import sys; from intent_browser.shared_tokenizer import SharedTokenizerConfig, SharedTokenizer; '
                'c=SharedTokenizer(SharedTokenizerConfig(sys.argv[1]),sys.argv[2]); '
                'assert c.count("hello")==1; assert "tokenizers" not in sys.modules')
        result = subprocess.run([sys.executable, '-B', '-c', code, self.config.socket_path,
                                 self.asset['sha256']], capture_output=True, timeout=8)
        self.assertEqual(result.returncode, 0, result.stderr.decode())

    def test_unknown_digest_mode_unavailable_and_asset_mutation_fail_no_fallback(self):
        for digest, mode in [('0'*64, 'raw'), (self.asset['sha256'], 'ascii-json')]:
            with self.assertRaises(SharedTokenizerError):
                SharedTokenizer(self.config, digest, mode)
        with self.assertRaises(SharedTokenizerError):
            self.client(replace(self.config, socket_path=str(self.root/'missing.sock')))
        self.path.write_text('{}')
        with self.assertRaises(SharedTokenizerError):
            load_tokenizer(self.path, shared=self.config)
        self.assertEqual(self.client().count('hello'), 1)  # already pinned server resource

    def test_owner_shutdown_rejects_without_affecting_another_service(self):
        other_config, _ = self.start()
        client = self.client()
        self.service.stop(); self.services[0][1].join(3)
        with self.assertRaises(SharedTokenizerError): client.count('hello')
        self.assertEqual(self.client(other_config).count('hello'), 1)

    def test_restart_requires_requalification(self):
        client = self.client()
        self.service.instance = 'replacement-instance'
        with self.assertRaisesRegex(SharedTokenizerError, 'restarted'): client.count('hello')
        self.assertEqual(self.client().count('hello'), 1)

    def test_limits_invalid_inputs_and_no_dynamic_load_or_shutdown(self):
        config, _ = self.start(max_text_bytes=10, max_ids=2)
        client = self.client(config)
        for text in ['hello world', 'hello '*3]:
            with self.assertRaises(SharedTokenizerError):client.count(text)
        with self.assertRaises(SharedTokenizerError):client.decode([1,2,1])
        for value in [-1, True, '1', 2**32]:
            with self.assertRaises(ValueError): client.decode([value])
        with self.assertRaises(ValueError): client.encode('hello', 0)
        with self.assertRaises(SharedTokenizerError): client._rpc('shutdown')
        with self.assertRaises(SharedTokenizerError): client._rpc('load', path='/tmp/unknown')
        self.assertEqual(client.count('hello'), 1)

    def test_bounded_admission_and_slow_connection_deadline(self):
        config, service = self.start(max_clients=1, request_seconds=0.2)
        silent = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.addCleanup(silent.close); silent.connect(config.socket_path)
        until = time.monotonic()+1
        while not service._threads and time.monotonic()<until: time.sleep(.005)
        self.assertTrue(service._threads)
        with self.assertRaises(SharedTokenizerError):self.client(config)
        self.services[-1][1].join(.3)
        self.assertEqual(self.client(config).count('hello'), 1)

    def test_bad_frames_are_rejected_and_text_not_reflected(self):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.connect(self.config.socket_path)
            payload={'protocol':PROTOCOL,'version':VERSION,'asset':self.asset['sha256'],
                     'normalization':'raw','operation':'count','text':'secret-needle',
                     'add_special_tokens':False,'surprise':'also-secret'}
            send_frame(connection,payload,16384,time.monotonic()+2)
            result=receive_frame(connection,16384,time.monotonic()+2)
            self.assertEqual(result,{'ok':False,'error':'tokenizer_request_rejected'})
        self.assertEqual(self.client().count('hello'),1)

    def test_pin_validation_socket_permissions_and_existing_path(self):
        bad = {**self.asset,'sha256':'0'*64}
        with self.assertRaisesRegex(ValueError,'digest mismatch'):
            TokenizerService(self.root/'bad.sock',[bad])
        with self.assertRaisesRegex(ValueError,'already exists'):
            TokenizerService(self.config.socket_path,[self.asset])
        os.chmod(self.config.socket_path,0o666)
        with self.assertRaises(SharedTokenizerError):self.client()
        os.chmod(self.config.socket_path,0o600)
        os.chmod(self.root,0o755)
        with self.assertRaisesRegex(ValueError,'0700'):
            TokenizerService(self.root/'public.sock',[self.asset])
        os.chmod(self.root,0o700)

    def test_ax_clipping_search_and_pagination_identical(self):
        def node(i,role,name,children=()):
            return {'nodeId':str(i),'role':{'value':role},'name':{'value':name},
                    'childIds':list(map(str,children)),'ignored':False,'browsergym_id':str(i)}
        nodes=[node(0,'RootWebArea','world',range(1,15))]+[
               node(i,'button','hello world '*150) for i in range(1,15)]
        obs={'url':'http://fixture/','last_action_error':'','axtree_object':{'nodes':nodes}}
        local=AXExplorer(AXConfig(str(self.path)))
        remote=AXExplorer(AXConfig(str(self.path),shared_tokenizer=self.config))
        self.assertEqual(local.overview(obs),remote.overview(obs))
        self.assertEqual(local._clip('hello world '*100,10),remote._clip('hello world '*100,10))
        self.assertEqual(local.search('hello',limit=2),remote.search('hello',limit=2))
        for offset in (0,1):
            self.assertEqual(local.read(local.ref(0),limit=1,offset=offset),
                             remote.read(remote.ref(0),limit=1,offset=offset))

    def test_incremental_ax_batched_parity_delivery_and_bounded_cache(self):
        from intent_browser.ax_context import AXContext
        from unittest.mock import patch
        def node(i,role,name,children=()):
            return {'nodeId':str(i),'role':{'value':role},'name':{'value':name},
                    'childIds':list(map(str,children)),'ignored':False,'browsergym_id':str(i),
                    'backendDOMNodeId':100+i}
        nodes=[node(0,'RootWebArea','world',range(1,65))]+[
               node(i,'button','hello '+str(i)+' world '*100) for i in range(1,65)]
        obs={'url':'http://fixture/','last_action_error':'','axtree_object':{'nodes':nodes}}
        local=AXContext(AXConfig(str(self.path),incremental=True))
        remote=AXContext(AXConfig(str(self.path),incremental=True,shared_tokenizer=self.config))
        with patch.object(remote.tokenizer,'_rpc',wraps=remote.tokenizer._rpc) as rpc:
            self.assertEqual(local.prepare_observation(obs),remote.prepare_observation(obs))
            batch_ops=sum(c.args[0] in ('encode_batch','decode_batch','count_batch') for c in rpc.call_args_list)
            self.assertGreater(batch_ops,0)
            self.assertLess(rpc.call_count,64)
        local.acknowledge();remote.acknowledge()
        self.assertEqual(local.search(['hello','world'],limit=2),remote.search(['hello','world'],limit=2))
        local.acknowledge();remote.acknowledge()
        for view,extra in [('node',{'radius':1}),('node',{}),('children',{})]:
            self.assertEqual(local.read(local.ref(1),view=view,repeat=True,**extra),
                             remote.read(remote.ref(1),view=view,repeat=True,**extra))
        changed=deepcopy(obs);changed['axtree_object']['nodes'][1]['name']['value']='changed'
        self.assertEqual(local.prepare_observation(changed),remote.prepare_observation(changed))
        for group in range(30):remote._prime_clips([(f'hello {group} {i} world',40) for i in range(64)])
        self.assertLessEqual(len(remote._clip_cache),512)
        self.assertLessEqual(remote._clip_cache_bytes,1024*1024)

    def test_templates_and_opaque_accounting_remain_episode_local(self):
        template=self.path.with_name('chat_template.jinja')
        template.write_text('{% for m in messages %}{{ m.role }} {{ m.content }}{% endfor %} {{ tools | tojson }}')
        local=QwenInputCounter(self.path)
        remote=QwenInputCounter(self.path,shared_tokenizer=self.config)
        messages=[{'role':'user','content':'hello world'}]
        tools=[{'type':'function','function':{'name':'x','parameters':{'type':'object','properties':{'z':{},'a':{}}}}}]
        before=deepcopy((messages,tools))
        measured=remote(messages,tools);measured.pop('tokenizer_service')
        self.assertEqual(measured,local(messages,tools));self.assertEqual((messages,tools),before)
        first=OpaqueReasoningInputCounter(remote);second=OpaqueReasoningInputCounter(remote)
        opaque={'role':'assistant','content':None,'reasoning_details':[{'type':'reasoning.encrypted','data':'episode-secret'}]}
        first.observe_completion({'messages':messages,'tools':tools},
            {'choices':[{'message':opaque}],'usage':{'completion_tokens':7}})
        self.assertEqual(first(messages+[opaque],tools)['retained_hidden_tokens_estimate'],7)
        with self.assertRaisesRegex(ValueError,'no matching'):second(messages+[opaque],tools)


if __name__ == '__main__':
    unittest.main()
