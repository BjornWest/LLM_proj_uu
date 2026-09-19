"""Safety boundaries for the narrowly scoped reset recipe; no Docker calls."""
import unittest

from .clones import CANONICAL, OWNER, SITES, canonical_url, create_argv, validate_container


def fixture(site='shopping'):
    s = SITES[site]
    return {'Id': 'a' * 64, 'Name': '/' + s['name'], 'Image': s['image_id'], 'Created': 'fixture', 'Mounts': [],
            'Config': {'Image': s['image'], 'Env': ['WA_ENV_CTRL_EXTERNAL_SITE_URL=' + CANONICAL],
                       'Labels': {'intent.owner': OWNER, 'intent.site': site, 'intent.reset-scope': 'isolated-disposable'}},
            'HostConfig': {'PortBindings': {'80/tcp': [{'HostIp': '127.0.0.1', 'HostPort': str(s['port'])}],
                                          '8877/tcp': [{'HostIp': '127.0.0.1', 'HostPort': str(s['control_port'])}]}}}


class CloneSafety(unittest.TestCase):
    def test_pinned_cache_only_creation(self):
        for site in SITES:
            argv = create_argv(site, CANONICAL)
            self.assertIn('--pull=never', argv)
            self.assertEqual(argv[-1], SITES[site]['image'])
            self.assertNotIn('-v', argv)
            self.assertNotIn('--mount', argv)
            self.assertEqual(validate_container(fixture(site), site, CANONICAL)['Mounts'], [])

    def test_wrong_identity_owner_image_and_mount_rejected(self):
        mutations = [lambda d: d.update(Name='/intent-webarena-verified-shopping-1'),
                     lambda d: d.update(Image='sha256:other'),
                     lambda d: d.update(Mounts=[{'Source': 'shared-data'}]),
                     lambda d: d['Config'].update(Image='unpinned:latest'),
                     lambda d: d['Config']['Labels'].update({'intent.owner': 'someone-else'}),
                     lambda d: d['Config']['Labels'].update({'intent.site': 'forum'}),
                     lambda d: d['Config']['Labels'].update({'intent.reset-scope': 'persistent'}),
                     lambda d: d['Config'].update(Env=['WA_ENV_CTRL_EXTERNAL_SITE_URL=http://wrong:80'])]
        for change in mutations:
            d = fixture(); change(d)
            with self.subTest(d=d), self.assertRaises(ValueError):
                validate_container(d, 'shopping', CANONICAL)

    def test_wrong_or_extra_publication_rejected(self):
        for host in ('0.0.0.0', '::', ''):
            d = fixture(); d['HostConfig']['PortBindings']['80/tcp'][0]['HostIp'] = host
            with self.assertRaises(ValueError): validate_container(d, 'shopping', CANONICAL)
        d = fixture(); d['HostConfig']['PortBindings']['22/tcp'] = [{'HostIp': '127.0.0.1', 'HostPort': '22'}]
        with self.assertRaises(ValueError): validate_container(d, 'shopping', CANONICAL)

    def test_only_origin_allowed(self):
        self.assertEqual(canonical_url(CANONICAL + '/'), CANONICAL)
        for value in ('https://example.com', 'http://user:secret@localhost', 'http://localhost/path', 'http://localhost?q=1', 'file:///tmp/x'):
            with self.subTest(value=value), self.assertRaises(ValueError): canonical_url(value)


if __name__ == '__main__':
    unittest.main()
