"""Offline action-boundary checks; imports no BrowserGym or model backend."""
import ast
import math
import unittest
from manual_environment import action_code

class ManualActionTests(unittest.TestCase):
    def test_only_native_action_calls(self):
        examples = [({'type':'click','x':0,'y':719},'mouse_click'),
                    ({'type':'scroll','dx':-500,'dy':500},'scroll'),
                    ({'type':'press','key':'ArrowDown'},'keyboard_press'),
                    ({'type':'type','text':"'); danger(); #\n☃"},'keyboard_insert_text')]
        for value, name in examples:
            with self.subTest(value=value):
                parsed=ast.parse(action_code(value,1280,720)).body
                self.assertEqual(len(parsed),1);self.assertEqual(parsed[0].value.func.id,name)
                self.assertTrue(all(isinstance(arg, (ast.Constant, ast.UnaryOp)) for arg in parsed[0].value.args))
        self.assertEqual(ast.literal_eval(ast.parse(action_code(examples[-1][0],1280,720)).body[0].value.args[0]),examples[-1][0]['text'])
    def test_reject_unsupported_and_unbounded_inputs(self):
        invalid=[{},None,{'type':'eval','code':'x'}, {'type':'press','key':'ControlOrMeta+l'},
            {'type':'click','x':True,'y':0}, {'type':'click','x':1280,'y':0},
            {'type':'click','x':0,'y':720}, {'type':'click','x':-1,'y':0},
            {'type':'scroll','dx':0,'dy':501}, {'type':'scroll','dx':0,'dy':math.nan},
            {'type':'type','text':'x'*1001},{'type':'type','text':''},
            {'type':'click','x':0,'y':0,'script':'evil'}]
        for value in invalid:
            with self.subTest(value=value),self.assertRaises(ValueError):action_code(value,1280,720)
    def test_documented_boundary_values(self):
        for key in ['Tab','Enter','Escape','Backspace','ArrowUp','ArrowDown','ArrowLeft','ArrowRight']:
            self.assertTrue(action_code({'type':'press','key':key},1280,720))
        self.assertTrue(action_code({'type':'type','text':'a'*1000},1280,720))

if __name__=='__main__':unittest.main()
