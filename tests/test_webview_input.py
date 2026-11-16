import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import probe_source_app  # noqa: E402

NAMES = sorted(probe_source_app.WEBVIEW_DEVICE_INPUT)
SHIM = 'webview-t-lib/libwebview_bionic_shim.so'
LIBANDROID = 'webview-t-lib/libandroid.so'


class WebViewDeviceInputTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        files = []
        for name in NAMES:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(name.encode())
            files.append({'path': '/data/local/tmp/asx/' + name, 'category': 'webview',
                          'sha256': hashlib.sha256(name.encode()).hexdigest()})
        files.append({'path': '/system/lib64/libc.so', 'category': 'firmware', 'sha256': '0' * 64})
        self.lock = {'complete_build_input_closure': False, 'files': files}

    def tearDown(self):
        self.directory.cleanup()

    def test_all_six_files_without_a_shim_build(self):
        files, paths = probe_source_app.webview_device_input(self.lock, self.root)
        self.assertEqual(sorted(files), NAMES)
        self.assertEqual(paths[SHIM], self.root.resolve() / SHIM)

    def test_shim_build_replaces_shim_and_libandroid(self):
        replaced = probe_source_app.shim_replaced_webview_files(
            {'artifacts': {'libwebview_bionic_shim.so': {}, 'libandroid.so': {}, 'libaaudio.so': {}}})
        self.assertEqual(replaced, {SHIM, LIBANDROID})
        (self.root / SHIM).unlink()
        (self.root / LIBANDROID).unlink()
        files, paths = probe_source_app.webview_device_input(self.lock, self.root, replaced)
        self.assertEqual(sorted(files), sorted(set(NAMES) - {SHIM, LIBANDROID}))
        self.assertNotIn(SHIM, paths)

    def test_captured_libandroid_still_needed_when_the_build_has_none(self):
        replaced = probe_source_app.shim_replaced_webview_files(
            {'artifacts': {'libwebview_bionic_shim.so': {}}})
        (self.root / LIBANDROID).unlink()
        with self.assertRaisesRegex(ValueError, 'libandroid.so'):
            probe_source_app.webview_device_input(self.lock, self.root, replaced)

    def test_changed_file_is_refused(self):
        (self.root / 'webview-t.apk').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'webview-t.apk'):
            probe_source_app.webview_device_input(self.lock, self.root)

    def test_lock_must_stay_marked_incomplete(self):
        self.lock['complete_build_input_closure'] = True
        with self.assertRaisesRegex(ValueError, 'Unexpected WebView device-input lock'):
            probe_source_app.webview_device_input(self.lock, self.root)


if __name__ == '__main__':
    unittest.main()
