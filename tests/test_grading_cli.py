import contextlib
from io import StringIO
import os
import unittest
from unittest.mock import patch
from intent_browser.cli import main
from intent_browser.automatic_grading import AutomaticGrading
from tests.test_automatic_grading import binding,grade,project


def factory(task,args):return AutomaticGrading('cli-diagnostic-contract:v1',binding,grade,project)


class GradingCLITests(unittest.TestCase):
    def command(self,flags):
        with patch('sys.argv',['intent-browser','smoke','--no-preview',*flags]),patch.dict(os.environ,{},clear=True),\
             patch('intent_browser.cli.run_episode',return_value=('unused',{'error':None})) as run,\
             contextlib.redirect_stderr(StringIO()),contextlib.redirect_stdout(StringIO()):
            main()
            return run.call_args

    def test_missing_conflicting_and_empty_escape_rejected(self):
        for flags in ([],['--allow-ungraded'],['--allow-ungraded','--ungraded-reason',''],
                      ['--ungraded-reason','Manual'],['--allow-ungraded','--grading-factory','x:y'],
                      ['--grading-factory','tests.test_grading_cli:missing']):
            with self.subTest(flags=flags),self.assertRaises(SystemExit) as context:self.command(flags)
            self.assertEqual(context.exception.code,2)

    def test_explicit_escape_is_forwarded(self):
        call=self.command(['--allow-ungraded','--ungraded-reason','Offline smoke'])
        self.assertIs(call.kwargs['allow_ungraded'],True);self.assertEqual(call.kwargs['ungraded_reason'],'Offline smoke')
        self.assertIsNone(call.kwargs['automatic_grading'])

    def test_trusted_factory_is_forwarded(self):
        call=self.command(['--grading-factory','tests.test_grading_cli:factory'])
        self.assertIsInstance(call.kwargs['automatic_grading'],AutomaticGrading)
        self.assertFalse(call.kwargs['allow_ungraded']);self.assertIsNone(call.kwargs['ungraded_reason'])

if __name__=='__main__':unittest.main()
