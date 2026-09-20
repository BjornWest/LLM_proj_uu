import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from scripts.project_worker_trace import project, VENDOR


class WorkerTraceProjectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def archive(self, members):
        archive = self.root / 'trace.zip'
        with zipfile.ZipFile(archive, 'w') as out:
            for name, raw in members:
                out.writestr(name, raw)
        return archive

    def test_projection_preserves_missing_tool_response_and_nulls(self):
        response = {'choices': [{'finish_reason': 'tool_calls', 'message': {
            'content': '\n\n', 'reasoning': 'Inspect March orders'}}]}
        members = [('episode/metadata.json', json.dumps({'episode_id': 'episode', 'browsergym_version': 'test'})),
                   ('episode/episode.json', '{}'), ('episode/events.jsonl', ''),
                   ('episode/steps.jsonl', json.dumps({'step': 0, 'model_response': response,
                    'error': 'Expected exactly one native tool call', 'browser_stepped': False}) + '\n'),
                   ('episode/evaluation.json', json.dumps({'safe_success': None}))]
        output = self.root / 'bundle'
        project(self.archive(members), output)
        session = json.loads((output / 'session.json').read_text())
        responses = [m for m in session['messages'] if m['title'] == 'Raw model response']
        self.assertEqual(json.loads(responses[0]['text']), response)
        self.assertIsNone(json.loads((output / 'manifest.json').read_text())['raw_outcomes']['safe_success'])
        with self.assertRaises(FileExistsError):
            project(self.root / 'trace.zip', output)

    def test_unsafe_archive_paths_and_member_types(self):
        names = ['../escape', '/tmp/escape', 'a/../escape', 'a//escape', 'a\\b', 'a/x\x00y']
        for name in names:
            with self.subTest(name=name):
                # zipfile truncates NUL itself; test a duplicate produced by that truncation.
                entries = [(name, 'x')]
                if '\x00' in name:
                    entries.append((name.split('\x00')[0], 'y'))
                with self.assertRaises(ValueError):
                    project(self.archive(entries), self.root / ('out-' + hashlib.sha256(name.encode()).hexdigest()))
        for kind in [0o120777, 0o040777]:
            with self.subTest(mode=kind):
                info = zipfile.ZipInfo('episode/link'); info.external_attr = kind << 16
                with self.assertRaises(ValueError):
                    project(self.archive([(info, '/etc/passwd')]), self.root / str(kind))

    def test_duplicate_and_multiple_episodes_rejected(self):
        for i, members in enumerate([[('a/file', 'x'), ('a/file', 'y')], [('a/file', 'x'), ('b/file', 'y')]]):
            with self.assertRaises(ValueError):
                project(self.archive(members), self.root / str(i))

    def test_vendor_matches_pinned_source(self):
        provenance = json.loads((VENDOR / 'agent_trace/projection-provenance.json').read_text())
        for name, digest in provenance['files'].items():
            self.assertEqual(hashlib.sha256((VENDOR / 'agent_trace' / name).read_bytes()).hexdigest(), digest)


if __name__ == '__main__':
    unittest.main()
