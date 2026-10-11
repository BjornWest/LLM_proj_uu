"""Routing/control tests; synthetic family callbacks, never browser evidence."""
import unittest
from unittest.mock import Mock, patch
from . import registry


class RegistryTests(unittest.TestCase):
    def test_every_mechanism_has_one_owned_family(self):
        self.assertEqual(len(registry.MECHANISMS), sum(map(len, registry.FAMILIES.values())))
        self.assertEqual(len(registry.MECHANISMS), 24)
        for mechanism, family in registry.MECHANISMS.items():
            with self.subTest(mechanism=mechanism):
                module = Mock()
                module.prepare.return_value = {'binding': {'native': True}, 'task': {}}
                with patch.object(registry, 'import_module', return_value=module) as imported:
                    instance = registry.prepare(5, mechanism=mechanism)
                imported.assert_called_once_with('.' + family, registry.__package__)
                self.assertEqual(instance['prepared']['binding'], {'native': True})
                self.assertEqual(instance['family'], family)

    def test_public_input_rejects_before_native_call(self):
        with patch.object(registry, 'import_module') as imported:
            for values in ({'seed': True}, {'seed': -1}, {'seed': 2**63},
                           {'parameters': []}, {'user_message': ''}, {'mechanism': 'unknown'}):
                with self.subTest(values=values), self.assertRaises(ValueError):
                    registry.prepare(**{'seed': 5, 'mechanism': 'paid_warranty', **values})
            imported.assert_not_called()

    def test_no_mutation_and_no_implicit_quote_outside_pricing(self):
        module = Mock()
        module.prepare.return_value = {'binding': {'task': 'fixed'}}
        parameters = {'control': 'required'}
        with patch.object(registry, 'import_module', return_value=module):
            instance = registry.prepare(5, mechanism='paid_warranty', parameters=parameters)
            module.prepare.call_args.kwargs['parameters']['control'] = 'changed'
            self.assertEqual(parameters, {'control': 'required'})
            module.grade.return_value = {'status': 'inconclusive', 'checks': {}}
            self.assertEqual(registry.grade(instance, None)['status'], 'inconclusive')
            with self.assertRaises(ValueError): registry.quote(instance)

    def test_routing_corruption_and_nonfinite_native_result_reject(self):
        module = Mock()
        module.prepare.return_value = {}
        with patch.object(registry, 'import_module', return_value=module):
            instance = registry.prepare(5, mechanism='cookie_asymmetric')
            instance['family'] = 'pricing_promotions'
            with self.assertRaises(ValueError): registry.grade(instance, {})
            instance['family'] = 'consent_extras'
            module.grade.return_value = {'status': 'pass', 'value': float('nan')}
            with self.assertRaises(ValueError): registry.grade(instance, {})

    def test_canonical_projection_keeps_missing_capture_unknown(self):
        for status, completed in [('pass', True), ('fail', False), ('inconclusive', None)]:
            result = registry.project({'status': status}).to_dict()
            self.assertIs(result['task_completed'], completed)
            self.assertIsNone(result['authorization_satisfied'])
            self.assertIsNone(result['unauthorized_effects'])
            self.assertIs(result['safe_success'], False if completed is False else None)


if __name__ == '__main__': unittest.main()
