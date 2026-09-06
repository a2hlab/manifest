from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from rebuild import git

class SourceVerifierTests(unittest.TestCase):
    def test_tree_verification_does_not_lock_or_modify_checkout_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            subprocess.run(['git','init','-q',str(root)],check=True)
            (root/'source.c').write_text('int fixture;\n')
            subprocess.run(['git','-C',str(root),'add','source.c'],check=True)
            before=(root/'.git/index').read_bytes()
            # A second verifier must work even while the shared index is locked.
            (root/'.git/index.lock').write_text('simulated concurrent writer')
            first=git(root,'write-tree').strip()
            self.assertEqual(len(first),40)
            self.assertEqual(first,git(root,'write-tree').strip())
            self.assertEqual(before,(root/'.git/index').read_bytes())
            self.assertEqual((root/'.git/index.lock').read_text(),'simulated concurrent writer')

if __name__=='__main__':unittest.main()
