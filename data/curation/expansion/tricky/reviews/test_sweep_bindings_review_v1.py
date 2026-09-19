"""Offline regression checks over the frozen v3 invocation export."""
import ast
import copy
import unittest
from data.curation.expansion.tricky.reviews.audit_sweep_bindings_v1 import ROOT, load


class SweepBindingReview(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.export = load('.local/curation-expansion/sweep-inputs-170-v3.json')
        cls.rows = {row['id']: row for row in cls.export['tasks']}
        source = ast.parse((ROOT / cls.export['builder']['path']).read_text())
        function = next(node for node in source.body if isinstance(node, ast.FunctionDef) and node.name == 'policy_projection')
        namespace = {}
        exec(compile(ast.Module(body=[function], type_ignores=[]), '<projection-only>', 'exec'), namespace)
        cls.project = staticmethod(namespace['policy_projection'])

    def test_private_fields_cannot_be_forwarded(self):
        for row in self.rows.values():
            changed = copy.deepcopy(row)
            changed['grader_input'] = {'answer': 'PRIVATE_SENTINEL'}
            changed['evaluation'] = {'safe_success': True}
            changed['policy_input']['unexpected_private_field'] = 'PRIVATE_SENTINEL'
            self.assertEqual(self.project(changed), self.project(row))
            self.assertEqual(set(self.project(row)), {'goal', 'terminal_response_instruction'})

    def test_missing_goal_has_no_grader_fallback(self):
        for value in (None, '', '   ', 123):
            row = copy.deepcopy(self.rows['tricky:AU01'])
            row['policy_input']['goal'] = value
            with self.assertRaises(ValueError):
                self.project(row)

    def test_first_authored_cap_and_strict_draft_adapters(self):
        for number in range(1, 80):
            row = self.rows[f'tricky:AU{number:02}']
            self.assertEqual(row['validation_profile']['max_steps'], 24 if number <= 20 else 28)
        for number in (46, 47, 51, 52):
            self.assertTrue(self.rows[f'tricky:AU{number}']['implementation']['factory']['module'].endswith('authored03.native_v2'))

    def test_required_runtime_activation_precedes_import(self):
        for number in (399, 407, 689, 690, 691, 692, 693):
            row = self.rows[f'webarena:{number}']
            activation = row['implementation']['pre_import_runtime_activation']
            self.assertIs(activation['required'], True)
            self.assertEqual(activation['environment_variable'], 'CURATION_FROZEN_RUNTIME')
            self.assertEqual(activation['helper']['symbol'], 'activate')
            self.assertIn('Before importing', activation['timing'])
            self.assertIs(row['reference_runtime_for_new_offline_profile']['historical_execution_identity'], False)

    def test_constructor_argument_names(self):
        inherited = {'NativeLookup': ('data/curation/expansion/tricky/lookup_tasks.py', 'LookupTask'),
                     'NativeAction': ('data/curation/expansion/tricky/batch02/tasks.py', 'ActionTask')}
        for row in self.rows.values():
            impl = row['implementation']
            if 'factory' not in impl:
                continue
            factory = impl['factory']
            source, name = inherited.get(factory['symbol'], (factory['source']['path'], factory['symbol']))
            tree = ast.parse((ROOT / source).read_text())
            klass = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == name)
            init = next(node for node in klass.body if isinstance(node, ast.FunctionDef) and node.name == '__init__')
            positional = {arg.arg for arg in init.args.args if arg.arg != 'self'}
            provided = set(impl.get('constructor_kwargs', impl.get('constructor_bindings', {})))
            self.assertEqual(provided, positional, row['id'])

    def test_unknown_safety_and_held_votes_not_promoted(self):
        for number in (404, 405, 406, 408):
            self.assertNotIn(f'webarena:{number}', self.rows)
        self.assertIn('webarena:407', self.rows)
        for row in self.rows.values():
            for key in ('new_execution_ready', 'model_tested', 'training_eligible', 'production_ready'):
                self.assertIs(row[key], False)
            self.assertNotIn('safe_success', row)
            self.assertNotIn('authorization_satisfied', row)


if __name__ == '__main__':
    unittest.main()
