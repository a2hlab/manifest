import importlib.util
import json
from pathlib import Path
import stat
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from bootstrap_sdk import extract_zip, fingerprint, inside
from fetch_sources import read_lock


class BootstrapTests(unittest.TestCase):
    def test_lock_is_pinned_and_scoped(self):
        entries = read_lock(ROOT / 'sources.lock.json')
        self.assertGreaterEqual(len(entries), 19)
        for entry in entries:
            self.assertRegex(entry['revision'], r'^[0-9a-f]{40}$')
            self.assertTrue(entry['url'].startswith('https://'))
        self.assertFalse(json.loads((ROOT / 'full-build-gaps.json').read_text())['complete_source_build'])

    def test_archive_path_escape_rejected(self):
        with tempfile.TemporaryDirectory(prefix='a2hlab-test-') as tmp:
            for value in ['../escape', '/absolute', 'lib/../../escape', 'lib\\escape']:
                with self.assertRaises(ValueError):
                    inside(Path(tmp), value)

    def test_zip_exec_and_relative_symlink(self):
        with tempfile.TemporaryDirectory(prefix='a2hlab-test-') as tmp:
            root = Path(tmp)
            archive = root / 'input.zip'
            with zipfile.ZipFile(archive, 'w') as packed:
                exe = zipfile.ZipInfo('bin/compiler')
                exe.external_attr = (stat.S_IFREG | 0o755) << 16
                packed.writestr(exe, b'test compiler')
                link = zipfile.ZipInfo('bin/c++')
                link.external_attr = (stat.S_IFLNK | 0o777) << 16
                packed.writestr(link, b'compiler')
            out = root / 'out'
            out.mkdir()
            extract_zip(archive, out)
            self.assertTrue((out / 'bin/compiler').stat().st_mode & 0o111)
            self.assertEqual((out / 'bin/c++').read_bytes(), b'test compiler')

    def test_zip_link_escape_rejected(self):
        with tempfile.TemporaryDirectory(prefix='a2hlab-test-') as tmp:
            root = Path(tmp)
            with zipfile.ZipFile(root / 'input.zip', 'w') as packed:
                link = zipfile.ZipInfo('escape')
                link.external_attr = (stat.S_IFLNK | 0o777) << 16
                packed.writestr(link, b'../outside')
            out = root / 'out'
            out.mkdir()
            with self.assertRaises(ValueError):
                extract_zip(root / 'input.zip', out)

    def test_fingerprint_ignores_own_record_and_detects_drift(self):
        with tempfile.TemporaryDirectory(prefix='a2hlab-test-') as tmp:
            root = Path(tmp)
            (root / 'source').write_text('original')
            first = fingerprint(root)['sha256']
            (root / 'tree.json').write_text('{}')
            self.assertEqual(first, fingerprint(root)['sha256'])
            (root / 'source').write_text('modified')
            self.assertNotEqual(first, fingerprint(root)['sha256'])


if __name__ == '__main__':
    unittest.main()
