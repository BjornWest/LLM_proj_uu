"""Focused saved-input and actual review-route controls; no browser/model draw."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from .review_saved_inputs import REQUIRED, read_saved, target_setup
from .review_saved_execution import review_start
from . import review_saved_publication as publication
from intent_browser.connected_world_task import checked_files


class SavedReaderClosureTests(unittest.TestCase):
    def test_reader_is_bound_and_drift_rejected_by_dispatch_file_check(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            reader = root/'scripts/trace_grades.py'
            reader.parent.mkdir()
            reader.write_bytes(b'# frozen reader\n')
            with patch.object(publication, 'ROOT', root), patch.object(
                    publication, '_bind', return_value=lambda: {}):
                sources = publication.source_files()
            self.assertEqual(sources, {'scripts/trace_grades.py': sha256(reader.read_bytes()).hexdigest()})
            files = {str(root/name): expected for name, expected in sources.items()}
            checked_files(files)
            reader.write_bytes(b'# changed reader\n')
            with self.assertRaises(ValueError):
                checked_files(files)

    def test_existing_scripts_package_initializer_is_also_bound(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'scripts').mkdir()
            (root/'scripts/trace_grades.py').write_bytes(b'# reader\n')
            initializer = root/'scripts/__init__.py'
            initializer.write_bytes(b'# package\n')
            with patch.object(publication, 'ROOT', root), patch.object(
                    publication, '_bind', return_value=lambda: {'retained.py': 'a'*64}):
                sources = publication.source_files()
            self.assertEqual(sources['retained.py'], 'a'*64)
            self.assertEqual(sources['scripts/__init__.py'], sha256(initializer.read_bytes()).hexdigest())


class SavedInputsTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.saved = Path(self.temp.name)
        self.files = {name: (b'Natural review request.\n' if name.endswith('.txt') else b'{}\n')
                      for name in REQUIRED}
        self.files['retained-extra.private.json'] = b'{"unchanged": true}\n'
        self.manifest = {'files': {name: sha256(value).hexdigest() for name, value in self.files.items()},
                         'source_hashes': {'source.py': 'a'*64}}
        for name, payload in self.files.items():
            (self.saved/name).write_bytes(payload)
        self.write_manifest()

    def write_manifest(self):
        data = json.dumps(self.manifest).encode()
        (self.saved/'draft-manifest.json').write_bytes(data)
        self.expected = sha256(data).hexdigest()

    def read(self):
        return read_saved(self.saved, expected_manifest_sha256=self.expected)

    def test_complete_bytes_and_extra_inputs_retained(self):
        manifest, payloads, request = self.read()
        self.assertEqual(manifest, self.manifest)
        self.assertEqual({k:v for k,v in payloads.items() if k!='draft-manifest.json'}, self.files)
        self.assertEqual(request, 'Natural review request.')

    def test_stale_manifest_rejected(self):
        (self.saved/'draft-manifest.json').write_bytes(b'{}')
        with self.assertRaisesRegex(ValueError, 'manifest changed'): self.read()

    def test_changed_native_reference_rejected(self):
        (self.saved/'reference.private.json').write_bytes(b'{"different":true}')
        with self.assertRaisesRegex(ValueError, 'input changed'): self.read()

    def test_missing_required_input_rejected(self):
        self.manifest['files'].pop('task.private.json'); self.write_manifest()
        with self.assertRaisesRegex(ValueError, 'complete'): self.read()

    def test_escaping_name_rejected(self):
        self.manifest['files']['../foreign.json'] = 'b'*64; self.write_manifest()
        with self.assertRaisesRegex(ValueError, 'basename'): self.read()

    def test_escaping_symlink_rejected(self):
        with TemporaryDirectory() as outside:
            foreign=Path(outside)/'input'; foreign.write_bytes(b'{}\n')
            local=self.saved/'task.private.json'; local.unlink(); local.symlink_to(foreign)
            with self.assertRaisesRegex(ValueError, 'escapes'): self.read()

    def test_empty_request_rejected(self):
        payload=b' \n'; (self.saved/'proposed-user-request.txt').write_bytes(payload)
        self.manifest['files']['proposed-user-request.txt']=sha256(payload).hexdigest()
        self.write_manifest()
        with self.assertRaisesRegex(ValueError, 'empty'): self.read()


class ActualReviewRouteTests(unittest.TestCase):
    def setUp(self):
        self.world={'world_id':'saved-world'}
        self.task={'world_id':'saved-world','subject':{'product_id':'brand/shoe/00'}}
        self.surrounding={'source_world_id':'saved-world','sites':[
            {'site_id':'reviews','kind':'product_reviews','product_ids':['brand/shoe/00'],'name':'Model Review','layout':'editorial-magazine'},
            {'site_id':'other','kind':'aggregator','product_ids':['brand/shoe/00'],'name':'Other'}]}
        self.binding={'status':'bound','publication_ids':['reviews'],'world_repaired':False}
        self.setup=target_setup(self.world,self.task,self.surrounding,self.binding,review_site_id='reviews')
        self.url='https://model-review.local/reviews/brand%2Fshoe%2F00'
        self.runtime=SimpleNamespace(world=self.world,origin_map=object(),site_registry=[
            {'site_id':'reviews','kind':'product_reviews','name':'Model Review','origin':'https://model-review.local'}],
            bindings={'surrounding':{'review_products':{'brand/shoe/00':[self.url]}}})

    def start(self):
        return review_start(self.runtime,self.setup,self.task,self.surrounding,self.binding)

    def test_actual_readable_route_and_surrounding_unchanged(self):
        before=deepcopy(self.surrounding)
        self.assertEqual(self.start(),self.url)
        self.assertEqual(self.surrounding,before)
        self.assertEqual(self.setup['effects'],'unknown')

    def test_unpublished_target_site_rejected(self):
        with self.assertRaisesRegex(ValueError,'existing review site'):
            target_setup(self.world,self.task,self.surrounding,self.binding,review_site_id='other')

    def test_foreign_world_rejected(self):
        self.world['world_id']='another'
        with self.assertRaisesRegex(ValueError,'world identity'): self.start()

    def test_changed_subject_setup_rejected(self):
        self.setup['start']['product_id']='different'
        with self.assertRaisesRegex(ValueError,'setup changed'): self.start()

    def test_foreign_site_origin_cannot_invent_route(self):
        self.runtime.site_registry[0]['origin']='https://foreign.local'
        with self.assertRaisesRegex(ValueError,'route bindings'): self.start()

    def test_stale_coverage_binding_rejected(self):
        self.binding['publication_ids']=[]
        with self.assertRaisesRegex(ValueError,'coverage binding'): self.start()

    def test_readable_origin_binding_required(self):
        self.runtime.origin_map=None
        with self.assertRaisesRegex(ValueError,'readable-origin'): self.start()

    def test_reader_responses_query_uses_registered_base_route(self):
        self.setup=target_setup(self.world,self.task,self.surrounding,self.binding,
                               review_site_id='reviews',start_query={'part':'readers'})
        self.assertEqual(self.start(),self.url+'?part=readers')

    def test_highest_first_reader_query_retains_all_surrounding_sites(self):
        before=deepcopy(self.surrounding)
        query={'sort':'highest','part':'readers'}
        self.setup=target_setup(self.world,self.task,self.surrounding,self.binding,
                               review_site_id='reviews',start_query=query)
        self.assertEqual(self.start(),self.url+'?part=readers&sort=highest')
        query['sort']='lowest'
        self.assertEqual(self.start(),self.url+'?part=readers&sort=highest')
        self.assertEqual(self.surrounding,before)

    def test_empty_query_retains_legacy_setup_and_url(self):
        self.assertEqual(target_setup(self.world,self.task,self.surrounding,self.binding,
                        review_site_id='reviews',start_query={}),self.setup)
        self.assertEqual(self.start(),self.url)

    def test_start_query_cannot_filter_comments_or_choose_foreign_subject(self):
        for query in ({'stars':'5'}, {'sku':'other'}, {'q':'wet'}, {'sort':['highest']},
                      {'part':'readers','page':'2'}, {'part':'overview'}, {'sort':'unknown'}):
            with self.subTest(query=query), self.assertRaisesRegex(ValueError,'start query'):
                target_setup(self.world,self.task,self.surrounding,self.binding,
                             review_site_id='reviews',start_query=query)

    def test_readers_article_query_requires_editorial_layout(self):
        self.surrounding['sites'][0]['layout']='community-feed'
        with self.assertRaisesRegex(ValueError,'start query'):
            target_setup(self.world,self.task,self.surrounding,self.binding,
                         review_site_id='reviews',start_query={'part':'readers'})

    def test_query_cannot_make_unbound_foreign_origin_valid(self):
        self.setup=target_setup(self.world,self.task,self.surrounding,self.binding,
                               review_site_id='reviews',start_query={'part':'readers'})
        self.runtime.site_registry[0]['origin']='https://foreign.local'
        with self.assertRaisesRegex(ValueError,'route bindings'): self.start()

    def test_present_malformed_start_never_selects_legacy_fallback(self):
        source_hashes={'source.py':'a'*64}
        task={**self.task,'task_id':'review-task','concept_id':'footwear.walking_shoes','user_message':'Native',
              'memories':[],'source_sha256':source_hashes}
        values={'world.private.json':{**self.world,'schema_version':'accepted-catalog-commerce-world-v1'},
                'task.private.json':task,'reference.private.json':{},
                'native-episode-control.json':{'task_id':task['task_id'],
                    'manual_task':{'user_message':task['user_message'],'memories':task['memories']}},
                'surrounding.private.json':self.surrounding,'review-binding.private.json':self.binding}
        for declaration in (None, [], 'readers'):
            payloads={name:json.dumps(value).encode() for name,value in values.items()}
            payloads['diagnostic-start.private.json']=json.dumps(declaration).encode()
            with self.subTest(declaration=declaration), TemporaryDirectory() as directory, \
                    patch.object(publication,'read_saved',return_value=(
                        {'source_hashes':source_hashes},payloads,'Natural request')), \
                    patch.object(publication.native,'ReviewInventory',return_value=SimpleNamespace(
                        source_hashes=source_hashes)), patch.object(publication.native,'reference',return_value={}), \
                    patch.object(publication,'Execution') as freeze:
                with self.assertRaisesRegex(ValueError,'Declared saved review start identity'):
                    publication.prepare_saved(Path(directory)/'saved',Path(directory)/'out',
                        expected_manifest_sha256='a'*64,review_site_id='reviews')
                freeze.assert_not_called()


if __name__=='__main__': unittest.main()
