"""Explicit local official-asset parity; no downloads, providers or browsers."""
import base64
from copy import deepcopy
from dataclasses import replace
from io import BytesIO
import json
import os
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest

from PIL import Image
from intent_browser.model_input_budget import model_matched_input_counter, REGISTRY
from intent_browser.shared_tokenizer import SharedTokenizerConfig, SharedTokenizerError
from intent_browser.tokenizer_service import TokenizerService

ASSETS = Path(os.environ.get('SHARED_TOKENIZER_TEST_ASSETS',
                             Path(__file__).resolve().parents[1]/'.local/model-tokenizers'))
ENTRIES = json.loads(REGISTRY.read_text())['models']
INSTALLED = all((ASSETS/entry['bundle']/'tokenizer.json').is_file() for entry in ENTRIES.values())


@unittest.skipUnless(INSTALLED, 'Explicit official asset install required')
class OfficialParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        assets = [{'path': str(ASSETS/entry['bundle']/'tokenizer.json'),
                   'sha256': entry['files']['tokenizer.json']['sha256'],
                   'normalization': 'ascii-json' if entry['counter']=='glm' else 'raw'}
                  for entry in ENTRIES.values()]
        cls.service = TokenizerService(Path(cls.temp.name)/'tokens.sock',assets)
        cls.thread = threading.Thread(target=cls.service.serve,daemon=True)
        ready = threading.Event()
        cls.thread = threading.Thread(target=cls.service.serve,args=(ready,),daemon=True)
        cls.thread.start()
        if not ready.wait(15):raise AssertionError('Service not ready')
        cls.config = SharedTokenizerConfig(str(cls.service.path))

    @classmethod
    def tearDownClass(cls):
        cls.service.stop();cls.thread.join(3);cls.temp.cleanup()

    def counters(self, model, reasoning):
        backend=SimpleNamespace(model=model,base_url='https://openrouter.ai/api/v1',
                                request_options={'reasoning':reasoning})
        return (model_matched_input_counter(backend,assets_root=ASSETS),
                model_matched_input_counter(backend,assets_root=ASSETS,shared_tokenizer=self.config))

    def test_complete_tools_history_images_all_registered_models_and_modes(self):
        data=BytesIO();Image.new('RGB',(560,280)).save(data,format='PNG')
        image={'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(data.getvalue()).decode()}}
        messages=[{'role':'system','content':'Compare offers'},
                  {'role':'user','content':[{'type':'text','text':'Which is cheaper?'},image]},
                  {'role':'assistant','content':None,
                   'reasoning_details':[{'type':'reasoning.text','text':'Compute the complete price.'}],
                   'tool_calls':[{'id':'one','type':'function','function':{'name':'read','arguments':'{"z":2,"a":1}'}}]},
                  {'role':'tool','tool_call_id':'one','content':'Two offers'}]
        for model in ENTRIES:
            for reasoning in [{'enabled':True,'effort':'low'},{'enabled':False}]:
                with self.subTest(model=model,reasoning=reasoning):
                    local,shared=self.counters(model,reasoning)
                    for properties in [{'z':{'type':'number'},'a':{'type':'number'}},
                                       {'a':{'type':'number'},'z':{'type':'number'}}]:
                        tools=[{'type':'function','function':{'name':'read','parameters':{'type':'object','properties':properties}}}]
                        before=deepcopy((messages,tools))
                        actual=shared(messages,tools);actual.pop('tokenizer_service')
                        self.assertEqual(actual,local(messages,tools))
                        self.assertEqual((messages,tools),before)
                        text='å "escaped"\n商品 [Special token] '*3
                        ids=local.visible_counter.tokenizer.encode(text,add_special_tokens=False).ids
                        self.assertEqual(shared.visible_counter.tokenizer.encode(text,False).ids,ids)
                        self.assertEqual(shared.visible_counter.tokenizer.decode(ids,False),
                                         local.visible_counter.tokenizer.decode(ids,skip_special_tokens=False))

    def test_unknown_model_missing_bundle_and_unavailable_never_fall_back(self):
        unknown=SimpleNamespace(model='unknown/model',base_url='https://openrouter.ai/api/v1')
        with self.assertRaisesRegex(ValueError,'No model-matched'):
            model_matched_input_counter(unknown,assets_root=ASSETS,shared_tokenizer=self.config)
        known=SimpleNamespace(model=next(iter(ENTRIES)),base_url='https://openrouter.ai/api/v1',request_options={})
        with tempfile.TemporaryDirectory() as empty:
            with self.assertRaisesRegex(ValueError,'Missing local tokenizer'):
                model_matched_input_counter(known,assets_root=empty,shared_tokenizer=self.config)
        with self.assertRaises(SharedTokenizerError):
            model_matched_input_counter(known,assets_root=ASSETS,
                shared_tokenizer=replace(self.config,socket_path=str(Path(self.temp.name)/'absent.sock')))

    def test_worker_reasoning_receipts_do_not_cross_episodes(self):
        _,first=self.counters(next(iter(ENTRIES)),{'enabled':True})
        _,second=self.counters(next(iter(ENTRIES)),{'enabled':True})
        messages=[{'role':'user','content':'Compare prices'}]
        first(messages,[])
        answer={'role':'assistant','content':None,
                'reasoning_details':[{'type':'reasoning.encrypted','data':'one-episode-only'}]}
        first.observe_completion({'messages':messages,'tools':[]},
            {'choices':[{'message':answer}],'usage':{'prompt_tokens':20,'completion_tokens_details':{'reasoning_tokens':14}}})
        self.assertEqual(first(messages+[answer],[])['retained_hidden_tokens_estimate'],14)
        with self.assertRaisesRegex(ValueError,'no matching'):second(messages+[answer],[])


if __name__=='__main__':unittest.main()
