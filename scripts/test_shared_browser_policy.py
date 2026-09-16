import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from shared_browser_policy import parse_reply,messages_for
from unittest.mock import patch

class PolicyTests(unittest.TestCase):
    def test_literal_action_and_answer(self):
        self.assertEqual(parse_reply('{"action":"click(\\"12\\")"}').code,"click('12')")
        self.assertEqual(parse_reply('{"action":"send_msg_to_user(\\"Actual answer\\")"}').arguments['text'],'Actual answer')
    def test_no_python_or_plain_answer_repair(self):
        for text in ['I have all the information','{"action":"eval(\\"bad\\")"}','{"action":"click(str(2))"}','{"action":"click(\\"1\\");click(\\"2\\")"}','{"action":"click(\\"1\\")","extra":1}']:
            with self.subTest(text=text),self.assertRaises((ValueError,SyntaxError)):parse_reply(text)
    def test_goal_separate_from_reference_and_history_bounded(self):
        with patch('shared_browser_policy.observation_text',return_value='fresh AX'):
            messages=messages_for({'goal':'PRIVATE REFERENCE'},'My question',[{'action':str(i)} for i in range(30)])
        self.assertNotIn('PRIVATE REFERENCE',str(messages))
        self.assertIn('My question',messages[-1]['content'])
        self.assertNotIn('"action": "0"',messages[-1]['content'])
        self.assertIn('fresh AX',messages[-1]['content'])
if __name__=='__main__':unittest.main()
