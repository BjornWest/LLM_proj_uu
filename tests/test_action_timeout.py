import ast
import unittest
from browsergym.core.action.highlevel import HighLevelActionSet
from intent_browser.actions import ACTION_NAMES, NAVIGATION_NAMES, action_function, make_action_set

class ActionTimeoutTests(unittest.TestCase):
    def test_default_and_override_only_selected_deadlines(self):
        for timeout in (500, 5000, 1200):
            mapping=make_action_set(ACTION_NAMES+NAVIGATION_NAMES,action_timeout_ms=timeout)
            tree=ast.parse(mapping.python_includes)
            functions={n.name:n for n in tree.body if isinstance(n,ast.FunctionDef)}
            for name in ('click','fill','check','uncheck','select_option','press'):
                values=[n.value.value for n in ast.walk(functions[name]) if isinstance(n,ast.keyword) and n.arg=='timeout' and isinstance(n.value,ast.Constant)]
                self.assertIn(timeout,values)
                self.assertNotIn(0 if name!='fill' else -1,values)
            # Helpers retain their original deadline; navigation/default sleeps untouched.
            self.assertIn('timeout=500',ast.unparse(functions['get_elem_by_bid']))
            self.assertNotIn('timeout=',ast.unparse(functions['goto']))
            self.assertIn('wait_ms',ast.unparse(functions['noop']))
            self.assertFalse(mapping.retry_with_force)
            self.assertEqual(mapping.timeout_metadata()['action_timeout_ms'],timeout)

    def test_legacy_exact_code_and_policy_catalog(self):
        old=HighLevelActionSet(subsets=['custom'],custom_actions=[action_function(n) for n in ACTION_NAMES],multiaction=False,strict=True)
        legacy=make_action_set(action_timeout_ms=500)
        current=make_action_set()
        self.assertEqual(old.to_python_code("click('7')"),legacy.to_python_code("click('7')"))
        self.assertEqual(old.describe(),current.describe())
        self.assertEqual(old.action_set,current.action_set)

    def test_invalid_values(self):
        for value in (True,0,-1,99,60001,5.0,'5000',None):
            with self.subTest(value=value),self.assertRaises(ValueError):make_action_set(action_timeout_ms=value)

if __name__=='__main__':unittest.main()
