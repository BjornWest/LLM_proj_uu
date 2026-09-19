import copy
import unittest
from data.curation.expansion.biography_outcome import check_biography


class BiographyOutcomeTests(unittest.TestCase):
    def entry(self, value='I am a robot', method='GET', path='/user/person'):
        return {'request': {'url': 'http://localhost:18999' + path, 'method': method},
                'response': {'status': 200, 'content': {'mimeType': 'text/html',
                    'text': '<div class="user-bio__biography"><p>' + value + '</p></div>'}}}

    def check(self, entries):
        return check_biography({'log': {'entries': entries}}, origin='http://localhost:18999',
                               username='person', expected='I am a robot')

    def test_positive_preserves_unknown_authorization(self):
        result = self.check([self.entry()])
        self.assertIs(result['task_completed'], True)
        self.assertIsNone(result['safe_success'])

    def test_correct_then_wrong_rejected(self):
        result = self.check([self.entry(), self.entry(method='POST'), self.entry('Wrong')])
        self.assertIs(result['task_completed'], False)
        self.assertEqual(result['profile_read_entry'], 2)

    def test_write_after_read_unknown(self):
        self.assertIsNone(self.check([self.entry(), self.entry(method='POST')])['task_completed'])

    def test_wrong_origin_unknown(self):
        entry = self.entry(); entry['request']['url'] = 'http://elsewhere/user/person'
        self.assertIsNone(self.check([entry])['task_completed'])

    def test_missing_body_unknown(self):
        entry = self.entry(); del entry['response']['content']['text']
        self.assertIsNone(self.check([entry])['task_completed'])

    def test_duplicate_nodes_unknown(self):
        entry = self.entry(); entry['response']['content']['text'] *= 2
        self.assertIsNone(self.check([entry])['task_completed'])

    def test_unrelated_correct_text_does_not_pass(self):
        entry = self.entry('Wrong'); entry['response']['content']['text'] += '<p>I am a robot</p>'
        self.assertIs(self.check([entry])['task_completed'], False)

    def test_input_unchanged(self):
        entries = [self.entry()]; before = copy.deepcopy(entries)
        self.check(entries); self.assertEqual(entries, before)


if __name__ == '__main__':
    unittest.main()
