import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

TOOLS = Path(__file__).resolve().parents[1] / 'tools'
sys.path.insert(0, str(TOOLS))
from compose_native_runtime import compose


class NativeComposition(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def build(self, name, content, **fields):
        path = self.root / name
        path.mkdir()
        (path / 'libprovider.so').write_bytes(content)
        report = {'errors': [], 'artifacts': {'libprovider.so': {
            'bytes': len(content), 'sha256': hashlib.sha256(content).hexdigest()}}, **fields}
        (path / 'artifacts.json').write_text(json.dumps(report))
        return path

    def test_replacement_records_both_sources(self):
        before, after = self.build('old', b'old'), self.build('new', b'new')
        result = compose([before, after], {'libprovider.so'}, self.root / 'out')
        self.assertEqual((self.root / 'out/libprovider.so').read_bytes(), b'new')
        self.assertEqual(result['replacements']['libprovider.so']['from'], str(before / 'libprovider.so'))
        self.assertEqual(len(result['prerequisites']), 2)

    def test_conflict_requires_explicit_replacement(self):
        before, after = self.build('old', b'old'), self.build('new', b'new')
        with self.assertRaisesRegex(ValueError, 'Undeclared'):
            compose([before, after], set(), self.root / 'out')
        self.assertFalse((self.root / 'out').exists())

    def test_cannot_stage_link_declarations(self):
        build = self.build('imports', b'trap', deployable=False)
        with self.assertRaisesRegex(ValueError, 'link-only'):
            compose([build], set(), self.root / 'out')

    def test_tampered_artifact_is_rejected(self):
        build = self.build('input', b'original')
        (build / 'libprovider.so').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'Changed runtime'):
            compose([build], set(), self.root / 'out')

    def test_replacement_must_actually_occur(self):
        build = self.build('input', b'original')
        with self.assertRaisesRegex(ValueError, 'Unused replacement'):
            compose([build], {'libprovider.so'}, self.root / 'out')


if __name__ == '__main__':
    unittest.main()
