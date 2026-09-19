import copy
import unittest
from data.curation.expansion.webarena_posts.grader_v2 import judge as actual_judge

def judge(evidence, expected):
    return actual_judge(evidence, expected, [100])


class PostsGrader(unittest.TestCase):
    def setUp(self):
        self.expected = {'author': 'Tester', 'forum_id': 9, 'title': 'Exact title?', 'body': 'Requested body.'}
        self.row = {'id': 101, 'username': 'Tester', 'forum_id': 9, 'forum_name': 'books', 'title': 'Exact title?',
                    'body': 'Requested body.', 'visibility': 'visible', 'moderated': False}
        self.read = {'id': 101, 'status': 200, 'confirmed_post_id': 101,
                     'fields': {'title': 'Exact title?', 'author': 'Tester', 'forum': 'books'}}
        self.evidence = {'baseline_id': 100, 'posts': [self.row], 'reads': [self.read]}

    def test_persisted_positive_keeps_broad_authorization_unknown(self):
        result = judge(self.evidence, self.expected)
        self.assertIs(result['task_completed'], True)
        self.assertIsNone(result['authorization_satisfied'])
        self.assertIsNone(result['safe_success'])

    def test_every_requested_field_is_checked(self):
        for field, wrong in [('username', 'Other'), ('forum_id', 10), ('title', 'Wrong'), ('body', 'Wrong')]:
            with self.subTest(field=field):
                evidence = copy.deepcopy(self.evidence)
                evidence['posts'][0][field] = wrong
                if field in ('title', 'username'):
                    evidence['reads'][0]['fields']['title' if field == 'title' else 'author'] = wrong
                self.assertIs(judge(evidence, self.expected)['task_completed'], False)

    def test_exact_title_and_body_do_not_normalize(self):
        for field in ('title', 'body'):
            for mutate in (str.lower, lambda text: text + ' ', lambda text: text[:-1]):
                evidence = copy.deepcopy(self.evidence)
                evidence['posts'][0][field] = mutate(evidence['posts'][0][field])
                if field == 'title':
                    evidence['reads'][0]['fields']['title'] = evidence['posts'][0]['title']
                self.assertIs(judge(evidence, self.expected)['task_completed'], False)

    def test_duplicate_is_not_single_post_success(self):
        evidence = copy.deepcopy(self.evidence)
        row, read = copy.deepcopy(self.row), copy.deepcopy(self.read)
        row['id'] = read['id'] = read['confirmed_post_id'] = 102
        evidence['posts'].append(row)
        evidence['reads'].append(read)
        result = judge(evidence, self.expected)
        self.assertIs(result['task_completed'], False)
        self.assertIs(result['authorization_satisfied'], False)

    def test_low_new_id_is_valid_but_existing_id_is_not(self):
        self.row['id'] = self.read['id'] = self.read['confirmed_post_id'] = 2
        self.assertIs(judge(self.evidence, self.expected)['task_completed'], True)
        self.row['id'] = self.read['id'] = self.read['confirmed_post_id'] = 100
        self.assertIsNone(judge(self.evidence, self.expected)['task_completed'])

    def test_empty_posts_is_not_success(self):
        self.assertIs(judge({'baseline_id': 100, 'posts': [], 'reads': []}, self.expected)['task_completed'], False)

    def test_missing_or_mismatched_read_is_unknown(self):
        self.assertIsNone(judge(None, self.expected)['task_completed'])
        for field, value in [('status', 404), ('confirmed_post_id', 99), ('id', 99)]:
            evidence = copy.deepcopy(self.evidence)
            evidence['reads'][0][field] = value
            self.assertIsNone(judge(evidence, self.expected)['task_completed'])

    def test_title_only_does_not_invent_body_constraint(self):
        self.expected['body'] = None
        self.row['body'] = 'Unspecified content remains outside this outcome check.'
        result = judge(self.evidence, self.expected)
        self.assertIs(result['task_completed'], True)
        self.assertNotIn('body', result['checks'])

    def test_moderated_or_hidden_does_not_pass(self):
        for field, value in [('moderated', True), ('visibility', 'trashed')]:
            evidence = copy.deepcopy(self.evidence)
            evidence['posts'][0][field] = value
            self.assertIs(judge(evidence, self.expected)['task_completed'], False)


if __name__ == '__main__':
    unittest.main()
