"""The prebuilt lock has to fail closed, or it is only documentation."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'tools' / (name + '.py'))
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


class PrebuiltLockTests(unittest.TestCase):

    def setUp(self):
        self.verifier = module('verify_prebuilts')
        self.entries = json.loads((ROOT / 'sources.lock.json').read_text()).get('prebuilts', [])

    def test_declared_prebuilts_match_the_lock(self):
        records = self.verifier.verify()
        self.assertEqual(len(records), len(self.entries))
        for record in records:
            self.assertEqual(record['verified_sha256'], record['sha256'])

    def test_every_prebuilt_names_a_recipe_that_exists(self):
        """A binary nobody can regenerate is the thing the lock exists to stop."""
        for entry in self.entries:
            self.assertTrue((ROOT / entry['recipe']).is_file(), entry['recipe'])

    def test_recorded_size_matches_the_file(self):
        for entry in self.entries:
            self.assertEqual((ROOT / entry['path']).stat().st_size, entry['bytes'])

    def _lock_with(self, changes, prebuilt_bytes=None):
        """A throwaway tree holding one prebuilt, so tampering can be simulated."""
        temporary = tempfile.mkdtemp(prefix='a2hlab-prebuilt-test-')
        self.addCleanup(shutil.rmtree, temporary, True)
        root = Path(temporary)
        (root / 'prebuilts').mkdir()
        (root / 'tools' / 'recipes').mkdir(parents=True)
        (root / 'tools' / 'recipes' / 'r.sh').write_text('#!/bin/sh\n')
        payload = prebuilt_bytes if prebuilt_bytes is not None else b'payload'
        (root / 'prebuilts' / 'p.jar').write_bytes(payload)
        entry = {'path': 'prebuilts/p.jar', 'bytes': len(b'payload'),
                 'sha256': hashlib.sha256(b'payload').hexdigest(),
                 'recipe': 'tools/recipes/r.sh'}
        entry.update(changes)
        lock = root / 'lock.json'
        lock.write_text(json.dumps({'prebuilts': [entry]}))
        self.verifier.ROOT = root
        self.addCleanup(setattr, self.verifier, 'ROOT', ROOT)
        return lock

    def test_rejects_altered_content(self):
        # Same length as the recorded payload, so this isolates the hash check
        # rather than tripping the size check first.
        lock = self._lock_with({}, prebuilt_bytes=b'PAYLOAD')
        with self.assertRaisesRegex(ValueError, 'content differs'):
            self.verifier.verify(lock)

    def test_rejects_altered_size(self):
        lock = self._lock_with({'bytes': 999})
        with self.assertRaisesRegex(ValueError, 'size differs'):
            self.verifier.verify(lock)

    def test_rejects_missing_recipe(self):
        lock = self._lock_with({'recipe': 'tools/recipes/gone.sh'})
        with self.assertRaisesRegex(ValueError, 'recipe that is not in the tree'):
            self.verifier.verify(lock)

    def test_rejects_path_escaping_the_manifest(self):
        lock = self._lock_with({'path': '../../etc/passwd'})
        with self.assertRaisesRegex(ValueError, 'escapes the manifest'):
            self.verifier.verify(lock)


if __name__ == '__main__':
    unittest.main()
