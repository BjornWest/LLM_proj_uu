import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts.prepare_connected_qwen import prepare_bank
from intent_browser.connected_world_task import sha
from environments.product_world.generator import digest

class PreparationTests(unittest.TestCase):
    def fixture(self, root):
        def save(name,value):
            p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(value,indent=2));return p
        runtime=save('world/manifest.json',{'index_url':'http://localhost:12345','sites':[]})
        public=save('public/task.json',{'schema_version':'manual-shopping-task-v1','task_id':'opaque',
            'user_message':'Read a price.','memories':{},'environment_context':{},'start_url':'http://localhost:12345'})
        private=save('private/task.json',{'task_id':'opaque','public_sha256':digest(json.loads(public.read_text())),
            'source_bindings':{str(runtime):sha(runtime)},'clarification':None,'reference':{'answer':999}})
        manifest=save('manifest.private.json',{'cases':[{'case_id':'D01','public_path':str(public),'private_path':str(private)}]})
        save('pins.json',{'inputs':{str(runtime):sha(runtime)},'files':{str(public):sha(public),str(private):sha(private),str(manifest):sha(manifest)},'code':{}})
        return public,private

    def test_canonical_upstream_hash_file_byte_local_hash(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);public,private=self.fixture(root)
            self.assertNotEqual(sha(public),json.loads(private.read_text())['public_sha256'])
            with patch('scripts.prepare_connected_qwen.proposed_profile',return_value={'cases':['D01']}):
                prepare_bank(root,root/'prepared')
            target=root/'prepared/D01/public/task.json'
            binding=json.loads((root/'prepared/D01/private/binding.json').read_text())
            self.assertEqual(binding['public_sha256'],sha(target))
            self.assertNotIn('999',target.read_text())
            with self.assertRaises(FileExistsError):prepare_bank(root,root/'prepared')

    def test_changed_public_rejected_before_output(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);public,_=self.fixture(root);public.write_text('{}')
            with self.assertRaisesRegex(ValueError,'changed'):prepare_bank(root,root/'prepared')
            self.assertFalse((root/'prepared').exists())

if __name__=='__main__':unittest.main()
