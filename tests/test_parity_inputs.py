import hashlib
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from verify_parity_inputs import verify

class ParityInputTests(unittest.TestCase):
    def fixture(self,root):
        path=root/'system/lib64/libfixture.so'
        path.parent.mkdir(parents=True)
        path.write_bytes(b'input identity fixture')
        return path,dict(files=[dict(path='/system/lib64/libfixture.so',category='firmware',
                                    sha256=hashlib.sha256(path.read_bytes()).hexdigest())])

    def test_checks_bytes_and_reports_missing_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);path,lock=self.fixture(root)
            self.assertTrue(verify(root,lock,['firmware'])['input_hashes_match'])
            path.write_bytes(b'different')
            self.assertEqual(verify(root,lock,['firmware'])['different'],['/system/lib64/libfixture.so'])
            path.unlink()
            self.assertEqual(verify(root,lock,['firmware'])['missing'],['/system/lib64/libfixture.so'])

    def test_rejects_escaping_links_and_empty_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);path,lock=self.fixture(root)
            with self.assertRaisesRegex(ValueError,'No inputs selected'):verify(root,lock,['webview'])
            path.unlink();path.symlink_to('/etc/passwd')
            with self.assertRaisesRegex(ValueError,'escapes'):verify(root,lock,['firmware'])

if __name__=='__main__':unittest.main()
