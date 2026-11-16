import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from probe_source_app import restore_carried_app_data


class CarriedAppDataTest(unittest.TestCase):
    def test_missing_package_does_not_replace_existing_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / 'runtime/app-data/example.app'
            target.mkdir(parents=True)
            (target / 'identity').write_text('existing')
            with self.assertRaisesRegex(ValueError, 'not restored'):
                restore_carried_app_data(self.shell, str(root / 'missing'), 'example.app', str(root / 'runtime'))
            self.assertEqual((target / 'identity').read_text(), 'existing')

    def test_update_preserves_identity_and_clears_only_compiled_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parent = root / "carry data 'quoted'"
            source = parent / 'example.app'
            (source / 'code_cache').mkdir(parents=True)
            (source / 'identity').write_text('preserved')
            (source / 'code_cache/old').write_text('compiled')
            result = restore_carried_app_data(self.shell, str(parent), 'example.app', str(root / 'runtime'))
            target = root / 'runtime/app-data/example.app'
            self.assertEqual(result, str(source))
            self.assertEqual((target / 'identity').read_text(), 'preserved')
            self.assertFalse((target / 'code_cache').exists())
            self.assertFalse(source.exists())

    def test_source_equal_to_target_is_rejected_before_shell(self):
        with self.assertRaisesRegex(ValueError, 'outside'):
            restore_carried_app_data(lambda _: self.fail('shell must not run'),
                                     '/runtime/app-data', 'example.app', '/runtime')

    @staticmethod
    def shell(command):
        return subprocess.check_output(['sh', '-c', command], text=True)


if __name__ == '__main__':
    unittest.main()
