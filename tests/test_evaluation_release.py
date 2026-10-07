"""Small temporary Git fixtures; no real ledger, browser, model or source writes."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

spec = importlib.util.spec_from_file_location(
    'evaluation_release', Path(__file__).parents[1] / 'scripts/evaluation_release.py')
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class ReleaseTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root / 'development'
        self.repo.mkdir()
        release.git(self.repo, 'init')
        release.git(self.repo, 'config', 'user.name', 'Fixture')
        release.git(self.repo, 'config', 'user.email', 'fixture@example.invalid')
        (self.repo / 'main.txt').write_text('original\n')
        release.git(self.repo, 'add', 'main.txt')
        release.git(self.repo, 'commit', '-m', 'fixture')
        (self.repo / 'main.txt').write_text('staged change\n')
        release.git(self.repo, 'add', 'main.txt')
        (self.repo / 'main.txt').write_text('unstaged change\n')
        self.before = (release.git(self.repo, 'rev-parse', 'HEAD'),
                       release.git(self.repo, 'diff', '--cached'),
                       release.git(self.repo, 'diff'))
        self.sources = self.root / 'sources'
        self.sources.mkdir()
        self.files = {}
        for name in (*release.REQUIRED_ASSETS, 'package.py'):
            path = self.sources / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('fixture: ' + name)
            self.files[name] = {'source': str(path), 'sha256': release.digest(path)}
        self.worktree = self.root / 'candidate'

    def build(self, files=None):
        return release.write_candidate(self.repo, files=files or self.files,
            metadata={'fixture_only': True}, ref='refs/heads/eval-candidates/fixture',
            worktree=self.worktree, receipt=self.root / 'candidate.json')

    def proof(self, commit):
        artifact = self.root / 'scripted-fixture.json'
        release.save_new(artifact, {'fixture_only': True})
        record = release.pin(artifact)
        proof = {'schema': 1, 'commit': commit, 'worktree': str(self.worktree),
                 'model_requests': 0, 'environment': record,
                 'cases': [{'task_id': 'fixture', 'recipe': record, 'authority': record,
                            'checks': {stage: {'status': 'pass', 'artifact': record}
                                       for stage in release.STAGES}}]}
        return proof

    def test_development_head_index_and_unstaged_bytes_unchanged(self):
        result = self.build()
        after = (release.git(self.repo, 'rev-parse', 'HEAD'),
                 release.git(self.repo, 'diff', '--cached'), release.git(self.repo, 'diff'))
        self.assertEqual(self.before, after)
        self.assertEqual(result['source_count'], 3)
        self.assertFalse(result['model_dispatch_released'])
        self.assertNotEqual(release.commit_id(self.worktree, 'HEAD'),
                            release.commit_id(self.repo, 'HEAD'))

    def test_missing_chat_asset_blocks_creation(self):
        files = dict(self.files)
        del files[release.REQUIRED_ASSETS[0]]
        with self.assertRaisesRegex(ValueError, 'asset omitted'):
            self.build(files)
        self.assertFalse(self.worktree.exists())

    def test_changed_asset_rejects_before_commit(self):
        (self.sources / release.REQUIRED_ASSETS[0]).write_text('drift')
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.build()

    def test_source_candidate_is_not_runtime_certificate(self):
        self.build()
        with self.assertRaisesRegex(ValueError, 'readiness'):
            release.require_ready(self.worktree, self.root / 'candidate.json')

    def test_actual_smoke_stage_is_required(self):
        result = self.build()
        proof = self.proof(result['commit'])
        del proof['cases'][0]['checks']['browser_reset']
        release.save_new(self.root / 'proof.json', proof)
        with self.assertRaisesRegex(ValueError, 'browser_reset'):
            release.certify(self.worktree, self.root / 'proof.json', self.root / 'ready.json')

    def test_foreign_commit_smoke_rejected(self):
        result = self.build()
        proof = self.proof('0' * 40)
        release.save_new(self.root / 'proof.json', proof)
        with self.assertRaisesRegex(ValueError, 'exact worktree'):
            release.certify(self.worktree, self.root / 'proof.json', self.root / 'ready.json')

    def test_changed_grade_evidence_invalidates_readiness(self):
        result = self.build()
        release.save_new(self.root / 'proof.json', self.proof(result['commit']))
        release.certify(self.worktree, self.root / 'proof.json', self.root / 'ready.json')
        release.require_ready(self.worktree, self.root / 'ready.json')
        (self.root / 'scripted-fixture.json').write_text('changed')
        with self.assertRaisesRegex(ValueError, 'Changed evidence'):
            release.require_ready(self.worktree, self.root / 'ready.json')

    def test_candidate_change_only_updates_declared_source(self):
        first = self.build()
        (self.sources / 'package.py').write_text('new feature')
        changed = dict(self.files)
        changed['package.py'] = {'source': str(self.sources / 'package.py'),
                                 'sha256': release.digest(self.sources / 'package.py')}
        second = release.write_candidate(self.repo, files=changed, metadata={'fixture_only': True},
            base=first['commit'], ref='refs/heads/dev/feature',
            worktree=self.root / 'second', receipt=self.root / 'second.json')
        self.assertEqual(release.git(self.repo, 'diff', '--name-only', first['commit'],
            second['commit']).decode().splitlines(), [release.MANIFEST, 'package.py'])

    def test_unsafe_ref_path_and_empty_asset_rejected(self):
        for name in ('../secret', '.env', 'a/.git/x', '/absolute', 'a\tb'):
            with self.assertRaises(ValueError):
                release.relative_name(name)
        self.build()
        (self.worktree / release.REQUIRED_ASSETS[0]).write_text('')
        with self.assertRaises(ValueError):
            release.verify_worktree(self.worktree)

    def test_partial_source_root_inherits_undeclared_git_assets(self):
        first = self.build()
        partial = self.root / 'partial'
        partial.mkdir()
        (partial / 'package.py').write_text('owned feature')
        paths = self.root / 'paths.json'
        paths.write_text(json.dumps(['package.py']))
        output = self.root / 'partial-receipt.json'
        subprocess.run(['python3', str(Path(release.__file__)), 'candidate',
            '--repo', str(self.repo), '--base', first['commit'],
            '--source-root', str(partial), '--paths', str(paths),
            '--ref', 'refs/heads/dev/partial', '--worktree', str(self.root / 'partial-worktree'),
            '--receipt', str(output)], check=True, capture_output=True)
        second = json.loads(output.read_bytes())
        release.verify_worktree(second['worktree'], second['commit'])
        for name in release.REQUIRED_ASSETS:
            self.assertEqual((self.worktree / name).read_bytes(),
                             (Path(second['worktree']) / name).read_bytes())

    def test_promotion_requires_exact_acceptance(self):
        result = self.build()
        release.save_new(self.root / 'proof.json', self.proof(result['commit']))
        release.certify(self.worktree, self.root / 'proof.json', self.root / 'ready.json')
        release.save_new(self.root / 'approval.json', {'status': 'accepted',
            'owner': 'Evaluation', 'commit': result['commit'],
            'certificate': release.pin(self.root / 'ready.json')})
        promoted = release.promote(self.worktree, self.root / 'ready.json',
            self.root / 'approval.json', self.root / 'current.json', 'fixture-r1')
        self.assertEqual(promoted['state'], 'accepted')
        self.assertFalse(promoted['model_dispatch_released'])
        with self.assertRaises(subprocess.CalledProcessError):
            release.promote(self.worktree, self.root / 'ready.json',
                self.root / 'approval.json', self.root / 'current.json', 'fixture-r1')


if __name__ == '__main__':
    unittest.main()
