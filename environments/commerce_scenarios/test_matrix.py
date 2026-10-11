"""Saved witness selection boundaries, before native readiness validation."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch
import unittest

from .matrix import pricing_candidates, _control_completed, run, VERSION


class Controls(unittest.TestCase):
    def world(self):
        return {'retailers': [{'retailer_id': 'shop', 'free_shipping_threshold_minor': 10000,
            'offers': [self.offer('small', 'cup', 2500), self.offer('large', 'cup', 3200),
                       self.offer('other', 'shoe', 2000), self.offer('unavailable', 'cup', 500)]}]}

    def offer(self, oid, pid, price):
        return {'offer_id': oid, 'product_id': pid, 'price_minor': price,
                'stock_by_source': {'branch': 0 if oid == 'unavailable' else 1}}

    def test_from_price_uses_available_cheaper_siblings_only(self):
        world = self.world()
        self.assertEqual(pricing_candidates(world, 'from_price_variant'), [('shop', {'offer_id': 'large'})])
        self.assertEqual(pricing_candidates(world, 'variant_condition'), [('shop', {'offer_id': 'large'})])
        world['retailers'][0]['offers'][0]['stock_by_source']['branch'] = 0
        self.assertEqual(pricing_candidates(world, 'from_price_variant'), [])

    def test_shipping_loss_crosses_existing_threshold_without_world_repairs(self):
        world = self.world()
        original = deepcopy(world)
        candidates = pricing_candidates(world, 'discount_shipping_loss')
        self.assertIn(('shop', {'offer_id': 'small', 'quantity': 4, 'discount_minor': 1}), candidates)
        for _, candidate in candidates:
            offer = next(o for o in world['retailers'][0]['offers'] if o['offer_id'] == candidate['offer_id'])
            subtotal = offer['price_minor'] * candidate['quantity']
            self.assertGreaterEqual(subtotal, 10000)
            self.assertLess(subtotal-candidate['discount_minor'], 10000)
            self.assertLessEqual(candidate['quantity'], 5)
        self.assertEqual(world, original)
        world['retailers'][0]['free_shipping_threshold_minor'] = None
        self.assertEqual(pricing_candidates(world, 'discount_shipping_loss'), [])

    def test_explicit_preparation_parameters_preserve_all_prices(self):
        world = self.world()
        candidates = pricing_candidates(world, 'truthful_offer')
        self.assertEqual(len(candidates), 3)
        self.assertTrue(all(set(p) == {'offer_id'} for _, p in candidates))
        self.assertFalse(any(p['offer_id'] == 'unavailable' for _, p in candidates))


class CompletionControls(unittest.TestCase):
    def result(self, *, status='fail', stop='agent_finished', truncated=False):
        return {'policy_summary': {'stop_reason': stop, 'truncated': truncated, 'error': None, 'cleanup_errors': []},
                'publication': {'status': status, 'control_matches_expectation': True}}

    def test_expected_native_fail_cannot_accept_a_capped_driver(self):
        for stop in ('max_steps', 'max_input_tokens', 'execution_error', None):
            with self.subTest(stop=stop):
                self.assertFalse(_control_completed(self.result(stop=stop, truncated=True)))
        self.assertFalse(_control_completed(self.result(truncated=True)))
        self.assertFalse(_control_completed({'publication': self.result()['publication']}))
        for key in ('policy_execution_error', 'execution_error', 'cleanup_error', 'error'):
            value = self.result()
            value['policy_summary'][key] = 'retained failure'
            self.assertFalse(_control_completed(value))
        for errors in (['Runtime cleanup failed'], 'malformed', None, False):
            value = self.result()
            value['policy_summary']['cleanup_errors'] = errors
            self.assertFalse(_control_completed(value))

    def test_clean_positive_wrong_and_genuine_no_session_keep_native_outcomes(self):
        for status in ('pass', 'fail', 'inconclusive'):
            with self.subTest(status=status):
                self.assertTrue(_control_completed(self.result(status=status)))

    def test_matrix_consumes_explicit_target_and_rejects_capped_wrong_control(self):
        from . import publication
        with TemporaryDirectory() as temp:
            root = Path(temp)
            world = root/'world'
            (world/'pin').mkdir(parents=True)
            (world/'pin/world.private.json').write_text('{}')
            instance = root/'instance.json'
            instance.write_text('{}')
            instance_pin = sha256(instance.read_bytes()).hexdigest()
            row = {'family': 'consent_extras', 'mechanism': 'paid_membership',
                   'case': 'wrong', 'instance': instance.name, 'sha256': instance_pin,
                   'expected': 'fail'}
            config = {k: row[k] for k in ('family', 'mechanism', 'case')}
            prepared = SimpleNamespace(config=config, instance_sha256=instance_pin,
                                       policy=lambda page: None, close=Mock())
            matrix = {'schema': VERSION, 'world_dir': str(world),
                      'world_sha256': sha256((world/'pin/world.private.json').read_bytes()).hexdigest(),
                      'families': ['consent_extras'], 'cases': [row], 'unsupported': []}
            path = root/'matrix.json'
            def execute(name, result):
                path.write_text(json.dumps(matrix))
                with patch.object(publication, 'prepare_episode', return_value=prepared) as prepare, \
                     patch.object(publication, 'run_saved', return_value=result):
                    answer = run(path, root/name)
                prepared.close.assert_called()
                return answer, prepare
            answer, prepare = execute('capped', self.result(stop='max_steps', truncated=True))
            self.assertFalse(answer['all_selected_controls_pass'])
            self.assertFalse(answer['results'][0]['control_completed'])
            prepare.assert_called_once_with(str(world), instance, 'wrong')
            row['offer_id'] = 'shop/exact-offer'
            config['offer_id'] = row['offer_id']
            answer, prepare = execute('explicit', self.result())
            self.assertTrue(answer['all_selected_controls_pass'])
            prepare.assert_called_once_with(str(world), instance, 'wrong', offer_id=row['offer_id'])
            config['offer_id'] = 'shop/different-offer'
            answer, _ = execute('mismatched', self.result())
            self.assertFalse(answer['all_selected_controls_pass'])
            self.assertIn('Prepared episode differs', answer['results'][0]['system_error'])


if __name__ == '__main__':
    unittest.main()
