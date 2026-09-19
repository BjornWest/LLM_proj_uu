import unittest
from intent_browser.actions import ACTION_NAMES, NAVIGATION_NAMES, make_action_set, parse_decision
from intent_browser.harness import BrowserTools, native_tools_profile
from intent_browser.navigation import origin, validate_origins, validate_url
from tests.test_native_tools import completion, response


class NavigationTests(unittest.TestCase):
    def test_legacy_catalog_and_parser_stay_closed(self):
        self.assertEqual(native_tools_profile().tools.names, ACTION_NAMES)
        for name in NAVIGATION_NAMES:
            with self.assertRaises(ValueError):
                parse_decision(name + "('http://localhost')" if name == 'goto' else name + '()')
            with self.assertRaises(ValueError):
                BrowserTools(names=(name,))

    def test_native_shapes_and_action_mapping(self):
        profile = native_tools_profile(navigation_origins=('http://localhost:7770',))
        self.assertEqual(profile.name, 'core-tools-v4-navigation')
        mapping = make_action_set(profile.tools.names)
        for name in NAVIGATION_NAMES:
            args = {'url': 'http://localhost:7770/catalog?p=2#reviews'} if name == 'goto' else {}
            decision, _ = profile.tools.parse_completion(completion(response(name, args)))
            self.assertEqual(decision.name, name)
            self.assertTrue(mapping.to_python_code(decision.code).rstrip().endswith(decision.code))
        self.assertIn('http://localhost:7770', str(profile.describe()))

    def test_origins_are_exact_not_prefixes_or_subdomains(self):
        allowed = validate_origins(('http://localhost:7770', 'https://example.test'))
        for url in ('http://localhost:7770/one', 'https://EXAMPLE.test:443/two?q=3'):
            validate_url(url, allowed)
        for url in ('http://localhost:7771/', 'https://localhost:7770/',
                    'http://localhost:7770.evil.test/', 'https://evil.example.test/',
                    'https://example.test.evil/', 'https://example.test@evil.test/',
                    'https://user:password@example.test/', '//example.test/', '/relative',
                    'javascript:alert(1)', 'file:///tmp/a', 'data:text/html,hello',
                    'https://example.test\\@evil.test/', 'https://example.test/\nfoo'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_url(url, allowed)
        self.assertEqual(origin('http://localhost:0'), 'http://localhost:0')

    def test_reject_path_allowlist_and_disallowed_native_goto(self):
        for values in ((), ['https://example.test'], ('https://example.test/private',)):
            with self.assertRaises(ValueError):
                validate_origins(values)
        tools = native_tools_profile(navigation_origins=('https://example.test',)).tools
        for url in ('https://example.test.evil', 'file:///etc/passwd'):
            with self.assertRaises(ValueError):
                tools.parse_completion(completion(response('goto', {'url': url})))
        with self.assertRaises(Exception):
            tools.parse_completion(completion(response('go_back', {'bid': '1'})))


if __name__ == '__main__':
    unittest.main()
