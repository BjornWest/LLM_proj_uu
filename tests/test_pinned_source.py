import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from scripts.cache_pinned_source import checked_source


class PinnedSourceTests(unittest.TestCase):
    def pin(self, raw):
        return {'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),
                'git_blob':hashlib.sha1(f'blob {len(raw)}\0'.encode()+raw).hexdigest(),
                'url':'https://raw.githubusercontent.com/example/repo/pinned/file.js'}

    def test_existing_cache_checked_without_network(self):
        with tempfile.TemporaryDirectory() as directory, patch('scripts.cache_pinned_source.urlopen') as network:
            p=Path(directory)/'file';p.write_bytes(b'const source = 1;')
            self.assertEqual(checked_source(p,self.pin(p.read_bytes())),p.read_bytes())
            with self.assertRaises(ValueError):checked_source(p,self.pin(b'changed'))
            network.assert_not_called()

    def test_bad_download_never_installed(self):
        with tempfile.TemporaryDirectory() as directory, patch('scripts.cache_pinned_source.urlopen') as network:
            p=Path(directory)/'file';network.return_value.__enter__.return_value.read.return_value=b'truncated'
            with self.assertRaises(ValueError):checked_source(p,self.pin(b'exact source'),fetch=True)
            self.assertFalse(p.exists())
            network.return_value.__enter__.return_value.read.assert_called_once_with(len(b'exact source')+1)

    def test_no_implicit_fetch_and_verified_restore(self):
        with tempfile.TemporaryDirectory() as directory, patch('scripts.cache_pinned_source.urlopen') as network:
            p=Path(directory)/'new'/'file';raw=b'exact source';pin=self.pin(raw)
            with self.assertRaises(FileNotFoundError):checked_source(p,pin)
            network.assert_not_called()
            network.return_value.__enter__.return_value.read.return_value=raw
            self.assertEqual(checked_source(p,pin,fetch=True),raw)
            self.assertEqual(p.read_bytes(),raw)
