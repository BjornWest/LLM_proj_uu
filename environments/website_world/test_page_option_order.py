"""Tiny source controls; full browser/native task acceptance is separate."""
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from environments.website_world import page_option_order as order


def page(identity):
    return {'id': identity, 'options': [
        {'key': 'width', 'values': ['standard']}, {'key': 'size_eu', 'values': ['38', '39']},
        {'key': 'colour', 'values': ['brown', 'black']}],
        'variants': [{'key': identity+'/'+str(i), 'skuId': identity+'/'+str(i),
            'offerId': 'shop/'+identity+'/'+str(i), 'priceMinor': 43000+i,
            'state': 'in_stock', 'sourceStock': [{'quantity': i}],
            'selection': {'width': 'standard', 'size_eu': size, 'colour': colour}}
            for i, (size, colour) in enumerate([('38', 'brown'), ('39', 'brown'), ('39', 'black')])],
        'description': 'Native description', 'reviewCorpus': {'reviews': [{'text': 'Native comment'}]}}


def catalog():
    return {'siteId': 'shop', 'configuration': {'url': 'none'},
        'products': [page('first'), page('second')], 'initialAddress': {'unit': '24'}}


class OptionOrderControls(unittest.TestCase):
    def test_default_and_non_target_are_identity(self):
        original = catalog()
        for settings in [None, {'other': {'first': {}}}]:
            result, evidence = order.project_catalog(original, retailer_id='shop', settings=settings)
            self.assertIs(result, original);self.assertIsNone(evidence)

    def test_one_page_exact_inverse_and_no_mutable_aliases(self):
        original = catalog();copy = deepcopy(original)
        result, evidence = order.project_catalog(original, retailer_id='shop', settings={'shop': {'first': {}}})
        self.assertEqual([o['key'] for o in result['products'][0]['options']], ['width', 'colour', 'size_eu'])
        self.assertEqual(result['products'][1], original['products'][1])
        self.assertEqual(order.restore_catalog(result, evidence), original)
        self.assertEqual(original, copy)
        result['products'][1]['description'] = 'Changed copy'
        self.assertEqual(original['products'][1]['description'], 'Native description')

    def test_multiple_pages_preserve_every_tuple_and_review(self):
        original = catalog()
        result, evidence = order.project_catalog(original, retailer_id='shop', settings={'shop': {'first': {}, 'second': {}}})
        self.assertEqual(evidence['changed_pages'], ['first', 'second'])
        for before, after in zip(original['products'], result['products']):
            self.assertEqual(before['variants'], after['variants'])
            self.assertEqual(before['reviewCorpus'], after['reviewCorpus'])
        self.assertEqual(order.restore_catalog(result, evidence), original)

    def test_already_ordered_is_explicit_noop(self):
        original = catalog();axes = original['products'][0]['options'];axes[1], axes[2] = axes[2], axes[1]
        result, evidence = order.project_catalog(original, retailer_id='shop', settings={'shop': {'first': {}}})
        self.assertEqual(result, original);self.assertEqual(evidence['changed_pages'], [])

    def test_invalid_configs_and_unknown_targets_fail(self):
        invalid = [False, [], {}, {'': {'first': {}}}, {'shop': {}}, {'shop': {'': {}}},
            {'shop': {'first': 'colour'}}, {'shop': {'first': {'extra': 1}}},
            {'shop': {'first': {'size_key': 'colour'}}}, {'shop': {'first': {'size_key': True}}}]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):order.options(value)
        with self.assertRaises(ValueError):
            order.project_catalog(catalog(), retailer_id='shop', settings={'shop': {'absent': {}}})
        with self.assertRaises(ValueError):
            order.project_catalog(catalog(), retailer_id='shop', settings={'shop': {'first': {'size_key': 'missing'}}})

    def test_mutated_unrelated_content_breaks_inverse(self):
        result, evidence = order.project_catalog(catalog(), retailer_id='shop', settings={'shop': {'first': {}}})
        result['products'][1]['variants'][0]['priceMinor'] += 1
        with self.assertRaises(ValueError):order.restore_catalog(result, evidence)

    def test_declared_other_size_system_uses_existing_controls(self):
        original = catalog()
        for p in original['products']:
            p['options'][1]['key'] = 'size_label'
            for v in p['variants']:v['selection']['size_label'] = v['selection'].pop('size_eu')
        result, evidence = order.project_catalog(original, retailer_id='shop', settings={'shop': {'first': {'size_key': 'size_label'}}})
        self.assertEqual(order.restore_catalog(result, evidence), original)

    def test_preflight_rejects_duplicate_pages_and_incompatible_tuples(self):
        original = catalog();settings = {'shop': {'first': {}}}
        order.validate_catalog(original, retailer_id='shop', settings=settings)
        bad = deepcopy(original);bad['products'].append(deepcopy(bad['products'][0]))
        with self.assertRaises(ValueError):order.validate_catalog(bad, retailer_id='shop', settings=settings)
        bad = deepcopy(original);bad['products'][0]['variants'][0]['selection']['colour'] = 'red'
        with self.assertRaises(ValueError):order.validate_catalog(bad, retailer_id='shop', settings=settings)
        with self.assertRaises(ValueError):order.validate_catalog(original, retailer_id='shop', settings={'shop': {'unknown': {}}})

    def test_runtime_rejects_malformed_options_before_loading_pin(self):
        from environments.website_world.runtime import Runtime
        with self.assertRaises(ValueError):Runtime('/does-not-exist', page_option_order={'shop': {'first': {'size_key': True}}})

    def test_runtime_rejects_unknown_retailer_before_any_host(self):
        self._runtime_preflight_failure({'missing': {'first': {}}}, catalog())

    def test_runtime_rejects_unknown_page_before_unrelated_host(self):
        self._runtime_preflight_failure({'shop': {'unknown': {}}}, catalog())

    def test_runtime_rejects_ambiguous_native_page_before_any_host(self):
        original = catalog();original['products'].append(deepcopy(original['products'][0]))
        self._runtime_preflight_failure({'shop': {'first': {}}}, original)

    def _runtime_preflight_failure(self, settings, public):
        # Real Runtime constructor, bounded synthetic adapter; no world/servers.
        from environments.website_world import runtime
        world = {'world_id': 'control', 'seed': 1}
        adapter = SimpleNamespace(retailers={'unrelated': {'name': 'Unrelated'}, 'shop': {'name': 'Shop'}},
                                  catalog=lambda *a, **kw: deepcopy(public))
        with TemporaryDirectory() as temporary:
            pin = Path(temporary);(pin/'manifest.json').write_text(json.dumps({'schema_version': 'native-control'}))
            with patch.object(runtime, 'load_pin', return_value=(world, {})), \
                 patch.object(runtime, 'PublicAdapter', return_value=adapter), \
                 patch.object(runtime, 'site_plan', return_value={'config': {}}), \
                 patch.object(runtime, 'Host') as host:
                with self.assertRaises(ValueError):runtime.Runtime(pin, page_option_order=settings)
                host.assert_not_called()


if __name__ == '__main__':unittest.main()
