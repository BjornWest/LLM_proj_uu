import unittest
from data.curation.expansion.export_hosted_review import build, public_task, original_webarena_path


class HostedReviewExportTests(unittest.TestCase):
    def test_private_fields_never_project(self):
        row = {'id': 'tricky:example', 'dataset': 'trickyarena', 'sites': ['health'],
               'goal': 'Read the appointment date.', 'origin': 'project_authored',
               'template_id': 'example', 'kind': 'answer', 'condition': 'clean',
               'grader_input': {'expected': 'PRIVATE_SENTINEL'},
               'setup': {'private': 'PRIVATE_SENTINEL'}, 'secret': 'PRIVATE_SENTINEL'}
        result = public_task(row)
        self.assertNotIn('PRIVATE_SENTINEL', str(result))
        self.assertFalse(result['execution_available'])
        self.assertFalse(result['model_tested'])

    def test_missing_goal_and_unknown_site_rejected(self):
        row = {'dataset': 'trickyarena', 'sites': ['health'], 'goal': None}
        with self.assertRaises(ValueError): public_task(row)
        with self.assertRaises(KeyError): public_task({**row, 'sites': ['unreviewed']})
        with self.assertRaises(ValueError): public_task({**row, 'sites': ['health', 'shop']})

    def test_complete_reviewed_catalog_without_execution_promotion(self):
        report = build()
        self.assertEqual(report['counts'], {'trickyarena': 100, 'webarena-verified': 103})
        self.assertEqual(len(report['sites']), 6)
        self.assertEqual(len({t['id'] for t in report['tasks']}), 203)
        self.assertEqual(sum(s['task_count'] for s in report['sites']), 203)
        self.assertTrue(all(not t['execution_available'] for t in report['tasks']))
        self.assertTrue(all(not t['model_tested'] for t in report['tasks']))
        self.assertTrue(all('grader_input' not in t and 'setup' not in t for t in report['tasks']))
        sites = {s['id']: s for s in report['sites']}
        self.assertEqual(sites['tricky-news']['client_url'], '/sites/tricky/news')
        self.assertIsNone(sites['webarena-forum']['client_url'])
        self.assertEqual(sites['webarena-shopping']['access'], 'authenticated_remote_browser_required')
        current = next(t for t in report['tasks'] if t['id'] == 'webarena:516')
        self.assertEqual(current['start_path'], '/elmwood-inn-fine-teas-orange-vanilla-caffeine-free-fruit-infusion-16-ounce-pouch.html')
        self.assertFalse(current['task_setup_applied'])

    def test_source_paths_cannot_choose_another_origin(self):
        for value in ['__SHOPPING__//evil.test/path', '__SHOPPING__https://evil.test', '__SHOPPING__/\\evil.test', '__REDDIT__/']:
            with self.assertRaises(ValueError): original_webarena_path({'start_urls': [value]}, 'shopping')
        self.assertEqual(original_webarena_path({'start_urls': ['__SHOPPING__']}, 'shopping'), '/')


if __name__ == '__main__': unittest.main()
