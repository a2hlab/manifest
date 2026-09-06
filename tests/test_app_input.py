import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest
import zipfile

PATH = Path(__file__).resolve().parents[1] / 'tools/prepare_app.py'
SPEC = importlib.util.spec_from_file_location('prepare_app', PATH)
APP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(APP)


class OriginalAppInputTest(unittest.TestCase):
    def fixture(self, root):
        apk = root / 'original.apk'
        with zipfile.ZipFile(apk, 'w') as archive:
            for name, bits, machine in [('actual.so', 2, 183), ('misplaced.so', 1, 40)]:
                header = bytearray(20)
                header[:6] = b'\x7fELF' + bytes([bits, 1])
                header[18:20] = machine.to_bytes(2, 'little')
                archive.writestr('lib/arm64-v8a/' + name, header)
        entry = {'sha256': APP.digest(apk), 'bytes': apk.stat().st_size, 'abi': 'arm64-v8a'}
        return apk, entry

    def test_original_bytes_and_actual_abi_are_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            apk, entry = self.fixture(root)
            result = APP.prepare(apk, root / 'out', entry)
            self.assertEqual(apk.read_bytes(), (root / 'out/toutiao.apk').read_bytes())
            libs = result['native_libraries']
            self.assertTrue(libs['lib/arm64-v8a/actual.so']['aarch64_provider'])
            self.assertFalse(libs['lib/arm64-v8a/misplaced.so']['aarch64_provider'])
            self.assertFalse(result['stack_build_input'])

    def test_modified_apk_is_rejected_before_staging(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            apk, entry = self.fixture(root)
            data = bytearray(apk.read_bytes())
            data[-1] ^= 1
            apk.write_bytes(data)
            with self.assertRaisesRegex(ValueError, 'does not match'):
                APP.prepare(apk, root / 'out', entry)
            self.assertFalse((root / 'out').exists())

    def test_existing_output_is_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            apk, entry = self.fixture(root)
            output = root / 'out'
            output.mkdir()
            (output / 'marker').write_text('keep')
            with self.assertRaisesRegex(ValueError, 'must be new'):
                APP.prepare(apk, output, entry)
            self.assertEqual((output / 'marker').read_text(), 'keep')


if __name__ == '__main__':
    unittest.main()
