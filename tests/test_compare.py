import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from compare_builds import compare, inventory


def populate(root, values):
    root.mkdir()
    record = {}
    for name, value in values.items():
        (root / name).write_bytes(value)
        record[name] = {'sha256': hashlib.sha256(value).hexdigest(), 'bytes': len(value)}
    (root / 'artifacts.json').write_text(json.dumps(record))


class CompareTests(unittest.TestCase):
    def test_compare_actual_files(self):
        with tempfile.TemporaryDirectory(prefix='a2hlab-test-') as tmp:
            a, b = Path(tmp) / 'a', Path(tmp) / 'b'
            populate(a, {'lib.so': b'one'})
            populate(b, {'lib.so': b'one'})
            self.assertEqual(compare(a, b)['result'], 'byte-identical')
            (b / 'lib.so').write_bytes(b'tampered')
            with self.assertRaisesRegex(ValueError, 'no longer matches'):
                compare(a, b)

    def test_mismatched_complete_inventory(self):
        with tempfile.TemporaryDirectory(prefix='a2hlab-test-') as tmp:
            a, b = Path(tmp) / 'a', Path(tmp) / 'b'
            populate(a, {'lib.so': b'one'})
            populate(b, {'lib.so': b'one', 'extra.so': b'two'})
            with self.assertRaisesRegex(ValueError, 'mismatch'):
                compare(a, b)

    def test_empty_inventory_rejected(self):
        with tempfile.TemporaryDirectory(prefix='a2hlab-test-') as tmp:
            root = Path(tmp) / 'empty'
            populate(root, {})
            with self.assertRaisesRegex(ValueError, 'Empty'):
                inventory(root)


if __name__ == '__main__':
    unittest.main()
