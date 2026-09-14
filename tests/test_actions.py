import unittest

from intent_browser.actions import parse_action


class ActionParsingTests(unittest.TestCase):
    def test_literals_and_quotes(self):
        self.assertEqual(parse_action('fill("12", "O\'Brien")'), 'fill(\'12\', "O\'Brien")')
        self.assertEqual(parse_action("```python\nclick('12')\n```"), "click('12')")
        self.assertEqual(parse_action("uncheck('42')"), "uncheck('42')")

    def test_rejects_executable_python_and_multiple_actions(self):
        for text in ["__import__('os').system('id')", "click(str(12))", "click('1'); click('2')",
                     "[click('1'), click('2')]", "click(**{'bid':'1'})", "goto('https://example.com')",
                     "noop(99999999)", "click()", "click('1', unexpected=True)"]:
            with self.subTest(text=text), self.assertRaises((ValueError, SyntaxError, TypeError)):
                parse_action(text)


if __name__ == "__main__":
    unittest.main()
